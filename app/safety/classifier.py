from __future__ import annotations

import json
import logging
import re

import httpx

from app.safety.models import SafetyClassification, SafetyDecision
from app.safety.taxonomy import CLASSIFIER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {
    "allow_rag", "out_of_scope", "block_harmful",
    "ask_clarification", "needs_human_review",
}
_VALID_SCOPE_AREAS = {
    "campus_store", "immediate_access", "textbook",
    "courseware_platform", "returns_refunds", "unknown", "out_of_scope",
}
_VALID_RISK_AREAS = {
    "none", "weapons", "explosives", "cyber_abuse", "unauthorized_access",
    "fraud", "credential_theft", "privacy_violation", "self_harm",
    "violence", "harassment", "sexual_content", "other",
}

# Classifier returned bad JSON or an empty body — ask for clarification rather
# than silently allowing ambiguous messages into RAG.
_PARSE_FAILURE_FALLBACK = SafetyDecision(
    action="ASK_CLARIFICATION",
    category="classifier_error",
    confidence=0.0,
    reason="Safety classifier returned unparseable output. Asking student to clarify.",
    matched_rules=["classifier_fallback"],
)

# Ollama returned a connectivity/HTTP error. The deterministic rules already
# ran and found no obvious harmful patterns, but the classifier could not
# confirm safety. Ask the student to clarify rather than letting an unreviewed
# ambiguous message straight into RAG.
_SERVER_ERROR_FALLBACK = SafetyDecision(
    action="ASK_CLARIFICATION",
    category="classifier_unavailable",
    confidence=0.0,
    reason="Safety classifier unreachable (server error). Asking student to clarify intent.",
    matched_rules=["classifier_fallback"],
)


def _parse_classification(raw: str) -> SafetyClassification | None:
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return None

    action = str(data.get("recommended_action", "")).strip()
    if action not in _VALID_ACTIONS:
        action = "needs_human_review"

    scope = str(data.get("scope_area", "unknown")).strip()
    if scope not in _VALID_SCOPE_AREAS:
        scope = "unknown"

    risk = str(data.get("risk_area", "none")).strip()
    if risk not in _VALID_RISK_AREAS:
        risk = "other"

    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    return SafetyClassification(
        is_in_scope=bool(data.get("is_in_scope", False)),
        scope_area=scope,
        is_harmful_or_sensitive=bool(data.get("is_harmful_or_sensitive", False)),
        risk_area=risk,
        recommended_action=action,
        confidence=confidence,
        brief_reason=str(data.get("brief_reason", ""))[:200],
    )


def _classification_to_decision(clf: SafetyClassification) -> SafetyDecision:
    action_map = {
        "allow_rag": "ALLOW",
        "out_of_scope": "OUT_OF_SCOPE_FALLBACK",
        "block_harmful": "HARMFUL_REFUSAL",
        "ask_clarification": "ASK_CLARIFICATION",
        "needs_human_review": "NEEDS_HUMAN_REVIEW",
    }

    # If classifier flags harmful but recommends allow → escalate to review
    if clf.is_harmful_or_sensitive and clf.recommended_action == "allow_rag":
        return SafetyDecision(
            action="NEEDS_HUMAN_REVIEW",
            category=clf.risk_area,
            confidence=clf.confidence,
            reason=f"Classifier flagged harmful/sensitive but recommended allow: {clf.brief_reason}",
            matched_rules=["classifier"],
        )

    action = action_map.get(clf.recommended_action, "NEEDS_HUMAN_REVIEW")
    category = clf.risk_area if clf.is_harmful_or_sensitive else clf.scope_area
    return SafetyDecision(
        action=action,
        category=category,
        confidence=clf.confidence,
        reason=clf.brief_reason,
        matched_rules=["classifier"],
    )


async def classify_with_llm(message: str, llm_client) -> SafetyDecision:
    """
    Call Ollama directly as a JSON-only safety classifier.

    Uses the primary model from LlamaClient but bypasses the Campus Store
    persona so the output is a pure safety classification, not an answer.

    Fails closed: any exception or invalid output → NEEDS_HUMAN_REVIEW.
    """
    from app.llm.llama_client import OLLAMA_CHAT_URL, PRIMARY_LLM_MODEL

    try:
        payload = {
            "model": PRIMARY_LLM_MODEL,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 300},
            "messages": [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": f'User message: "{message}"\n\nReturn JSON only.'},
            ],
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(OLLAMA_CHAT_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        raw = data.get("message", {}).get("content", "") or ""
        if not raw.strip():
            logger.warning("[SAFETY] Classifier returned empty response")
            return _PARSE_FAILURE_FALLBACK

        clf = _parse_classification(raw)
        if clf is None:
            logger.warning("[SAFETY] Classifier returned unparseable output: %s", raw[:200])
            return _PARSE_FAILURE_FALLBACK

        decision = _classification_to_decision(clf)
        logger.info(
            "[SAFETY] Classifier: action=%s category=%s confidence=%.2f reason=%s",
            decision.action,
            decision.category,
            decision.confidence,
            decision.reason,
        )
        return decision

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "[SAFETY] Classifier HTTP error %s — returning ASK_CLARIFICATION",
            exc.response.status_code,
        )
        return _SERVER_ERROR_FALLBACK
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.warning("[SAFETY] Classifier unavailable — returning ASK_CLARIFICATION: %s", exc)
        return _SERVER_ERROR_FALLBACK
    except Exception as exc:
        logger.warning("[SAFETY] Classifier unexpected error — returning ASK_CLARIFICATION: %s", exc)
        return _SERVER_ERROR_FALLBACK
