from email.mime import message
from fastapi import FastAPI, HTTPException
from app.schemas.chat import ChatRequest, ChatResponse
from app.llm.llama_client import LlamaClient
from app.rag.retriever import FAQRetriever
from app.platform_registry import load_registry, internal_platform_key, canonical_platform_key
import asyncio
import os
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
FAQ_DIRECT_MIN_CONFIDENCE = float(os.getenv("FAQ_DIRECT_MIN_CONFIDENCE", "0.2"))
MAX_HISTORY_TURNS = 6
SESSION_TIMEOUT = timedelta(hours=1)
MAX_CONCURRENT_LLM_REQUESTS = int(os.getenv("MAX_CONCURRENT_LLM_REQUESTS", "2"))

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
llm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_REQUESTS)
chat_request_queue: asyncio.Queue[str] = asyncio.Queue()
chat_jobs: Dict[str, Dict[str, Any]] = {}
chat_workers: list[asyncio.Task] = []

PLATFORM_ALIASES: Dict[str, list[str]] = {
    "CENGAGE": ["cengage", "mindtap", "cnow", "cnowv2"],
    "MCGRAW_HILL": ["mcgraw", "mcgraw hill", "connect", "aleks"],
    "PEARSON": ["pearson", "mylab", "mastering"],
    "WILEY": ["wiley", "wileyplus"],
    "MACMILLAN": ["macmillan", "achieve"],
    "SAGE": ["sage", "vantage"],
    "BEDFORD": ["bedford", "bookshelf"],
    "CLIFTON": ["clifton", "cliftonstrengths", "strengthsquest"],
    "SIMUCASE": ["simucase", "simucace"],
    "ZYBOOKS": ["zybooks", "zybook"],
    "STUKENT": ["stukent"],
    "VITALSOURCE": ["vitalsource"],
    "INQUIZITIVE": [
        "inquizitive",
        "inquizitve",
        "inquiztive",
        "inquisitive",
        "little seagull",
        "norton",
        "seagull handbook",
    ],
}

PLATFORM_DISPLAY_NAMES: Dict[str, str] = {
    "CENGAGE": "Cengage MindTap",
    "MCGRAW_HILL": "McGraw Hill Connect",
    "PEARSON": "Pearson MyLab/Mastering",
    "WILEY": "WileyPlus",
    "MACMILLAN": "Macmillan Achieve",
    "SAGE": "Sage Vantage",
    "BEDFORD": "Bedford Bookshelf",
    "CLIFTON": "CliftonStrengths",
    "SIMUCASE": "SimuCase",
    "ZYBOOKS": "zyBooks",
    "STUKENT": "Stukent",
    "VITALSOURCE": "VitalSource",
    "INQUIZITIVE": "InQuizitive",
}

# Merge dynamic registry entries (added by add_instruction.py)
_registry = load_registry()
for _platform_key, _aliases in _registry.get("platform_aliases", {}).items():
    _internal_key = internal_platform_key(_platform_key)
    existing_aliases = set(PLATFORM_ALIASES.get(_internal_key, []))
    for _alias in _aliases:
        if isinstance(_alias, str) and _alias.strip():
            existing_aliases.add(_alias.strip().lower())
    # Ensure canonical key itself is always an alias.
    existing_aliases.add(canonical_platform_key(_platform_key).replace("_", " "))
    existing_aliases.add(canonical_platform_key(_platform_key))
    PLATFORM_ALIASES[_internal_key] = sorted(existing_aliases)

for _platform_key, _display in _registry.get("platform_display_names", {}).items():
    _internal_key = internal_platform_key(_platform_key)
    if isinstance(_display, str) and _display.strip():
        PLATFORM_DISPLAY_NAMES[_internal_key] = _display.strip()


def detect_platforms_from_text(text: str) -> list[str]:
    """
    Return all matching platform keys from message text.
    """
    normalized = text.lower()
    matches: list[str] = []
    for platform_key, aliases in PLATFORM_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            matches.append(platform_key)
    return matches


def detect_platform_from_text(text: str) -> str | None:
    """
    Return the first matched platform key, or None.
    """
    matches = detect_platforms_from_text(text)
    return matches[0] if matches else None


