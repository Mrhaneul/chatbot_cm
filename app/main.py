from dotenv import load_dotenv
load_dotenv()
import json
from email.mime import message
from fastapi import FastAPI, HTTPException, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.llm.llama_client import (
    LlamaClient,
    build_system_prompt,
    build_grounded_prompt,
    build_vision_system_prompt,
    check_ollama_health,
    get_ollama_model_availability,
    stream_llm_response,
    stream_llm_chat_response,
)
# from app.rag.retriever import FAQRetriever  # Deprecated import
from app.rag.retriever import get_retriever  # New singleton accessor
from app.platform_registry import load_registry, internal_platform_key, canonical_platform_key
import asyncio
import os
import re
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any
import uuid
import time
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
try:
    from app.pdf_recommendations import get_recommendations_for_chat
except Exception:
    # Fallback stub when PDF recommendation module is unavailable (e.g., missing firebase_admin)
    def get_recommendations_for_chat(*args, **kwargs):
        return []
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import yaml
from app.rag.config import cfg
from app.rag.model import get_model
from app.rag.grounding_verifier import verify_answer_grounding, GROUNDING_SAFE_FALLBACK
from app.quick_help_routes import build_quick_help_match
from app.safety import run_safety_gate, get_safety_response, safety_source_label
from app.safety.deterministic_rules import check_deterministic as _safety_check_deterministic

from app.utils.logging_config import configure_logging
from app.config.loader import (
    PLATFORM_ALIASES,
    PLATFORM_DISPLAY_NAMES,
    PLATFORM_RETRIEVAL_KEY,
    PUBLISHER_LIST_TEXT,
    PUBLISHER_LIST_MAP,
    GREETING_KEYWORDS,
    GREETING_REPLY,
    PLATFORM_CLARIFICATION_MESSAGE,
    IA_KEYWORDS,
    OPT_OUT_POLICY_SIGNALS,
    OPT_OUT_TROUBLESHOOTING_EXCLUSIONS,
    INFORMATIONAL_PATTERNS,
    PLATFORMS_FOR_API,
)

from app.intake.models import IntakeProfile
from app.intake.flow import (
    should_enter_intake,
    update_profile,
    next_question as intake_next_question,
    intake_is_complete,
    intake_fallback_message,
)
from app.intake.llm_planner import run_intake_planner, should_run_planner, get_question_for_decision

from app.admin import admin_router
from app.feedback import feedback_router
from fastapi.responses import FileResponse
from app.admin_auth import verify_admin_credentials
from fastapi import Depends
from fastapi.security import HTTPBasicCredentials

# Configure logging once at startup
def parse_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_csv_env(name: str, default: str) -> list[str]:
    raw_value = os.getenv(name, default)
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    return values or [default]


def strip_meta_prefix(context: str) -> str:
    """Remove the [META:{...}] header from a retrieved context chunk.

    Handles leading BOM characters and whitespace before the tag.
    """
    # Strip BOM and surrounding whitespace before checking
    cleaned = context.replace("\ufeff", "").strip()
    if cleaned.startswith("[META:"):
        newline_pos = cleaned.find("\n")
        if newline_pos != -1:
            return cleaned[newline_pos + 1:].strip()
    return cleaned


