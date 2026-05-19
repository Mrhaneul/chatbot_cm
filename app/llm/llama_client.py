import base64
import json
import logging
import os
import re

import httpx
import requests

from app.llm.base import LLMClient

log = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"
PRIMARY_LLM_MODEL = os.getenv("PRIMARY_LLM_MODEL", "gemma4:e4b")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "gemma4:e2b")


_THINKING_TAG_RE: re.Pattern[str] = re.compile(
    r"<\|channel\>(?:thought)?.*?<channel\|>", re.DOTALL
)

_WORD_BOUNDARY_RE: re.Pattern[str] = re.compile(r"[ \n\t.,!?:;]")
_MODEL_NOT_FOUND_PATTERNS: tuple[str, ...] = (
    "model not found",
    "pull model",
    "no such model",
    "not found, try pulling it first",
    "file does not exist",
)


def _candidate_models() -> list[str]:
    models = [PRIMARY_LLM_MODEL]
    if FALLBACK_LLM_MODEL and FALLBACK_LLM_MODEL != PRIMARY_LLM_MODEL:
        models.append(FALLBACK_LLM_MODEL)
    return models


def _is_model_not_found_error(error_text: str) -> bool:
    normalized = (error_text or "").lower()
    return any(pattern in normalized for pattern in _MODEL_NOT_FOUND_PATTERNS)