def resolve_platform_correction(text: str) -> str | None:
    """
    Resolve explicit correction statements like:
      - "Cengage not McGraw"
      - "Cengage instead of McGraw"
    Returns the intended platform key when identifiable.
    """
    msg_lower = text.lower()
    platforms_found = detect_platforms_from_text(text)
    for primary in platforms_found:
        primary_aliases = PLATFORM_ALIASES.get(primary, [])
        for other in platforms_found:
            if other == primary:
                continue
            other_aliases = PLATFORM_ALIASES.get(other, [])
            primary_hit = next((a for a in primary_aliases if a in msg_lower), None)
            other_hit = next((a for a in other_aliases if a in msg_lower), None)
            if not primary_hit or not other_hit:
                continue
            patterns = [
                rf"\b{re.escape(primary_hit)}\b\s+not\s+\b{re.escape(other_hit)}\b",
                rf"\b{re.escape(primary_hit)}\b\s+instead of\s+\b{re.escape(other_hit)}\b",
                rf"\bnot\s+\b{re.escape(other_hit)}\b.*\b{re.escape(primary_hit)}\b",
            ]
            if any(re.search(p, msg_lower) for p in patterns):
                return primary
    return None


async def retrieve_async(query: str, collection: str = "auto", platform: str = None):
    """Run sync FAISS retrieval in a worker thread to avoid blocking the event loop."""
    return await asyncio.to_thread(
        retriever.retrieve,
        query,
        1,
        collection,
        platform
    )


async def call_llm_with_semaphore(
    message: str,
    context: str,
    history: list,
    system_hint: str
) -> tuple[str, float]:
    """
    Queue LLM requests behind a semaphore so concurrent users do not over-saturate the GPU.
    Returns (reply, queue_wait_ms).
    """
    queued_at = time.time()
    async with llm_semaphore:
        queue_wait_ms = (time.time() - queued_at) * 1000
        reply = await asyncio.to_thread(
            llm.chat,
            message,
            context,
            history,
            system_hint
        )
        return reply, queue_wait_ms


def get_queue_position(request_id: str) -> int:
    """
    Return 1-based queue position for queued requests, 0 otherwise.
    """
    try:
        queue_items = list(chat_request_queue._queue)  # noqa: SLF001 - internal deque is reliable for read-only status
        if request_id in queue_items:
            return queue_items.index(request_id) + 1
    except Exception:
        return 0
    return 0


async def chat_queue_worker(worker_id: int):
    """
    Background worker that processes queued chat requests.
    """
    print(f"[QUEUE] Worker {worker_id} started")
    while True:
        request_id = await chat_request_queue.get()
        job = chat_jobs.get(request_id)
        if not job:
            chat_request_queue.task_done()
            continue

        try:
            job["status"] = "running"
            job["started_at"] = datetime.now().isoformat()
            result = await process_chat_request(job["payload"])
            job["status"] = "done"
            job["result"] = result.model_dump()
            job["completed_at"] = datetime.now().isoformat()
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["completed_at"] = datetime.now().isoformat()
        finally:
            chat_request_queue.task_done()


@app.on_event("startup")
async def start_chat_queue_workers():
    """
    Start queue workers once on app startup.
    """
    if chat_workers:
        return
    for i in range(MAX_CONCURRENT_LLM_REQUESTS):
        task = asyncio.create_task(chat_queue_worker(i + 1))
        chat_workers.append(task)


@app.on_event("shutdown")
async def stop_chat_queue_workers():
    """
    Cancel queue workers on shutdown.
    """
    for task in chat_workers:
        task.cancel()
    if chat_workers:
        await asyncio.gather(*chat_workers, return_exceptions=True)
    chat_workers.clear()


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
    
    # Platform mentions include aliases from PLATFORM_ALIASES plus textbook synonyms.
    mentions_platform_or_textbook = (
        detect_platform_from_text(normalized) is not None
        or any(word in normalized for word in [
            "ebook", "e-book", "etext", "e-text", "textbook", "text book", "etextbook", "e-textbook"
        ])
    )

    print(f"🔍 [INTENT DEBUG] has_ia_keyword={has_ia_keyword}, mentions_platform_or_textbook={mentions_platform_or_textbook}")
    
    if has_ia_keyword and mentions_platform_or_textbook:
        return "IA_ACCESS_ISSUE"

    # Platform correction messages like "Actually it's Cengage not McGraw"
    # should stay in access/troubleshooting flow.
    if detect_platform_from_text(normalized) and any(
        word in normalized for word in ["actually", "instead of", "not "]
    ):
        return "IA_ACCESS_ISSUE"

    # Treat informational questions as GENERAL_FAQ only when they are not IA/platform access issues.
    if any(pattern in normalized for pattern in informational_patterns):
        print(f"🔍 [INTENT DEBUG] Informational question detected")
        return "GENERAL_FAQ"
    
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


