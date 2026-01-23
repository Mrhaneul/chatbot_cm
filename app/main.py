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
    if "immediate access" in normalized or "opted in" in normalized:
        return "IA_ACCESS_ISSUE"
    return "GENERAL_FAQ"


def extract_course_code(message: str):
    """Extract course code like BIO101, PSY200A, etc."""
    match = re.search(r"[A-Z]{2,4}\d{3}[A-Z\-]*", message)
    return match.group(0) if match else None


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

        # ===== STATE HANDLING (LLM-FIRST FLOW) =====
        if session["awaiting_course_code"]:
            # User is providing the course code as a follow-up
            course_code = extract_course_code(message)  # FIXED: Extract with regex
            intent = session["stored_intent"]
            platform = session["stored_platform"]

            # Clear state
            session["awaiting_course_code"] = False
            session["stored_intent"] = None
            session["stored_platform"] = None
        else:
            # New request - detect intent and extract course code
            intent = detect_intent(message)
            course_code = extract_course_code(message)
            
            # Detect platform
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
            # FIXED: Force instructions collection for IA_ACCESS_ISSUE
            if intent == "IA_ACCESS_ISSUE":
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

        if intent == "IA_ACCESS_ISSUE":
            system_hint = (
                "The user is asking about Immediate Access digital course materials. "
                "Do NOT suggest purchasing or renting physical textbooks unless the user explicitly asks. "
                "If required information such as course code or platform is missing, ask for it. "
                "Do NOT assume availability of print textbooks."
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