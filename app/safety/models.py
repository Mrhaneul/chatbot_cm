from __future__ import annotations

from typing import Literal
from pydantic import BaseModel


class SafetyDecision(BaseModel):
    action: Literal[
        "ALLOW",
        "ASK_CLARIFICATION",
        "OUT_OF_SCOPE_FALLBACK",
        "HARMFUL_REFUSAL",
        "ABUSE_REFUSAL",
        "NEEDS_HUMAN_REVIEW",
    ]
    category: str
    confidence: float
    reason: str
    matched_rules: list[str] = []


class SafetyClassification(BaseModel):
    is_in_scope: bool
    scope_area: Literal[
        "campus_store",
        "immediate_access",
        "textbook",
        "courseware_platform",
        "returns_refunds",
        "unknown",
        "out_of_scope",
    ]
    is_harmful_or_sensitive: bool
    risk_area: Literal[
        "none",
        "weapons",
        "explosives",
        "cyber_abuse",
        "unauthorized_access",
        "fraud",
        "credential_theft",
        "privacy_violation",
        "self_harm",
        "violence",
        "harassment",
        "sexual_content",
        "other",
    ]
    recommended_action: Literal[
        "allow_rag",
        "out_of_scope",
        "block_harmful",
        "ask_clarification",
        "needs_human_review",
    ]
    confidence: float
    brief_reason: str