def extract_faq_answer(context: str) -> str | None:
    """
    Extract the ANSWER section from a FAQ chunk.
    Expected format includes:
      QUESTION:
      ...
      ANSWER:
      ...
      Article link: ...
    """
    if not context or "ANSWER:" not in context:
        return None

    start = context.find("ANSWER:")
    if start == -1:
        return None
    answer = context[start + len("ANSWER:"):].strip()

    # Remove trailing article link line from the body if present.
    answer = re.sub(r'Article link:\s*"?[^"\n]+"?\s*$', "", answer, flags=re.IGNORECASE).strip()
    return answer if answer else None


def strip_article_link_lines(text: str) -> str:
    """Remove any `Article link: ...` lines from model or retrieval output."""
    if not text:
        return text
    cleaned = re.sub(r'(?im)^\s*Article link:\s*"?[^"\n]+"?\s*$', "", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def is_meta_or_greeting_misfire(reply: str) -> bool:
    """Detect model outputs that are meta/greeting instead of answering the user."""
    if not reply:
        return False
    normalized = reply.lower()
    return any(
        marker in normalized
        for marker in [
            "since the user only says",
            "i will give a greeting",
            "what can i help you with today",
            "hi! i'm lance",
        ]
    )


def build_instruction_fallback_from_context(context: str, platform: str | None) -> str | None:
    """
    Convert retrieved instruction context into a user-facing fallback answer.
    Used only when model output is clearly a greeting/meta misfire.
    """
    if not context:
        return None

    text = context.replace("\ufeff", "").strip()
    # Remove source/file prefix, if present.
    text = re.sub(r"^\[SOURCE_\d+\]\s*\[FILE:[^\]]+\]\s*", "", text, flags=re.IGNORECASE).strip()

    lines = [ln.strip() for ln in text.splitlines()]
    cleaned_lines = []
    for ln in lines:
        if not ln:
            cleaned_lines.append("")
            continue
        lower = ln.lower()
        if lower.startswith("platform:"):
            continue
        if lower.startswith("issue type:"):
            continue
        if lower.startswith("program:"):
            continue
        if lower.startswith("last updated:"):
            continue
        if ln == "---":
            continue
        cleaned_lines.append(ln)

    body = "\n".join(cleaned_lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not body:
        return None

    display = PLATFORM_DISPLAY_NAMES.get(platform or "", platform or "your platform")
    if not body.lower().startswith("here's how"):
        body = f"Here's how to access {display}:\n\n{body}"
    return body


def classify_platform_type_reply(message: str) -> str:
    """
    Classify a clarification follow-up as:
      - TEXTBOOK_EBOOK
      - COURSEWARE_PLATFORM
      - UNKNOWN
    Negation-aware so phrases like "textbook not platform" are handled correctly.
    """
    m = message.lower()
    textbook_terms = ["textbook", "ebook", "e-book", "etext", "e-text", "etextbook", "e-textbook", "book"]
    courseware_terms = [
        "platform", "courseware", "mindtap", "connect", "mylab",
        "mastering", "inquizitive", "inquisitive"
    ]

    has_textbook = any(t in m for t in textbook_terms)
    has_courseware = any(t in m for t in courseware_terms)
    has_not = "not" in m

    # Negation-first checks
    if has_textbook and has_courseware and has_not:
        if "not platform" in m or "not courseware" in m:
            return "TEXTBOOK_EBOOK"
        if "not textbook" in m or "not ebook" in m or "not e-book" in m:
            return "COURSEWARE_PLATFORM"

    # Positive-only checks
    if has_textbook and not has_courseware:
        return "TEXTBOOK_EBOOK"
    if has_courseware and not has_textbook:
        return "COURSEWARE_PLATFORM"

    # Mixed without clear negation target is ambiguous
    if has_textbook and has_courseware:
        return "UNKNOWN"

    return "UNKNOWN"


def is_out_of_scope_query(message: str) -> bool:
    """
    Lightweight keyword check for obvious non-campus-store topics.
    """
    m = message.lower()
    out_of_scope_keywords = [
        "parking permit",
        "parking permits",
        "parking pass",
        "parking services",
        "housing",
        "dorm",
        "meal plan",
        "financial aid",
        "scholarship",
        "transcript",
        "registrar",
        "admissions",
        "tuition payment",
    ]
    return any(k in m for k in out_of_scope_keywords)


def detect_platform_and_check_ambiguity(message: str) -> tuple[str, bool]:
    """
    Returns: (platform, is_ambiguous)
    """
    platforms_found = detect_platforms_from_text(message)
    corrected = resolve_platform_correction(message)
    if corrected:
        print(f"🔍 DEBUG: Negation/correction detected - choosing {corrected}")
        return corrected, False
    
    print(f"🔍 DEBUG: Platforms found = {[p.lower() for p in platforms_found]}")
    
    if len(platforms_found) > 1:
        print(f"🔍 DEBUG: AMBIGUOUS - returning (None, True)")
        return None, True
    elif len(platforms_found) == 1:
        print(f"🔍 DEBUG: Single platform - returning ({platforms_found[0]}, False)")
        return platforms_found[0], False
    else:
        print(f"🔍 DEBUG: No platform - returning (None, False)")
        return None, False


def detect_topic_switch(message: str, stored_intent: str, stored_platform: str | None = None) -> bool:
    """Detect if user is switching topics."""
    current_intent = detect_intent(message)
    detected_platform = detect_platform_from_text(message)
    
    if stored_intent == "IA_ACCESS_ISSUE" and current_intent == "GENERAL_FAQ":
        return True
    
    if stored_intent == "IA_ACCESS_ISSUE" and current_intent == "AMBIGUOUS_PLATFORM":
        return True

    # If user now mentions a platform explicitly, treat it as a topic switch so we don't
    # keep following the previous platform's course-code flow.
    if stored_intent == "IA_ACCESS_ISSUE" and detected_platform is not None:
        if stored_platform is None:
            return True
        if detected_platform != stored_platform:
            return True

    # Session-aware correction phrases should always count as topic switch.
    msg_lower = message.lower()
    if stored_platform and ("not " in msg_lower or "instead of" in msg_lower):
        mentioned_platforms = detect_platforms_from_text(message)
        if any(p != stored_platform for p in mentioned_platforms):
            return True
    
    topic_switch_keywords = ["actually", "instead", "what about", "by the way", "nevermind"]
    return any(keyword in message.lower() for keyword in topic_switch_keywords)


def is_ambiguous_platform_query(message: str) -> tuple[str | None, bool]:
    """
    Check if query mentions a publisher without specifying textbook vs platform.
    Returns: (publisher_name, is_ambiguous)
    """
    msg_lower = message.lower()
    corrected = resolve_platform_correction(message)
    if corrected:
        return corrected, False
    
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

    # InQuizitive is always a courseware platform query (not ambiguous textbook-vs-platform).
    inquizitive_terms = [
        "inquizitive",
        "inquizitve",
        "inquiztive",
        "inquisitive",
    ]
    norton_terms = [
        "norton",
        "little seagull",
        "seagull handbook",
    ]
    textbook_terms = ["textbook", "etextbook", "ebook", "e-book", "etext", "e-text"]

    # Explicit InQuizitive mention is specific enough.
    if any(term in msg_lower for term in inquizitive_terms):
        return "INQUIZITIVE", False

    # Norton publisher mention may be ambiguous (Norton eTextbook vs Norton InQuizitive),
    # mirroring Cengage/McGraw/Pearson clarification behavior.
    if any(term in msg_lower for term in norton_terms):
        if any(term in msg_lower for term in textbook_terms):
            return "INQUIZITIVE", False
        return "INQUIZITIVE", True
    
    # ✨ UPDATED: Immediate Access without platform
    if "immediate access" in msg_lower:
        # Check for troubleshooting keywords
        troubleshooting_keywords = [
            "can't access", "cannot access", "unable to access",
            "not working", "doesn't work", "trouble", "issue", "problem"
        ]
        
        has_trouble_keyword = any(keyword in msg_lower for keyword in troubleshooting_keywords)
        has_platform_mention = (
            detect_platform_from_text(msg_lower) is not None
            or any(word in msg_lower for word in ["ebook", "e-book", "etext", "e-text"])
        )
        
        # Only trigger clarification if:
        # 1. They have a troubleshooting issue AND
        # 2. No platform is mentioned
        if has_trouble_keyword and not has_platform_mention:
            return "IMMEDIATE_ACCESS", True
    
    return None, False


async def process_chat_request(payload: ChatRequest) -> ChatResponse:
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
        explicit_textbook_selection = False
        
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
            elif publisher == "INQUIZITIVE":
                clarification = (
                    "I can help you with Norton! To give you the most accurate instructions, "
                    "could you please specify: Are you trying to access a **Norton textbook** "
                    "or **Norton InQuizitive**?"
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
            platform_type_reply = classify_platform_type_reply(message)

            low_info_responses = [
                "i don't know",
                "i dont know",
                "not sure",
                "no idea",
                "idk",
                "i'm not sure",
                "im not sure",
                "don't know",
                "do not know",
                "unsure",
            ]
            is_low_info_response = any(phrase in msg_lower for phrase in low_info_responses)

            # Keep clarification state open and do not run retrieval when the student
            # explicitly says they don't know the platform yet.
            if is_low_info_response:
                redirect_reply = (
                    "No worries! You can usually find the platform name on your Blackboard "
                    "course page under the Immediate Access tab. It will say something like "
                    "\"Cengage MindTap,\" \"McGraw Hill Connect,\" or \"Pearson MyLab.\" "
                    "Once you find it, let me know and I can walk you through the steps. "
                    "You can also visit the CBU Campus Store for in-person help."
                )

                session["history"].append({
                    "role": "user",
                    "content": message
                })
                session["history"].append({
                    "role": "assistant",
                    "content": redirect_reply
                })

                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=redirect_reply,
                    source="CLARIFICATION_NEEDED",
                    article_link=None,
                    confidence=0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=0,
                    llm_time_ms=0
                )
            
            # Handle textbook/platform clarification replies
            if publisher == "TEXTBOOK_GENERIC":
                intent = "IA_ACCESS_ISSUE"
                platform = detect_platform_from_text(msg_lower)
                
                # ✨ Use original query + platform for better retrieval
                if platform and original_query:
                    enhanced_query = f"{original_query} {platform} access instructions"
                    print(f"🔍 [QUERY DEBUG] Enhanced query: {enhanced_query}")

            elif platform_type_reply == "TEXTBOOK_EBOOK":
                intent = "IA_ACCESS_ISSUE"
                platform = None
                explicit_textbook_selection = True
                # Force general ebook/textbook instructions path.
                enhanced_query = "eTextbook immediate access general instructions VitalSource Blackboard step-by-step"
            elif platform_type_reply == "COURSEWARE_PLATFORM":
                intent = "IA_ACCESS_ISSUE"
                if publisher in PLATFORM_ALIASES:
                    platform = publisher
                else:
                    platform = detect_platform_from_text(msg_lower)
            else:
                intent = "IA_ACCESS_ISSUE"
                platform = None

            if platform is None:
                # If this was a textbook/ebook selection, skip platform requirement and
                # continue with general instructions retrieval.
                if platform_type_reply == "TEXTBOOK_EBOOK":
                    print("🔍 [STATE DEBUG] Textbook/Ebook clarification detected; using general instructions")
                else:
                    followup_reply = (
                        "I still need the platform name to give the correct steps. "
                        "Please share which one you see in Blackboard Immediate Access "
                        "(for example: Cengage MindTap, McGraw Hill Connect, or Pearson MyLab)."
                    )
                    session["history"].append({
                        "role": "user",
                        "content": message
                    })
                    session["history"].append({
                        "role": "assistant",
                        "content": followup_reply
                    })
                    total_time = (time.time() - request_start) * 1000
                    return ChatResponse(
                        reply=followup_reply,
                        source="CLARIFICATION_NEEDED",
                        article_link=None,
                        confidence=0.0,
                        total_time_ms=round(total_time, 2),
                        retrieval_time_ms=0,
                        llm_time_ms=0
                    )

            # Only clear platform-clarification state once we actually have a platform.
            if platform is not None or platform_type_reply == "TEXTBOOK_EBOOK":
                session["awaiting_platform_type"] = False
                session["stored_publisher"] = None
                session["stored_original_query"] = None  # ✨ Clear stored query
            course_code = extract_course_code(message)
            
            if platform is None:
                platform = detect_platform_from_text(message)
            
            print(f"🔍 [PLATFORM DEBUG] Detected platform: {platform}")

            # ✨ ADD THIS ELIF BLOCK FOR COURSE CODE HANDLING
        elif session.get("awaiting_course_code", False):
            if detect_topic_switch(message, session["stored_intent"], session.get("stored_platform")):
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
                    "textbook or norton inquizitive",
                    "cengage textbook or cengage mindtap",
                    "mcgraw hill textbook or mcgraw hill connect",
                    "pearson textbook or pearson mylab",
                    "norton textbook or norton inquizitive",
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
                platform = detect_platform_from_text(message)
            
            print(f"🔍 [PLATFORM DEBUG] Detected platform: {platform}")

        # NOW the intent is set!
        # 1. Intent detection happens somewhere up here
        print(f"🔍 [INTENT DEBUG] Final intent: {intent}")

        # 2. Platform detection
        print(f"🔍 [PLATFORM DEBUG] Detected platform: {platform}")

        # Out-of-scope guard for obvious non-campus-store topics.
        if intent == "GENERAL_FAQ" and is_out_of_scope_query(message):
            out_of_scope_reply = (
                "I can help with Campus Store topics like Immediate Access, textbook access, "
                "returns, and related policies. For parking permits, please check the appropriate "
                "CBU parking/transportation office resources."
            )
            session["history"].append({
                "role": "user",
                "content": message
            })
            session["history"].append({
                "role": "assistant",
                "content": out_of_scope_reply
            })
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=out_of_scope_reply,
                source="LLM_ONLY",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[]
            )

        # Do not require course code up front for IA troubleshooting.
        # Platform/publisher is the primary disambiguation input.
        if intent == "IA_ACCESS_ISSUE":
            session["awaiting_course_code"] = False
            session["stored_intent"] = None
            session["stored_platform"] = None

        is_vague_query = (
            intent == "IA_ACCESS_ISSUE" and
            platform is None and
            not explicit_textbook_selection and
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
                
                retrieval = await retrieve_async(
                    enhanced_query,
                    collection="instructions",
                    platform=platform
                )
            elif course_code:
                enhanced_query = enhance_query_with_conversation_context(message, session["history"])
                retrieval = await retrieve_async(
                    enhanced_query,
                    collection="instructions",
                    platform=platform
                )
            elif intent == "GENERAL_FAQ":
                retrieval = await retrieve_async(
                    message,
                    collection="faqs"
                )
            else:
                retrieval = await retrieve_async(message)

            if retrieval and "context" in retrieval:
                context = retrieval["context"]
            
            # ✨ END RETRIEVAL TIMER
            retrieval_time_ms = (time.time() - retrieval_start) * 1000

        except AttributeError as e:
            print(f"⚠️  Platform-specific index not found ({e}), falling back to general index")
            try:
                retrieval = await retrieve_async(
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

        # Deterministic FAQ response path: return the retrieved FAQ answer directly
        # to avoid hallucinated policy/instruction steps.
        if intent == "GENERAL_FAQ" and retrieval and retrieval.get("source_id", "").startswith("FAQ_SOURCE_"):
            faq_confidence = float(retrieval.get("score") or 0.0)
            if faq_confidence < FAQ_DIRECT_MIN_CONFIDENCE:
                low_conf_reply = (
                    "I want to make sure I give you accurate Campus Store information. "
                    "Could you clarify your question in terms of Immediate Access, textbook access, "
                    "returns, or course-material policies?"
                )
                session["history"].append({
                    "role": "assistant",
                    "content": low_conf_reply
                })
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=low_conf_reply,
                    source="LLM_ONLY",
                    article_link=None,
                    confidence=faq_confidence,
                    retrieval_time_ms=round(retrieval_time_ms, 2),
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[]
                )

            faq_answer = extract_faq_answer(context)
            if faq_answer:
                reply = strip_article_link_lines(faq_answer)

                session["history"].append({
                    "role": "assistant",
                    "content": reply
                })
                if len(session["history"]) > MAX_HISTORY_TURNS * 2:
                    session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]

                total_time_ms = (time.time() - request_start) * 1000
                confidence = retrieval["score"]
                source = retrieval["source_id"]
                article_link = retrieval.get("article_link")

                print(f"\n⏱️  PERFORMANCE METRICS:")
                print(f"   Retrieval: {retrieval_time_ms:.2f}ms")
                print(f"   LLM: 0.00ms (FAQ direct answer)")
                print(f"   Total: {total_time_ms:.2f}ms\n")

                return ChatResponse(
                    reply=reply,
                    source=source,
                    article_link=article_link,
                    confidence=confidence,
                    retrieval_time_ms=round(retrieval_time_ms, 2),
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[]
                )

        # Deterministic instruction response path for instruction retrieval.
        # This avoids LLM variability (greeting/meta leakage, meta commentary) when docs are available.
        if (
            intent == "IA_ACCESS_ISSUE"
            and retrieval
            and retrieval.get("source_id", "").startswith("INSTR_")
            and context
            and (platform is not None or explicit_textbook_selection)
        ):
            direct_platform = platform if platform is not None else "TEXTBOOK_EBOOK"
            direct_instruction = build_instruction_fallback_from_context(context, direct_platform)
            if direct_instruction and explicit_textbook_selection and platform is None:
                # Normalize heading for textbook clarification branch.
                direct_instruction = re.sub(
                    r"^Here's how to access [^:]+:",
                    "Here's how to access your eTextbook:",
                    direct_instruction,
                    flags=re.IGNORECASE,
                )
            if direct_instruction:
                session["history"].append({
                    "role": "assistant",
                    "content": direct_instruction
                })
                if len(session["history"]) > MAX_HISTORY_TURNS * 2:
                    session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]

                recommended_pdfs = []
                try:
                    recommended_pdfs = get_recommendations_for_chat(
                        retrieval_result=retrieval,
                        platform=platform,
                        query=message
                    )
                    print(f"📄 Recommending {len(recommended_pdfs)} PDFs")
                except Exception as e:
                    print(f"⚠️  PDF recommendation failed: {e}")
                    recommended_pdfs = []

                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=direct_instruction,
                    source=retrieval["source_id"],
                    article_link=None,
                    confidence=float(retrieval.get("score") or 0.0),
                    retrieval_time_ms=round(retrieval_time_ms, 2),
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=recommended_pdfs
                )
            
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
                "If required information is missing, ask for the platform/publisher first "
                "(for example: Cengage, McGraw Hill, Pearson, Norton/InQuizitive). "
                "Do NOT ask for course code unless platform is already known and a course-specific step truly requires it. "
                "Do NOT assume availability of print textbooks. "
                "Only provide instructions for the specific platform mentioned in the official instructions."
            )

        # ✨ START LLM TIMER
        llm_start = time.time()
        
        reply, llm_queue_wait_ms = await call_llm_with_semaphore(
            message=message,
            context=context,
            history=session["history"][-MAX_HISTORY_TURNS:],
            system_hint=system_hint
        )
        reply = strip_article_link_lines(reply)

        # Safety fallback: for platform-specific IA queries, never return greeting/meta text.
        if (
            intent == "IA_ACCESS_ISSUE"
            and platform is not None
            and retrieval
            and retrieval.get("source_id", "").startswith("INSTR_")
            and is_meta_or_greeting_misfire(reply)
        ):
            fallback_reply = build_instruction_fallback_from_context(context, platform)
            if fallback_reply:
                print("⚠️ [LLM GUARD] Detected greeting/meta misfire; using context-derived fallback")
                reply = fallback_reply
        
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
        print(f"   LLM Queue Wait: {llm_queue_wait_ms:.2f}ms")
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


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    """
    Backward-compatible synchronous endpoint.
    """
    return await process_chat_request(payload)


