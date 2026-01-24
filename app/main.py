from fastapi import FastAPI, HTTPException
from app.schemas.chat import ChatRequest, ChatResponse
from app.llm.llama_client import LlamaClient
from app.rag.retriever import FAQRetriever
import re
from datetime import datetime, timedelta
from typing import Dict, Any
import uuid

"""
MAIN API (FIXED)
- Session-scoped memory (Bug #4)
- Automatic session cleanup
- Multi-user safe
- Works with multiple uvicorn workers (if using shared storage later)
"""

CONFIDENCE_THRESHOLD = 0.1
MAX_HISTORY_TURNS = 6
SESSION_TIMEOUT = timedelta(hours=1)

# Create FastAPI app
app = FastAPI(title="Campus Store Chatbot (Session-Safe)")

# Session storage: session_id -> session_data
# NOTE: This is in-memory for now. For production with multiple workers,
# migrate to Redis or a database.
sessions: Dict[str, Dict[str, Any]] = {}

# Initialize services
llm = LlamaClient()
retriever = FAQRetriever()


def get_or_create_session(session_id: str) -> Dict[str, Any]:
    """
    Get existing session or create new one.
    Returns session data dictionary.
    """
    if session_id not in sessions:
        sessions[session_id] = {
            "history": [],
            "awaiting_course_code": False,
            "stored_intent": None,
            "stored_platform": None,
            "last_activity": datetime.now(),
            "created_at": datetime.now()
        }
    
    # Update last activity timestamp
    sessions[session_id]["last_activity"] = datetime.now()
    return sessions[session_id]


def cleanup_expired_sessions():
    """Remove sessions that haven't been active for SESSION_TIMEOUT."""
    now = datetime.now()
    expired = [
        sid for sid, data in sessions.items()
        if now - data["last_activity"] > SESSION_TIMEOUT
    ]
    for sid in expired:
        del sessions[sid]
        print(f"🗑️  Cleaned up expired session: {sid[:8]}...")
    
    if expired:
        print(f"✓ Removed {len(expired)} expired sessions. Active: {len(sessions)}")


def detect_intent(message: str) -> str:
    """Detect user intent from message."""
    normalized = message.lower()
    
    # Immediate Access keywords
    ia_keywords = [
        "immediate access",
        "opted in",
        "can't access",
        "cant access",
        "cannot access",
        "unable to access",
        "trouble accessing",
        "access issue",
        "access problem",
        "not working",
        "doesn't work",
        "doesnt work",
        "won't open",
        "wont open",
    ]
    
    # Check if any IA keyword is present AND mentions a platform
    has_ia_keyword = any(keyword in normalized for keyword in ia_keywords)
    mentions_platform = any(platform in normalized for platform in [
        "cengage", "mindtap", "mcgraw", "connect", "pearson", 
        "vitalsource", "bedford", "ebook", "e-book", "etext", "e-text"
    ])
    
    if has_ia_keyword and mentions_platform:
        return "IA_ACCESS_ISSUE"
    
    # Also detect IA_ACCESS_ISSUE if they mention "immediate access" alone
    if "immediate access" in normalized or "opted in" in normalized:
        return "IA_ACCESS_ISSUE"
    
    return "GENERAL_FAQ"


def extract_course_code(message: str):
    """Extract course code like BIO101, PSY200A, etc."""
    match = re.search(r"[A-Z]{2,4}\d{3}[A-Z\-]*", message)
    return match.group(0) if match else None


def detect_platform_and_check_ambiguity(message: str) -> tuple[str, bool]:
    """
    Returns: (platform, is_ambiguous)
    """
    platforms_found = []
    
    if "cengage" in message.lower() or "mindtap" in message.lower():
        platforms_found.append("CENGAGE")
    if "mcgraw" in message.lower() or "connect" in message.lower():
        platforms_found.append("MCGRAW_HILL")
    if "bedford" in message.lower():
        platforms_found.append("BEDFORD")
    
    print(f"🔍 DEBUG: Platforms found = {platforms_found}")
    
    # Check for ambiguity
    if len(platforms_found) > 1:
        print(f"🔍 DEBUG: AMBIGUOUS - returning (None, True)")
        return None, True  # Ambiguous
    elif len(platforms_found) == 1:
        print(f"🔍 DEBUG: Single platform - returning ({platforms_found[0]}, False)")
        return platforms_found[0], False  # Clear
    else:
        print(f"🔍 DEBUG: No platform - returning (None, False)")
        return None, False  # No platform mentioned


