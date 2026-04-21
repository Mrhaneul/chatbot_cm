import base64
import json
import re

import httpx
import requests

from app.llm.base import LLMClient

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4:e2b"


_THINKING_TAG_RE: re.Pattern[str] = re.compile(
    r"<\|channel\>(?:thought)?.*?<channel\|>", re.DOTALL
)

_WORD_BOUNDARY_RE: re.Pattern[str] = re.compile(r"[ \n\t.,!?:;]")


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
        "You are extracting screenshot details for semantic retrieval. "
        "Read all visible text in the image and return JSON only."
    )
    user_prompt = (
        "Return a JSON object with exactly these keys: "
        'detected_platform, page_title, error_text, text_signals. '
        "Rules: detected_platform should be a short platform key or null; "
        "page_title should be the main page heading or null; "
        "error_text should be the most important visible error/problem text or null; "
        "text_signals should be an array of up to 8 short strings copied or paraphrased "
        "from the screenshot, focusing on platform names, page labels, buttons, and errors. "
        f"The image media type is {image_media_type}. "
        "Do not include markdown fences or explanations."
    )

    payload = {
        "model": OLLAMA_MODEL,
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
            "num_predict": 256,
        },
    }

    try:
        timeout = httpx.Timeout(5.0, read=60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(OLLAMA_CHAT_URL, json=payload)
            response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        print(f"[VISION WARN] image analysis request failed: {exc}")
        return {}

    content = (
        response.json().get("message", {}).get("content", "")
        if response.content
        else ""
    )
    parsed = _extract_json_object(content)
    if not parsed:
        print("[VISION WARN] image analysis returned non-JSON content")
        return {}

    page_title = _normalize_text_signal(parsed.get("page_title"))
    error_text = _normalize_text_signal(parsed.get("error_text"))

    raw_signals = parsed.get("text_signals", [])
    if isinstance(raw_signals, str):
        raw_signals = [raw_signals]
    if not isinstance(raw_signals, list):
        raw_signals = []

    text_signals: list[str] = []
    seen: set[str] = set()
    for item in raw_signals:
        normalized = _normalize_text_signal(item)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        text_signals.append(normalized)
        if len(text_signals) >= 8:
            break

    detected_platform = _normalize_text_signal(parsed.get("detected_platform"))
    combined_text = " ".join(filter(None, [detected_platform, page_title, error_text, *text_signals]))
    inferred_platform = _detect_platform_hint(combined_text)
    if inferred_platform:
        detected_platform = inferred_platform

    result: dict[str, object] = {}
    if detected_platform:
        result["detected_platform"] = detected_platform
    if page_title:
        result["page_title"] = page_title
    if error_text:
        result["error_text"] = error_text
    if text_signals:
        result["text_signals"] = text_signals
    return result


def build_augmented_query(message: str, image_context: dict) -> str:
    """Append screenshot-derived retrieval clues to the user's text query."""
    base_query = (message or "").strip()
    if not image_context:
        return base_query

    parts: list[str] = [base_query]
    seen: set[str] = {base_query.casefold()} if base_query else set()

    for key in ("detected_platform", "page_title", "error_text"):
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

    raw_signals = image_context.get("text_signals", [])
    if isinstance(raw_signals, str):
        raw_signals = [raw_signals]
    if isinstance(raw_signals, list):
        for item in raw_signals:
            normalized = _normalize_text_signal(item)
            if not normalized:
                continue
            dedupe_key = normalized.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
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
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": True,
        "think": enable_thinking,
    }
    if image_base64:
        payload["images"] = [image_base64]

    thought_start_marker = "<|channel>thought"
    thought_end_marker = "<channel|>"
    in_thought_block = False
    marker_buffer = ""
    response_word_buffer = ""
    thought_word_buffer = ""

    try:
        timeout = httpx.Timeout(5.0, read=120.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", OLLAMA_GENERATE_URL, json=payload) as response:
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
                                    yield {"type": "response", "token": chunk_text}
                                marker_buffer = marker_buffer[start_idx + len(thought_start_marker):]
                                in_thought_block = True
                                continue

                            safe_len = max(0, len(marker_buffer) - (len(thought_start_marker) - 1))
                            if safe_len > 0:
                                response_word_buffer += marker_buffer[:safe_len]
                                chunks, response_word_buffer = flush_word_boundaries(response_word_buffer)
                                for chunk_text in chunks:
                                    yield {"type": "response", "token": chunk_text}
                                marker_buffer = marker_buffer[safe_len:]
                            break

                        end_idx = marker_buffer.find(thought_end_marker)
                        if end_idx != -1:
                            thought_word_buffer += marker_buffer[:end_idx]
                            chunks, thought_word_buffer = flush_word_boundaries(thought_word_buffer)
                            for chunk_text in chunks:
                                yield {"type": "thought", "token": chunk_text}
                            marker_buffer = marker_buffer[end_idx + len(thought_end_marker):]
                            in_thought_block = False
                            continue

                        safe_len = max(0, len(marker_buffer) - (len(thought_end_marker) - 1))
                        if safe_len > 0:
                            thought_word_buffer += marker_buffer[:safe_len]
                            chunks, thought_word_buffer = flush_word_boundaries(thought_word_buffer)
                            for chunk_text in chunks:
                                yield {"type": "thought", "token": chunk_text}
                            marker_buffer = marker_buffer[safe_len:]
                        break

                if marker_buffer:
                    if in_thought_block:
                        thought_word_buffer += marker_buffer
                    else:
                        response_word_buffer += marker_buffer

                if thought_word_buffer:
                    yield {"type": "thought", "token": thought_word_buffer}

                if response_word_buffer and not in_thought_block:
                    cleaned = strip_thinking_tags_preserve_spacing(response_word_buffer)
                    if cleaned:
                        yield {"type": "response", "token": cleaned}

    except httpx.ConnectError:
        yield {"type": "response", "token": "[ERROR: Ollama is not running. Please start Ollama and try again.]"}
    except httpx.ReadTimeout:
        yield {"type": "response", "token": "[ERROR: LLM response timed out.]"}


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
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "think": True,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }

    response_word_buffer = ""
    thought_word_buffer = ""

    try:
        timeout = httpx.Timeout(5.0, read=120.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", OLLAMA_CHAT_URL, json=payload) as response:
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
                            yield {"type": "thought", "token": t}

                    if response_token:
                        response_word_buffer += response_token
                        chunks, response_word_buffer = flush_word_boundaries(response_word_buffer)
                        for t in chunks:
                            yield {"type": "response", "token": t}

        if thought_word_buffer:
            yield {"type": "thought", "token": thought_word_buffer}
        if response_word_buffer:
            yield {"type": "response", "token": response_word_buffer}

    except httpx.ConnectError:
        yield {"type": "response", "token": "[ERROR: Ollama is not running. Please start Ollama and try again.]"}
    except httpx.ReadTimeout:
        yield {"type": "response", "token": "[ERROR: LLM response timed out.]"}


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

            # Choose system prompt: vision-aware variant when screenshot is present
            if image_base64:
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
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1024,
                },
            }

            response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=(5, 120))
            response.raise_for_status()

            return strip_thinking_tags(response.json()["message"]["content"])

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Ollama request failed: {e}")
            return "I'm having trouble connecting right now. Please try again in a moment."