def _format_error_text(error_text: str, max_chars: int = 300) -> str:
    compact = " ".join((error_text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars] + "..."


def _failure_reason_from_status(status_code: int, error_text: str) -> str:
    formatted_body = _format_error_text(error_text)
    if formatted_body:
        return f"status={status_code} body={formatted_body}"
    return f"status={status_code}"


def _should_fallback_status(status_code: int, error_text: str) -> bool:
    # Ollama returns 404 when the requested model tag is missing.
    # Retry with the fallback model for any 404 here so the /chat path
    # remains resilient even when the response body wording varies.
    return status_code >= 500 or status_code == 404 or _is_model_not_found_error(error_text)


def _should_fallback_exception(exc: Exception) -> bool:
    timeout_types = (
        httpx.ConnectError,
        httpx.TimeoutException,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
    )
    return isinstance(exc, timeout_types)


def _log_model_use(purpose: str, model_name: str) -> None:
    log.info("Using Ollama model '%s' for %s", model_name, purpose)


def _log_primary_failure(model_name: str, reason: str) -> None:
    log.warning("[LLM] primary model failed: %s %s", model_name, reason)


def _log_retry_with_fallback(model_name: str) -> None:
    log.info("[LLM] retrying with fallback model: %s", model_name)


def _log_fallback_success(model_name: str) -> None:
    log.info("[LLM] fallback model succeeded: %s", model_name)


def _evaluate_fallback_attempt(
    current_model: str,
    fallback_model: str | None,
    *,
    status_code: int | None = None,
    error_text: str = "",
    exc: Exception | None = None,
) -> tuple[bool, str]:
    if exc is not None:
        reason = f"{exc.__class__.__name__}: {exc}"
        return bool(fallback_model) and _should_fallback_exception(exc), reason

    if status_code is not None:
        reason = _failure_reason_from_status(status_code, error_text)
        return bool(fallback_model) and _should_fallback_status(status_code, error_text), reason

    return False, "unknown failure"


async def check_ollama_health(timeout_seconds: float = 2.0) -> bool:
    """Lightweight reachability check for Ollama."""
    try:
        timeout = httpx.Timeout(timeout_seconds, read=timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(OLLAMA_TAGS_URL)
            return response.status_code == 200
    except (httpx.HTTPError, httpx.TimeoutException):
        return False


async def get_ollama_model_availability(timeout_seconds: float = 2.0) -> dict[str, object]:
    """Return Ollama reachability plus whether the configured model tags are installed."""
    result: dict[str, object] = {
        "ollama_reachable": False,
        "primary_model": PRIMARY_LLM_MODEL,
        "primary_model_available": False,
        "fallback_model": FALLBACK_LLM_MODEL,
        "fallback_model_available": False,
        "warnings": [],
    }
    try:
        timeout = httpx.Timeout(timeout_seconds, read=timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(OLLAMA_TAGS_URL)
            response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        result["warnings"] = [f"Ollama not reachable: {exc}"]
        return result

    result["ollama_reachable"] = True
    try:
        payload = response.json()
    except ValueError:
        result["warnings"] = ["Ollama /api/tags returned non-JSON response"]
        return result

    models = payload.get("models", []) if isinstance(payload, dict) else []
    installed_tags = {
        model.get("name")
        for model in models
        if isinstance(model, dict) and isinstance(model.get("name"), str)
    }

    result["primary_model_available"] = PRIMARY_LLM_MODEL in installed_tags
    result["fallback_model_available"] = FALLBACK_LLM_MODEL in installed_tags

    warnings: list[str] = []
    if not result["primary_model_available"]:
        warnings.append(f"Primary model tag not installed: {PRIMARY_LLM_MODEL}")
    if not result["fallback_model_available"]:
        warnings.append(f"Fallback model tag not installed: {FALLBACK_LLM_MODEL}")
    result["warnings"] = warnings
    return result


def flush_word_boundaries(text: str) -> tuple[list[str], str]:
    """Split text at word boundaries, returning completed chunks and the remainder."""
    m = _WORD_BOUNDARY_RE.search(text)
    if m is None:
        return [], text
    parts = _WORD_BOUNDARY_RE.split(text)
    separators = _WORD_BOUNDARY_RE.findall(text)
    chunks: list[str] = []
    for part, sep in zip(parts[:-1], separators):
        chunks.append(part + sep)
    return chunks, parts[-1]


def strip_thinking_tags_preserve_spacing(text: str) -> str:
    """Remove Gemma 4 thought blocks while preserving surrounding whitespace."""
    return _THINKING_TAG_RE.sub("", text)


def strip_thinking_tags(text: str) -> str:
    """Remove Gemma 4 thought blocks from response text."""
    return strip_thinking_tags_preserve_spacing(text).strip()


def build_system_prompt(context: str = "", system_hint: str = "") -> str:
    """Build the system prompt used for grounded Lance responses."""
    system_content = """You are Lance, the Campus Store AI Assistant for California Baptist University.

    
=== When to Give a Greeting ===

ONLY give a greeting when ALL of these are true:
1. User ONLY says "Hi", "Hello", or "Hey" with nothing else
2. There is NO documentation context below
3. The user hasn't asked a specific question

=== Response Formats ===

**With Instructions:**
"Here's how to access [platform]:

1. [Step from documentation]
2. [Step from documentation]
..."

**With FAQ:**
"[Direct answer from FAQ, preserving formatting]"

**Pure Greeting:**
"Hi! I'm Lance, your Campus Store AI Assistant. I can help with Immediate Access, textbook policies, and troubleshooting. What can I help you with today?"

**Need Clarification:**
"I can help with [topic]! Could you specify: [specific question]?"

=== OUTPUT SAFETY RULES ===
- Do NOT explain your internal reasoning.
- Do NOT write meta lines like "Since the user..." or "Based on the documentation...".
- Never mention instructions, prompts, rules, or context tags.
- Give only the final user-facing answer.
"""

    if system_hint:
        system_content += f"\n\n=== ADDITIONAL CONTEXT ===\n{system_hint}\n"

    if context:
        is_faq = "QUESTION:" in context and "ANSWER:" in context

        if is_faq:
            system_content += f"""

=== RETRIEVED FAQ (PROVIDE THIS ANSWER) ===
{context}
=== END FAQ ===

THIS IS A FAQ - NOT INSTRUCTIONS!
The user asked an informational question like "What is..." or "Tell me about..."
The FAQ above has the complete answer in the ANSWER section.

Your response should:
1. Start directly with the answer (no greeting)
2. Provide the complete ANSWER from the FAQ
3. Keep the formatting (bullet points, bold text, etc.)
4. DO NOT add step-by-step access instructions
5. DO NOT say "Here's how to access..."
6. If the FAQ appears unrelated to the user's message, ask a short clarification question instead of forcing the FAQ.

Example:
User: "What is Immediate Access?"
FAQ: "Immediate Access is California Baptist University's program..."
CORRECT: "Immediate Access is California Baptist University's program..."
WRONG: "Here's how to access Immediate Access: 1. Log into..."
"""
        else:
            system_content += f"""

=== RETRIEVED DOCUMENTATION (USE THIS!) ===
{context}
=== END DOCUMENTATION ===

CRITICAL REMINDER: These are step-by-step instructions!
- You MUST use this documentation to answer
- You MUST skip any greeting
- Start with: "Here's how to..."
- Provide the step-by-step instructions from the documentation
- If the user can't access to a textbook and provides the course code, ask which platform is the user using (e.g. Cengage MindTap).
- If documentation does not match the user's platform/topic, ask for clarification and do not invent platform steps.
"""
    else:
        system_content += """

No documentation was retrieved. Handle based on the query type:
- If just "Hi"/"Hello" -> Give greeting
- If specific question -> Answer from your knowledge or ask for details
"""

    system_content += """

BEFORE YOU RESPOND, ASK YOURSELF:
1. Is there FAQ documentation above?
   -> YES: Provide the FAQ ANSWER directly, NO GREETING
2. Is there instruction documentation above?
   -> YES: Provide those steps, NO GREETING
3. No documentation?
   -> Is it just "Hi"? Give greeting
   -> Otherwise: Answer or ask for clarification

Now respond:
"""
    return system_content


def build_vision_system_prompt(context: str = "", system_hint: str = "") -> str:
    """
    System prompt for image-augmented requests.
    Instructs Gemma4 to read the screenshot and then apply retrieved context.
    """
    base = build_system_prompt(context=context, system_hint=system_hint)
    vision_preamble = """=== SCREENSHOT PROVIDED ===
The student has shared a screenshot of the error or issue they are experiencing.
Carefully read ALL text visible in the image — error messages, button labels, page titles,
platform names, and any on-screen instructions. Use what you see to give a more specific answer.
If the screenshot clearly identifies the platform (e.g. Cengage MindTap, McGraw Hill Connect),
use that platform name in your response.

"""
    return vision_preamble + base


def _is_faq_context(context: str) -> bool:
    return "QUESTION:" in context and "ANSWER:" in context


def build_grounded_vision_faq_prompt(message: str, context: str) -> str:
    """Ground FAQ answers even when the student attaches a screenshot."""
    return f"""You are Lance, the CBU Campus Store assistant. Answer the student's question using ONLY the information provided below.

RULES:
- Answer directly from the provided context only
- If the context does not contain a direct answer to the question, say: "I don't have specific information about that. Please contact ImmediateAccess@calbaptist.edu for assistance."
- Do NOT reproduce any URLs or links from the context
- Do NOT add information not present in the context
- The student has also attached a screenshot. Use it only to understand their error or screen state.
- Your answer must come from the FAQ content below, not from the screenshot by itself.
- Do NOT describe the screenshot back to the student
- Be concise and helpful

CONTEXT:
{context}

STUDENT QUESTION: {message}

ANSWER:"""


_JSON_OBJECT_RE: re.Pattern[str] = re.compile(r"\{.*\}", re.DOTALL)
_MULTISPACE_RE: re.Pattern[str] = re.compile(r"\s+")
_PLATFORM_HINT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("VITALSOURCE", re.compile(r"\b(vitalsource|bookshelf)\b", re.IGNORECASE)),
    ("CENGAGE", re.compile(r"\b(cengage|mindtap|cnow|cnowv2|webassign)\b", re.IGNORECASE)),
    ("MCGRAW_HILL", re.compile(r"\b(mcgraw|connect|aleks)\b", re.IGNORECASE)),
    ("PEARSON", re.compile(r"\b(pearson|mylab|mastering)\b", re.IGNORECASE)),
    ("WILEY", re.compile(r"\b(wiley|wileyplus)\b", re.IGNORECASE)),
    ("MACMILLAN", re.compile(r"\b(macmillan|achieve)\b", re.IGNORECASE)),
    ("SAGE", re.compile(r"\b(sage|vantage)\b", re.IGNORECASE)),
    ("BEDFORD", re.compile(r"\b(bedford)\b", re.IGNORECASE)),
    ("SIMUCASE", re.compile(r"\b(simucase)\b", re.IGNORECASE)),
    ("ZYBOOKS", re.compile(r"\b(zybooks|zylabs)\b", re.IGNORECASE)),
    ("STUKENT", re.compile(r"\b(stukent)\b", re.IGNORECASE)),
    ("INQUIZITIVE", re.compile(r"\b(inquizitive|norton)\b", re.IGNORECASE)),
]


def _normalize_text_signal(value: object) -> str:
    """Normalize OCR-like snippets before using them in retrieval queries."""
    if not isinstance(value, str):
        return ""
    cleaned = _MULTISPACE_RE.sub(" ", value.replace("\r", " ").replace("\n", " ")).strip()
    if not cleaned:
        return ""
    return cleaned[:160]


def _extract_json_object(text: str) -> dict:
    """Parse a JSON object from model output, tolerating extra wrapper text."""
    if not text:
        return {}

    candidate = text.strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(candidate)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _detect_platform_hint(text: str) -> str | None:
    """Infer a platform key from visible screenshot text."""
    for platform_key, pattern in _PLATFORM_HINT_PATTERNS:
        if pattern.search(text):
            return platform_key
    return None


async def analyze_image_for_retrieval(
    image_base64: str,
    image_media_type: str = "image/jpeg",
) -> dict:
    """
    Extract retrieval-friendly text signals from a screenshot.

    Returns an empty dict on failure so the caller can fall back to text-only retrieval.
    """
    if not image_base64:
        return {}

    system_prompt = (
        "You are a screenshot analyzer. Return ONLY a JSON object, nothing else."
    )
    user_prompt = (
        'Look at this screenshot. Return ONLY this JSON object with no explanation: '
        '{"visible_error": "<most important error text visible, or empty string>", '
        '"detected_platform": "<platform or publisher name visible, or empty string>"}'
    )

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_prompt,
                "images": [image_base64],
            },
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 512,
        },
    }

    response: httpx.Response | None = None
    models = _candidate_models()
    for index, model_name in enumerate(models):
        fallback_model = models[index + 1] if index < len(models) - 1 else None
        try:
            timeout = httpx.Timeout(15.0, read=90.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                request_payload = {**payload, "model": model_name}
                _log_model_use("image analysis", model_name)
                response = await client.post(OLLAMA_CHAT_URL, json=request_payload)
                if response.status_code >= 400:
                    error_text = response.text
                    should_retry, reason = _evaluate_fallback_attempt(
                        model_name,
                        fallback_model,
                        status_code=response.status_code,
                        error_text=error_text,
                    )
                    if should_retry and fallback_model:
                        _log_primary_failure(model_name, reason)
                        _log_retry_with_fallback(fallback_model)
                        continue
                    response.raise_for_status()
                break
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            should_retry, reason = _evaluate_fallback_attempt(
                model_name,
                fallback_model,
                exc=exc,
            )
            if should_retry and fallback_model:
                _log_primary_failure(model_name, reason)
                _log_retry_with_fallback(fallback_model)
                continue
            print(f"[VISION WARN] image analysis request failed: {exc}")
            return {}
        except httpx.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None:
                log.error(
                    "[LLM] image-analysis request failed: %s %s",
                    model_name,
                    _failure_reason_from_status(response.status_code, response.text),
                )
            print(f"[VISION WARN] image analysis request failed: {exc}")
            return {}
    else:
        return {}

    if not response.content:
        print("[VISION WARN] image analysis: empty HTTP response body")
        return {}
    resp_data = response.json()
    msg = resp_data.get("message", {})
    content = msg.get("content", "").strip()
    if not content:
        # gemma4:e2b routes multimodal responses into message.thinking
        # when called non-streaming - fall back to that field
        content = msg.get("thinking", "").strip()
        if content:
            print("[VISION] using message.thinking fallback for image analysis")
        else:
            print("[VISION WARN] image analysis: both content and thinking are empty. Response keys:", list(resp_data.keys()))
            return {}
    parsed = _extract_json_object(content)
    if not parsed:
        print(f"[VISION WARN] image analysis returned non-JSON content: {content[:200]!r}")
        return {}

    visible_error = _normalize_text_signal(parsed.get("visible_error"))
    detected_platform = _normalize_text_signal(parsed.get("detected_platform"))

    combined_text = " ".join(filter(None, [detected_platform, visible_error]))
    inferred_platform = _detect_platform_hint(combined_text)
    if inferred_platform:
        detected_platform = inferred_platform

    result: dict[str, object] = {}
    if detected_platform:
        result["detected_platform"] = detected_platform
    if visible_error:
        result["visible_error"] = visible_error
    return result


def build_augmented_query(message: str, image_context: dict) -> str:
    """Append screenshot-derived retrieval clues to the user's text query."""
    base_query = (message or "").strip()
    if not image_context:
        return base_query

    parts: list[str] = [base_query]
    seen: set[str] = {base_query.casefold()} if base_query else set()

    for key in ("detected_platform", "visible_error"):
        normalized = _normalize_text_signal(image_context.get(key))
        if not normalized:
            continue
        dedupe_key = normalized.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if key == "detected_platform":
            parts.append(f"platform {normalized}")
        else:
            parts.append(normalized)

    return " ".join(part for part in parts if part).strip()


async def stream_llm_response(
    prompt: str,
    system: str = "",
    enable_thinking: bool = True,
    image_base64: str | None = None,
):
    """
    Async generator that streams tokens from Ollama one chunk at a time.
    Emits Gemma 4 thought blocks separately from response text.
    When image_base64 is provided the request is sent as a multimodal generate call.
    """
    if enable_thinking:
        system = f"<|think|>\n{system}" if system else "<|think|>"

    payload = {
        "prompt": prompt,
        "system": system,
        "stream": True,
        "think": enable_thinking,
    }
    if image_base64:
        payload["images"] = [image_base64]

    models = _candidate_models()
    for index, model_name in enumerate(models):
        fallback_model = models[index + 1] if index < len(models) - 1 else None
        thought_start_marker = "<|channel>thought"
        thought_end_marker = "<channel|>"
        in_thought_block = False
        marker_buffer = ""
        response_word_buffer = ""
        thought_word_buffer = ""
        emitted_anything = False
        try:
            timeout = httpx.Timeout(5.0, read=120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                request_payload = {**payload, "model": model_name}
                _log_model_use("streamed generate response", model_name)
                async with client.stream("POST", OLLAMA_GENERATE_URL, json=request_payload) as response:
                    if response.status_code >= 400:
                        error_text = (await response.aread()).decode("utf-8", errors="ignore")
                        should_retry, reason = _evaluate_fallback_attempt(
                            model_name,
                            fallback_model,
                            status_code=response.status_code,
                            error_text=error_text,
                        )
                        if should_retry and fallback_model:
                            _log_primary_failure(model_name, reason)
                            _log_retry_with_fallback(fallback_model)
                            continue
                        response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if chunk.get("done"):
                            break

                        thought_token = chunk.get("thinking", "")
                        token = chunk.get("response", "")

                        if thought_token:
                            thought_word_buffer += thought_token
                            chunks, thought_word_buffer = flush_word_boundaries(thought_word_buffer)
                            for chunk_text in chunks:
                                emitted_anything = True
                                yield {"type": "thought", "token": chunk_text}

                        if not token:
                            continue

                        marker_buffer += token

                        while marker_buffer:
                            if not in_thought_block:
                                start_idx = marker_buffer.find(thought_start_marker)
                                if start_idx != -1:
                                    response_word_buffer += marker_buffer[:start_idx]
                                    chunks, response_word_buffer = flush_word_boundaries(response_word_buffer)
                                    for chunk_text in chunks:
                                        emitted_anything = True
                                        yield {"type": "response", "token": chunk_text}
                                    marker_buffer = marker_buffer[start_idx + len(thought_start_marker):]
                                    in_thought_block = True
                                    continue

                                safe_len = max(0, len(marker_buffer) - (len(thought_start_marker) - 1))
                                if safe_len > 0:
                                    response_word_buffer += marker_buffer[:safe_len]
                                    chunks, response_word_buffer = flush_word_boundaries(response_word_buffer)
                                    for chunk_text in chunks:
                                        emitted_anything = True
                                        yield {"type": "response", "token": chunk_text}
                                    marker_buffer = marker_buffer[safe_len:]
                                break

                            end_idx = marker_buffer.find(thought_end_marker)
                            if end_idx != -1:
                                thought_word_buffer += marker_buffer[:end_idx]
                                chunks, thought_word_buffer = flush_word_boundaries(thought_word_buffer)
                                for chunk_text in chunks:
                                    emitted_anything = True
                                    yield {"type": "thought", "token": chunk_text}
                                marker_buffer = marker_buffer[end_idx + len(thought_end_marker):]
                                in_thought_block = False
                                continue

                            safe_len = max(0, len(marker_buffer) - (len(thought_end_marker) - 1))
                            if safe_len > 0:
                                thought_word_buffer += marker_buffer[:safe_len]
                                chunks, thought_word_buffer = flush_word_boundaries(thought_word_buffer)
                                for chunk_text in chunks:
                                    emitted_anything = True
                                    yield {"type": "thought", "token": chunk_text}
                                marker_buffer = marker_buffer[safe_len:]
                            break

                    if marker_buffer:
                        if in_thought_block:
                            thought_word_buffer += marker_buffer
                        else:
                            response_word_buffer += marker_buffer

                    if thought_word_buffer:
                        emitted_anything = True
                        yield {"type": "thought", "token": thought_word_buffer}

                    if response_word_buffer and not in_thought_block:
                        cleaned = strip_thinking_tags_preserve_spacing(response_word_buffer)
                        if cleaned:
                            emitted_anything = True
                            yield {"type": "response", "token": cleaned}
            if index > 0:
                _log_fallback_success(model_name)
            return
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            should_retry, reason = _evaluate_fallback_attempt(
                model_name,
                fallback_model,
                exc=exc,
            )
            if should_retry and fallback_model and not emitted_anything:
                _log_primary_failure(model_name, reason)
                _log_retry_with_fallback(fallback_model)
                continue
            if isinstance(exc, httpx.ConnectError):
                yield {"type": "response", "token": "[ERROR: Ollama is not running. Please start Ollama and try again.]"}
            else:
                yield {"type": "response", "token": "[ERROR: LLM response timed out.]"}
            return
        except httpx.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None:
                log.error(
                    "[LLM] streamed generate request failed: %s %s",
                    model_name,
                    _failure_reason_from_status(response.status_code, response.text),
                )
            yield {"type": "response", "token": f"[ERROR: Ollama request failed: {exc}]"}
            return


async def stream_llm_chat_response(
    message: str,
    system: str = "",
    history: list | None = None,
    image_base64: str | None = None,
):
    """
    Async generator that streams tokens from Ollama's /api/chat endpoint.

    Use this instead of stream_llm_response when images are involved — the
    chat endpoint correctly handles the multimodal `images` field on the user
    message, while the generate endpoint ignores it for vision tasks.

    Thinking tokens are extracted from the `thinking` field in each chunk and
    emitted as {"type": "thought", ...}; response text is emitted as
    {"type": "response", ...}.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        for msg in history:
            if "role" in msg and "content" in msg:
                messages.append(msg)
    user_msg: dict = {"role": "user", "content": message or "Please look at this screenshot and help me."}
    if image_base64:
        user_msg["images"] = [image_base64]
    messages.append(user_msg)

    payload = {
        "messages": messages,
        "stream": True,
        "think": True,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }

    models = _candidate_models()
    for index, model_name in enumerate(models):
        fallback_model = models[index + 1] if index < len(models) - 1 else None
        response_word_buffer = ""
        thought_word_buffer = ""
        emitted_anything = False
        try:
            timeout = httpx.Timeout(5.0, read=120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                request_payload = {**payload, "model": model_name}
                _log_model_use("streamed chat response", model_name)
                async with client.stream("POST", OLLAMA_CHAT_URL, json=request_payload) as response:
                    if response.status_code >= 400:
                        error_text = (await response.aread()).decode("utf-8", errors="ignore")
                        should_retry, reason = _evaluate_fallback_attempt(
                            model_name,
                            fallback_model,
                            status_code=response.status_code,
                            error_text=error_text,
                        )
                        if should_retry and fallback_model:
                            _log_primary_failure(model_name, reason)
                            _log_retry_with_fallback(fallback_model)
                            continue
                        response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if chunk.get("done"):
                            break

                        msg = chunk.get("message", {})
                        thinking_token = msg.get("thinking", "") or ""
                        response_token = msg.get("content", "") or ""

                        if thinking_token:
                            thought_word_buffer += thinking_token
                            chunks, thought_word_buffer = flush_word_boundaries(thought_word_buffer)
                            for t in chunks:
                                emitted_anything = True
                                yield {"type": "thought", "token": t}

                        if response_token:
                            response_word_buffer += response_token
                            chunks, response_word_buffer = flush_word_boundaries(response_word_buffer)
                            for t in chunks:
                                emitted_anything = True
                                yield {"type": "response", "token": t}

            if thought_word_buffer:
                emitted_anything = True
                yield {"type": "thought", "token": thought_word_buffer}
            if response_word_buffer:
                emitted_anything = True
                yield {"type": "response", "token": response_word_buffer}
            if index > 0:
                _log_fallback_success(model_name)
            return
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            should_retry, reason = _evaluate_fallback_attempt(
                model_name,
                fallback_model,
                exc=exc,
            )
            if should_retry and fallback_model and not emitted_anything:
                _log_primary_failure(model_name, reason)
                _log_retry_with_fallback(fallback_model)
                continue
            if isinstance(exc, httpx.ConnectError):
                yield {"type": "response", "token": "[ERROR: Ollama is not running. Please start Ollama and try again.]"}
            else:
                yield {"type": "response", "token": "[ERROR: LLM response timed out.]"}
            return
        except httpx.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None:
                log.error(
                    "[LLM] streamed chat request failed: %s %s",
                    model_name,
                    _failure_reason_from_status(response.status_code, response.text),
                )
            yield {"type": "response", "token": f"[ERROR: Ollama request failed: {exc}]"}
            return


class LlamaClient(LLMClient):
    def chat(
        self,
        message: str,
        context: str = "",
        history: list | None = None,
        system_hint: str = "",
        image_base64: str | None = None,
    ) -> str:
        """
        Send a chat message to Gemma4 via the Ollama /api/chat endpoint.

        If image_base64 is provided, the message is sent as a multimodal
        request with the screenshot attached. Gemma4 will read the visible
        text and UI state from the image before answering.

        Per the Ollama docs, images are passed as a list on the user message.
        The REST API expects plain base64 strings (no data-URI prefix).
        """
        try:
            print("\n" + "=" * 50)
            print("[DEBUG] User Message:", message)
            if image_base64:
                print("[DEBUG] Screenshot attached — using vision path")
            if context:
                preview = context[:500] + "..." if len(context) > 500 else context
                print("[DEBUG] Context Preview:", preview)
            print("=" * 50 + "\n")

            # FAQ+image should stay grounded in the FAQ answer rather than
            # switching to the troubleshooting-oriented vision prompt.
            if image_base64 and context and _is_faq_context(context):
                system_content = build_grounded_vision_faq_prompt(message, context)
            elif image_base64:
                system_content = build_vision_system_prompt(context, system_hint)
            else:
                system_content = build_system_prompt(context, system_hint)

            messages = [{"role": "system", "content": system_content}]

            if history:
                for msg in history:
                    if "role" in msg and "content" in msg:
                        messages.append(msg)

            # Build the user message — attach image if provided
            user_message: dict = {"role": "user", "content": message or "Please look at this screenshot and help me."}
            if image_base64:
                user_message["images"] = [image_base64]

            messages.append(user_message)

            payload = {
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1024,
                },
            }

            models = _candidate_models()
            for index, model_name in enumerate(models):
                fallback_model = models[index + 1] if index < len(models) - 1 else None
                try:
                    request_payload = {**payload, "model": model_name}
                    _log_model_use("chat response", model_name)
                    response = requests.post(OLLAMA_CHAT_URL, json=request_payload, timeout=(15, 240))
                    if response.status_code >= 400:
                        error_text = response.text
                        should_retry, reason = _evaluate_fallback_attempt(
                            model_name,
                            fallback_model,
                            status_code=response.status_code,
                            error_text=error_text,
                        )
                        if should_retry and fallback_model:
                            _log_primary_failure(model_name, reason)
                            _log_retry_with_fallback(fallback_model)
                            continue
                        response.raise_for_status()
                    if index > 0:
                        _log_fallback_success(model_name)
                    return strip_thinking_tags(response.json()["message"].get("content", ""))
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                    should_retry, reason = _evaluate_fallback_attempt(
                        model_name,
                        fallback_model,
                        exc=exc,
                    )
                    if should_retry and fallback_model:
                        _log_primary_failure(model_name, reason)
                        _log_retry_with_fallback(fallback_model)
                        continue
                    log.error("[LLM] model request failed: %s %s", model_name, reason)
                    print(f"[ERROR] Ollama request failed: {exc}")
                    return "I'm having trouble connecting right now. Please try again in a moment."
                except requests.exceptions.RequestException as exc:
                    response = getattr(exc, "response", None)
                    if response is not None:
                        error_text = response.text
                        should_retry, reason = _evaluate_fallback_attempt(
                            model_name,
                            fallback_model,
                            status_code=response.status_code,
                            error_text=error_text,
                        )
                        if should_retry and fallback_model:
                            _log_primary_failure(model_name, reason)
                            _log_retry_with_fallback(fallback_model)
                            continue
                        log.error("[LLM] model request failed: %s %s", model_name, reason)
                    else:
                        log.error("[LLM] model request failed: %s %s: %s", model_name, exc.__class__.__name__, exc)
                    print(f"[ERROR] Ollama request failed: {exc}")
                    return "I'm having trouble connecting right now. Please try again in a moment."

            log.error(
                "[LLM] both primary and fallback models failed: primary=%s fallback=%s",
                PRIMARY_LLM_MODEL,
                FALLBACK_LLM_MODEL,
            )
            return "I'm having trouble connecting right now. Please try again in a moment."

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Ollama request failed: {e}")
            return "I'm having trouble connecting right now. Please try again in a moment."