def detect_topic_switch(message: str, stored_intent: str) -> bool:
    """Detect if user is switching topics."""
    current_intent = detect_intent(message)
    
    # If stored intent was IA but current is FAQ, that's a switch
    if stored_intent == "IA_ACCESS_ISSUE" and current_intent == "GENERAL_FAQ":
        return True
    
    # If stored intent was IA but current is AMBIGUOUS, that's a switch
    if stored_intent == "IA_ACCESS_ISSUE" and current_intent == "AMBIGUOUS_PLATFORM":
        return True
    
    # Keywords that indicate explicit topic change
    topic_switch_keywords = ["actually", "instead", "what about", "by the way", "nevermind"]
    return any(keyword in message.lower() for keyword in topic_switch_keywords)


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    """
    Main chat endpoint with session management.
    """
    try:
        # Periodic cleanup (every request is fine for low traffic)
        cleanup_expired_sessions()
        
        # Get or create session
        session_id = payload.session_id or str(uuid.uuid4())
        session = get_or_create_session(session_id)
        
        message = payload.message.strip()
        
        # Initialize variables
        platform = None
        course_code = None
        intent = None
        
        # ===== EARLY CHECK: Ambiguous Platforms =====
        platform_temp, is_ambiguous = detect_platform_and_check_ambiguity(message)
        
        print(f"🔍 DEBUG: is_ambiguous = {is_ambiguous}")
        
        if is_ambiguous:
            print(f"🔍 DEBUG: ENTERING ambiguity block")
            # Add to history
            session["history"].append({
                "role": "user",
                "content": message
            })
            
            # Return clarification request immediately
            reply = (
                "I notice you mentioned multiple platforms. To give you the most "
                "accurate troubleshooting steps, could you please clarify which "
                "platform you're having trouble with? (e.g., McGraw Hill Connect, "
                "Cengage MindTap, etc.)"
            )
            
            session["history"].append({
                "role": "assistant",
                "content": reply
            })
            
            print(f"🔍 DEBUG: RETURNING clarification response")
            return ChatResponse(
                reply=reply,
                source="CLARIFICATION",
                article_link=None,
                confidence=0.0
            )
        
        # Use detected platform if found
        platform = platform_temp

        # ===== STATE HANDLING (LLM-FIRST FLOW) =====
        if session["awaiting_course_code"]:
            # Check for topic switch FIRST
            if detect_topic_switch(message, session["stored_intent"]):
                # User is changing topics - clear state
                session["awaiting_course_code"] = False
                session["stored_intent"] = None
                session["stored_platform"] = None
                # Process as new query
                intent = detect_intent(message)
                course_code = extract_course_code(message)
                # Detect platform for new query
                if "cengage" in message.lower() or "mindtap" in message.lower():
                    platform = "CENGAGE"
                elif "mcgraw" in message.lower() or "connect" in message.lower():
                    platform = "MCGRAW_HILL"
            else:
                # Continue with stored intent - user is providing course code
                course_code = extract_course_code(message)  # FIXED: Extract with regex
                intent = session["stored_intent"]
                platform = session["stored_platform"]
                # Clear state after processing
                session["awaiting_course_code"] = False
                session["stored_intent"] = None
                session["stored_platform"] = None
        else:
            # New request - detect intent and extract course code
            intent = detect_intent(message)
            course_code = extract_course_code(message)
            
            # Platform was already detected earlier, but verify/update if needed
            if platform is None:
                if "cengage" in message.lower() or "mindtap" in message.lower():
                    platform = "CENGAGE"
                elif "mcgraw" in message.lower() or "connect" in message.lower():
                    platform = "MCGRAW_HILL"

        # ===== CLARIFICATION GATE (STATE ONLY) =====
        if intent == "IA_ACCESS_ISSUE" and not course_code:
            # Store state for next turn
            session["awaiting_course_code"] = True
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            
            # Optional platform inference
            if "cengage" in message.lower() or "mindtap" in message.lower():
                session["stored_platform"] = "CENGAGE"
            elif "mcgraw" in message.lower() or "connect" in message.lower():
                session["stored_platform"] = "MCGRAW_HILL"
            else:
                session["stored_platform"] = None

        # FIXED (Bug #3): Add to history AFTER state handling
        session["history"].append({
            "role": "user",
            "content": message
        })

        # ===== OPTIONAL RAG =====
        retrieval = None
        context = ""

        try:
            # Skip retrieval for unsupported platforms
            if intent == "UNSUPPORTED_PLATFORM":
                retrieval = None
                context = ""
            # FIXED: Force instructions collection for IA_ACCESS_ISSUE
            elif intent == "IA_ACCESS_ISSUE":
                # Always use instructions for Immediate Access issues
                retrieval = retriever.retrieve(
                    message,
                    collection="instructions",
                    platform=platform
                )
            elif course_code:
                # If they mentioned a course code, probably want instructions
                retrieval = retriever.retrieve(
                    message,
                    collection="instructions",
                    platform=platform
                )
            else:
                # Let heuristic decide between FAQs and instructions
                retrieval = retriever.retrieve(message)

            if retrieval and "context" in retrieval:
                context = retrieval["context"]

        except Exception as e:
            print(f"⚠️  Retrieval failed: {e}")
            retrieval = None
            context = ""

        # ===== LLM CALL (ALWAYS RUNS) =====
        system_hint = ""

        if intent == "UNSUPPORTED_PLATFORM":
            # Extract the platform name from the message
            platform_mentioned = None
            unsupported = ["pearson", "mylab", "mastering", "wiley", "sapling"]
            for p in unsupported:
                if p in message.lower():
                    platform_mentioned = p.title()
                    break
            
            platform_text = f"{platform_mentioned} " if platform_mentioned else "this platform "
            
            system_hint = (
                f"The user is asking about {platform_text}which we don't have specific instructions for. "
                "Respond with EXACTLY this message (you can adjust wording slightly but keep the same meaning):\n\n"
                f"'I understand you're having trouble accessing {platform_text}materials. "
                "Unfortunately, I don't have specific troubleshooting instructions for this platform in my knowledge base. "
                "I recommend contacting the CBU Campus Store directly for assistance with this specific platform. "
                "They'll be able to provide you with the specific help you need. "
                "Is there anything else I can help you with regarding textbook policies or other campus store services?'\n\n"
                "DO NOT mention other platforms like McGraw Hill or Cengage. "
                "DO NOT ask for course codes. "
                "DO NOT provide generic troubleshooting steps."
            )
        elif intent == "IA_ACCESS_ISSUE":
            system_hint = (
                "The user is asking about Immediate Access digital course materials. "
                "Do NOT suggest purchasing or renting physical textbooks unless the user explicitly asks. "
                "If required information such as course code or platform is missing, ask for it. "
                "Do NOT assume availability of print textbooks. "
                "Only provide instructions for the specific platform mentioned in the official instructions."
            )

        reply = llm.chat(
            message=message,
            context=context,
            history=session["history"][-MAX_HISTORY_TURNS:],
            system_hint=system_hint
        )

        # Add assistant response to history
        session["history"].append({
            "role": "assistant",
            "content": reply
        })

        # Trim history to prevent context overflow
        if len(session["history"]) > MAX_HISTORY_TURNS * 2:
            session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]

        # Prepare response
        confidence = retrieval["score"] if retrieval else 0.0
        source = retrieval["source_id"] if retrieval else "LLM_ONLY"
        article_link = (
            retrieval.get("article_link")
            if retrieval and confidence >= CONFIDENCE_THRESHOLD
            else None
        )

        return ChatResponse(
            reply=reply,
            source=source,
            article_link=article_link,
            confidence=confidence
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/stats")
def get_session_stats():
    """Debug endpoint to view active sessions."""
    cleanup_expired_sessions()
    return {
        "active_sessions": len(sessions),
        "sessions": [
            {
                "id": sid[:8] + "...",
                "history_length": len(data["history"]),
                "awaiting_course_code": data["awaiting_course_code"],
                "last_activity": data["last_activity"].isoformat(),
                "age_minutes": (datetime.now() - data["created_at"]).total_seconds() / 60
            }
            for sid, data in sessions.items()
        ]
    }


@app.delete("/sessions/{session_id}")
def clear_session(session_id: str):
    """Clear a specific session (useful for testing)."""
    if session_id in sessions:
        del sessions[session_id]
        return {"message": f"Session {session_id[:8]}... cleared"}
    return {"message": "Session not found"}


# ===== DEBUG ENDPOINTS =====
@app.post("/debug/retrieval-only")
def debug_retrieval(payload: ChatRequest):
    """Test retrieval speed in isolation."""
    import time
    start = time.time()
    
    result = retriever.retrieve(
        payload.message,
        collection="instructions",
        platform="MCGRAW_HILL"
    )
    
    elapsed = time.time() - start
    return {
        "elapsed_ms": round(elapsed * 1000, 2),
        "source": result["source_id"],
        "score": result["score"],
        "context_preview": result["context"][:200] + "..."
    }


@app.post("/debug/llm-only")
def debug_llm(payload: ChatRequest):
    """Test LLM generation speed in isolation."""
    import time
    start = time.time()
    
    reply = llm.chat(
        message=payload.message,
        context="",
        history=[],
        system_hint=""
    )
    
    elapsed = time.time() - start
    return {
        "elapsed_seconds": round(elapsed, 2),
        "reply_length": len(reply),
        "reply_preview": reply[:200] + "..."
    }