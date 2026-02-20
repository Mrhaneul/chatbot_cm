from email.mime import message
from fastapi import FastAPI, HTTPException
from app.schemas.chat import ChatRequest, ChatResponse
from app.llm.llama_client import LlamaClient
from app.rag.retriever import FAQRetriever
import re
from datetime import datetime, timedelta
from typing import Dict, Any
import uuid
import time  
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
try:
    from app.pdf_recommendations import get_recommendations_for_chat
except Exception:
    # Fallback stub when PDF recommendation module is unavailable (e.g., missing firebase_admin)
    def get_recommendations_for_chat(*args, **kwargs):
        return []
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

"""
MAIN API (FIXED + PERFORMANCE TRACKING)
- Session-scoped memory (Bug #4)
- Automatic session cleanup
- Multi-user safe
- ✨ NEW: Response time tracking for model comparison
"""

CONFIDENCE_THRESHOLD = 0.1
MAX_HISTORY_TURNS = 6
SESSION_TIMEOUT = timedelta(hours=1)

# Create FastAPI app FIRST
app = FastAPI(title="Campus Store Chatbot (Session-Safe + Performance Tracking)")

# THEN define and add middleware
class NgrokMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["ngrok-skip-browser-warning"] = "true"
        return response

app.add_middleware(NgrokMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://lance-cbu.web.app",
        "https://lance-cbu.firebaseapp.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "http://localhost:3000",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true",
        }
    )
# Session storage: session_id -> session_data
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
            "awaiting_platform_type": False,
            "stored_intent": None,
            "stored_platform": None,
            "stored_publisher": None,
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
    
    # ✨ Check for informational questions FIRST
    informational_patterns = [
        "what is",
        "what's",
        "what are",
        "how does",
        "how do",
        "how can i",
        "tell me about",
        "explain",
        "describe",
        "can you tell me",
        "i want to know",
        "help me understand",
        "definition of",
        "define",
    ]
    
    # If it's an informational question, return GENERAL_FAQ immediately
    if any(pattern in normalized for pattern in informational_patterns):
        print(f"🔍 [INTENT DEBUG] Informational question detected")
        return "GENERAL_FAQ"
    
    # Immediate Access AND Textbook troubleshooting keywords
    ia_keywords = [
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
        "need access",       
        "need to access",     
        "how do i access",    
        "how to access",
        "access",
        "help with",
        "help",
        "having trouble",
        "trouble with",
        "having issues",       # ✨ NEW
        "issues with",         # ✨ NEW
    ]
    
    # Check if any IA keyword is present AND mentions a platform OR textbook
    has_ia_keyword = any(keyword in normalized for keyword in ia_keywords)
    
    # ✨ EXPANDED: Include textbook mentions
    mentions_platform_or_textbook = any(word in normalized for word in [
        "cengage", "mindtap", "mcgraw", "connect", "pearson", 
        "vitalsource", "bedford", "ebook", "e-book", "etext", "e-text",
        "simucase", "sage", "vantage", "wiley", "zybooks", "clifton", "macmillan",
        "textbook", "text book", "etextbook", "e-textbook"  # ✨ NEW
    ])

    print(f"🔍 [INTENT DEBUG] has_ia_keyword={has_ia_keyword}, mentions_platform_or_textbook={mentions_platform_or_textbook}")
    
    if has_ia_keyword and mentions_platform_or_textbook:
        return "IA_ACCESS_ISSUE"
    
    # Only trigger IA_ACCESS_ISSUE for "immediate access" if combined with troubleshooting keywords
    if "immediate access" in normalized and has_ia_keyword:
        return "IA_ACCESS_ISSUE"
    
    return "GENERAL_FAQ"