def extract_step_by_step(content: str) -> str:
    """
    Extract just the numbered step-by-step resolution from an instruction
    file chunk, discarding boilerplate sections (PROBLEM, APPLIES TO,
    BLACKBOARD LOCATION, EXPECTED RESULT, IF ISSUE PERSISTS).

    Falls back to returning the full content if no STEP-BY-STEP section
    is found (so the response is never empty).
    """
    match = re.search(
        r"STEP-BY-STEP RESOLUTION:\s*\n(.*?)(?=\nEXPECTED RESULT:|\nIF ISSUE PERSISTS:|$)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return content



CONFIDENCE_THRESHOLD = 0.1
FAQ_DIRECT_MIN_CONFIDENCE = float(os.getenv("FAQ_DIRECT_MIN_CONFIDENCE", "0.2"))
# Minimum rerank_score for a FAQ pre-check result to suppress clarification
FAQ_PRECHECK_CONFIDENCE_THRESHOLD = 0.55
MAX_HISTORY_TURNS = 6
SESSION_TIMEOUT = timedelta(hours=1)
MAX_CONCURRENT_LLM_REQUESTS = int(os.getenv("MAX_CONCURRENT_LLM_REQUESTS", "2"))
GROUNDING_TOP_K = int(os.getenv("GROUNDING_TOP_K", "3"))
CORS_ORIGINS = parse_csv_env("CORS_ORIGINS", "http://localhost:3000")
ENABLE_DEBUG_ROUTES = parse_bool_env("ENABLE_DEBUG_ROUTES", default=False)
ENABLE_SAFETY_FILTER = parse_bool_env("ENABLE_SAFETY_FILTER", default=True)
ENABLE_SAFETY_CLASSIFIER = parse_bool_env("ENABLE_SAFETY_CLASSIFIER", default=True)

# Create FastAPI app FIRST
app = FastAPI(title="Campus Store Chatbot (Session-Safe + Performance Tracking)")

# THEN define and add middleware
class NgrokMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["ngrok-skip-browser-warning"] = "true"
        return response

app.add_middleware(NgrokMiddleware)

app.include_router(admin_router)
app.include_router(feedback_router)

@app.get("/admin")
def admin_ui(username: str = Depends(verify_admin_credentials)):
    return FileResponse("lance_admin_ui.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)
# Session storage: session_id -> session_data
sessions: Dict[str, Dict[str, Any]] = {}

# Initialize services
llm = LlamaClient()
retriever = get_retriever()
llm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_REQUESTS)
chat_request_queue: asyncio.Queue[str] = asyncio.Queue()
chat_jobs: Dict[str, Dict[str, Any]] = {}
chat_workers: list[asyncio.Task] = []


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    model_status = await get_ollama_model_availability()
    payload = {
        "status": "ready",
        "ollama_reachable": bool(model_status["ollama_reachable"]),
        "primary_model": model_status["primary_model"],
        "primary_model_available": bool(model_status["primary_model_available"]),
        "fallback_model": model_status["fallback_model"],
        "fallback_model_available": bool(model_status["fallback_model_available"]),
        "faq_index_loaded": retriever.faq_index is not None,
        "instructions_index_loaded": retriever.instructions_index is not None,
        "warnings": list(model_status["warnings"]),
    }
    is_ready = (
        payload["ollama_reachable"]
        and payload["primary_model_available"]
        and payload["fallback_model_available"]
        and payload["faq_index_loaded"]
        and payload["instructions_index_loaded"]
    )
    if is_ready:
        return payload
    payload["status"] = "not_ready"
    raise HTTPException(status_code=503, detail=payload)

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
    Uses word-boundary matching to avoid false positives (e.g. 'sage' inside 'message').
    """
    normalized = text.lower()
    matches: list[str] = []
    for platform_key, aliases in PLATFORM_ALIASES.items():
        if any(re.search(r"\b" + re.escape(alias) + r"\b", normalized) for alias in aliases):
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


async def retrieve_async(query: str, collection: str = "auto", platform: str = None, top_k: int = 1):
    """Run sync FAISS retrieval in a worker thread to avoid blocking the event loop."""
    return await asyncio.to_thread(
        retriever.retrieve,
        query,
        top_k,
        collection,
        platform
    )


async def retrieve_faq_candidates(query: str, top_k: int = 5) -> list[dict]:
    """
    Retrieve top-k FAQ candidates as individual dicts for reranking.

    Each returned dict has:
        context   - the raw chunk text (single FAQ, not merged)
        score     - FAISS cosine similarity score
        source_id - e.g. "FAQ_SOURCE_3"

    Uses the retriever's internal FAQ search path so each candidate remains
    separate instead of being merged into one combined context blob.
    Falls back to empty list on any error.
    """
    try:
        def _retrieve_faq_candidates_sync() -> list[dict]:
            if retriever.faq_index is None:
                return []

            query_vector = get_model().encode([query], normalize_embeddings=True)
            query_vector = np.array(query_vector).astype("float32")
            results = retriever._search(retriever.faq_index, retriever.faq_chunks, query_vector, top_k)

            candidates: list[dict] = []
            for chunk, score, idx in results:
                source_id = f"FAQ_SOURCE_{idx}"
                candidates.append({
                    "context": chunk,
                    "score": score,
                    "source_id": source_id,
                    "article_link": retriever._extract_article_link(chunk),
                    "metadata": retriever._extract_metadata(chunk, source_id),
                })
            return candidates

        return await asyncio.to_thread(_retrieve_faq_candidates_sync)
    except Exception as e:
        print(f"[WARN] retrieve_faq_candidates failed: {e}")
        return []


def _extract_faq_question(context: str) -> str:
    """
    Extract the canonical QUESTION text from a FAQ chunk.
    FAQ files follow the format:
        QUESTION:
        <question text>
        ANSWER:
        ...
    Returns empty string if no QUESTION field found.
    """
    match = re.search(r"QUESTION:\s*\n(.+?)(?:\n\s*\n|\nANSWER:)", context, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _jaccard_overlap(text_a: str, text_b: str) -> float:
    """
    Token-level Jaccard similarity between two strings.
    Uses 3+ character alphanumeric tokens to filter noise.
    Returns 0.0 if either string is empty.
    """
    tokens_a = set(re.findall(r"[a-z0-9]{3,}", text_a.lower()))
    tokens_b = set(re.findall(r"[a-z0-9]{3,}", text_b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _is_overview_doc(context: str, source_id: str) -> bool:
    """
    Detect broad overview documents that should be penalized
    when the user query is specific.
    Checks source_id name and context content signals.
    """
    sid = source_id.lower()
    if "overview" in sid:
        return True
    # Check for overview signals in the canonical question
    question = _extract_faq_question(context).lower()
    overview_phrases = ["what is immediate access", "overview", "how does immediate access work"]
    return any(p in question for p in overview_phrases)


def _is_specific_query(query: str) -> bool:
    """
    Detect whether a query is specific/narrow (vs. general/broad).
    Specific queries contain concrete policy terms, error descriptions,
    or named actions that point to a narrow FAQ.
    """
    q = query.lower()
    specific_signals = [
        "restocking fee", "25%", "30 days", "60 days", "refund",
        "opt out", "cannot access", "can't access", "not allow",
        "physical copy", "physical textbook", "print copy",
        "isbn", "buy", "purchase",
        "missing", "bundle", "not showing",
        "return policy", "return window",
        "access code", "code",
        "opt out option",
        # Access problem language — student describing a specific error state
        "opted in",
        "already opted in",
        "got back",
        "this is what i got",
        "this is what i see",
        "but i still",
        "but it still",
        "still not",
        "still can't",
        "still cannot",
        "not working",
        "doesn't work",
        "won't load",
        "won't open",
        "can't get in",
        "cannot get in",
        "showing me",
        "it shows",
        "getting an error",
        "getting error",
        "error message",
        "keeps saying",
        "says it",
    ]
    return any(s in q for s in specific_signals)


def rerank_faq_candidates(candidates: list[dict], query: str) -> list[dict]:
    """
    Rerank FAQ candidates using a combination of:
        1. Semantic score     - FAISS cosine similarity (already computed)
        2. Question overlap   - Jaccard similarity between query and FAQ's QUESTION field
        3. Subtype bonus      - small bonus when source_id suggests a specific subtype match
        4. Broadness penalty  - penalize overview docs when query is specific

    Returns candidates sorted by rerank_score descending.
    Each dict gets a new "rerank_score" field added.

    Scoring weights (conservative - break ties, don't override semantics):
        semantic:          0.60
        question_overlap:  0.25
        specificity_bonus: 0.10  (applied when doc is NOT overview and query IS specific)
        broadness_penalty: 0.10  (subtracted when doc IS overview and query IS specific)
    """
    if not candidates:
        return []

    query_is_specific = _is_specific_query(query)

    scored = []
    for c in candidates:
        context = c.get("context", "")
        source_id = c.get("source_id", "")
        semantic = float(c.get("score", 0.0))

        # Extract canonical question for lexical overlap
        faq_question = _extract_faq_question(context)
        question_overlap = _jaccard_overlap(query, faq_question)

        # Broadness signals
        is_overview = _is_overview_doc(context, source_id)

        # Compute rerank score
        rerank_score = (
            0.60 * semantic
            + 0.25 * question_overlap
        )

        if query_is_specific:
            if not is_overview:
                rerank_score += 0.10  # specificity bonus
            else:
                rerank_score -= 0.20  # broadness penalty — increased from 0.10
        else:
            # Even for non-specific queries, apply a small penalty to overview docs
            # to prevent them winning on shared vocabulary alone (e.g. "immediate access"
            # appearing in both the query and the overview canonical question).
            if is_overview:
                rerank_score -= 0.08

        print(
            f"[RERANK] {source_id} | semantic={semantic:.4f} "
            f"q_overlap={question_overlap:.4f} overview={is_overview} "
            f"specific_query={query_is_specific} rerank={rerank_score:.4f}"
        )

        scored.append({**c, "rerank_score": rerank_score})

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored


async def faq_precheck(query: str) -> dict | None:
    """
    Run a fast top-5 FAQ retrieval + rerank before clarification branches fire.

    Returns the top reranked candidate dict if its rerank_score exceeds
    FAQ_PRECHECK_CONFIDENCE_THRESHOLD, otherwise returns None.

    Used to suppress clarification when an exact FAQ match already exists,
    e.g. "What should I do if a textbook is missing from my bundle?" should
    answer directly rather than triggering the VitalSource screen confirm flow.
    """
    try:
        candidates = await retrieve_faq_candidates(query, top_k=5)
        if not candidates:
            return None
        ranked = rerank_faq_candidates(candidates, query)
        if not ranked:
            return None
        top = ranked[0]
        score = top.get("rerank_score", 0.0)
        print(f"[FAQ PRECHECK] top={top.get('source_id')} rerank_score={score:.4f}")
        if score >= FAQ_PRECHECK_CONFIDENCE_THRESHOLD:
            return top
        return None
    except Exception as e:
        print(f"[FAQ PRECHECK] failed: {e}")
        return None


async def call_llm_with_semaphore(
    message: str,
    context: str,
    history: list,
    system_hint: str,
    image_base64: str | None = None,
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
            system_hint,
            image_base64,
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


def init_session() -> Dict[str, Any]:
    """Create a new session state object with global defaults."""
    now = datetime.now()
    return {
        "history": [],
        "awaiting_course_code": False,
        "awaiting_platform_type": False,
        "awaiting_vitalsource_screen_confirm": False,
        "awaiting_class_access_clarification": False,
        "stored_intent": None,
        "stored_platform": None,
        "ia_context": False,
        "stored_publisher": None,
        "ia_tab_missing_escalated": False,
        "last_activity": now,
        "created_at": now,
    }


def get_or_create_session(session_id: str) -> Dict[str, Any]:
    """
    Get existing session or create new one.
    Returns session data dictionary.
    """
    if session_id not in sessions:
        sessions[session_id] = init_session()
    
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
        print(f"[SESSION] Cleaned up expired session: {sid[:8]}...")
    
    if expired:
        print(f"[SESSION] Removed {len(expired)} expired sessions. Active: {len(sessions)}")


def detect_intent(message: str) -> str:
    """Detect user intent from message."""
    normalized = message.lower()

    # Opt-out and physical textbook policy questions must go to FAQ, not IA troubleshooting.
    # "access" in IA_KEYWORDS is too broad and would otherwise match "immediate access"
    # in a policy question, misrouting it to IA_ACCESS_ISSUE.
    # Guard: if troubleshooting context is present, the "opt out" text is likely
    # describing the Blackboard button ("Want to opt out?"), not asking about policy.
    if any(s in normalized for s in OPT_OUT_POLICY_SIGNALS) and not any(
        t in normalized for t in OPT_OUT_TROUBLESHOOTING_EXCLUSIONS
    ):
        return "GENERAL_FAQ"

    # Bundle admin questions are FAQ, not access troubleshooting.
    if is_bundle_admin_question(message):
        return "GENERAL_FAQ"

    if is_ia_enrollment_query(message):
        return "GENERAL_FAQ"

    if is_general_ia_question(message) or is_access_code_question(message):
        return "GENERAL_FAQ"

    # Check if any IA keyword is present AND mentions a platform OR textbook
    has_ia_keyword = any(keyword in normalized for keyword in IA_KEYWORDS)
    
    # Platform mentions include aliases from PLATFORM_ALIASES plus textbook synonyms.
    mentions_platform_or_textbook = (
        detect_platform_from_text(normalized) is not None
        or any(word in normalized for word in [
            "ebook", "e-book", "etext", "e-text", "textbook", "text book", "etextbook", "e-textbook"
        ])
    )

    print(f"[INTENT DEBUG] has_ia_keyword={has_ia_keyword}, mentions_platform_or_textbook={mentions_platform_or_textbook}")
    
    if has_ia_keyword and mentions_platform_or_textbook:
        return "IA_ACCESS_ISSUE"

    # Short platform-only follow-ups (e.g., "McGraw Hill Connect") should stay
    # in IA troubleshooting flow.
    if detect_platform_from_text(normalized) is not None and len(normalized.split()) <= 5:
        return "IA_ACCESS_ISSUE"

    # Platform correction messages like "Actually it's Cengage not McGraw"
    # should stay in access/troubleshooting flow.
    if detect_platform_from_text(normalized) and any(
        word in normalized for word in ["actually", "instead of", "not "]
    ):
        return "IA_ACCESS_ISSUE"

    # Treat informational questions as GENERAL_FAQ only when they are not IA/platform access issues.
    if any(pattern in normalized for pattern in INFORMATIONAL_PATTERNS):
        print("[INTENT DEBUG] Informational question detected")
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


def is_store_hours_query(message: str) -> bool:
    """Detect queries asking about store operating hours."""
    m = (message or "").lower()
    has_store_term = any(term in m for term in ["campus store", "store", "bookstore"])
    has_hours_term = any(term in m for term in ["hour", "hours", "open", "close", "closing", "opening", "time"])
    return has_store_term and has_hours_term


def context_contains_store_hours(context: str) -> bool:
    """Check whether retrieved text actually contains store-hours information."""
    c = (context or "").lower()
    if not c:
        return False

    has_hours_phrase = bool(re.search(r"\b(store\s+hours|hours\s+of\s+operation|business\s+hours)\b", c))
    has_weekday = bool(re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", c))
    has_time = bool(re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", c))
    has_open_close_word = bool(re.search(r"\b(open|closed|close|opening|closing)\b", c))

    # Require explicit schedule-like evidence, not incidental words like "opened".
    if has_hours_phrase and (has_weekday or has_time or has_open_close_word):
        return True
    if has_weekday and (has_time or has_open_close_word):
        return True
    if has_time and has_open_close_word:
        return True
    return False


def extract_faq_answer(context: str, message: str = "") -> str | None:
    """
    Extract the ANSWER section from a FAQ chunk.
    Expected format includes:
      QUESTION:
      ...
      ANSWER:
      ...
      Article link: ...
    """
    if not context:
        return None

    if "ANSWER:" not in context:
        # Fallback parser for numbered FAQ blocks:
        # [FAQ_n]
        # n. Question?
        # Answer...
        blocks = re.split(r"(?=\[FAQ_\d+\])", context)
        candidates: list[tuple[int, str]] = []
        msg_terms = set(re.findall(r"[a-z0-9]{3,}", (message or "").lower()))
        for raw in blocks:
            block = raw.strip()
            if not block.startswith("[FAQ_"):
                continue
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if len(lines) < 3:
                continue

            question_idx = None
            for i, ln in enumerate(lines):
                if re.match(r"^\d+\.\s+.+\?$", ln):
                    question_idx = i
                    break
            if question_idx is None or question_idx + 1 >= len(lines):
                continue

            answer_lines = []
            for ln in lines[question_idx + 1:]:
                if re.match(r"^\[FAQ_\d+\]$", ln):
                    break
                answer_lines.append(ln)
            answer = "\n".join(answer_lines).strip()
            if not answer:
                continue

            question_text = lines[question_idx].lower()
            score = 0
            if msg_terms:
                question_terms = set(re.findall(r"[a-z0-9]{3,}", question_text))
                score = len(msg_terms & question_terms)
            candidates.append((score, answer))

        if not candidates:
            # Last-resort fallback: plain "N. Question?\nAnswer..." format (no bracket markers).
            # The chunk is already the closest match from FAISS; skip the first question line
            # and return the rest as the answer.
            lines = [ln.strip() for ln in context.splitlines() if ln.strip()]
            if len(lines) >= 2 and re.match(r"^\d+\.\s+.+", lines[0]):
                return "\n".join(lines[1:]).strip() or None
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1].strip() or None

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
            "absolute rule #1",
            "documentation context appears below",
        ]
    )


def faq_suggests_platform_clarification(answer: str) -> bool:
    """Detect FAQ answers that explicitly ask user to specify a platform."""
    if not answer:
        return False
    a = answer.lower()
    markers = [
        "please specify which platform",
        "which platform you need help",
        "help with mcgraw hill connect",
        "help with cengage mindtap",
    ]
    return any(m in a for m in markers)


def build_instruction_fallback_from_context(context: str, platform: str | None) -> str | None:
    """
    Convert retrieved instruction context into a user-facing fallback answer.
    Used only when model output is clearly a greeting/meta misfire.
    """
    if not context:
        return None

    text = context.replace("\ufeff", "").strip()
    # Remove META header if strip_meta_prefix was not called upstream.
    if text.startswith("[META:"):
        newline_pos = text.find("\n")
        if newline_pos != -1:
            text = text[newline_pos + 1:].strip()
    # Remove legacy source/file prefix, if present.
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
    textbook_terms = ["textbook", "ebook", "e-book", "etext", "e-text", "etextbook", "e-textbook"]
    courseware_terms = [
        "platform", "courseware", "mindtap", "connect", "mylab",
        "mastering", "inquizitive", "inquisitive"
    ]

    # Use word boundary for bare "book"/"books" to avoid false matches on "QuickBooks" etc.
    has_textbook = any(t in m for t in textbook_terms) or bool(re.search(r"\bbooks?\b", m))
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


def classify_book_format_reply(message: str) -> str:
    """
    Classify whether the user means physical textbooks or Immediate Access digital materials.
    Returns:
      - PHYSICAL_TEXTBOOK
      - IMMEDIATE_ACCESS_DIGITAL
      - UNKNOWN
    """
    m = (message or "").lower()
    physical_terms = [
        "physical", "print", "printed", "paper", "hard copy", "hardcopy",
        "in-store", "in store", "bookstore shelf", "book store"
    ]
    digital_terms = [
        "immediate access", "digital", "ebook", "e-book", "etext",
        "e-text", "online", "publisher platform", "courseware"
    ]

    has_physical = any(t in m for t in physical_terms)
    has_digital = any(t in m for t in digital_terms)

    if has_physical and not has_digital:
        return "PHYSICAL_TEXTBOOK"
    if has_digital and not has_physical:
        return "IMMEDIATE_ACCESS_DIGITAL"
    return "UNKNOWN"


def is_book_finding_discovery_query(message: str) -> bool:
    """
    Detect student queries about not being able to find books/materials,
    where we should clarify physical vs Immediate Access.
    """
    m = (message or "").lower()
    if not m:
        return False

    trouble_terms = [
        "having trouble",
        "trouble finding",
        "can't find",
        "cant find",
        "cannot find",
        "not finding",
        "issues finding",
        "struggling",
        "need help finding",
        "looking for",
    ]
    book_terms = [
        "book",
        "books",
        "textbook",
        "textbooks",
        "course materials",
        "materials",
    ]

    # Avoid overriding cases that already clearly specify IA platform access.
    has_clear_ia = (
        "immediate access" in m
        or detect_platform_from_text(m) is not None
        or any(t in m for t in ["connect", "mindtap", "mylab", "mastering"])
    )
    has_physical_only = any(t in m for t in ["physical", "print", "printed", "hard copy", "hardcopy"])

    return (
        any(t in m for t in trouble_terms)
        and any(t in m for t in book_terms)
        and not has_clear_ia
        and not has_physical_only
    )


def is_blackboard_location_query(message: str) -> bool:
    """
    Detect queries asking for the physical location/address of a web-based platform
    (Blackboard, InsideCBU, Canvas, etc.). These should never return the campus store
    address — they need a safe redirect response instead.
    """
    m = (message or "").lower()
    web_platforms = ["blackboard", "insidecbu", "inside cbu", "canvas", "lms"]
    location_terms = [
        "where is", "where can i find", "where do i find",
        "address", "located", "location", "directions to",
        "how do i get to", "how do i find", "where do i go",
        "website", "url", "link", "site",
    ]
    has_web_platform = any(p in m for p in web_platforms)
    has_location_term = any(t in m for t in location_terms)
    return has_web_platform and has_location_term


def is_explicit_login_issue(message: str) -> bool:
    """
    Detect EXPLICIT account/login issues (password, can't log in, etc.).
    This should NOT trigger for ambiguous "access class" queries.
    """
    m = (message or "").lower()
    if not m:
        return False

    system_terms = ["blackboard", "insidecbu", "inside cbu", "class", "course"]
    explicit_login_terms = [
        "can't log in", "cant log in", "cannot log in", "unable to log in",
        "can't login", "cant login", "cannot login", "unable to login",
        "password", "username", "sign in", "log into", "logging in",
        "account", "credential",
    ]

    has_system = any(t in m for t in system_terms)
    has_explicit_login = any(t in m for t in explicit_login_terms)

    # If user already provides a publisher platform, keep IA flow.
    has_platform = detect_platform_from_text(m) is not None

    return has_system and has_explicit_login and not has_platform


def is_ambiguous_class_access_query(message: str) -> bool:
    """
    Detect AMBIGUOUS "access class" queries where it's unclear if user means:
    - Login/class access itself, OR
    - Class materials (textbook/Immediate Access)

    These need clarification before routing.
    """
    m = (message or "").lower()
    if not m:
        return False

    # Phrases that suggest ambiguous "access class" intent
    ambiguous_terms = [
        "how to access the class", "access the class", "access my class",
        "access class", "access the course", "access my course",
        "how do i access", "how to access",
    ]

    # Phrases that explicitly indicate materials/textbook (not ambiguous)
    material_terms = [
        "textbook", "book", "ebook", "immediate access",
        "cengage", "mcgraw", "pearson", "vitalsource", "platform",
        "homework", "assignment", "reading",
    ]

    # Phrases that explicitly indicate login issues (not ambiguous)
    login_terms = [
        "can't log in", "cant log in", "cannot log in", "password",
        "username", "sign in", "log into", "account",
    ]

    has_ambiguous = any(t in m for t in ambiguous_terms)
    has_material = any(t in m for t in material_terms)
    has_login = any(t in m for t in login_terms)

    # If user already provides a platform, it's about materials
    has_platform = detect_platform_from_text(m) is not None

    # Ambiguous if: has ambiguous term AND no explicit material AND no explicit login AND no platform
    return has_ambiguous and not has_material and not has_login and not has_platform


def is_confirmed_class_access_issue(message: str) -> bool:
    """Detect when user confirms they're having class ACCESS (login) issues."""
    m = (message or "").lower()
    if not m:
        return False

    access_itself_terms = [
        "class itself", "course itself", "the class itself", "the course itself",
        "logging in", "log in", "login", "sign in", "access the class itself",
        "can't get into", "cant get into", "get into the class", "get into class",
        "account", "password", "class access"
    ]
    return any(t in m for t in access_itself_terms)


def is_merchandise_query(message: str) -> bool:
    """
    Detect questions about buying campus store merchandise, apparel, gifts, etc.
    These should never be routed to IA/textbook troubleshooting paths.

    To expand detection coverage, add keyword strings to merch_signals below.
    Short words (hat, mug, cup, etc.) use word-boundary matching to avoid
    false positives from substrings (e.g. "hat" inside "what").
    To expand the answer content, edit: data/faqs/campus_store_merchandise.txt
    """
    m = (message or "").lower()

    # Long/safe signals — substring match is fine
    phrase_signals = [
        "merch", "merchandise", "apparel", "clothing",
        "hoodie", "hoodies", "shirt", "shirts", "jacket",
        "lanyard", "keychain", "graduation regalia", "regalia",
        "water bottle",
        "buy cbu", "purchase cbu", "sell merchandise", "sell merch",
        "sell apparel", "does the store sell", "does campus store sell",
        "can i buy", "where can i buy", "where do i buy",
    ]

    # Short words — must match as whole words to avoid substring false positives
    # e.g. "hat" inside "what", "cup" inside "occupy", "gear" inside "appear"
    word_signals = [
        "mug", "mugs", "cup", "cups", "bottle",
        "hat", "hats", "gear", "gift", "gifts", "supplies",
    ]

    if any(s in m for s in phrase_signals):
        return True

    if any(re.search(rf"\b{re.escape(w)}\b", m) for w in word_signals):
        return True

    return False


def is_ia_overview_query(message: str) -> bool:
    """
    Detect 'what is Immediate Access' style overview/definition queries.
    Used to boost retrieval toward ia_overview.txt rather than issue-specific chunks.
    """
    m = (message or "").lower()
    overview_signals = [
        "what is immediate access",
        "what's immediate access",
        "what is ia",
        "tell me about immediate access",
        "explain immediate access",
        "explain what immediate access",
        "how does immediate access work",
        "how does ia work",
        "describe immediate access",
        "what does immediate access mean",
        "what is the immediate access program",
        "can you explain immediate access",
        "can you tell me about immediate access",
        "want to know about immediate access",
    ]
    return any(s in m for s in overview_signals)


def is_textbook_return_query(message: str) -> bool:
    """
    Detect questions about returning textbooks or understanding the
    textbook return/refund policy at the Campus Store.
    """
    m = (message or "").lower()
    direct_signals = [
        "return a textbook",
        "return my textbook",
        "return textbook",
        "textbook return",
        "textbook return policy",
        "return policy textbook",
        "return policy for textbook",
        "get a refund for my textbook",
        "get a refund on my textbook",
        "refund on my textbook",
        "refund on textbook",
        "refund my textbook",
        "refund for textbook",
        "textbook refund",
        "refund policy for immediate access",
        "refund policy immediate access",
        "immediate access refund",
        "immediate access charge",
        "charged for immediate access",
    ]
    if any(s in m for s in direct_signals):
        return True

    return "how do i return" in m and any(
        term in m for term in ["textbook", "book", "immediate access"]
    )


def is_merchandise_return_query(message: str) -> bool:
    """
    Detect questions about returning general merchandise, clothing,
    trade books, or other non-textbook Campus Store items.
    """
    m = (message or "").lower()
    return any(s in m for s in [
        "return merchandise",
        "return a hoodie",
        "return clothing",
        "return apparel",
        "return trade book",
        "merchandise return",
        "return general merchandise",
        "return policy merchandise",
        "return policy for merchandise",
        "refund merchandise",
        "exchange merchandise",
        "return something from the store",
        "return an item",
        "return my purchase",
        "30 day return",
        "restocking fee merchandise",
    ])


def is_technology_return_query(message: str) -> bool:
    """
    Detect questions about returning technology or Apple products
    from the CBU Campus Store.
    """
    m = (message or "").lower()
    return any(s in m for s in [
        "return technology",
        "return apple",
        "return laptop",
        "return computer",
        "return tablet",
        "return ipad",
        "return headphones",
        "return printer",
        "return camera",
        "return monitor",
        "technology return",
        "apple return",
        "return policy technology",
        "return policy for technology",
        "return policy apple",
        "tech return",
        "restocking fee technology",
        "10% restocking",
        "defective technology",
        "defective apple",
    ])


def is_ambiguous_refund_policy_query(message: str) -> bool:
    """
    Detect generic refund questions that need product/category clarification.

    Without a scope like Immediate Access, textbook, merchandise, or technology,
    semantic retrieval can choose a specific return policy by accident and answer
    too confidently.
    """
    m = (message or "").lower().strip()
    if "refund" not in m:
        return False

    scoped_terms = [
        "immediate access",
        "ia ",
        "ia textbook",
        "digital",
        "access code",
        "textbook",
        "book",
        "merchandise",
        "clothing",
        "apparel",
        "shirt",
        "hoodie",
        "technology",
        "tech",
        "apple",
        "laptop",
        "computer",
        "ipad",
        "tablet",
        "printer",
        "software",
    ]
    if any(term in m for term in scoped_terms):
        return False

    generic_refund_patterns = [
        "can i get a refund",
        "will i get a refund",
        "do i get a refund",
        "am i eligible for a refund",
        "guarantee i will get a refund",
        "guarantee my refund",
        "refund after",
    ]
    has_generic_refund = any(pattern in m for pattern in generic_refund_patterns)
    has_timeline = bool(re.search(r"\bafter\s+\d+\s*(day|days|week|weeks|month|months)\b", m))
    has_guarantee = "guarantee" in m
    return has_generic_refund or has_timeline or has_guarantee


def ambiguous_refund_clarification_reply() -> str:
    return (
        "I can help with refund policies, but the answer depends on what you're asking about: "
        "Immediate Access/digital content, textbooks, general merchandise, or technology items. "
        "I cannot confirm refund eligibility without that context. Could you clarify which type of item "
        "or charge you mean?"
    )


def is_browser_cache_issue(message: str) -> bool:
    """
    Detect browser/session cache issues that show '0 Courses, 0 Materials' or
    'no content available' in Immediate Access. These are device-level issues, not
    platform-specific, and should route to the FAQ cache-clearing instructions.
    """
    m = (message or "").lower()
    cache_symptoms = [
        "0 courses",
        "0 materials",
        "no content available",
        "you currently have no content",
        "currently have no content",
        "no courses available",
        "no materials available",
        "content not loading",
        "materials not loading",
        "nothing shows up",
        "nothing is showing",
        "nothing showing up",
        "shows nothing",
        "page is blank",
        "blank page",
        "blank screen",
        "empty page",
        "it's blank",
        "its blank",
        "currently don't have content",
        "don't have content available",
        "no content",
        "can't see my content",
        "cannot see my content",
        "content is not available",
        "not showing my content",
        "it says no content",
    ]
    ia_terms = [
        "immediate access",
        "blackboard",
        "ia tab",
        "access tab",
        "my courses",
        "my materials",
        "the tab",
        "my ia",
        "immediate access tab",
        "the link",
        "blackboard link",
        # Browser/device names in combination with a cache symptom confirm web-based IA context
        "safari",
        "firefox",
        "chrome",
        "ipad",
        "tablet",
    ]
    # These are verbatim IA/VitalSource error strings — IA context is inherent,
    # no second signal needed.
    strong_ia_symptoms = [
        "you currently have no content available",
        "currently have no content available",
        "you currently have no content",
    ]
    if is_blank_page_query(message):
        return False

    if any(s in m for s in strong_ia_symptoms):
        return True

    has_symptom = any(s in m for s in cache_symptoms)
    has_ia_context = any(t in m for t in ia_terms)
    return has_symptom and has_ia_context


def is_vague_books_missing_query(message: str) -> bool:
    """
    Detect vague 'books not showing / can't see my materials' queries that
    need a targeted clarification before routing to browser cache fix or
    platform-specific instructions.
    """
    # Bundle admin questions are FAQ lookups, not vague access issues.
    if is_bundle_admin_question(message):
        return False

    m = (message or "").lower()
    vague_signals = [
        "have not been able to see",
        "haven't been able to see",
        "not been able to see",
        "not able to see",
        "cannot see",
        "can't see",
        "not showing",
        "not showing up",
        "not visible",
        "not appearing",
        "don't see",
        "doesn't show",
        "no books",
        "books are missing",
        "book is missing",
        "books not there",
        "can't find my book",
        "cannot find my book",
        "not there",
        "not coming up",
        "won't show",
        "not loading",
    ]
    ia_terms = [
        "immediate access",
        "blackboard",
        "ia tab",
        "my side",
        "my account",
        "opt in",
        "opt out",
        "book",
        "books",
        "materials",
        "textbook",
    ]
    has_vague = any(s in m for s in vague_signals)
    has_ia = any(t in m for t in ia_terms)
    return has_vague and has_ia


def is_bundle_admin_question(message: str) -> bool:
    """
    Detect questions about IA bundle composition (adding/missing textbooks in bundle).
    These are Campus Store admin questions, not access troubleshooting.
    """
    # Cache issue symptoms take priority over bundle admin detection.
    # "0 Courses, 0 Materials" and "no content available" are cache issues,
    # not bundle admin questions.
    if is_browser_cache_issue(message):
        return False

    m = (message or "").lower()
    bundle_signals = [
        "not in my bundle",
        "not in the bundle",
        "isn't in my bundle",
        "add it to my bundle",
        "add to my bundle",
        "add to the bundle",
        "add a textbook",
        "add the textbook",
        "missing from my bundle",
        "missing from bundle",
        "not included in",
        "not part of my bundle",
        "missing from my immediate access",
        "missing from my ia",
        "textbook is missing",
        "book is missing from",
        "not showing in my bundle",
        "not in my immediate access",
        "missing from my course",
        "textbook not in my",
        "book not in my",
        "not included in my bundle",
        "what should i do if a textbook is missing",
        "what do i do if a textbook is missing",
        "what should i do if my textbook is missing",
    ]
    return any(s in m for s in bundle_signals)


def is_opt_out_policy_question(message: str) -> bool:
    """
    Detect policy questions about opting out of Immediate Access or physical
    textbook availability.  These are FAQ questions, not access troubleshooting.

    IMPORTANT: "opt out" appears as button text in Blackboard ("Want to opt out?").
    Students describing this button are reporting an ACCESS issue, not asking about
    opt-out policy.  Exclude messages that also contain troubleshooting context.
    """
    m = (message or "").lower()

    # If the message also contains troubleshooting signals, do NOT treat it as a
    # policy question.  The student is describing an access problem, not asking
    # about whether/how to opt out.
    troubleshooting_signals = [
        "cannot access", "can't access", "cant access",
        "no read now", "read now button", "read now",
        "not showing", "not there", "not appear",
        "only shows", "only gives", "only option",
        "green check", "checkmark", "opted in",
        "still cannot", "still can't", "still cant",
    ]
    if any(t in m for t in troubleshooting_signals):
        return False

    signals = [
        "opt out", "opt-out", "opting out", "opted out",
        "physical textbook", "physical copy", "print textbook",
        "buy a textbook", "purchase textbook", "purchase a textbook",
        "buy textbook", "student store", "available in the",
    ]
    return any(s in m for s in signals)


def is_ia_enrollment_query(message: str) -> bool:
    """
    Detect questions about whether a course/textbook is included in Immediate
    Access. These require manual enrollment verification, not platform support.
    """
    m = (message or "").lower()
    if not m:
        return False

    signals = [
        "available for free",
        "available through the bookstore",
        "is it free",
        "is this book free",
        "does my course have immediate access",
        "is my book part of immediate access",
        "is this part of immediate access",
        "not part of immediate access",
        "included in immediate access",
        "covered by immediate access",
    ]
    return any(s in m for s in signals)


def is_general_ia_question(message: str) -> bool:
    """
    Detect questions about the Immediate Access program itself
    that don't require platform-specific instructions.
    These should fall through to grounded LLM fallback, not
    platform clarification.
    """
    m = (message or "").lower()
    ia_signals = [
        "immediate access",
        "access code",
        "the code",
        "a code",
        "my code",
        "used textbook",
        "used book",
        "second hand",
        "opted out",
        "opt back in",
        "charged",
        "charge on my",
        "financial aid",
        "after the semester",
        "end of semester",
        "mid-semester",
        "expired",
        "disappeared from my account",
        "lost access",
        "print pages",
        "download my textbook",
        "offline",
        "wrong language",
        "professor said",
        "professor gave",
        "professor mentioned",
        "don't have a code",
        "i don't have the code",
        "i need a code",
        "missing the code",
        "where can i get",
        "where do i get",
        "how do i get the code",
        "will it work",
        "already been used",
        "code expired",
        "share my access",
    ]
    troubleshooting_exclusions = [
        "can't access",
        "cant access",
        "cannot access",
        "unable to access",
        "not able to access",
        "not showing",
        "not populating",
        "missing",
        "can't find",
        "cant find",
        "cannot find",
        "no immediate access tab",
        "there is no immediate access tab",
        "tab is missing",
        "blank page",
        "blank screen",
        "link doesn't work",
        "link isnt working",
        "broken link",
        "error",
        "issue",
        "problem",
        "won't load",
        "doesn't load",
        "doesnt load",
    ]
    platform_mentions = [
        "cengage", "mindtap", "mcgraw", "connect", "pearson",
        "mylab", "mastering", "wiley", "bedford", "vitalsource",
        "sage", "vantage", "macmillan", "achieve", "simucase",
        "zybooks", "inquizitive", "norton", "stukent",
    ]
    has_ia_signal = any(s in m for s in ia_signals)
    has_platform = any(p in m for p in platform_mentions)
    has_troubleshooting = any(s in m for s in troubleshooting_exclusions)
    return has_ia_signal and not has_platform and not has_troubleshooting


def is_access_code_question(message: str) -> bool:
    """
    Detect general questions about access codes that don't require
    platform-specific instructions. These should reach the grounded
    LLM fallback, not platform clarification.
    """
    m = (message or "").lower()
    return any(s in m for s in [
        "where can i get the code",
        "where do i get the code",
        "how do i get the code",
        "where is the code",
        "i don't have the code",
        "i don't have a code",
        "don't have a code",
        "i need a code",
        "need the code",
        "missing the code",
        "code for immediate access",
        "get the code",
        "find the code",
        "where to find the code",
        "professor said use a code",
        "professor gave a code",
        "professor mentioned a code",
        "professor said to use a code",
        "came with a code",
        "used textbook",
        "used book",
        "code already used",
        "already been used",
        "code isn't working",
        "code doesn't work",
        "code not working",
        "redeem a code",
        "how to redeem",
        "where to redeem",
    ])


def is_login_account_issue(message: str) -> bool:
    """
    Detect account-specific login issues that are not browser cache
    problems and not general platform access issues.
    """
    m = (message or "").lower()
    account_signals = [
        "shared my account",
        "sharing my account",
        "someone else used",
        "someone logged in",
        "locked out",
        "account locked",
        "forgot my password",
        "reset my password",
        "wrong email",
        "wrong account",
        "can't log in",
        "cannot log in",
        "can't login",
        "cannot login",
        "won't let me log in",
        "won't let me login",
        "login not working",
        "log in not working",
        "account not working",
        "duplicate account",
        "two accounts",
        "multiple accounts",
    ]
    ia_terms = [
        "immediate access",
        "vitalsource",
        "cengage",
        "pearson",
        "mcgraw",
        "wiley",
        "bedford",
        "bookshelf",
        "textbook",
        "my account",
        "my book",
        "my materials",
        "platform",
        "publisher",
        "mindtap",
        "mylab",
    ]
    has_account = any(s in m for s in account_signals)
    has_ia = any(t in m for t in ia_terms)
    return has_account and has_ia


def is_confirmed_materials_issue(message: str) -> bool:
    """Detect when user confirms they're having MATERIALS (textbook/IA) issues."""
    m = (message or "").lower()
    if not m:
        return False

    # Policy/FAQ questions about opting out, physical availability, or bundle
    # admin are not access troubleshooting issues — exclude them.
    if (
        is_opt_out_policy_question(message)
        or is_bundle_admin_question(message)
        or is_ia_enrollment_query(message)
        or is_textbook_return_query(message)
        or is_general_ia_question(message)
        or is_access_code_question(message)
        or is_blank_page_query(message)
        or is_login_account_issue(message)
    ):
        return False

    # Informational "what is / how does" questions are FAQ lookups, not access issues.
    informational_prefixes = [
        "what is", "what's", "what are",
        "how does", "how do", "tell me about",
        "explain", "describe", "definition of", "define",
        "can you tell me", "i want to know",
    ]
    if any(p in m for p in informational_prefixes):
        return False

    materials_terms = [
        "material", "materials", "textbook", "textbooks",
        "ebook", "ebooks", "immediate access", "platform", "cengage",
        "mcgraw", "pearson", "vitalsource", "homework", "assignment",
        "digital", "content",
    ]
    # Use word boundary for bare "book"/"books" to avoid false matches on "QuickBooks" etc.
    return any(t in m for t in materials_terms) or bool(re.search(r"\bbooks?\b", m))


def ia_enrollment_reply() -> str:
    return (
        "Whether a specific textbook is included in Immediate Access depends on your course enrollment. "
        "If your book is not appearing in your Immediate Access tab in Blackboard, it may not be part of the "
        "program for that course section.\n\n"
        "For confirmation, please contact us directly at ImmediateAccess@calbaptist.edu. Include your name, "
        "student ID number, and course information (course code, section, and instructor name) and we will "
        "check your enrollment."
    )


def vitalsource_screen_clarification_reply() -> str:
    return (
        "When you open Immediate Access in Blackboard, do you see a VitalSource page that says "
        "\"0 Courses, 0 Materials\" or \"You currently have no content available\"?\n\n"
        "- If yes, reply \"yes\" and I can help you fix it.\n"
        "- If no, let me know which publisher or platform your textbook uses "
        "(for example: Pearson, Cengage, McGraw Hill, Bedford, etc.) and I'll get you the right steps."
    )


def build_browser_cache_faq_query(message: str) -> str:
    _m = (message or "").lower()
    if "safari" in _m:
        return "clear browser cache cookies Immediate Access Safari Mac no content available"
    if "ipad" in _m or "tablet" in _m:
        return "clear browser cache cookies Immediate Access iPad Chrome no content available"
    if "firefox" in _m:
        return "clear browser cache cookies Immediate Access Firefox Mac no content available"
    return "clear browser cache cookies Immediate Access Chrome no content available"


def extract_likely_platform_name(message: str) -> str:
    """
    Best-effort extraction of what looks like a platform name from a message.
    Used only for display in the 'I don't recognize X' response — does not need
    to be perfect.
    """
    _stop = {
        "i", "my", "the", "a", "an", "is", "it", "its", "use", "using", "am",
        "have", "has", "with", "for", "to", "of", "in", "on", "at", "by", "im",
        "its", "its", "that", "this", "and", "or", "but", "so", "if", "do",
        "textbook", "platform", "publisher", "app", "software", "program",
        "course", "class", "access", "through", "via", "need", "help", "trying",
        "get", "got", "can", "cant", "cannot", "see", "find", "open", "work",
        "link", "links", "button", "buttons", "page", "pages", "blank",
        "error", "errors", "message", "messages", "screen", "window",
        "takes", "took", "goes", "went", "opens", "opened", "shows",
        "showing", "clicking", "clicked", "tap", "tapped", "loading",
        "loaded", "redirect", "redirected", "nothing",
    }
    words = message.strip().split()
    candidates = [w.strip(".,!?\"'") for w in words if w.lower().strip(".,!?\"'") not in _stop and len(w) > 1]
    return candidates[0] if candidates else message.strip()


def is_blank_page_query(message: str) -> bool:
    """
    Detect queries about blank pages, broken links, or error screens
    in Blackboard/Immediate Access that are not platform-specific.
    """
    m = (message or "").lower()
    blank_signals = [
        "blank page",
        "blank screen",
        "takes me to a blank",
        "goes to a blank",
        "white page",
        "nothing loads",
        "page won't load",
        "page doesn't load",
        "link doesn't work",
        "link isn't working",
        "link takes me to",
        "link goes to",
        "broken link",
        "error page",
        "page not found",
        "404",
        "just a blank",
        "only a blank",
    ]
    ia_terms = [
        "blackboard",
        "immediate access",
        "ia tab",
        "the link",
        "my link",
        "course link",
    ]
    has_blank = any(s in m for s in blank_signals)
    has_ia = any(t in m for t in ia_terms)
    return has_blank and has_ia


# Keep legacy function for backward compatibility
def is_blackboard_insidecbu_login_issue(message: str) -> bool:
    """Legacy function - now redirects to is_explicit_login_issue."""
    return is_explicit_login_issue(message)


def is_cannot_find_immediate_access_query(message: str) -> bool:
    """Detect queries indicating the user cannot find Immediate Access in Blackboard."""
    m = (message or "").lower()
    direct_terms = [
        "don't see immediate access",
        "dont see immediate access",
        "can't find immediate access",
        "cant find immediate access",
        "cannot find immediate access",
        "there is no immediate access tab",
        "there's no immediate access tab",
        "no immediate access tab",
        "immediate access tab is missing",
        "missing immediate access tab",
        "immediate access not showing",
        "immediate access not populating",
        "immediate access not pulling up",
    ]
    return any(t in m for t in direct_terms)


def is_missing_read_now_button(message: str) -> bool:
    """Detect queries where the user cannot find or see the 'Read Now' button in McGraw Hill.

    Strips quotes before matching so 'read now' and "read now" both resolve to
    the plain token 'read now', preventing false negatives from quoted forms.
    """
    # Strip all straight quotes so quoted forms ("read now", 'read now') unify
    m = (message or "").lower().replace("'", "").replace('"', "")

    if "read now" not in m:
        return False

    missing_signals = [
        "do not have",
        "dont have",
        "don't have",
        "no read now",
        "not have",
        "can't find",
        "cant find",
        "cannot find",
        "don't see",
        "dont see",
        "do not see",
        "missing",
        "not there",
        "not showing",
        "i don't see",
        "i dont see",
    ]
    return any(s in m for s in missing_signals)


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
        "library",
        "library hours",
        "library close",
        "library open",
        "what time does the library",
        "when does the library",
        "library building",
        "financial aid office",
        "scholarship",
        "transcript",
        "registrar",
        "admissions",
        "bursar",
        "student accounts office",
        "it help desk",
        "tech support cbu",
        "canvas",
        "moodle",
        "tuition payment",
    ]
    return any(k in m for k in out_of_scope_keywords)


def is_vague_campus_store_query(message: str) -> bool:
    """
    Detect short, ambiguous campus-store mentions that should trigger clarification.
    Examples: "Campus Store", "CBU Campus Store", "store info"
    """
    m = (message or "").strip().lower()
    if not m:
        return False

    has_store = any(term in m for term in ["campus store", "bookstore", "store"])
    if not has_store:
        return False

    specific_intent_terms = [
        "hour", "open", "close", "time", "located", "location", "address",
        "direction", "delivery", "phone", "return", "refund", "immediate access",
        "textbook", "policy", "policies", "parking"
    ]
    if any(term in m for term in specific_intent_terms):
        return False

    return len(m.split()) <= 4


def detect_platform_and_check_ambiguity(message: str) -> tuple[str, bool]:
    """
    Returns: (platform, is_ambiguous)
    """
    platforms_found = detect_platforms_from_text(message)
    corrected = resolve_platform_correction(message)
    if corrected:
        print(f"[PLATFORM DEBUG] Negation/correction detected - choosing {corrected}")
        return corrected, False
    
    print(f"[PLATFORM DEBUG] Platforms found = {[p.lower() for p in platforms_found]}")
    
    if len(platforms_found) > 1:
        print("[PLATFORM DEBUG] AMBIGUOUS - returning (None, True)")
        return None, True
    elif len(platforms_found) == 1:
        print(f"[PLATFORM DEBUG] Single platform - returning ({platforms_found[0]}, False)")
        return platforms_found[0], False
    else:
        print("[PLATFORM DEBUG] No platform - returning (None, False)")
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


def detect_recent_platform_from_history(history: list) -> str | None:
    """Find the most recently mentioned platform in prior user turns."""
    for msg in reversed(history):
        if msg.get("role") != "user":
            continue
        detected = detect_platform_from_text(msg.get("content", ""))
        if detected:
            return detected
    return None


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


_LOW_RISK_CLARIFICATION_RE = re.compile(
    r"""(?ix)
    ^(
      (i\s+)?don'?t\s+know
      | not\s+sure
      | yes | no | maybe | okay | ok
      | cengage | mindtap | mcgraw(\s+hill)? | pearson | vitalsource
      | wiley(plus)? | bedford | stukent | simucase | zybooks | sage
      | norton | inquizitive | macmillan | achieve
      | [a-z]{2,4}\s?\d{3,4}[a-z]?       # course codes: CS101, MPA545
    )\s*[.!?]?\s*$
    """,
)

# Explicit allowlist for "I don't know / not sure" clarification replies.
# Only a bare statement or a safe trailing noun phrase (platform, publisher,
# one, textbook …) is accepted. fullmatch prevents arbitrary trailing content
# such as "I don't know how to jailbreak courseware" from matching.
_DONT_KNOW_SAFE_RE = re.compile(
    r"""(?ix)
    ^(
      i\s+(do\s+not|don'?t)\s+know
      | (i'?m\s+)?not\s+sure
    )
    (
      \s+(
        which\s+(platform|publisher|one|textbook|book|e-?book|course)
        | the\s+(platform|publisher|textbook|book|e-?book|name)
      )
    )?
    \s*[.!?]?\s*$
    """,
)


def _is_low_risk_clarification_reply(message: str) -> bool:
    """
    Return True only for short, clearly safe clarification answers.

    Used to decide whether to skip the LLM safety classifier for follow-up
    messages in an active clarification session. Longer messages or messages
    that fail the pattern check must still go through the full classifier.
    """
    msg = message.strip()
    if len(msg) > 80:
        return False
    # Also check: if the deterministic rules already flagged anything harmful, don't skip
    det = _safety_check_deterministic(msg)
    if det is not None and det.action not in ("ALLOW",):
        return False
    return bool(_LOW_RISK_CLARIFICATION_RE.fullmatch(msg)) or bool(_DONT_KNOW_SAFE_RE.fullmatch(msg))


async def process_chat_request(payload: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint with session management and performance tracking.
    """
    # ✨ START TIMER
    request_start = time.time()
    retrieval_time_ms = 0
    llm_time_ms = 0
    # Preserve the response field for the frontend LLM badge.
    debug_mode = True
    
    try:
        cleanup_expired_sessions()
        
        session_id = payload.session_id or str(uuid.uuid4())
        session = get_or_create_session(session_id)

        # Reset clarification flags for a fresh user query unless we are already awaiting clarification
        if not session.get("awaiting_platform_type", False):
            session["stored_publisher"] = None
            session["stored_original_query"] = None

        message = payload.message.strip()
        has_image = bool(getattr(payload, "image_base64", None))
        retrieval_query = message
        faq_precheck_result = None
        _enriched_query = None
        _intake_completed = False
        _completed_intake_platform = None
        _completed_intake_issue_type = None
        _completed_intake_material_type = None
        is_cache_issue = is_browser_cache_issue(message) or is_browser_cache_issue(retrieval_query)

        # ── Safety gate ───────────────────────────────────────────────────────
        # Runs before Quick Help, retrieval, and LLM generation.
        # The text portion is always checked, even for image+text messages —
        # image content itself is not inspected (known limitation: vision-only
        # harmful content could bypass this gate).
        #
        # Skip the fuzzy LLM classifier only for short, clearly safe follow-up
        # replies within an active clarification session (e.g. "I don't know",
        # "Cengage", "CS101"). Longer replies or replies containing suspicious
        # terms are always classified. The deterministic rules always run.
        _session_in_clarification = (
            session.get("awaiting_platform_type", False)
            or session.get("awaiting_publisher_list_response", False)
            or session.get("awaiting_class_access_clarification", False)
            or session.get("awaiting_vitalsource_screen_confirm", False)
        )
        _skip_classifier = (
            _session_in_clarification and _is_low_risk_clarification_reply(message)
        )
        safety_decision = await run_safety_gate(
            message,
            enable_filter=ENABLE_SAFETY_FILTER,
            enable_classifier=ENABLE_SAFETY_CLASSIFIER and not _skip_classifier,
            llm_client=llm,
        )
        if safety_decision.action != "ALLOW":
            safety_reply = get_safety_response(safety_decision)
            safety_src = safety_source_label(safety_decision)
            print(
                f"[SAFETY] action={safety_decision.action} "
                f"category={safety_decision.category} "
                f"confidence={safety_decision.confidence:.2f} "
                f"reason={safety_decision.reason}"
            )
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": safety_reply})
            if len(session["history"]) > MAX_HISTORY_TURNS * 2:
                session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]
            session["last_activity"] = datetime.now()
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=safety_reply,
                source=safety_src,
                article_link=None,
                confidence=safety_decision.confidence,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode,
            )
        # ─────────────────────────────────────────────────────────────────────

        quick_help_match = build_quick_help_match(message)
        if quick_help_match:
            print(
                "[QUICK HELP] Deterministic route matched "
                f"{quick_help_match.source}: {quick_help_match.source_paths}"
            )
            session["awaiting_vitalsource_screen_confirm"] = False
            session["awaiting_platform_type"] = False
            session["awaiting_publisher_list_response"] = False
            session["awaiting_class_access_clarification"] = False
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": quick_help_match.reply})
            if len(session["history"]) > MAX_HISTORY_TURNS * 2:
                session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]
            session["last_activity"] = datetime.now()
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=quick_help_match.reply,
                source=quick_help_match.source,
                article_link=None,
                confidence=1.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode,
            )

        # ── Intake: mid-flow turn (existing intake_profile in session) ───────────
        _raw_profile = session.get("intake_profile")
        if _raw_profile is not None:
            profile = IntakeProfile.from_dict(_raw_profile)
            profile = update_profile(profile, message)
            if intake_is_complete(profile):
                # Slots filled — enrich query and fall through to normal RAG.
                print(
                    f"[INTAKE] Complete: platform={profile.platform} "
                    f"issue={profile.issue_type} after {profile.turns_spent} turn(s)"
                )
                session["intake_profile"] = None
                # Seed session flags so existing RAG path picks up correctly.
                session["stored_platform"] = profile.platform
                session["stored_intent"] = "IA_ACCESS_ISSUE"
                # Continue below with enriched retrieval query.
                _enriched_query = profile.build_enriched_query(PLATFORM_DISPLAY_NAMES)
                _intake_completed = True
                _completed_intake_platform = profile.platform
                _completed_intake_issue_type = profile.issue_type
                _completed_intake_material_type = profile.material_type
            elif profile.is_expired():
                print(f"[INTAKE] Expired after {profile.turns_spent} turn(s) — using fallback")
                session["intake_profile"] = None
                fallback = intake_fallback_message()
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": fallback})
                session["last_activity"] = datetime.now()
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=fallback,
                    source="INTAKE",
                    article_link=None,
                    confidence=0.0,
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[],
                    debug_mode=debug_mode,
                )
            else:
                question = intake_next_question(profile)
                session["intake_profile"] = profile.to_dict()
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": question})
                session["last_activity"] = datetime.now()
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=question,
                    source="INTAKE",
                    article_link=None,
                    confidence=0.0,
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[],
                    debug_mode=debug_mode,
                )
        # ── Intake: first vague message — start intake if appropriate ─────────
        if should_enter_intake(message, session):
            new_profile = IntakeProfile(original_message=message)
            new_profile = update_profile(new_profile, message)
            if intake_is_complete(new_profile):
                # Unlikely on first turn, but handle gracefully.
                session["intake_profile"] = None
                _enriched_query = new_profile.build_enriched_query(PLATFORM_DISPLAY_NAMES)
                _intake_completed = True
                _completed_intake_platform = new_profile.platform
                _completed_intake_issue_type = new_profile.issue_type
                _completed_intake_material_type = new_profile.material_type
                session["stored_platform"] = new_profile.platform
                session["stored_intent"] = "IA_ACCESS_ISSUE"
            else:
                question = intake_next_question(new_profile)
                session["intake_profile"] = new_profile.to_dict()
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": question})
                session["last_activity"] = datetime.now()
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=question,
                    source="INTAKE",
                    article_link=None,
                    confidence=0.0,
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[],
                    debug_mode=debug_mode,
                )

        # ── LLM intake planner (catches vague cases deterministic missed) ──────
        # Only runs when neither mid-flow intake nor deterministic first-turn
        # intake handled this message, the message is topic-relevant, and there
        # is no image (image+text requests use the vision flow, not text-only planning).
        if not _intake_completed and not has_image and should_run_planner(message):
            planner_decision = await run_intake_planner(message, semaphore=llm_semaphore)
            if planner_decision.action == "ASK_CLARIFICATION":
                question = get_question_for_decision(planner_decision)
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": question})
                session["last_activity"] = datetime.now()
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=question,
                    source="INTAKE:LLM_PLANNER",
                    article_link=None,
                    confidence=0.0,
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[],
                    debug_mode=debug_mode,
                )
            if planner_decision.enriched_query:
                retrieval_query = planner_decision.enriched_query
        # ─────────────────────────────────────────────────────────────────────

        # Initialize variables
        platform = None
        # Detect platform early for direct mentions
        platform = detect_platform_from_text(message)
        intent = None
        course_code = None
        is_vague_query = False
        explicit_textbook_selection = False
        skip_platform_ambiguity_clarification = False

        # If intake just completed, force the IA instructions route and keep the
        # enriched query intact for retrieval. This prevents completed intake
        # follow-ups like "I can't access it" from being classified as FAQ.
        if _intake_completed:
            if (
                _completed_intake_issue_type in {"access", "missing", "account"}
                or _completed_intake_platform is not None
                or _completed_intake_material_type is not None
            ):
                intent = "IA_ACCESS_ISSUE"
            retrieval_query = _enriched_query
            platform = _completed_intake_platform
            session["stored_platform"] = platform
            session["stored_intent"] = "IA_ACCESS_ISSUE"

        if is_ambiguous_refund_policy_query(message):
            clarification = ambiguous_refund_clarification_reply()
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": clarification})
            session["last_activity"] = datetime.now()
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode,
            )
        
        # Check for ambiguous class access queries (need clarification)
        if is_ambiguous_class_access_query(message):
            clarification = (
                "I'd be happy to help! Just to clarify, are you having trouble accessing **the class itself** "
                "(logging in, finding your course), or accessing **the class materials** "
                "(textbook, Immediate Access, etc.)?"
            )
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": clarification})
            session["awaiting_class_access_clarification"] = True
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        if session.get("awaiting_vitalsource_screen_confirm", False):
            msg_lower = message.lower().strip()
            yes_signals = [
                "yes", "yeah", "yep", "it does", "i see it", "that's what i see",
                "thats what i see", "that's the one", "thats the one", "0 courses",
                "no content", "you currently have no content",
            ]
            no_signals = [
                "no", "nope", "not that", "different", "something else",
            ]
            detected_followup_platform = detect_platform_from_text(message)

            if detected_followup_platform:
                session["awaiting_vitalsource_screen_confirm"] = False
                session["awaiting_platform_type"] = False
                session["stored_intent"] = "IA_ACCESS_ISSUE"
                session["stored_platform"] = detected_followup_platform
                session["ia_context"] = True
                platform = detected_followup_platform
                intent = "IA_ACCESS_ISSUE"
                skip_platform_ambiguity_clarification = True
                print(f"[STATE DEBUG] Vague-books clarification resolved to platform: {platform}")
                # Fall through to normal platform instruction retrieval.
            elif any(s in msg_lower for s in yes_signals):
                faq_query = build_browser_cache_faq_query(message)
                retrieval_start = time.time()
                retrieval = await retrieve_async(
                    faq_query,
                    collection="faqs"
                )
                retrieval_time_ms = (time.time() - retrieval_start) * 1000
                context = strip_meta_prefix(retrieval["context"]) if retrieval and retrieval.get("context") else ""
                reply = extract_faq_answer(context, message) if context else None
                if not reply:
                    reply = (
                        "Please clear your browser cookies, cache, and history, then try the Immediate Access link again."
                    )
                reply = strip_article_link_lines(reply)
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": reply})
                session["awaiting_vitalsource_screen_confirm"] = False
                recommended_pdfs = []
                try:
                    recommended_pdfs = get_recommendations_for_chat(
                        retrieval_result=retrieval,
                        platform=None,
                        query=message
                    )
                    print(f"[PDF] Recommending {len(recommended_pdfs)} PDFs")
                except Exception as e:
                    print(f"[WARN] PDF recommendation failed: {e}")
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=reply,
                    source=retrieval.get("source_id", "GENERAL_FAQ") if retrieval else "GENERAL_FAQ",
                    article_link=retrieval.get("article_link") if retrieval else None,
                    confidence=float(retrieval.get("score") or 0.0) if retrieval else 1.0,
                    retrieval_time_ms=round(retrieval_time_ms, 2),
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=recommended_pdfs,
                    debug_mode=debug_mode
                )
            elif any(s in msg_lower for s in no_signals):
                clarification = PLATFORM_CLARIFICATION_MESSAGE
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": clarification})
                session["awaiting_vitalsource_screen_confirm"] = False
                session["awaiting_platform_type"] = True
                session["stored_publisher"] = "TEXTBOOK_GENERIC"
                session["stored_intent"] = "IA_ACCESS_ISSUE"
                session["stored_platform"] = None
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=clarification,
                    source="CLARIFICATION_NEEDED",
                    article_link=None,
                    confidence=0.0,
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[],
                    debug_mode=debug_mode
                )
            else:
                clarification = vitalsource_screen_clarification_reply()
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": clarification})
                total_time_ms = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=clarification,
                    source="CLARIFICATION_NEEDED",
                    article_link=None,
                    confidence=0.0,
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=[],
                    debug_mode=debug_mode
                )

        # FAQ pre-check: if intent is GENERAL_FAQ and a high-confidence FAQ match
        # exists, skip all clarification branches and answer directly.
        precheck_intent = intent or detect_intent(message)
        is_bundle_faq = is_bundle_admin_question(message)
        if (precheck_intent == "GENERAL_FAQ" or is_bundle_faq) and not session.get("awaiting_platform_type", False):
            faq_precheck_result = await faq_precheck(retrieval_query)
            if faq_precheck_result:
                print(f"[FAQ PRECHECK] High-confidence match found — suppressing clarification")
        if faq_precheck_result and is_bundle_faq:
            intent = "GENERAL_FAQ"
            print(f"[FAQ PRECHECK] Bundle admin question — overriding intent to GENERAL_FAQ")

        if (
            not faq_precheck_result
            and (is_vague_books_missing_query(message) or is_blank_page_query(message))
            and not is_browser_cache_issue(message)
            and not session.get("awaiting_platform_type", False)
            and not session.get("awaiting_publisher_list_response", False)
            and not session.get("awaiting_class_access_clarification", False)
            and not session.get("awaiting_vitalsource_screen_confirm", False)
        ):
            clarification = vitalsource_screen_clarification_reply()
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": clarification})
            session["awaiting_vitalsource_screen_confirm"] = True
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        if is_login_account_issue(message) and not session.get("awaiting_platform_type", False) and platform is None:
            reply = (
                "I can help with account access issues. To give you the right steps, "
                "could you let me know which platform or publisher your textbook uses?\n\n"
                "For example: VitalSource, Cengage MindTap, Pearson MyLab, McGraw Hill Connect, "
                "Bedford, Sage, WileyPlus, etc.\n\n"
                "If you're not sure, check the Immediate Access tab in Blackboard — "
                "it should show the name of the publisher."
            )
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": reply})
            session["awaiting_platform_type"] = True
            session["stored_publisher"] = "TEXTBOOK_GENERIC"
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=reply,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        # Handle follow-up questions about class materials
        if is_confirmed_materials_issue(message) and not is_browser_cache_issue(message) and not is_textbook_return_query(message) and not is_merchandise_return_query(message) and not is_technology_return_query(message) and not is_vague_books_missing_query(message) and not is_blank_page_query(message) and not session.get("awaiting_vitalsource_screen_confirm", False) and not session.get("awaiting_platform_type", False) and not session.get("awaiting_publisher_list_response", False) and not session.get("awaiting_class_access_clarification", False) and platform is None:
            # User is asking about materials, trigger platform clarification
            clarification = PLATFORM_CLARIFICATION_MESSAGE
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": clarification})
            session["awaiting_platform_type"] = True
            session["stored_publisher"] = "TEXTBOOK_GENERIC"
            session["stored_original_query"] = message
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            session["platform_clarification_count"] = session.get("platform_clarification_count", 0) + 1
            total_time = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                total_time_ms=round(total_time, 2),
                retrieval_time_ms=0,
                llm_time_ms=0,
                debug_mode=debug_mode
            )

        # ===== EARLY CHECK: Ambiguous Platforms =====
        platform_temp, is_ambiguous = detect_platform_and_check_ambiguity(message)
        
        print(f"[PLATFORM DEBUG] is_ambiguous = {is_ambiguous}")
        
        if is_ambiguous:
            print("[PLATFORM DEBUG] ENTERING ambiguity block")
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
                llm_time_ms=0,
                debug_mode=debug_mode
            )
        
        # ===== EARLY CHECK: Ambiguous Platform Queries =====
        publisher, needs_clarification = is_ambiguous_platform_query(message)

        if needs_clarification and not is_missing_read_now_button(message) and not skip_platform_ambiguity_clarification:
            print(f"[CLARIFICATION DEBUG] Detected ambiguous query for {publisher}")
            
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
            session["stored_original_query"] = message
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            session["stored_platform"] = None
            
            total_time = (time.time() - request_start) * 1000
            
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                total_time_ms=round(total_time, 2),
                retrieval_time_ms=0,
                llm_time_ms=0,
                debug_mode=debug_mode
            )
        
        platform = _completed_intake_platform if _intake_completed else platform_temp

        print(f"[PLATFORM DEBUG EARLY] platform_temp = {platform_temp}")
        print(f"[PLATFORM DEBUG EARLY] platform = {platform}")


        # Handle class access clarification state
        if session.get("awaiting_class_access_clarification", False):
            print("[STATE DEBUG] Processing class access clarification response")
            
            if is_confirmed_class_access_issue(message):
                # User confirmed it's about logging in / accessing the class itself
                access_reply = (
                    "Contact ImmediateAccess@calbaptist.edu for assistance. "
                    "Please send your email from your LancerMail address and include your name, ID#, and course info."
                )
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": access_reply})
                session["awaiting_class_access_clarification"] = False
                session["awaiting_platform_type"] = False
                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=access_reply,
                    source="LLM_ONLY",
                    article_link=None,
                    confidence=0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    debug_mode=debug_mode
                )
            elif is_confirmed_materials_issue(message):
                # User confirmed it's about materials/textbook
                clarification = PLATFORM_CLARIFICATION_MESSAGE
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": clarification})
                session["awaiting_class_access_clarification"] = False
                session["awaiting_platform_type"] = True
                session["stored_publisher"] = "TEXTBOOK_GENERIC"
                session["stored_original_query"] = message
                session["stored_intent"] = "IA_ACCESS_ISSUE"
                session["platform_clarification_count"] = session.get("platform_clarification_count", 0) + 1
                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=clarification,
                    source="CLARIFICATION_NEEDED",
                    article_link=None,
                    confidence=0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    debug_mode=debug_mode
                )
            else:
                # User didn't clearly answer - re-prompt
                clarification = (
                    "Could you please clarify: are you having trouble accessing **the class itself** "
                    "(logging in, finding your course), or accessing **the class materials** "
                    "(textbook, Immediate Access, etc.)?"
                )
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": clarification})
                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=clarification,
                    source="CLARIFICATION_NEEDED",
                    article_link=None,
                    confidence=0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    debug_mode=debug_mode
                )

        # ── Publisher list response handler ───────────────────────────────────────
        # Fires when the student is responding to the numbered publisher list.
        if session.get("awaiting_publisher_list_response", False):
            print("[STATE DEBUG] Processing publisher list response")
            msg_lower = message.lower().strip()
            unrecognized_name = session.get("unrecognized_platform_name", "your platform")

            # 3a — Student picked a number
            numeric_answer = msg_lower.strip(".,!? ")
            platform_from_number = PUBLISHER_LIST_MAP.get(numeric_answer)

            # 3b — Student named a publisher (detect via existing aliases)
            platform_from_text = detect_platform_from_text(msg_lower)

            # 3c — Student doesn't know / not on the list
            not_on_list_phrases = [
                "not on the list", "not on list", "don't know", "dont know",
                "not sure", "none of these", "none of them", "not listed",
                "other", "different publisher", "not listed", "no",
                "nope", "i'm not sure", "im not sure", "no idea", "idk",
            ]
            is_not_on_list = any(p in msg_lower for p in not_on_list_phrases)

            resolved_platform = platform_from_number or platform_from_text

            if resolved_platform and not is_not_on_list:
                # Routes 3a / 3b — valid platform identified, fall through to normal IA flow
                platform = resolved_platform
                intent = "IA_ACCESS_ISSUE"
                session["awaiting_publisher_list_response"] = False
                session.pop("platform_clarification_count", None)
                session["awaiting_platform_type"] = False
                session["stored_publisher"] = None
                session["stored_intent"] = "IA_ACCESS_ISSUE"
                session["stored_platform"] = platform
                print(f"[PUBLISHER LIST] Resolved platform: {platform}")
                # Fall through — let the normal retrieval path handle it below.

            else:
                # Route 3c — general IA fallback with contact prompt
                retrieval_start = time.time()
                general_retrieval = await retrieve_async(
                    "general Immediate Access etextbook access steps Blackboard opted in cannot access",
                    collection="instructions"
                )
                retrieval_ms = (time.time() - retrieval_start) * 1000

                if general_retrieval and general_retrieval.get("context"):
                    raw_context = strip_meta_prefix(general_retrieval["context"])
                    prefix = (
                        f"We don't have specific instructions for {unrecognized_name} through "
                        f"Immediate Access, but here are the general steps to access your materials:\n\n"
                    )
                    suffix = (
                        "\n\nIf you continue to have trouble accessing your materials, please contact us "
                        "directly at ImmediateAccess@calbaptist.edu and we'll be happy to help."
                    )
                    reply = prefix + raw_context + suffix
                else:
                    reply = (
                        f"We don't have specific instructions for {unrecognized_name} through "
                        f"Immediate Access. For general access, log in to Blackboard, open your course, "
                        f"and look for the Immediate Access tab on the left navigation panel. "
                        f"If you continue to have trouble, please contact us at "
                        f"ImmediateAccess@calbaptist.edu."
                    )

                route3c_pdfs = []
                try:
                    route3c_pdfs = get_recommendations_for_chat(
                        retrieval_result=general_retrieval,
                        platform=None,
                        query=message
                    )
                except Exception:
                    pass

                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": reply})
                session["awaiting_publisher_list_response"] = False
                session.pop("platform_clarification_count", None)
                session.pop("unrecognized_platform_name", None)
                session["awaiting_platform_type"] = False
                session["stored_publisher"] = None
                session["stored_intent"] = None

                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=reply,
                    source=general_retrieval.get("source_id", "FAQ_SOURCE_GENERAL") if general_retrieval else "FAQ_SOURCE_GENERAL",
                    article_link=None,
                    confidence=general_retrieval.get("score", 0.0) if general_retrieval else 0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=round(retrieval_ms, 2),
                    llm_time_ms=0,
                    recommended_pdfs=route3c_pdfs,
                    debug_mode=debug_mode
                )

        if session.get("awaiting_platform_type", False):
            print("[STATE DEBUG] Processing platform type clarification")

            msg_lower = message.lower()
            publisher = session.get("stored_publisher")
            original_query = session.get("stored_original_query", "")  # ✨ Get original query
            platform_type_reply = classify_platform_type_reply(message)
            book_format_reply = classify_book_format_reply(message)

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
            is_acknowledgement = any(
                phrase in msg_lower
                for phrase in [
                    "thank you",
                    "thanks",
                    "thx",
                    "got it",
                    "found it",
                    "i found it",
                    "that helped",
                ]
            )
            cannot_find_ia_terms = [
                "i don't see immediate access",
                "i dont see immediate access",
                "i can't find it",
                "i cant find it",
                "what do i do if i can't find it",
                "what do i do if i cant find it",
                "can't find it",
                "cant find it",
            ]
            is_cannot_find_immediate_access = (
                is_cannot_find_immediate_access_query(message)
                or any(term in msg_lower for term in cannot_find_ia_terms)
            )

            # Book-finding clarification branch (physical vs Immediate Access).
            if publisher == "BOOK_FORMAT":
                if book_format_reply == "PHYSICAL_TEXTBOOK":
                    physical_reply = (
                        "Got it - you're looking for physical textbooks. "
                        "If your course uses Immediate Access, the Campus Store may not carry print alternatives, "
                        "and print ISBNs are listed on the Campus Store website. "
                        "If you'd like in-person help, the CBU Campus Store is at 8432 Magnolia Ave, Riverside, CA 92504 "
                        "(phone: 951-343-4259)."
                    )
                    session["history"].append({
                        "role": "user",
                        "content": message
                    })
                    session["history"].append({
                        "role": "assistant",
                        "content": physical_reply
                    })
                    session["awaiting_platform_type"] = False
                    session["stored_publisher"] = None
                    session["stored_original_query"] = None
                    session["stored_intent"] = None
                    session["stored_platform"] = None
                    total_time = (time.time() - request_start) * 1000
                    return ChatResponse(
                        reply=physical_reply,
                        source="FAQ_SOURCE_3",
                        article_link=None,
                        confidence=0.0,
                        total_time_ms=round(total_time, 2),
                        retrieval_time_ms=0,
                        llm_time_ms=0,
                        debug_mode=debug_mode
                    )

                if book_format_reply == "IMMEDIATE_ACCESS_DIGITAL":
                    ia_reply = (
                        "Great - for Immediate Access digital materials, I can guide you step-by-step. "
                        "Which platform do you see in Blackboard? "
                        "For example: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, VitalSource, Bedford, or Sage."
                    )
                    session["history"].append({
                        "role": "user",
                        "content": message
                    })
                    session["history"].append({
                        "role": "assistant",
                        "content": ia_reply
                    })
                    session["awaiting_platform_type"] = True
                    session["stored_publisher"] = "TEXTBOOK_GENERIC"
                    session["stored_intent"] = "IA_ACCESS_ISSUE"
                    session["stored_platform"] = None
                    total_time = (time.time() - request_start) * 1000
                    return ChatResponse(
                        reply=ia_reply,
                        source="CLARIFICATION_NEEDED",
                        article_link=None,
                        confidence=0.0,
                        total_time_ms=round(total_time, 2),
                        retrieval_time_ms=0,
                        llm_time_ms=0,
                        debug_mode=debug_mode
                    )

                format_clarification = (
                    "I can help with that. Are you trying to find a **physical textbook** "
                    "or **Immediate Access digital materials**?"
                )
                session["history"].append({
                    "role": "user",
                    "content": message
                })
                session["history"].append({
                    "role": "assistant",
                    "content": format_clarification
                })
                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=format_clarification,
                    source="CLARIFICATION_NEEDED",
                    article_link=None,
                    confidence=0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    debug_mode=debug_mode
                )

            # Keep clarification state open and do not run retrieval when the student
            # explicitly says they don't know the platform yet.
            if is_low_info_response:
                redirect_reply = (
                    "No worries! You can usually find the platform name on your Blackboard "
                    "course page under the Immediate Access tab. It will say something like "
                    "\"Cengage MindTap,\" \"McGraw Hill Connect,\" or \"Pearson MyLab.\" "
                    "In Blackboard, Immediate Access is located on the dark left navigation panel "
                    "inside your course. "
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
                    llm_time_ms=0,
                    debug_mode=debug_mode
                )

            if is_cannot_find_immediate_access:
                escalate_reply = (
                    "If you still can't find the Immediate Access tab in Blackboard, please contact "
                    "ImmediateAccess@calbaptist.edu for assistance. Please send your email from your "
                    "LancerMail address and include your name, ID#, and course info."
                )
                session["history"].append({
                    "role": "user",
                    "content": message
                })
                session["history"].append({
                    "role": "assistant",
                    "content": escalate_reply
                })
                session["awaiting_platform_type"] = False
                session["stored_publisher"] = None
                session["stored_original_query"] = None
                session["stored_intent"] = None
                session["stored_platform"] = None
                session["ia_tab_missing_escalated"] = True
                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=escalate_reply,
                    source="LLM_ONLY",
                    article_link=None,
                    confidence=0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    debug_mode=debug_mode
                )

            # Avoid repeating a rigid fallback when the student acknowledges help
            # but still has not shared the platform name.
            if is_acknowledgement and detect_platform_from_text(msg_lower) is None:
                ack_reply = (
                    "Glad that helped. Please share the platform name you found in Blackboard "
                    "(for example: Cengage MindTap, McGraw Hill Connect, or Pearson MyLab), "
                    "and I'll walk you through the exact steps."
                )
                session["history"].append({
                    "role": "user",
                    "content": message
                })
                session["history"].append({
                    "role": "assistant",
                    "content": ack_reply
                })
                total_time = (time.time() - request_start) * 1000
                return ChatResponse(
                    reply=ack_reply,
                    source="CLARIFICATION_NEEDED",
                    article_link=None,
                    confidence=0.0,
                    total_time_ms=round(total_time, 2),
                    retrieval_time_ms=0,
                    llm_time_ms=0,
                    debug_mode=debug_mode
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
                elif session.get("platform_clarification_count", 0) >= 1 and not is_low_info_response:
                    # Student gave a response that didn't match any known platform after
                    # we already asked once — show the numbered publisher list.
                    unrecognized_name = extract_likely_platform_name(message)
                    session["unrecognized_platform_name"] = unrecognized_name
                    print(f"[PUBLISHER LIST] Unrecognized platform: {unrecognized_name!r}")

                    publisher_list_reply = (
                        f"I don't recognize \"{unrecognized_name}\" as one of our supported platforms.\n\n"
                        f"Is your textbook from one of these publishers?\n\n"
                        f"{PUBLISHER_LIST_TEXT}\n\n"
                        f"You can reply with the number or the name. If your publisher is not on this list, "
                        f"or you're not sure, just let me know and I'll share the general steps to access "
                        f"your Immediate Access materials."
                    )
                    session["history"].append({"role": "user", "content": message})
                    session["history"].append({"role": "assistant", "content": publisher_list_reply})
                    session["awaiting_publisher_list_response"] = True
                    session["awaiting_platform_type"] = False
                    session["platform_clarification_count"] = session.get("platform_clarification_count", 0) + 1

                    total_time = (time.time() - request_start) * 1000
                    return ChatResponse(
                        reply=publisher_list_reply,
                        source="CLARIFICATION_NEEDED",
                        article_link=None,
                        confidence=0.0,
                        total_time_ms=round(total_time, 2),
                        retrieval_time_ms=0,
                        llm_time_ms=0,
                        recommended_pdfs=[],
                        debug_mode=debug_mode
                    )
                else:
                    followup_reply = (
                        "I still need the platform name to give the correct steps. "
                        "Please share which one you see in Blackboard Immediate Access "
                        "(for example: Cengage MindTap, McGraw Hill Connect, or Pearson MyLab). "
                        "Immediate Access is located on the dark left navigation panel in your Blackboard course."
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
                        llm_time_ms=0,
                        debug_mode=debug_mode
                    )

            # Only clear platform-clarification state once we actually have a platform.
            if platform is not None or platform_type_reply == "TEXTBOOK_EBOOK":
                session["awaiting_platform_type"] = False
                session["stored_publisher"] = None
                session["stored_original_query"] = None  # ✨ Clear stored query
                session.pop("platform_clarification_count", None)
                session.pop("unrecognized_platform_name", None)
            course_code = extract_course_code(message)
            
            if platform is None:
                platform = detect_platform_from_text(message)
            if _intake_completed:
                intent = "IA_ACCESS_ISSUE"
                platform = _completed_intake_platform
                retrieval_query = _enriched_query
                session["stored_platform"] = platform
                session["stored_intent"] = "IA_ACCESS_ISSUE"
            
            print(f"[PLATFORM DEBUG] Detected platform: {platform}")

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
                    "which platform do you see in blackboard",
                    "platform name on your blackboard course page under the immediate access tab",
                    # Publisher list — numeric/short answers must not reset intent to GENERAL_FAQ
                    "is your textbook from one of these publishers",
                    "you can reply with the number or the name",
                ]
                
                if any(pattern in last_bot_message for pattern in platform_clarification_patterns):
                    is_platform_clarification = True
                    intent = "IA_ACCESS_ISSUE"
                    print("[INTENT DEBUG] Platform clarification detected - preserving IA_ACCESS_ISSUE intent")
            
            if _intake_completed:
                intent = "IA_ACCESS_ISSUE"
                print("[INTENT DEBUG] Intake completed - preserving IA_ACCESS_ISSUE intent")
            elif not is_platform_clarification:
                intent = detect_intent(message)  # ✨ THIS IS THE CRITICAL LINE!
                print(f"[INTENT DEBUG] Called detect_intent(), result: {intent}")
            
            course_code = extract_course_code(message)
            
            if platform is None:
                platform = detect_platform_from_text(message)
            
            print(f"🔍 [PLATFORM DEBUG] Detected platform: {platform}")

        # Check for ambiguous class access queries (need clarification)
        if is_ambiguous_class_access_query(message):
            clarification = (
                "I'd be happy to help! Just to clarify, are you having trouble accessing **the class itself** "
                "(logging in, finding your course), or accessing **the class materials** "
                "(textbook, Immediate Access, etc.)?"
            )
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": clarification})
            session["awaiting_class_access_clarification"] = True
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        # Check for explicit login issues (not ambiguous)
        if is_explicit_login_issue(message):
            login_reply = (
                "It sounds like this is a Blackboard/InsideCBU login or class-access issue. "
                "Please contact CBU IT support (or the Pre-College support team) to restore account/class access first. "
                "Once you can open your Blackboard course, share the platform name from the Immediate Access area "
                "(for example: Cengage MindTap, McGraw Hill Connect, or Pearson MyLab), and I'll guide you through textbook access."
            )
            session["history"].append({
                "role": "user",
                "content": message
            })
            session["history"].append({
                "role": "assistant",
                "content": login_reply
            })
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=login_reply,
                source="LLM_ONLY",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        # Force IA_ACCESS_ISSUE when a Read Now button is clearly missing and
        # a platform has already been identified — detect_intent() can misclassify
        # these as GENERAL_FAQ when the phrasing lacks other IA signals.
        if is_missing_read_now_button(message) and platform is not None and intent != "IA_ACCESS_ISSUE":
            intent = "IA_ACCESS_ISSUE"
            print(f"[INTENT DEBUG] Read Now missing override → IA_ACCESS_ISSUE (platform={platform})")

        # Browser/session cache issues ("0 Courses, 0 Materials", "no content available")
        # are device-level problems, not platform-specific. Force GENERAL_FAQ so they
        # route to the FAQ cache-clearing instructions rather than platform clarification.
        if is_cache_issue and intent != "GENERAL_FAQ":
            intent = "GENERAL_FAQ"
            print(f"[INTENT DEBUG] Browser cache issue override → GENERAL_FAQ (cache detected in query or image)")

        # NOW the intent is set!
        if _intake_completed:
            intent = "IA_ACCESS_ISSUE"
            platform = _completed_intake_platform
            retrieval_query = _enriched_query
            session["stored_platform"] = platform
            session["stored_intent"] = "IA_ACCESS_ISSUE"

        # 1. Intent detection happens somewhere up here
        print(f"[INTENT DEBUG] Final intent: {intent}")

        # 2. Platform detection
        print(f"[PLATFORM DEBUG] Detected platform: {platform}")

        # Keep escalation sticky for follow-ups after user says they still cannot
        # find Immediate Access in Blackboard.
        missing_ia_followup_terms = [
            "can't find it",
            "cant find it",
            "cannot find it",
            "what do i do if i can't find it",
            "what do i do if i cant find it",
            "still can't find it",
            "still cant find it",
        ]
        if is_cannot_find_immediate_access_query(message) or (
            session.get("ia_tab_missing_escalated")
            and any(t in message.lower() for t in missing_ia_followup_terms)
        ):
            escalate_reply = (
                "If you still can't find the Immediate Access tab in Blackboard, please contact "
                "ImmediateAccess@calbaptist.edu for assistance. Please send your email from your "
                "LancerMail address and include your name, ID#, and course info."
            )
            session["history"].append({
                "role": "user",
                "content": message
            })
            session["history"].append({
                "role": "assistant",
                "content": escalate_reply
            })
            session["awaiting_platform_type"] = False
            session["stored_publisher"] = None
            session["stored_original_query"] = None
            session["stored_intent"] = None
            session["stored_platform"] = None
            session["ia_tab_missing_escalated"] = True
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=escalate_reply,
                source="LLM_ONLY",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        # If user provides a platform follow-up while already in IA flow,
        # keep it in IA routing even if the utterance is short.
        if (
            intent == "GENERAL_FAQ"
            and platform is not None
            and session.get("stored_intent") == "IA_ACCESS_ISSUE"
        ):
            intent = "IA_ACCESS_ISSUE"
            print(f"🔍 [INTENT DEBUG] IA platform follow-up applied: platform={platform}")

        # Deterministic handoff: if user provides only a platform name while we are
        # already in IA flow, return platform instructions directly.
        if (
            intent == "IA_ACCESS_ISSUE"
            and not _intake_completed
            and platform is not None
            and len(message.split()) <= 5
            and session.get("stored_intent") == "IA_ACCESS_ISSUE"
        ):
            try:
                retrieval_start = time.time()
                platform_query = f"{PLATFORM_DISPLAY_NAMES.get(platform, platform)} immediate access instructions"
                handoff_retrieval = await retrieve_async(
                    platform_query,
                    collection="instructions",
                    platform=platform
                )
                handoff_context = strip_meta_prefix(handoff_retrieval.get("context", "") if handoff_retrieval else "")
                handoff_reply = build_instruction_fallback_from_context(handoff_context, platform)
                if handoff_reply and handoff_retrieval:
                    session["history"].append({
                        "role": "user",
                        "content": message
                    })
                    session["history"].append({
                        "role": "assistant",
                        "content": handoff_reply
                    })
                    session["awaiting_platform_type"] = False
                    session["stored_publisher"] = None
                    session["stored_original_query"] = None
                    session["stored_platform"] = platform
                    retrieval_time_ms = (time.time() - retrieval_start) * 1000
                    total_time_ms = (time.time() - request_start) * 1000
                    handoff_pdfs = []
                    try:
                        handoff_pdfs = get_recommendations_for_chat(
                            retrieval_result=handoff_retrieval,
                            platform=platform,
                            query=message
                        )
                        print(f"[PDF] Handoff recommending {len(handoff_pdfs)} PDFs")
                    except Exception as pdf_err:
                        print(f"[WARN] PDF recommendation failed in handoff: {pdf_err}")
                    return ChatResponse(
                        reply=handoff_reply,
                        source=handoff_retrieval.get("source_id", "INSTR_GENERAL_SOURCE_0"),
                        article_link=handoff_retrieval.get("article_link"),
                        confidence=float(handoff_retrieval.get("score") or 0.0),
                        retrieval_time_ms=round(retrieval_time_ms, 2),
                        llm_time_ms=0,
                        total_time_ms=round(total_time_ms, 2),
                        recommended_pdfs=handoff_pdfs,
                        debug_mode=debug_mode
                    )
            except Exception as e:
                print(f"[WARN] IA platform handoff retrieval failed: {e}")

        # IA continuity guard: keep short troubleshooting follow-ups in IA flow
        # when the previous intent was IA and the platform is implied from context.
        if (
            intent == "GENERAL_FAQ"
            and platform is None
            and session.get("stored_intent") == "IA_ACCESS_ISSUE"
        ):
            msg_lower = message.lower()
            followup_issue_terms = [
                "still",
                "doesn't open",
                "doesnt open",
                "can't open",
                "cant open",
                "not opening",
                "not working",
                "doesn't work",
                "doesnt work",
                "error",
                "issue",
                "problem",
                "unable",
            ]
            non_ia_store_terms = [
                "campus store",
                "store hours",
                "where is",
                "location",
                "located",
                "address",
                "phone",
                "direction",
            ]
            ia_context_terms = [
                "blackboard",
                "immediate access",
                "textbook",
                "materials",
                "platform",
                "course materials",
                "read now",
                "read now button",
            ]
            looks_like_ia_followup = (
                any(t in msg_lower for t in followup_issue_terms)
                or any(t in msg_lower for t in ia_context_terms)
            )
            if (
                looks_like_ia_followup
                and not any(t in msg_lower for t in non_ia_store_terms)
                and not is_opt_out_policy_question(message)
                and not is_ia_enrollment_query(message)
                and not is_general_ia_question(message)
                and not is_access_code_question(message)
                and not is_login_account_issue(message)
                and not is_bundle_admin_question(message)
                and not is_merchandise_return_query(message)
                and not is_technology_return_query(message)
                and not is_merchandise_query(message)
                and not is_textbook_return_query(message)
                and not is_browser_cache_issue(message)
                and not is_vague_books_missing_query(message)
                and not is_blank_page_query(message)
            ):
                intent = "IA_ACCESS_ISSUE"
                platform = session.get("stored_platform") or detect_recent_platform_from_history(session["history"])
                print(f"[INTENT DEBUG] IA continuity applied: platform={platform}")

        if intent == "GENERAL_FAQ" and is_ia_enrollment_query(message):
            enrollment_reply = ia_enrollment_reply()
            session["history"].append({
                "role": "user",
                "content": message
            })
            session["history"].append({
                "role": "assistant",
                "content": enrollment_reply
            })
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=enrollment_reply,
                source="GENERAL_FAQ",
                article_link=None,
                confidence=1.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

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
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        if intent == "GENERAL_FAQ" and is_blackboard_location_query(message) and not is_blank_page_query(message):
            blackboard_reply = (
                "Blackboard is a web-based learning platform — it doesn't have a physical location. "
                "You can access it through your web browser by searching for \"CBU Blackboard\" or "
                "through the InsideCBU portal.\n\n"
                "If you're having trouble logging in, please contact the CBU IT Help Desk for assistance."
            )
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": blackboard_reply})
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=blackboard_reply,
                source="GENERAL_FAQ",
                article_link=None,
                confidence=1.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        if intent == "GENERAL_FAQ" and is_vague_campus_store_query(message):
            clarification_reply = (
                "I can help with Campus Store information. What do you need specifically: "
                "store hours, location/address, phone, directions, or textbook return policy?"
            )
            session["history"].append({
                "role": "user",
                "content": message
            })
            session["history"].append({
                "role": "assistant",
                "content": clarification_reply
            })
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification_reply,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )
        if intent == "GENERAL_FAQ" and is_book_finding_discovery_query(message):
            format_question = (
                "I can help with that. Are you trying to find a **physical textbook** "
                "or **Immediate Access digital materials**?"
            )
            session["history"].append({
                "role": "user",
                "content": message
            })
            session["history"].append({
                "role": "assistant",
                "content": format_question
            })
            session["awaiting_platform_type"] = True
            session["stored_publisher"] = "BOOK_FORMAT"
            session["stored_original_query"] = message
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            session["stored_platform"] = None
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=format_question,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        # Do not require course code up front for IA troubleshooting.
        # Platform/publisher is the primary disambiguation input.
        if intent == "IA_ACCESS_ISSUE":
            session["awaiting_course_code"] = False
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            session["ia_tab_missing_escalated"] = False
            if platform is None and session.get("ia_context") and session.get("stored_platform"):
                platform = session.get("stored_platform")
                print(f"[INTENT DEBUG] Reusing stored IA platform context: {platform}")

        # Only re-detect platform if it was not already set by the IA continuity
        # guard or other earlier logic.  Overwriting here would lose the session
        # platform recovered by the continuity guard (e.g. for follow-ups like
        # "I can't find the read now button" which have no platform name in text).
        if platform is None:
            platform = detect_platform_from_text(message)
        needs_platform_clarification = (
            intent == "IA_ACCESS_ISSUE" and
            platform is None and
            not explicit_textbook_selection
        )
        if needs_platform_clarification:
            clarification = PLATFORM_CLARIFICATION_MESSAGE
            session["awaiting_platform_type"] = True
            session["stored_publisher"] = "TEXTBOOK_GENERIC"
            session["stored_original_query"] = message
            session["stored_intent"] = "IA_ACCESS_ISSUE"
            session["stored_platform"] = None


            total_time = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=clarification,
                source="CLARIFICATION_NEEDED",
                article_link=None,
                confidence=0.0,
                total_time_ms=round(total_time, 2),
                retrieval_time_ms=0,
                llm_time_ms=0,
                debug_mode=debug_mode
            )

        is_vague_query = needs_platform_clarification

        if intent == "IA_ACCESS_ISSUE" and platform is not None:
            session["stored_platform"] = platform
            session["ia_context"] = True
            session["awaiting_platform_type"] = False
            session["ia_tab_missing_escalated"] = False

        print(f"[VAGUE QUERY DEBUG] intent={intent}, platform={platform}")
        print(f"[VAGUE QUERY DEBUG] is_vague_query={is_vague_query}")

        # 5. Then add to history
        session["history"].append({
            "role": "user",
            "content": message
        })

        retrieval = None
        context = ""

        is_greeting = (
            len(message.split()) <= 3
            and any(kw in message.lower() for kw in GREETING_KEYWORDS)
        )
        if is_greeting:
            session["history"].append({"role": "assistant", "content": GREETING_REPLY})
            if len(session["history"]) > MAX_HISTORY_TURNS * 2:
                session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]
            total_time_ms = (time.time() - request_start) * 1000
            return ChatResponse(
                reply=GREETING_REPLY,
                source="DETERMINISTIC_GREETING",
                article_link=None,
                confidence=1.0,
                retrieval_time_ms=0,
                llm_time_ms=0,
                total_time_ms=round(total_time_ms, 2),
                recommended_pdfs=[],
                debug_mode=debug_mode
            )

        try:
            # --- Vision retrieval augmentation ---
            image_context = {}

            if payload.image_base64:
                from app.llm.llama_client import analyze_image_for_retrieval, build_augmented_query
                image_context = await analyze_image_for_retrieval(
                    payload.image_base64,
                    payload.image_media_type or "image/jpeg",
                )
                retrieval_query = build_augmented_query(message, image_context)
                print(f"[VISION] image_context={image_context}")
                print(f"[VISION] augmented retrieval_query={retrieval_query!r}")

                if not platform and image_context.get("detected_platform"):
                    print(f"[VISION] detected_platform from image: {image_context['detected_platform']!r}")
                is_cache_issue = is_browser_cache_issue(message) or is_browser_cache_issue(retrieval_query)
                if is_cache_issue and intent != "GENERAL_FAQ":
                    intent = "GENERAL_FAQ"
                    print(f"[INTENT DEBUG] Browser cache issue override → GENERAL_FAQ (cache detected in query or image)")

            # ✨ START RETRIEVAL TIMER
            retrieval_start = time.time()

            # ✨ NEW: Skip retrieval for vague queries
            if is_vague_query:
                retrieval = None
                context = ""
                print("[RAG DEBUG] Query too vague - skipping retrieval, will ask for clarification")
            # Skip retrieval for unsupported platforms
            elif intent == "UNSUPPORTED_PLATFORM":
                retrieval = None
                context = ""
            elif intent == "IA_ACCESS_ISSUE":
                # Preserve query set in awaiting_platform_type TEXTBOOK_EBOOK handler —
                # do not let conversation context pollute it (causes MacMillan false-match).
                if _intake_completed:
                    enhanced_query = retrieval_query
                elif not explicit_textbook_selection:
                    enhanced_query = enhance_query_with_conversation_context(message, session["history"])

                # Deterministic override: "Read Now button missing" is a general
                # Immediate Access concept — not platform-specific. Retrieve from the
                # general instructions index so any platform finds the same guidance.
                # Without this override, platform-specific general-access chunks win
                # in FAISS because they contain "Read section" language.
                _plat_raw = platform.lower().split('_')[0] if platform else None
                # Resolve aliased platforms to their shared index key (e.g. VITALSOURCE → bedford)
                read_now_retrieval_platform = PLATFORM_RETRIEVAL_KEY.get(
                    platform, _plat_raw
                ) if platform else None
                # "Launch Courseware" (VitalSource-specific button) needs the bedford
                # index, not the general Read Now index — keep platform as-is.
                is_launch_courseware = "launch courseware" in message.lower()
                if (is_missing_read_now_button(message) or session.get("read_now_missing_active")) and not is_launch_courseware:
                    if platform == "MCGRAW_HILL":
                        # McGraw Hill does not use a Read Now button by design.
                        # Route to mcgraw-specific index with a targeted query.
                        enhanced_query = "McGraw Hill Connect no Read Now button Immediate Access tab Connect link eTextbook"
                        read_now_retrieval_platform = "mcgraw"
                        print(f"[RAG DEBUG] Read Now override — McGraw Hill specific path")
                    else:
                        enhanced_query = (
                            "Read Now button missing Immediate Access not available processing"
                        )
                        read_now_retrieval_platform = None  # use general index, not platform-specific
                        print(f"[RAG DEBUG] Read Now button override applied — using general index")
                    session["read_now_missing_active"] = True
                elif is_launch_courseware:
                    enhanced_query = "launch courseware button VitalSource instead of Read Now access eTextbook"
                    print(f"[RAG DEBUG] Launch Courseware override applied — platform={read_now_retrieval_platform}")

                print(f"[RAG DEBUG] Original query: '{message}'")
                print(f"[RAG DEBUG] Enhanced query: '{enhanced_query}'")
                print(f"[RAG DEBUG] Platform: {platform}")

                retrieval = await retrieve_async(
                    enhanced_query,
                    collection="instructions",
                    platform=read_now_retrieval_platform
                )
            elif course_code:
                enhanced_query = enhance_query_with_conversation_context(message, session["history"])
                _plat_key = PLATFORM_RETRIEVAL_KEY.get(platform, platform.lower().split('_')[0] if platform else None)
                retrieval = await retrieve_async(
                    enhanced_query,
                    collection="instructions",
                    platform=_plat_key
                )
            elif intent == "GENERAL_FAQ":
                faq_retrieval_query = build_browser_cache_faq_query(retrieval_query) if is_cache_issue else retrieval_query
                if faq_precheck_result and not is_cache_issue:
                    # Already retrieved and reranked — reuse the result
                    retrieval = faq_precheck_result
                    print(f"[FAQ PRECHECK] Reusing precheck result: {retrieval.get('source_id')}")
                else:
                    candidates = await retrieve_faq_candidates(faq_retrieval_query, top_k=5)
                    if candidates:
                        ranked = rerank_faq_candidates(candidates, faq_retrieval_query)
                        retrieval = ranked[0]
                        print(f"[RERANK] Winner: {retrieval.get('source_id')} rerank_score={retrieval.get('rerank_score', 0):.4f}")
                    else:
                        retrieval = None
            else:
                retrieval = await retrieve_async(retrieval_query)

            if retrieval and "context" in retrieval:
                context = strip_article_link_lines(strip_meta_prefix(retrieval["context"]))
            
            # ✨ END RETRIEVAL TIMER
            retrieval_time_ms = (time.time() - retrieval_start) * 1000

        except AttributeError as e:
            print(f"[WARN] Platform-specific index not found ({e}), falling back to general index")
            try:
                retrieval = await retrieve_async(
                    enhanced_query if 'enhanced_query' in locals() else retrieval_query,
                    collection="instructions",
                    platform=None
                )
                if retrieval and "context" in retrieval:
                    context = strip_meta_prefix(retrieval["context"])
                retrieval_time_ms = (time.time() - retrieval_start) * 1000
            except Exception as e2:
                print(f"[WARN] Fallback retrieval also failed: {e2}")
                retrieval = None
                context = ""
                retrieval_time_ms = (time.time() - retrieval_start) * 1000
        except Exception as e:
            print(f"[WARN] Retrieval failed: {e}")
            retrieval = None
            context = ""
            retrieval_time_ms = (time.time() - retrieval_start) * 1000

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
                    print(f"[PDF] Recommending {len(recommended_pdfs)} PDFs")
                except Exception as e:
                    print(f"[WARN] PDF recommendation failed: {e}")
                    recommended_pdfs = []

                total_time_ms = (time.time() - request_start) * 1000
                print("\n[PERF] PERFORMANCE METRICS:")
                print(f"   Retrieval: {retrieval_time_ms:.2f}ms")
                print(f"   LLM: 0.00ms (direct instruction)")
                print(f"   Platform: {platform}")
                print(f"   Total: {total_time_ms:.2f}ms\n")
                return ChatResponse(
                    reply=direct_instruction,
                    source=retrieval["source_id"],
                    article_link=None,
                    confidence=float(retrieval.get("score") or 0.0),
                    retrieval_time_ms=round(retrieval_time_ms, 2),
                    llm_time_ms=0,
                    total_time_ms=round(total_time_ms, 2),
                    recommended_pdfs=recommended_pdfs,
                    debug_mode=debug_mode
                )

        print("[LLM FALLBACK] No deterministic route matched - attempting grounded RAG fallback")

        # ===== LLM CALL (TIMED) =====
        system_hint = ""

        # Store hours guard: if the user is asking about store hours but the
        # retrieved context does not contain verified hours, instruct the LLM
        # not to invent them.
        if is_store_hours_query(message) and not context_contains_store_hours(context):
            system_hint = (
                "The user is asking about Campus Store hours. "
                "The retrieved documentation does not contain verified store hours. "
                "Do NOT invent or guess store hours. "
                "Tell the user you do not have current verified hours in your knowledge base "
                "and direct them to check the Campus Store website or call 951-343-4259."
            )
        # ✨ UPDATED: Add hint for vague queries with textbook/IA detection
        elif is_vague_query:
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
            if not has_image:
                system_hint += (
                    " If your answer does not fully resolve the issue, end with a single sentence "
                    "suggesting the student attach a screenshot using the camera icon in the chat, "
                    "so you can see the exact error message they are getting."
                )

        # ✨ START LLM TIMER
        llm_start = time.time()
        
        reply, llm_queue_wait_ms = await call_llm_with_semaphore(
            message=message,
            context=context,
            history=session["history"][-MAX_HISTORY_TURNS:],
            system_hint=system_hint,
            image_base64=payload.image_base64,
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
                print("[WARN] [LLM GUARD] Detected greeting/meta misfire; using context-derived fallback")
                reply = fallback_reply

        if (
            intent == "GENERAL_FAQ"
            and retrieval
            and retrieval.get("source_id", "").startswith("FAQ_SOURCE_")
            and is_meta_or_greeting_misfire(reply)
        ):
            fallback_reply = extract_faq_answer(context, message) or strip_article_link_lines(context)
            if fallback_reply:
                print("[WARN] [LLM GUARD] Detected FAQ prompt/meta misfire; using FAQ fallback")
                reply = strip_article_link_lines(fallback_reply)

        # Grounding verifier: block unsupported high-risk claims before returning.
        # Only runs on LLM-generated answers with retrieved context; Quick Help and
        # deterministic paths return before reaching this point.
        if cfg.ENABLE_GROUNDING_VERIFIER and context:
            _gv_result = verify_answer_grounding(reply, context)
            if not _gv_result.passed:
                print(
                    f"[GROUNDING VERIFIER] {len(_gv_result.unsupported_claims)} unsupported "
                    f"claim(s) detected — triggering safe fallback. "
                    f"Claims: {[(c.claim_type, c.claim_text) for c in _gv_result.unsupported_claims]}"
                )
                reply = GROUNDING_SAFE_FALLBACK

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
            if retrieval and not is_greeting:
                recommended_pdfs = get_recommendations_for_chat(
                    retrieval_result=retrieval,
                    platform=platform,
                    query=message
                )
                print(f"[PDF] Recommending {len(recommended_pdfs)} PDFs")
        except Exception as e:
            print(f"[WARN] PDF recommendation failed: {e}")
            recommended_pdfs = []

        # ✨ PRINT PERFORMANCE METRICS
        print("\n[PERF] PERFORMANCE METRICS:")
        print(f"   LLM Queue Wait: {llm_queue_wait_ms:.2f}ms")
        print(f"   Retrieval: {retrieval_time_ms:.2f}ms")
        print(f"   LLM: {llm_time_ms:.2f}ms")
        print(f"   Platform: {platform}")
        print(f"   Total: {total_time_ms:.2f}ms\n")

        return ChatResponse(
            reply=reply,
            source=source,
            article_link=article_link,
            confidence=confidence,
            retrieval_time_ms=round(retrieval_time_ms, 2),
            llm_time_ms=round(llm_time_ms, 2),
            total_time_ms=round(total_time_ms, 2),
            recommended_pdfs=recommended_pdfs,
            debug_mode=debug_mode
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    """
    Backward-compatible synchronous endpoint.
    """
    session_id = payload.session_id or str(uuid.uuid4())
    payload.session_id = session_id
    response = await process_chat_request(payload)
    response.response_id = response.response_id or str(uuid.uuid4())
    response.session_id = response.session_id or session_id
    return response


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    """
    Streaming chat endpoint. Returns Server-Sent Events (SSE).
    This leaves /chat and /chat/submit unchanged while providing
    token-by-token responses for the streaming UI path.
    """
    session_id = payload.session_id or str(uuid.uuid4())
    response_id = str(uuid.uuid4())
    session = get_or_create_session(session_id)
    message = payload.message.strip()

    async def event_stream():
        try:
            # Preserve the response field for the frontend LLM badge.
            debug_mode = True

            # ── Safety gate (same order as /chat: runs before everything) ────────
            _session_in_clarification = (
                session.get("awaiting_platform_type", False)
                or session.get("awaiting_publisher_list_response", False)
                or session.get("awaiting_class_access_clarification", False)
                or session.get("awaiting_vitalsource_screen_confirm", False)
            )
            _skip_classifier = (
                _session_in_clarification and _is_low_risk_clarification_reply(message)
            )
            safety_decision = await run_safety_gate(
                message,
                enable_filter=ENABLE_SAFETY_FILTER,
                enable_classifier=ENABLE_SAFETY_CLASSIFIER and not _skip_classifier,
                llm_client=llm,
            )
            if safety_decision.action != "ALLOW":
                safety_reply = get_safety_response(safety_decision)
                safety_src = safety_source_label(safety_decision)
                print(
                    f"[SAFETY] action={safety_decision.action} "
                    f"category={safety_decision.category} "
                    f"confidence={safety_decision.confidence:.2f} "
                    f"reason={safety_decision.reason}"
                )
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": safety_reply})
                if len(session["history"]) > MAX_HISTORY_TURNS * 2:
                    session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]
                session["last_activity"] = datetime.now()
                yield f"data: {json.dumps({'type': 'response', 'token': safety_reply, 'done': False})}\n\n"
                yield (
                    "data: "
                    f"{json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': safety_src, 'confidence': safety_decision.confidence, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
                )
                return

            platform = detect_platform_from_text(message)
            intent = detect_intent(message)

            # Deterministic greeting: skip retrieval and LLM entirely.
            if len(message.split()) <= 3 and any(kw in message.lower() for kw in GREETING_KEYWORDS):
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": GREETING_REPLY})
                session["last_activity"] = datetime.now()
                yield f"data: {json.dumps({'type': 'response', 'token': GREETING_REPLY, 'done': False})}\n\n"
                yield (
                    "data: "
                    f"{json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': 'DETERMINISTIC_GREETING', 'confidence': 1.0, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
                )
                return

            # --- Vision retrieval augmentation ---
            image_context = {}
            retrieval_query = message

            if payload.image_base64:
                from app.llm.llama_client import analyze_image_for_retrieval, build_augmented_query
                image_context = await analyze_image_for_retrieval(
                    payload.image_base64,
                    payload.image_media_type or "image/jpeg",
                )
                retrieval_query = build_augmented_query(message, image_context)
                print(f"[VISION] image_context={image_context}")
                print(f"[VISION] augmented retrieval_query={retrieval_query!r}")

                if not platform and image_context.get("detected_platform"):
                    print(f"[VISION] detected_platform from image: {image_context['detected_platform']!r}")

            is_cache_issue = is_browser_cache_issue(message) or is_browser_cache_issue(retrieval_query)
            if is_cache_issue and intent != "GENERAL_FAQ":
                intent = "GENERAL_FAQ"
                print("[STREAM INTENT] Browser cache override → GENERAL_FAQ (cache detected in query or image)")

            # ── Intake: mid-flow turn (user replied to an intake question) ────────
            _raw_profile = session.get("intake_profile")
            if _raw_profile is not None:
                profile = IntakeProfile.from_dict(_raw_profile)
                profile = update_profile(profile, message)
                if intake_is_complete(profile):
                    session["intake_profile"] = None
                    session["stored_platform"] = profile.platform
                    session["stored_intent"] = "IA_ACCESS_ISSUE"
                    platform = profile.platform
                    intent = "IA_ACCESS_ISSUE"
                    retrieval_query = profile.build_enriched_query(PLATFORM_DISPLAY_NAMES)
                    # fall through to retrieval
                elif profile.is_expired():
                    session["intake_profile"] = None
                    fallback = intake_fallback_message()
                    session["history"].append({"role": "user", "content": message})
                    session["history"].append({"role": "assistant", "content": fallback})
                    session["last_activity"] = datetime.now()
                    yield f"data: {json.dumps({'type': 'response', 'token': fallback, 'done': False})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': 'INTAKE', 'confidence': 0.0, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
                    return
                else:
                    question = intake_next_question(profile)
                    session["intake_profile"] = profile.to_dict()
                    session["history"].append({"role": "user", "content": message})
                    session["history"].append({"role": "assistant", "content": question})
                    session["last_activity"] = datetime.now()
                    yield f"data: {json.dumps({'type': 'response', 'token': question, 'done': False})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': 'INTAKE', 'confidence': 0.0, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
                    return

            # ── Intake: first vague message ──────────────────────────────────────
            elif should_enter_intake(message, session):
                new_profile = IntakeProfile(original_message=message)
                new_profile = update_profile(new_profile, message)
                if intake_is_complete(new_profile):
                    session["intake_profile"] = None
                    session["stored_platform"] = new_profile.platform
                    session["stored_intent"] = "IA_ACCESS_ISSUE"
                    platform = new_profile.platform
                    intent = "IA_ACCESS_ISSUE"
                    retrieval_query = new_profile.build_enriched_query(PLATFORM_DISPLAY_NAMES)
                    # fall through to retrieval
                else:
                    question = intake_next_question(new_profile)
                    session["intake_profile"] = new_profile.to_dict()
                    session["history"].append({"role": "user", "content": message})
                    session["history"].append({"role": "assistant", "content": question})
                    session["last_activity"] = datetime.now()
                    yield f"data: {json.dumps({'type': 'response', 'token': question, 'done': False})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': 'INTAKE', 'confidence': 0.0, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
                    return

            else:
                # ── LLM intake planner (catches vague cases deterministic missed) ──
                # Skip for image+text requests: vision analysis runs separately and
                # may identify the platform from the screenshot. Text-only planning
                # before vision would risk asking "which platform?" unnecessarily.
                # Vision-aware intake planning is a future enhancement.
                if not payload.image_base64 and should_run_planner(message):
                    planner_decision = await run_intake_planner(message, semaphore=llm_semaphore)
                    if planner_decision.action == "ASK_CLARIFICATION":
                        question = get_question_for_decision(planner_decision)
                        session["history"].append({"role": "user", "content": message})
                        session["history"].append({"role": "assistant", "content": question})
                        session["last_activity"] = datetime.now()
                        yield f"data: {json.dumps({'type': 'response', 'token': question, 'done': False})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': 'INTAKE:LLM_PLANNER', 'confidence': 0.0, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
                        return
                    if planner_decision.enriched_query:
                        retrieval_query = planner_decision.enriched_query

            # Ask for platform before retrieval — prevents wrong-platform hallucination.
            # Skip when already overridden to GENERAL_FAQ (e.g. browser cache issue).
            if intent == "IA_ACCESS_ISSUE" and platform is None:
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": PLATFORM_CLARIFICATION_MESSAGE})
                session["last_activity"] = datetime.now()
                session["awaiting_platform_type"] = True
                session["stored_original_query"] = message
                session["stored_intent"] = "IA_ACCESS_ISSUE"
                session["stored_platform"] = None
                yield f"data: {json.dumps({'type': 'response', 'token': PLATFORM_CLARIFICATION_MESSAGE, 'done': False})}\n\n"
                yield (
                    "data: "
                    f"{json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': 'CLARIFICATION_NEEDED', 'confidence': 0.0, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
                )
                return

            retrieval_start = time.time()
            retrieval = None
            try:
                if platform and intent == "IA_ACCESS_ISSUE":
                    retrieval = await retrieve_async(
                        retrieval_query,
                        collection="instructions",
                        platform=platform,
                    )
                elif intent == "GENERAL_FAQ":
                    # For browser cache issues, augment the retrieval query with cache-specific terms
                    faq_retrieval_query = build_browser_cache_faq_query(retrieval_query) if is_cache_issue else retrieval_query
                    candidates = await retrieve_faq_candidates(faq_retrieval_query, top_k=5)
                    if candidates:
                        ranked = rerank_faq_candidates(candidates, faq_retrieval_query)
                        retrieval = ranked[0]
                        print(f"[RERANK] Winner: {retrieval.get('source_id')} rerank_score={retrieval.get('rerank_score', 0):.4f}")
                    else:
                        retrieval = None
                else:
                    retrieval = await retrieve_async(
                        retrieval_query,
                        collection="auto",
                        platform=platform,
                    )
            except Exception as retrieval_error:
                print(f"[STREAM WARN] Primary retrieval failed: {retrieval_error}")
                try:
                    retrieval = await retrieve_async(
                        retrieval_query,
                        collection="auto",
                        platform=None,
                    )
                except Exception as fallback_error:
                    print(f"[STREAM WARN] Fallback retrieval failed: {fallback_error}")
                    retrieval = None

            retrieval_ms = (time.time() - retrieval_start) * 1000
            context = (
                strip_article_link_lines(strip_meta_prefix(retrieval["context"]))
                if retrieval and retrieval.get("context")
                else ""
            )
            confidence = float(retrieval.get("score") or 0.0) if retrieval else 0.0

            if confidence < CONFIDENCE_THRESHOLD or not context:
                escalation = (
                    "I'm not able to find specific information about that in my knowledge base. "
                    "Please contact the Campus Store directly at ImmediateAccess@calbaptist.edu "
                    "or call 951-343-4259 for assistance."
                )
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": escalation})
                session["last_activity"] = datetime.now()
                yield f"data: {json.dumps({'token': escalation, 'done': False})}\n\n"
                yield (
                    "data: "
                    f"{json.dumps({'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': 'ESCALATION', 'confidence': confidence, 'recommended_pdfs': [], 'debug_mode': debug_mode})}\n\n"
                )
                return

            system_hint = ""
            if is_store_hours_query(message) and not context_contains_store_hours(context):
                system_hint = (
                    "The user is asking about Campus Store hours. "
                    "The retrieved documentation does not contain verified store hours. "
                    "Do NOT invent or guess store hours. "
                    "Tell the user you do not have current verified hours in your knowledge base "
                    "and direct them to check the Campus Store website or call 951-343-4259."
                )
            elif intent == "IA_ACCESS_ISSUE":
                system_hint = (
                    "The user is asking about Immediate Access digital course materials. "
                    "Do NOT suggest purchasing or renting physical textbooks unless the user explicitly asks. "
                    "If required information is missing, ask for the platform or publisher first. "
                    "Only provide instructions for the specific platform mentioned in the documentation."
                )
            elif intent == "GENERAL_FAQ":
                system_hint = (
                    "The user is asking a general Campus Store or Immediate Access question. "
                    "If the retrieved content is a FAQ, answer directly from it with no greeting."
                )

            has_image = bool(payload.image_base64)
            if has_image and intent == "GENERAL_FAQ" and context:
                # FAQ with image: use grounded FAQ prompt but append vision awareness section
                # so the LLM can still reference screenshot details for context.
                # Do NOT use build_vision_system_prompt here — it is designed for instruction
                # retrieval and causes the LLM to misidentify FAQ content as irrelevant.
                base = build_grounded_prompt(message, context)
                vision_note = (
                    "\n\n=== STUDENT HAS PROVIDED A SCREENSHOT ===\n"
                    "The student also attached a screenshot of their current screen.\n"
                    "Use the screenshot only to understand their specific error or screen state.\n"
                    "Your answer must come from the FAQ content above, not from the screenshot.\n"
                    "Do NOT describe the image back to the student.\n"
                    "=== END SCREENSHOT GUIDANCE ==="
                )
                system = base + vision_note
            elif has_image:
                system = build_vision_system_prompt(context=context, system_hint=system_hint)
            elif intent == "GENERAL_FAQ" and context:
                system = build_grounded_prompt(message, context)
            else:
                system = build_system_prompt(context=context, system_hint=system_hint)
            full_thought = ""
            full_response = ""
            pending_tail = ""

            # Vision requests must use the /api/chat endpoint (multimodal).
            # stream_llm_response uses /api/generate with thinking mode, which
            # causes the model to emit everything inside a thought block and
            # produces an empty visible response. stream_llm_chat_response uses
            # /api/chat with images=[...] and extracts thinking tokens correctly.
            if has_image:
                vision_thought = ""
                vision_response = ""
                async with llm_semaphore:
                    async for chunk in stream_llm_chat_response(
                        message=message,
                        system=system,
                        history=session["history"][-MAX_HISTORY_TURNS:],
                        image_base64=payload.image_base64,
                    ):
                        chunk_type = chunk.get("type", "response")
                        token = chunk.get("token", "")
                        if not token:
                            continue
                        if chunk_type == "thought":
                            vision_thought += token
                            yield f"data: {json.dumps({'type': 'thought', 'token': token, 'done': False})}\n\n"
                        else:
                            vision_response += token
                            yield f"data: {json.dumps({'type': 'response', 'token': token, 'done': False})}\n\n"

                vision_response = strip_article_link_lines(vision_response).strip()
                session["history"].append({"role": "user", "content": message})
                session["history"].append({"role": "assistant", "content": vision_response})
                session["last_activity"] = datetime.now()
                recommended_pdfs = []
                try:
                    if retrieval:
                        recommended_pdfs = get_recommendations_for_chat(
                            retrieval_result=retrieval,
                            platform=platform,
                            query=message,
                        )
                        print(f"[STREAM PDF] Recommending {len(recommended_pdfs)} PDFs")
                except Exception as pdf_error:
                    print(f"[STREAM WARN] PDF recommendation failed: {pdf_error}")
                    recommended_pdfs = []
                yield (
                    "data: "
                    f"{json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': retrieval.get('source_id', 'LLM_VISION') if retrieval else 'LLM_VISION', 'confidence': confidence, 'recommended_pdfs': recommended_pdfs, 'debug_mode': debug_mode, 'thought': vision_thought})}\n\n"
                )
                return

            def extract_safe_stream_text(text: str) -> tuple[str, str]:
                """
                Hold back a short trailing buffer so partial `Article link:` markers
                can be detected before anything is yielded to the client.
                """
                if not text:
                    return "", ""

                sanitized = re.sub(r"(?im)^\s*Article link:\s*\"?[^\n\"]*\"?\s*(?:\n|$)", "", text)
                hold_chars = 32
                if len(sanitized) <= hold_chars:
                    return "", sanitized
                return sanitized[:-hold_chars], sanitized[-hold_chars:]

            async with llm_semaphore:
                async for chunk in stream_llm_response(message, system, image_base64=payload.image_base64):
                    chunk_type = chunk.get("type", "response")
                    token = chunk.get("token", "")
                    if not token:
                        continue

                    if chunk_type == "thought":
                        full_thought += token
                        yield f"data: {json.dumps({'type': 'thought', 'token': token, 'done': False})}\n\n"
                    else:
                        full_response += token
                        safe_chunk, pending_tail = extract_safe_stream_text(pending_tail + token)
                        if safe_chunk:
                            yield f"data: {json.dumps({'type': 'response', 'token': safe_chunk, 'done': False})}\n\n"

            cleaned_full_response = strip_article_link_lines(full_response).strip()
            final_safe_chunk, pending_tail = extract_safe_stream_text(pending_tail)
            if final_safe_chunk:
                yield f"data: {json.dumps({'type': 'response', 'token': final_safe_chunk, 'done': False})}\n\n"

            pending_tail = strip_article_link_lines(pending_tail).strip()
            if pending_tail:
                yield f"data: {json.dumps({'type': 'response', 'token': pending_tail, 'done': False})}\n\n"

            full_response = cleaned_full_response
            source = retrieval.get("source_id", "LLM_GROUNDED_STREAM") if retrieval else "LLM_GROUNDED_STREAM"
            recommended_pdfs = []
            try:
                if retrieval:
                    recommended_pdfs = get_recommendations_for_chat(
                        retrieval_result=retrieval,
                        platform=platform,
                        query=message,
                    )
                    print(f"[STREAM PDF] Recommending {len(recommended_pdfs)} PDFs")
            except Exception as pdf_error:
                print(f"[STREAM WARN] PDF recommendation failed: {pdf_error}")
                recommended_pdfs = []

            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": full_response})
            if len(session["history"]) > MAX_HISTORY_TURNS * 2:
                session["history"] = session["history"][-MAX_HISTORY_TURNS * 2:]
            session["last_activity"] = datetime.now()

            print(
                f"[STREAM] Completed response in {retrieval_ms:.2f}ms retrieval "
                f"with source={source} confidence={confidence:.3f}"
            )
            yield (
                "data: "
                f"{json.dumps({'type': 'done', 'token': '', 'done': True, 'response_id': response_id, 'session_id': session_id, 'source': source, 'confidence': confidence, 'recommended_pdfs': recommended_pdfs, 'debug_mode': debug_mode, 'thought': full_thought})}\n\n"
            )

        except Exception as e:
            print(f"[STREAM ERROR] {e}")
            yield (
                "data: "
                f"{json.dumps({'type': 'done', 'token': '[Error generating response]', 'done': True, 'response_id': response_id, 'session_id': session_id, 'recommended_pdfs': [], 'debug_mode': debug_mode, 'thought': ''})}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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

@app.post("/debug/retrieval-context")
def debug_retrieval_context(payload: ChatRequest, platform: str | None = None):
    """
    Return the full retrieved context for inspection.
    Optional query param: ?platform=mcgraw (or any platform key).
    """
    start = time.time()
    result = retriever.retrieve(
        payload.message,
        collection="instructions",
        platform=platform
    )
    elapsed = time.time() - start
    return {
        "elapsed_ms": round(elapsed * 1000, 2),
        "source": result["source_id"],
        "score": result["score"],
        "metadata": result.get("metadata", {}),
        "context": result["context"],
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
        "model": "configured-at-runtime",
        "message": payload.message,
        "runs": results,
        "average_ms": round(avg_time, 2),
        "min_ms": round(min(r["elapsed_ms"] for r in results), 2),
        "max_ms": round(max(r["elapsed_ms"] for r in results), 2)
    }

if not ENABLE_DEBUG_ROUTES:
    app.router.routes = [
        route for route in app.router.routes
        if not getattr(route, "path", "").startswith("/debug/")
    ]

@app.get("/platforms")
async def get_platforms():
    """
    Returns supported platforms from config/platforms.yaml via the config loader.
    Each entry has 'key' (rag_key), 'display_name', and 'keywords' (aliases).
    """
    return PLATFORMS_FOR_API