@app.post("/chat/submit", status_code=202)
async def chat_submit(payload: ChatRequest):
    """
    Queue-first endpoint:
    - returns immediately with request_id
    - client polls /chat/status/{request_id}
    """
    request_id = str(uuid.uuid4())
    enqueued_at = datetime.now().isoformat()
    chat_jobs[request_id] = {
        "request_id": request_id,
        "status": "queued",
        "payload": payload,
        "result": None,
        "error": None,
        "enqueued_at": enqueued_at,
        "started_at": None,
        "completed_at": None,
    }
    await chat_request_queue.put(request_id)

    return {
        "request_id": request_id,
        "status": "queued",
        "queue_position": get_queue_position(request_id),
        "enqueued_at": enqueued_at,
    }


@app.get("/chat/status/{request_id}")
async def chat_status(request_id: str):
    """
    Poll status endpoint for queued chat requests.
    """
    job = chat_jobs.get(request_id)
    if not job:
        raise HTTPException(status_code=404, detail="request_id not found")

    status = job["status"]
    response = {
        "request_id": request_id,
        "status": status,
        "queue_position": get_queue_position(request_id) if status == "queued" else 0,
        "enqueued_at": job["enqueued_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "error": job["error"],
    }

    if status == "done":
        response["result"] = job["result"]

    return response


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