def enhance_query_with_conversation_context(message: str, history: list) -> str:
    """
    Enhance query with conversation context to improve RAG retrieval.
    """
    msg_lower = message.lower().strip()
    
    if len(history) >= 2 and len(msg_lower.split()) <= 3:
        last_bot_message = ""
        
        for msg in reversed(history):
            if msg.get("role") == "assistant":
                last_bot_message = msg.get("content", "").lower()
                break
        
        # ===== HANDLE "I DON'T KNOW" RESPONSES =====
        doesnt_know_phrases = [
            "i don't know", "i dont know", "not sure", "unsure",
            "no idea", "i'm not sure", "im not sure", "don't know",
            "idk", "not certain", "i have no idea", "i'm unsure",
            "i do not know", "no clue"
        ]
        user_doesnt_know = any(phrase in msg_lower for phrase in doesnt_know_phrases)

        # If student doesn't know ebook vs courseware → escalate to email
        if user_doesnt_know and any(keyword in last_bot_message for keyword in [
            "standalone ebook", "stand-alone ebook", "courseware",
            "homework assignments", "publisher's platform"
        ]):
            return "ESCALATE_TO_EMAIL"

        # If student doesn't know textbook vs platform → ask ebook vs courseware
        if user_doesnt_know and any(keyword in last_bot_message for keyword in [
            "mcgraw hill textbook or mcgraw hill connect",
            "cengage textbook or cengage mindtap",
            "pearson textbook or pearson mylab",
            "textbook or", "mindtap or", "mylab or"
        ]):
            return "ASK_EBOOK_OR_COURSEWARE"

        # McGraw Hill clarification
        if "mcgraw hill textbook or mcgraw hill connect" in last_bot_message:
            if "connect" in msg_lower:
                return "McGraw Hill Connect immediate access platform instructions"
            elif "textbook" in msg_lower or "etextbook" in msg_lower or "ebook" in msg_lower:
                return "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif "ebook" in msg_lower or "standalone" in msg_lower or "stand-alone" in msg_lower:
                return "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif "courseware" in msg_lower or "homework" in msg_lower or "assignment" in msg_lower:
                return "McGraw Hill Connect immediate access platform instructions"

        # Cengage clarification
        if "cengage textbook or cengage mindtap" in last_bot_message:
            if "mindtap" in msg_lower or "cnow" in msg_lower:
                return "Cengage MindTap immediate access platform instructions"
            elif "textbook" in msg_lower or "etextbook" in msg_lower or "ebook" in msg_lower:
                return "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif "ebook" in msg_lower or "standalone" in msg_lower or "stand-alone" in msg_lower:
                return "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif "courseware" in msg_lower or "homework" in msg_lower or "assignment" in msg_lower:
                return "Cengage MindTap immediate access platform instructions"

        # Pearson clarification
        if "pearson textbook or pearson mylab" in last_bot_message:
            if "mylab" in msg_lower or "mastering" in msg_lower:
                return "Pearson MyLab Mastering immediate access platform instructions"
            elif "textbook" in msg_lower or "etextbook" in msg_lower or "ebook" in msg_lower:
                return "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif "ebook" in msg_lower or "standalone" in msg_lower or "stand-alone" in msg_lower:
                return "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif "courseware" in msg_lower or "homework" in msg_lower or "assignment" in msg_lower:
                return "Pearson MyLab Mastering immediate access platform instructions"

        # ===== ASK EBOOK VS COURSEWARE =====
        if any(keyword in last_bot_message for keyword in [
            "standalone ebook", "stand-alone ebook", "courseware",
            "homework assignments", "publisher's platform"
        ]):
            if any(keyword in msg_lower for keyword in [
                "ebook", "standalone", "stand-alone", "just reading", "read", "book"
            ]):
                return "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif any(keyword in msg_lower for keyword in [
                "courseware", "homework", "assignment", "quiz", "platform", "connect",
                "mindtap", "mylab", "mastering"
            ]):
                # Return platform-specific courseware instructions
                for msg in reversed(history):
                    if msg.get("role") == "user":
                        prev = msg.get("content", "").lower()
                        if "mcgraw" in prev or "connect" in prev:
                            return "McGraw Hill Connect immediate access platform instructions"
                        elif "cengage" in prev or "mindtap" in prev:
                            return "Cengage MindTap immediate access platform instructions"
                        elif "pearson" in prev or "mylab" in prev:
                            return "Pearson MyLab Mastering immediate access platform instructions"

    return message


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
    if "simucase" in message.lower():
        platforms_found.append("SIMUCASE")
    if "pearson" in message.lower():
        platforms_found.append("PEARSON")
    if "wiley" in message.lower():
        platforms_found.append("WILEY")
    if "sage" in message.lower():
        platforms_found.append("SAGE")
    if "macmillan" in message.lower() or "achieve" in message.lower():
        platforms_found.append("MACMILLAN")
    if "zybooks" in message.lower():
        platforms_found.append("ZYBOOKS")
    if "clifton" in message.lower():
        platforms_found.append("CLIFTON")
    
    print(f"🔍 DEBUG: Platforms found = {platforms_found}")
    
    if len(platforms_found) > 1:
        print(f"🔍 DEBUG: AMBIGUOUS - returning (None, True)")
        return None, True
    elif len(platforms_found) == 1:
        print(f"🔍 DEBUG: Single platform - returning ({platforms_found[0]}, False)")
        return platforms_found[0], False
    else:
        print(f"🔍 DEBUG: No platform - returning (None, False)")
        return None, False


