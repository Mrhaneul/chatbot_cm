"""
Safety and scope taxonomy for the Lance safety gate.

Defines the allowed domain, harmful categories, out-of-scope categories,
and the source label emitted when a decision is made.
"""
from __future__ import annotations

ALLOWED_SCOPE_DESCRIPTION = (
    "Campus Store, Immediate Access, textbooks, digital course materials, "
    "courseware platforms, eBooks, access codes, returns/refunds, store hours, "
    "shipping, and supported publisher/platform access issues."
)

CAMPUS_STORE_ALLOWLIST_KEYWORDS: list[str] = [
    "immediate access",
    "textbook",
    "ebook",
    "e-book",
    "course material",
    "access code",
    "blackboard",
    "cengage",
    "mindtap",
    "mcgraw",
    "connect",
    "pearson",
    "mylab",
    "mastering",
    "vitalsource",
    "bookshelf",
    "wiley",
    "wileyplus",
    "stukent",
    "simucase",
    "zybooks",
    "zybook",
    "sage vantage",
    "bedford",
    "macmillan",
    "achieve",
    "inquizitive",
    "norton",
    "campus store",
    "opt out",
    "opt-out",
    "refund",
    "return",
    "rental",
    "store hours",
    "digital content",
    "publisher",
    "my book",
    "my textbook",
    "my ebook",
    "homework",
    "courseware",
    "aleks",
    "mylab",
    "mastering",
    "cliftonstrengths",
]

HARMFUL_RISK_CATEGORIES: list[str] = [
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
]

CLASSIFIER_SYSTEM_PROMPT = (
    "Classify the user's message for the Lance Campus Store assistant. "
    "Do not answer the user. Return JSON only with no extra text.\n\n"
    f"Allowed scope: {ALLOWED_SCOPE_DESCRIPTION}\n\n"
    "Mark harmful/sensitive if the user asks for instructions, procurement, evasion, "
    "exploitation, unauthorized access, credential theft, fraud, privacy invasion, "
    "violence, weapons, explosives, self-harm, harassment, sexual content, or illegal activity.\n\n"
    "If the message is unrelated to the allowed scope and harmless, choose out_of_scope.\n"
    "If it is related to the allowed scope but missing needed context, choose ask_clarification.\n"
    "If it is clearly safe and in scope, choose allow_rag.\n\n"
    "Return ONLY valid JSON matching this schema:\n"
    '{"is_in_scope": bool, "scope_area": "campus_store"|"immediate_access"|"textbook"'
    '|"courseware_platform"|"returns_refunds"|"unknown"|"out_of_scope", '
    '"is_harmful_or_sensitive": bool, "risk_area": "none"|"weapons"|"explosives"'
    '|"cyber_abuse"|"unauthorized_access"|"fraud"|"credential_theft"'
    '|"privacy_violation"|"self_harm"|"violence"|"harassment"|"sexual_content"|"other", '
    '"recommended_action": "allow_rag"|"out_of_scope"|"block_harmful"'
    '|"ask_clarification"|"needs_human_review", '
    '"confidence": 0.0-1.0, "brief_reason": "short explanation"}'
)
