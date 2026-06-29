"""
app/intake/llm_planner.py

LLM-assisted intake planner for ambiguous/vague course-material access messages.

Calls the local Ollama LLM with a structured JSON-only prompt to decide whether
enough context exists for RAG retrieval, or whether one clarifying question is
needed first.

Design constraints:
- The LLM must NOT answer the student — it only returns structured JSON.
- On any failure (timeout, unreachable, bad JSON, unexpected keys), fail safe to
  ASK_CLARIFICATION rather than ALLOW_RAG.
- A lightweight topic pre-filter (should_run_planner) avoids adding latency to
  clearly unrelated messages (store hours, refund questions, etc.).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re

import httpx

from app.intake.planner_models import IntakePlannerDecision
from app.intake.question_templates import FALLBACK_QUESTION, QUESTION_TEMPLATES
from app.intake.slot_extractor import extract_platform, extract_issue_type

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
PRIMARY_LLM_MODEL = os.getenv("PRIMARY_LLM_MODEL", "ministral-3:3b-cloud")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "ministral-3:8b-cloud")
INTAKE_PLANNER_MODEL = os.getenv("INTAKE_PLANNER_MODEL", "ministral-3:3b-cloud")
INTAKE_PLANNER_FALLBACK_MODEL = os.getenv("INTAKE_PLANNER_FALLBACK_MODEL", "ministral-3:8b-cloud")
_PLANNER_TIMEOUT = float(os.getenv("INTAKE_PLANNER_TIMEOUT", "20.0"))
_PLANNER_MAX_TOKENS = int(os.getenv("INTAKE_PLANNER_MAX_TOKENS", "160"))

# ask_course_code is excluded: the planner must never ask students for their
# course code. If a model returns it anyway, _validate_decision maps it to
# ask_platform_for_book_access. Slot collection for course details is disabled.
_VALID_QUESTION_KEYS = frozenset(QUESTION_TEMPLATES.keys()) - {"ask_course_code"}

_TOPIC_KEYWORDS = frozenset({
    "book", "textbook", "ebook", "e-book", "etext", "material", "materials",
    "access", "locked", "pay", "payment", "publisher", "platform",
    "cengage", "pearson", "vitalsource", "mcgraw", "wiley", "sage",
    "macmillan", "bedford", "simucase", "zybooks", "stukent",
    "mindtap", "mylab", "mastering", "connect", "bookshelf", "achieve",
    "course material", "immediate access",
})

_POLICY_FAQ_PATTERNS = (
    re.compile(r"\b(how|where|can|could|do|does|what)\b.*\bopt[- ]?out\b"),
    re.compile(r"\bopt[- ]?out\b.*\b(immediate access|textbook|book|physical|print)\b"),
    re.compile(r"\bwhat\s+is\s+(immediate access|ia)\b"),
    re.compile(r"\bwhat(?:'s| is)\s+the\s+textbook\s+refund\s+policy\b"),
    re.compile(r"\bhow\s+do\s+i\s+return\s+(a\s+)?(textbook|book)\b"),
    re.compile(r"\b(can|do|will)\s+i\s+get\s+a\s+refund\b"),
    re.compile(r"\bwhere\s+do\s+i\s+buy\s+(my\s+)?(textbooks|textbook|books|book)\b"),
    re.compile(r"\bwhere\s+can\s+i\s+buy\s+(my\s+)?(textbooks|textbook|books|book)\b"),
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@contextlib.asynccontextmanager
async def _optional_semaphore(sem: asyncio.Semaphore | None):
    """Acquire sem if provided; otherwise proceed immediately."""
    if sem is not None:
        async with sem:
            yield
    else:
        yield

_SYSTEM_PROMPT = (
    "You are an intake classifier for a university campus store chatbot.\n"
    "ONLY output valid JSON — no explanation, no prose, no markdown fences.\n\n"
    "VALID next_question_key values (one of these exact strings, or null):\n"
    "ask_platform_for_book_access | ask_issue_for_platform | "
    "ask_error_message | ask_material_type | ask_blackboard_or_publisher_location\n\n"
    "RULES:\n"
    "1. Platform named AND issue described → action=ALLOW_RAG, next_question_key=null.\n"
    "   Treat 'can't find the link', 'where do I find it', and "
    "'don't know where to access it' as a described access/navigation issue, "
    "not as an unknown answer.\n"
    "2. Platform or issue missing → action=ASK_CLARIFICATION, set next_question_key.\n"
    "3. Unrelated to course materials → action=ALLOW_RAG, next_question_key=null.\n"
    "4. When uncertain → action=ASK_CLARIFICATION.\n\n"
    "Output JSON only, no other text:\n"
    '{"action":"ALLOW_RAG or ASK_CLARIFICATION","intent":"<3 words max>",'
    '"confidence":0.0,"known_slots":{},"missing_slots":[],'
    '"next_question_key":null,"enriched_query":null}'
)

_SAFE_FALLBACK = IntakePlannerDecision(
    action="ASK_CLARIFICATION",
    intent="unknown",
    confidence=0.0,
    known_slots={},
    missing_slots=["platform", "issue_type"],
    next_question_key="ask_platform_for_book_access",
    enriched_query=None,
)


def should_run_planner(
    message: str,
    known_slots: dict[str, str] | None = None,
) -> bool:
    """
    Return True only when the LLM planner can add value.

    Returns False when:
    - The message contains no course-material/access keywords (unrelated query).
    - Both platform and issue type are already known (from session or message text).
    """
    msg_lower = message.lower()
    if any(pattern.search(msg_lower) for pattern in _POLICY_FAQ_PATTERNS):
        return False
    if not any(kw in msg_lower for kw in _TOPIC_KEYWORDS):
        return False
    # Skip if both slots are already known from the session.
    if known_slots and known_slots.get("platform") and known_slots.get("issue_type"):
        return False
    # Skip if both slots are extractable from the message text alone.
    if extract_platform(message) is not None and extract_issue_type(message) is not None:
        return False
    return True


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJECT_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def _validate_decision(raw: dict) -> IntakePlannerDecision | None:
    """Parse and validate the LLM output. Returns None on schema errors."""
    try:
        decision = IntakePlannerDecision(**raw)
    except Exception:
        return None
    if (
        decision.next_question_key is not None
        and decision.next_question_key not in _VALID_QUESTION_KEYS
    ):
        decision.next_question_key = "ask_platform_for_book_access"
    return decision


async def run_intake_planner(
    message: str,
    semaphore: asyncio.Semaphore | None = None,
    known_slots: dict[str, str] | None = None,
    last_requested_slot: str | None = None,
    attempted_slots: list[str] | None = None,
) -> IntakePlannerDecision:
    """
    Call the Ollama LLM and return a structured intake decision.

    Always returns a valid IntakePlannerDecision — never raises.
    On any failure the safe fallback (ASK_CLARIFICATION) is returned.

    The optional semaphore parameter should be the same llm_semaphore used for
    normal answer generation, keeping total Ollama concurrency bounded.

    known_slots, if provided, surfaces already-collected session state to the LLM
    so it does not ask for slots the student already supplied.

    last_requested_slot and attempted_slots surface prior intake state so the
    planner can choose an alternative question when the student cannot answer.
    """
    models = [INTAKE_PLANNER_MODEL]
    if INTAKE_PLANNER_FALLBACK_MODEL and INTAKE_PLANNER_FALLBACK_MODEL != INTAKE_PLANNER_MODEL:
        models.append(INTAKE_PLANNER_FALLBACK_MODEL)

    user_content = f"Student message: {message}"
    if known_slots:
        filled = {k: v for k, v in known_slots.items() if v}
        if filled:
            user_content += f"\nAlready known from session: {filled}"
    if last_requested_slot:
        user_content += f"\nLast question asked about slot: {last_requested_slot}"
    if attempted_slots:
        user_content += f"\nSlots student said they don't know: {attempted_slots}"

    payload: dict = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "num_predict": _PLANNER_MAX_TOKENS,
        },
    }

    response: httpx.Response | None = None
    for index, model_name in enumerate(models):
        fallback_model = models[index + 1] if index < len(models) - 1 else None
        try:
            timeout = httpx.Timeout(_PLANNER_TIMEOUT, read=_PLANNER_TIMEOUT)
            async with _optional_semaphore(semaphore):
                async with httpx.AsyncClient(timeout=timeout) as client:
                    print(
                        f"[PLANNER] model={model_name} url={OLLAMA_CHAT_URL} "
                        f"message={message[:80]!r}"
                    )
                    response = await client.post(
                        OLLAMA_CHAT_URL, json={**payload, "model": model_name}
                    )
            if response.status_code >= 400:
                if fallback_model:
                    print(
                        f"[PLANNER WARN] {model_name} HTTP {response.status_code}, "
                        f"retrying with {fallback_model}"
                    )
                    continue
                print(f"[PLANNER WARN] HTTP {response.status_code}, using safe fallback")
                return _SAFE_FALLBACK
            break
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            if fallback_model:
                print(f"[PLANNER WARN] {model_name} unreachable ({exc}), retrying with {fallback_model}")
                continue
            print(f"[PLANNER WARN] LLM unreachable ({exc}), using safe fallback")
            return _SAFE_FALLBACK
        except Exception as exc:
            print(f"[PLANNER WARN] unexpected error ({exc}), using safe fallback")
            return _SAFE_FALLBACK
    else:
        print("[PLANNER WARN] all models exhausted, using safe fallback")
        return _SAFE_FALLBACK

    if response is None or not response.content:
        print("[PLANNER WARN] empty response, using safe fallback")
        return _SAFE_FALLBACK

    try:
        resp_data = response.json()
    except Exception:
        print("[PLANNER WARN] response not JSON, using safe fallback")
        return _SAFE_FALLBACK

    content = resp_data.get("message", {}).get("content", "").strip()
    if not content:
        print("[PLANNER WARN] empty content, using safe fallback")
        return _SAFE_FALLBACK

    raw = _extract_json(content)
    if not raw:
        print(f"[PLANNER WARN] no JSON in content: {content[:200]!r}")
        return _SAFE_FALLBACK

    decision = _validate_decision(raw)
    if decision is None:
        print(f"[PLANNER WARN] schema invalid: {raw}")
        return _SAFE_FALLBACK

    print(
        f"[PLANNER] action={decision.action} intent={decision.intent!r} "
        f"confidence={decision.confidence:.2f} next_q={decision.next_question_key!r}"
    )
    return decision


def get_question_for_decision(decision: IntakePlannerDecision) -> str:
    """Return the controlled question text for an ASK_CLARIFICATION decision."""
    return QUESTION_TEMPLATES.get(decision.next_question_key or "", FALLBACK_QUESTION)
