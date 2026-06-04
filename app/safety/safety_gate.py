from __future__ import annotations

import logging

from app.safety.classifier import classify_with_llm
from app.safety.deterministic_rules import check_deterministic
from app.safety.models import SafetyDecision
from app.safety.response_templates import get_template

logger = logging.getLogger(__name__)

_AMBIGUOUS_ALLOW = SafetyDecision(
    action="ALLOW",
    category="unknown",
    confidence=0.6,
    reason="No deterministic rule matched and classifier is disabled; defaulting to ALLOW.",
    matched_rules=[],
)


async def run_safety_gate(
    message: str,
    *,
    enable_filter: bool = True,
    enable_classifier: bool = True,
    llm_client=None,
) -> SafetyDecision:
    """
    Main entry point for the safety gate.

    Decision order:
      1. If filter is disabled → ALLOW unconditionally.
      2. Run deterministic rules. If a clear decision is found, return it.
      3. If ambiguous and classifier is enabled, call LLM classifier.
      4. If classifier is disabled or unavailable, default to ALLOW (conservative
         for in-scope traffic, since deterministic rules already caught harmful cases).

    Args:
        message: The raw student message.
        enable_filter: ENABLE_SAFETY_FILTER env flag.
        enable_classifier: ENABLE_SAFETY_CLASSIFIER env flag.
        llm_client: LlamaClient instance for classifier calls (may be None).

    Returns:
        SafetyDecision with action, category, confidence, reason.
    """
    if not enable_filter:
        return SafetyDecision(
            action="ALLOW",
            category="filter_disabled",
            confidence=1.0,
            reason="Safety filter disabled by configuration.",
            matched_rules=[],
        )

    if not message or not message.strip():
        return SafetyDecision(
            action="ALLOW",
            category="empty_message",
            confidence=1.0,
            reason="Empty message passes through.",
            matched_rules=[],
        )

    # 1. Deterministic rules — fast path
    decision = check_deterministic(message)
    if decision is not None:
        _log_decision(decision, source="deterministic")
        return decision

    # 2. Ambiguous — try LLM classifier
    if enable_classifier and llm_client is not None:
        decision = await classify_with_llm(message, llm_client)
        _log_decision(decision, source="classifier")
        return decision

    # 3. No classifier available — default to ALLOW for ambiguous messages
    # (deterministic rules already blocked obvious harmful cases)
    _log_decision(_AMBIGUOUS_ALLOW, source="default")
    return _AMBIGUOUS_ALLOW


def get_safety_response(decision: SafetyDecision) -> str:
    """Return the user-facing response text for a non-ALLOW decision."""
    template_map = {
        "HARMFUL_REFUSAL": "harmful_refusal",
        "ABUSE_REFUSAL": "abuse_refusal",
        "OUT_OF_SCOPE_FALLBACK": "campus_store_scope_fallback",
        "NEEDS_HUMAN_REVIEW": "needs_human_review",
        "ASK_CLARIFICATION": "ask_clarification",
    }
    template_name = template_map.get(decision.action, "campus_store_scope_fallback")
    return get_template(template_name)


def safety_source_label(decision: SafetyDecision) -> str:
    """Return a structured source label for logging and response metadata."""
    return f"SAFETY:{decision.action}:{decision.category}"


def _log_decision(decision: SafetyDecision, *, source: str) -> None:
    level = logging.WARNING if decision.action != "ALLOW" else logging.DEBUG
    logger.log(
        level,
        "[SAFETY][%s] action=%s category=%s confidence=%.2f reason=%s rules=%s",
        source,
        decision.action,
        decision.category,
        decision.confidence,
        decision.reason,
        decision.matched_rules,
    )