def detect_topic_switch(message: str, stored_intent: str) -> bool:
    """Detect if user is switching topics."""
    current_intent = detect_intent(message)
    
    if stored_intent == "IA_ACCESS_ISSUE" and current_intent == "GENERAL_FAQ":
        return True
    
    if stored_intent == "IA_ACCESS_ISSUE" and current_intent == "AMBIGUOUS_PLATFORM":
        return True
    
    topic_switch_keywords = ["actually", "instead", "what about", "by the way", "nevermind"]
    return any(keyword in message.lower() for keyword in topic_switch_keywords)


def is_ambiguous_platform_query(message: str) -> tuple[str | None, bool]:
    """
    Check if query mentions a publisher without specifying textbook vs platform.
    Returns: (publisher_name, is_ambiguous)
    """
    msg_lower = message.lower()
    
    # ✨ NEW: Check for informational questions FIRST
    informational_patterns = [
        "what is",
        "what's",
        "tell me about",
        "explain",
        "describe",
        "definition of",
    ]
    
    # If it's an informational question, don't treat as ambiguous
    if any(pattern in msg_lower for pattern in informational_patterns):
        return None, False  # Let it proceed to FAQ retrieval
    
    # McGraw Hill
    if "mcgraw" in msg_lower or "mcgraw hill" in msg_lower:
        if "connect" in msg_lower:
            return "MCGRAW_HILL", False
        elif any(word in msg_lower for word in ["textbook", "etextbook", "ebook", "e-book"]):
            return "MCGRAW_HILL", False
        else:
            return "MCGRAW_HILL", True
    
    # Cengage
    if "cengage" in msg_lower:
        if "mindtap" in msg_lower or "cnow" in msg_lower:
            return "CENGAGE", False
        elif any(word in msg_lower for word in ["textbook", "etextbook", "ebook", "e-book"]):
            return "CENGAGE", False
        else:
            return "CENGAGE", True
    
    # Pearson
    if "pearson" in msg_lower:
        if "mylab" in msg_lower or "mastering" in msg_lower:
            return "PEARSON", False
        elif any(word in msg_lower for word in ["textbook", "etextbook", "ebook", "e-book"]):
            return "PEARSON", False
        else:
            return "PEARSON", True
    
    # ✨ UPDATED: Immediate Access without platform
    if "immediate access" in msg_lower:
        # Check for troubleshooting keywords
        troubleshooting_keywords = [
            "can't access", "cannot access", "unable to access",
            "not working", "doesn't work", "trouble", "issue", "problem"
        ]
        
        has_trouble_keyword = any(keyword in msg_lower for keyword in troubleshooting_keywords)
        has_platform_mention = any(platform in msg_lower for platform in [
            "cengage", "mindtap", "mcgraw", "connect", "pearson", 
            "vitalsource", "bedford", "ebook", "e-book", "etext", "e-text",
            "simucase", "sage", "vantage", "wiley", "zybooks", "clifton", "macmillan"
        ])
        
        # Only trigger clarification if:
        # 1. They have a troubleshooting issue AND
        # 2. No platform is mentioned
        if has_trouble_keyword and not has_platform_mention:
            return "IMMEDIATE_ACCESS", True
    
    return None, False


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    """
    Main chat endpoint with session management and performance tracking.
    """
    # ✨ START TIMER
    request_start = time.time()
    retrieval_time_ms = 0
    llm_time_ms = 0
    
    try:
        cleanup_expired_sessions()
        
        session_id = payload.session_id or str(uuid.uuid4())
        session = get_or_create_session(session_id)

        # Reset clarification flags for a fresh user query unless we are already awaiting clarification
        if not session.get("awaiting_platform_type", False):
            session["stored_publisher"] = None
            session["stored_original_query"] = None

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
            session["history"].append({
                "role": "user",
                "content": message
            })
            
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
            
            total_time = (time.time() - request_start) * 1000
            
            return ChatResponse(
                reply=reply,
                source="CLARIFICATION",
                article_link=None,
                confidence=0.0,
                total_time_ms=round(total_time, 2),
                retrieval_time_ms=0,
                llm_time_ms=0
            )
        
        # ===== EARLY CHECK: Ambiguous Platform Queries =====
        publisher, needs_clarification = is_ambiguous_platform_query(message)

        if needs_clarification:
            print(f"🔍 [CLARIFICATION DEBUG] Detected ambiguous query for {publisher}")
            
            session["history"].append({
                "role": "user",
                "content": message
            })
            
            if publisher == "MCGRAW_HILL":
                clarification = (
                    "I can help you with McGraw Hill! To give you the most accurate instructions, "
                    "could you please specify: Are you trying to access a **McGraw Hill textbook** "
                    "or **McGraw Hill Connect**?"
                )
            elif publisher == "CENGAGE":
                clarification = (
                    "I can help you with Cengage! To give you the most accurate instructions, "
                    "could you please specify: Are you trying to access a **Cengage textbook** "
                    "or **Cengage MindTap** (also called cnowv2)?"
                )
            elif publisher == "PEARSON":
                clarification = (
                    "I can help you with Pearson! To give you the most accurate instructions, "
                    "could you please specify: Are you trying to access a **Pearson textbook** "
                    "or **Pearson MyLab/Mastering**?"
                )
            elif publisher == "IMMEDIATE_ACCESS":
                clarification = (
                    "I can help you with Immediate Access! To give you the most accurate instructions, "
                    "could you please specify: Which platform do you need help with? For example:\n"
                    "- McGraw Hill Connect\n"
                    "- Cengage MindTap\n"
                    "- Pearson MyLab/Mastering\n"
                    "- SimuCase\n"
                    "- Another platform"
                )
            else:
                clarification = (
                    "I can help you with that! Could you please specify what type of access "
                    "you need (textbook or platform/courseware)?"
                )
            
            session["history"].append({
                "role": "assistant",
                "content": clarification
            })
            
            session["awaiting_platform_type"] = True
            session["stored_publisher"] = publisher
            
            total_time = (time.time() - request_start) * 1000
            
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                total_time_ms=round(total_time, 2),
                retrieval_time_ms=0,
                llm_time_ms=0
            )
        
        platform = platform_temp

        print(f"🔍 [PLATFORM DEBUG EARLY] platform_temp = {platform_temp}")
        print(f"🔍 [PLATFORM DEBUG EARLY] platform = {platform}")

        if session.get("awaiting_platform_type", False):
            print(f"🔍 [STATE DEBUG] Processing platform type clarification")
            
            msg_lower = message.lower()
            publisher = session.get("stored_publisher")
            original_query = session.get("stored_original_query", "")  # ✨ Get original query
            
            # ✨ NEW: Handle textbook-specific follow-ups
            if publisher == "TEXTBOOK_GENERIC":
                intent = "IA_ACCESS_ISSUE"
                
                # Detect platform from response
                if "bedford" in msg_lower:
                    platform = "BEDFORD"
                elif "cengage" in msg_lower or "mindtap" in msg_lower:
                    platform = "CENGAGE"
                elif "mcgraw" in msg_lower or "connect" in msg_lower:
                    platform = "MCGRAW_HILL"
                elif "pearson" in msg_lower or "mylab" in msg_lower or "mastering" in msg_lower:
                    platform = "PEARSON"
                elif "vitalsource" in msg_lower:
                    platform = "VITALSOURCE"
                elif "simucase" in msg_lower:
                    platform = "SIMUCASE"
                elif "sage" in msg_lower:
                    platform = "SAGE"
                elif "wiley" in msg_lower:
                    platform = "WILEY"
                elif "zybooks" in msg_lower:
                    platform = "ZYBOOKS"
                elif "clifton" in msg_lower:
                    platform = "CLIFTON"
                elif "macmillan" in msg_lower:
                    platform = "MACMILLAN"
                
                # ✨ Use original query + platform for better retrieval
                if platform and original_query:
                    enhanced_query = f"{original_query} {platform} access instructions"
                    print(f"🔍 [QUERY DEBUG] Enhanced query: {enhanced_query}")
                
            elif "connect" in msg_lower or "mindtap" in msg_lower or "mylab" in msg_lower or "mastering" in msg_lower or "platform" in msg_lower:
                # Existing logic for Cengage/McGraw/Pearson clarification
                intent = "IA_ACCESS_ISSUE"
                if publisher == "MCGRAW_HILL":
                    platform = "MCGRAW_HILL"
                elif publisher == "CENGAGE":
                    platform = "CENGAGE"
                elif publisher == "PEARSON":
                    platform = "PEARSON"
            else:
                intent = "IA_ACCESS_ISSUE"
                platform = None
            
            session["awaiting_platform_type"] = False
            session["stored_publisher"] = None
            session["stored_original_query"] = None  # ✨ Clear stored query
            course_code = extract_course_code(message)
            
            if platform is None:
                if "cengage" in message.lower() or "mindtap" in message.lower():
                    platform = "CENGAGE"
                elif "mcgraw" in message.lower() or "connect" in message.lower():
                    platform = "MCGRAW_HILL"
                elif "simucase" in message.lower():
                    platform = "SIMUCASE"
                elif "pearson" in message.lower():
                    platform = "PEARSON"
                elif "bedford" in message.lower():
                    platform = "BEDFORD"
                elif "wiley" in message.lower():
                    platform = "WILEY"
                elif "sage" in message.lower():
                    platform = "SAGE"
                elif "macmillan" in message.lower() or "achieve" in message.lower():
                    platform = "MACMILLAN"
                elif "zybooks" in message.lower():
                    platform = "ZYBOOKS"
                elif "clifton" in message.lower():
                    platform = "CLIFTON"
            
            print(f"🔍 [PLATFORM DEBUG] Detected platform: {platform}")

            # ✨ ADD THIS ELIF BLOCK FOR COURSE CODE HANDLING
        elif session.get("awaiting_course_code", False):
            if detect_topic_switch(message, session["stored_intent"]):
                session["awaiting_course_code"] = False
                session["stored_intent"] = None
                session["stored_platform"] = None
                platform, _ = detect_platform_and_check_ambiguity(message)
                intent = detect_intent(message)
                course_code = extract_course_code(message)
            else:
                course_code = extract_course_code(message)
                intent = session["stored_intent"]
                platform = session["stored_platform"]
                session["awaiting_course_code"] = False
                session["stored_intent"] = None
                session["stored_platform"] = None
        
        # ✨ ADD THIS ELSE BLOCK FOR NEW QUERIES
        else:
            # This handles NEW conversations
            is_platform_clarification = False
            if len(session["history"]) >= 2:
                last_bot_message = ""
                for msg in reversed(session["history"]):
                    if msg.get("role") == "assistant":
                        last_bot_message = msg.get("content", "").lower()
                        break
                
                platform_clarification_patterns = [
                    "textbook or mcgraw hill connect",
                    "textbook or cengage mindtap",
                    "textbook or pearson mylab",
                    "cengage textbook or cengage mindtap",
                    "mcgraw hill textbook or mcgraw hill connect",
                    "pearson textbook or pearson mylab"
                ]
                
                if any(pattern in last_bot_message for pattern in platform_clarification_patterns):
                    is_platform_clarification = True
                    intent = "IA_ACCESS_ISSUE"
                    print(f"🔍 [INTENT DEBUG] Platform clarification detected - preserving IA_ACCESS_ISSUE intent")
            
            if not is_platform_clarification:
                intent = detect_intent(message)  # ✨ THIS IS THE CRITICAL LINE!
                print(f"🔍 [INTENT DEBUG] Called detect_intent(), result: {intent}")
            
            course_code = extract_course_code(message)
            
            if platform is None:
                if "cengage" in message.lower() or "mindtap" in message.lower():
                    platform = "CENGAGE"
                elif "mcgraw" in message.lower() or "connect" in message.lower():
                    platform = "MCGRAW_HILL"
                elif "simucase" in message.lower():
                    platform = "SIMUCASE"
                elif "pearson" in message.lower():
                    platform = "PEARSON"
                elif "bedford" in message.lower():
                    platform = "BEDFORD"
                elif "wiley" in message.lower():
                    platform = "WILEY"
                elif "sage" in message.lower():
                    platform = "SAGE"
                elif "macmillan" in message.lower() or "achieve" in message.lower():
                    platform = "MACMILLAN"
                elif "zybooks" in message.lower():
                    platform = "ZYBOOKS"
                elif "clifton" in message.lower():
                    platform = "CLIFTON"
            
            print(f"🔍 [PLATFORM DEBUG] Detected platform: {platform}")

        # NOW the intent is set!
        # 1. Intent detection happens somewhere up here
        print(f"🔍 [INTENT DEBUG] Final intent: {intent}")

        # 2. Platform detection
        print(f"🔍 [PLATFORM DEBUG] Detected platform: {platform}")

        # Check for course code requirement
        if intent == "IA_ACCESS_ISSUE" and not course_code:
            session["awaiting_course_code"] = True
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            session["stored_platform"] = platform

        is_vague_query = (
            intent == "IA_ACCESS_ISSUE" and
            platform is None and
            len(message.split()) <= 20 and  # allow slightly longer queries
            any(word in message.lower() for word in [
                "immediate access",
                "textbook",
                "text book",
                "etextbook",
                "e-textbook",
                "ebook",
                "e-book",
                "access to my textbook",
                "access to textbook",
            ])
        )
        if is_vague_query:
            clarification = (
                "I can help you with textbook access! To give you the most accurate instructions, "
                "could you please specify which platform or publisher your textbook uses? "
                "Examples: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, VitalSource, Bedford, "
                "Sage, SimuCase, etc."
            )
            session["awaiting_platform_type"] = True
            session["stored_publisher"] = "TEXTBOOK_GENERIC"
            session["stored_original_query"] = message


            total_time = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                total_time_ms=round(total_time, 2),
                retrieval_time_ms=0,
                llm_time_ms=0
            )

        print(f"🔍 [VAGUE QUERY DEBUG] intent={intent}, platform={platform}")
        print(f"🔍 [VAGUE QUERY DEBUG] is_vague_query={is_vague_query}")

        # 5. Then add to history
        session["history"].append({
            "role": "user",
            "content": message
        })

        retrieval = None
        context = ""

        greeting_keywords = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings"]
        is_greeting = (
            len(message.split()) <= 3 and  # Short message
            any(keyword in message.lower() for keyword in greeting_keywords)
        )

        try:
            # ✨ START RETRIEVAL TIMER
            retrieval_start = time.time()
            
            if is_greeting:
                retrieval = None
                context = ""
                print("🔍 [RAG DEBUG] Greeting detected - skipping retrieval")
            # ✨ NEW: Skip retrieval for vague queries
            elif is_vague_query:
                retrieval = None
                context = ""
                print("🔍 [RAG DEBUG] Query too vague - skipping retrieval, will ask for clarification")
            # Skip retrieval for unsupported platforms
            elif intent == "UNSUPPORTED_PLATFORM":
                retrieval = None
                context = ""
            elif intent == "IA_ACCESS_ISSUE":
                enhanced_query = enhance_query_with_conversation_context(message, session["history"])
                
                print(f"🔍 [RAG DEBUG] Original query: '{message}'")
                print(f"🔍 [RAG DEBUG] Enhanced query: '{enhanced_query}'")
                print(f"🔍 [RAG DEBUG] Platform: {platform}")
                
                retrieval = retriever.retrieve(
                    enhanced_query,
                    collection="instructions",
                    platform=platform
                )
            elif course_code:
                enhanced_query = enhance_query_with_conversation_context(message, session["history"])
                retrieval = retriever.retrieve(
                    enhanced_query,
                    collection="instructions",
                    platform=platform
                )
            else:
                retrieval = retriever.retrieve(message)

            if retrieval and "context" in retrieval:
                context = retrieval["context"]
            
            # ✨ END RETRIEVAL TIMER
            retrieval_time_ms = (time.time() - retrieval_start) * 1000

        except AttributeError as e:
            print(f"⚠️  Platform-specific index not found ({e}), falling back to general index")
            try:
                retrieval = retriever.retrieve(
                    enhanced_query if 'enhanced_query' in locals() else message,
                    collection="instructions",
                    platform=None
                )
                if retrieval and "context" in retrieval:
                    context = retrieval["context"]
                retrieval_time_ms = (time.time() - retrieval_start) * 1000
            except Exception as e2:
                print(f"⚠️  Fallback retrieval also failed: {e2}")
                retrieval = None
                context = ""
                retrieval_time_ms = (time.time() - retrieval_start) * 1000
        except Exception as e:
            print(f"⚠️  Retrieval failed: {e}")
            retrieval = None
            context = ""
            retrieval_time_ms = (time.time() - retrieval_start) * 1000
            
        # ===== LLM CALL (TIMED) =====
        system_hint = ""

        # ✨ UPDATED: Add hint for vague queries with textbook/IA detection
        if is_vague_query:
            # Check what type of vague query it is
            msg_lower = message.lower()
            
            if any(word in msg_lower for word in ["textbook", "text book", "etextbook", "e-textbook", "ebook", "e-book"]):
                system_hint = (
                    "The user mentioned they're having trouble with their textbook but didn't specify which platform or publisher. "
                    "DO NOT provide a generic greeting. "
                    "DO NOT provide troubleshooting steps yet. "
                    "Ask them which platform or publisher their textbook uses. Be specific with examples: "
                    "Cengage, McGraw Hill, Pearson, VitalSource, Bedford, Sage, SimuCase, etc. "
                    "Keep your question friendly and helpful."
                )
            else:
                # Immediate Access specific
                system_hint = (
                    "The user mentioned they can't access 'Immediate Access' but didn't provide specific details. "
                    "DO NOT provide a generic greeting. "
                    "Ask specific clarifying questions to help them: "
                    "1) Which course or textbook platform are they trying to access? "
                    "   (Examples: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, etc.) "
                    "2) Or are they having trouble with the Immediate Access page in Blackboard? "
                    "Be friendly but direct in asking for this information."
                )

        elif intent == "UNSUPPORTED_PLATFORM":
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

        # ✨ START LLM TIMER
        llm_start = time.time()
        
        reply = llm.chat(
            message=message,
            context=context,
            history=session["history"][-MAX_HISTORY_TURNS:],
            system_hint=system_hint
        )
        
        # ✨ END LLM TIMER
        llm_time_ms = (time.time() - llm_start) * 1000

        session["history"].append({
            "role": "assistant",
            "content": reply
        })

        if len(session["history"]) > MAX_HISTORY_TURNS * 2:
            session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]

        # ✨ CALCULATE TOTAL TIME
        total_time_ms = (time.time() - request_start) * 1000

        confidence = retrieval["score"] if retrieval else 0.0
        source = retrieval["source_id"] if retrieval else "LLM_ONLY"
        article_link = (
            retrieval.get("article_link")
            if retrieval and confidence >= CONFIDENCE_THRESHOLD
            else None
        )

        # ===== PDF RECOMMENDATIONS =====
        recommended_pdfs = []
        try:
            if intent == "IA_ACCESS_ISSUE" and retrieval and not is_greeting:
                recommended_pdfs = get_recommendations_for_chat(
                    retrieval_result=retrieval,
                    platform=platform,
                    query=message
                )
                print(f"📄 Recommending {len(recommended_pdfs)} PDFs")
        except Exception as e:
            print(f"⚠️  PDF recommendation failed: {e}")
            recommended_pdfs = []

        # ✨ PRINT PERFORMANCE METRICS
        print(f"\n⏱️  PERFORMANCE METRICS:")
        print(f"   Retrieval: {retrieval_time_ms:.2f}ms")
        print(f"   LLM: {llm_time_ms:.2f}ms")
        print(f"   Total: {total_time_ms:.2f}ms\n")

        return ChatResponse(
            reply=reply,
            source=source,
            article_link=article_link,
            confidence=confidence,
            retrieval_time_ms=round(retrieval_time_ms, 2),
            llm_time_ms=round(llm_time_ms, 2),
            total_time_ms=round(total_time_ms, 2),
            recommended_pdfs=recommended_pdfs
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
        "elapsed_ms": round(elapsed * 1000, 2),
        "reply_length": len(reply),
        "reply_preview": reply[:200] + "..."
    }


# ✨ NEW: Model comparison endpoint
@app.post("/debug/compare-models")
def compare_models(payload: ChatRequest):
    """
    Compare response times across different models.
    Requires manually switching models in llama_client.py
    """
    results = []
    
    # You would need to modify this to actually test different models
    # For now, it tests the current model multiple times
    for i in range(3):
        start = time.time()
        reply = llm.chat(
            message=payload.message,
            context="",
            history=[],
            system_hint=""
        )
        elapsed_ms = (time.time() - start) * 1000
        
        results.append({
            "run": i + 1,
            "elapsed_ms": round(elapsed_ms, 2),
            "reply_length": len(reply)
        })
    
    avg_time = sum(r["elapsed_ms"] for r in results) / len(results)
    
    return {
        "model": "llama3.2",  # Update this when you change models
        "message": payload.message,
        "runs": results,
        "average_ms": round(avg_time, 2),
        "min_ms": round(min(r["elapsed_ms"] for r in results), 2),
        "max_ms": round(max(r["elapsed_ms"] for r in results), 2)
    }
