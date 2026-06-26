"""
app/intake/flow.py

Stateless functions that drive the intake / slot-filling conversation turn.
All mutable state lives in the caller (session["intake_profile"]).
"""
from __future__ import annotations

import re
from typing import Optional

from app.intake.models import IntakeProfile
from app.intake.questions import NEXT_QUESTION, VAGUE_PATTERN_RE, INTAKE_FALLBACK_MESSAGE
from app.intake.slot_extractor import (
    extract_platform,
    extract_issue_type,
    extract_course_code,
    extract_material_type,
)

_MAX_INTAKE_TURNS = 3

# -- Personal-info detection (student ID / email) ------------------------------
# When a student provides personal info instead of answering the platform/issue
# question, Lance must not collect it — escalate to ImmediateAccess instead.

# Any email address. Official Campus Store support addresses are excluded so a
# student referencing them ("I already emailed ImmediateAccess@...") is not
# escalated for that reason alone.
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
_OFFICIAL_EMAILS = frozenset({
    "immediateaccess@calbaptist.edu",
    "optout@calbaptist.edu",
})

# Labeled student ID, 5-10 digits: "ID 774117", "ID: 774117", "ID# 774117",
# "ID is 774117", "student ID 774117". The connector between "id" and the
# digits is constrained so far-apart numbers do not false-match.
_LABELED_ID_RE = re.compile(
    r"\b(?:student\s+)?id\b\s*(?:number|num|no\.?|#)?\s*(?:is|=|:)?\s*(\d{5,10})\b",
    re.IGNORECASE,
)

# Bare 6-8 digit number — treated as a student ID only during active intake
# (stricter mode), to avoid false positives on prices, page counts, etc.
_BARE_ID_RE = re.compile(r"\b\d{6,8}\b")

# Course code (ENGL1301, BIOL2401) — never treated as a student ID.
_COURSE_CODE_RE = re.compile(r"\b[A-Za-z]{2,6}\s*-?\s*\d{3,4}[A-Za-z]?\b")

MAX_UNKNOWN_ATTEMPTS = 1  # kept for import compatibility; escalation now fires on the first unknown

INTAKE_ESCALATION_MESSAGE = (
    "No problem. Please contact ImmediateAccess@calbaptist.edu for help with your "
    "textbook access issue. They can help identify the correct platform and material "
    "for your course. If possible, include a screenshot of what you are seeing when "
    "you email them."
)

INTAKE_ACCOUNT_ESCALATION_MESSAGE = (
    "Please contact ImmediateAccess@calbaptist.edu for help with your account "
    "or login issue. If possible, include a screenshot of what you are seeing."
)

# Neutral wording: do not state that the student shared personal information.
INTAKE_PERSONAL_INFO_ESCALATION_MESSAGE = (
    "Please contact ImmediateAccess@calbaptist.edu for more help with this issue. "
    "If possible, include a screenshot of what you are seeing."
)

_UNKNOWN_ANSWER_PHRASES = (
    "don't know",
    "dont know",
    "do not know",
    "not sure",
    "no idea",
    "have no idea",
    "unsure",
    "no clue",
    "have no clue",
    "idk",
    "can't find",
    "cant find",
    "cannot find",
    "can not find",
    "don't see",
    "dont see",
    "do not see",
)

_PLATFORM_LOW_INFO_PATTERNS = (
    "issue",
    "problem",
    "question",
    "not working",
    "does not work",
    "doesn't work",
    "confusing",
    "does not show",
    "doesn't show",
    "not show anything",
    "not showing anything",
)

_GENERIC_COURSE_MATERIAL_ISSUE_RE = re.compile(
    r"\b(course|class)\s+(material|materials|textbook|book|content)s?\b.*\b(issue|problem|trouble)\b"
    r"|\b(issue|problem|trouble)\b.*\b(course|class)\s+(material|materials|textbook|book|content)s?\b"
    r"|\bneed (help|assistance)\b.*\b(course|class)\s+(material|materials|textbook|book|content)s?\b",
    re.IGNORECASE,
)


def is_unknown_answer(message: str) -> bool:
    """True when the user signals they cannot supply the requested slot value."""
    if extract_issue_type(message) is not None:
        return False
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in _UNKNOWN_ANSWER_PHRASES)


def _has_non_official_email(message: str) -> bool:
    """True when the message contains an email address other than an official one."""
    return any(addr.lower() not in _OFFICIAL_EMAILS for addr in _EMAIL_RE.findall(message))


def is_personal_info_reply(message: str, *, active_intake: bool = False) -> bool:
    """
    True when the student provides personal info (a student ID or email address)
    instead of answering the platform/issue clarification. Lance must not collect
    this; escalate to ImmediateAccess instead.

    - Non-official email addresses always count.
    - Labeled student IDs ("my ID is 774117", "ID# 774117") with 5-10 digits
      always count.
    - A bare 6-8 digit number counts only when active_intake=True, to avoid
      false positives on prices/quantities in fresh messages.
    - Course codes (ENGL1301, BIOL2401) are never treated as student IDs.
    """
    if _has_non_official_email(message):
        return True
    if _LABELED_ID_RE.search(message):
        return True
    if active_intake:
        # Strip course codes first so e.g. ENGL1301 cannot register as an ID,
        # then look for a bare 6-8 digit run.
        cleaned = _COURSE_CODE_RE.sub(" ", message)
        if _BARE_ID_RE.search(cleaned):
            return True
    return False


def is_vague_message(message: str) -> bool:
    """True when the message matches a vague-complaint pattern."""
    return bool(VAGUE_PATTERN_RE.search(message.strip()))


def _is_platform_low_info_message(message: str) -> bool:
    """
    True for platform-present complaints that name the platform but still do
    not give a specific issue type, e.g. "Cengage is not working."
    """
    if extract_platform(message) is None or extract_issue_type(message) is not None:
        return False
    msg_lower = message.lower()
    return any(pattern in msg_lower for pattern in _PLATFORM_LOW_INFO_PATTERNS)


def is_generic_course_material_issue(message: str) -> bool:
    """
    True for vague course-material complaints that should ask issue type before
    platform, e.g. "I have a course material issue".
    """
    return (
        extract_platform(message) is None
        and extract_issue_type(message) is None
        and bool(_GENERIC_COURSE_MATERIAL_ISSUE_RE.search(message))
    )


def should_enter_intake(message: str, session: dict) -> bool:
    """
    True when this message should start a new intake session.

    Returns False when:
    - An intake_profile is already active (mid-intake).
    - Any legacy clarification flag is active.
    - The message already supplies both a platform and an issue type — intake
      would complete immediately, so skip it and send the message directly to RAG.
    - The message is not vague.

    A platform signal alone does not bypass intake. Platform-present vague
    messages such as "Cengage is not working" still need an issue slot, so
    they enter intake with the platform prefilled and ask the next question.
    """
    if session.get("intake_profile"):
        return False
    if (
        session.get("awaiting_platform_type")
        or session.get("awaiting_publisher_list_response")
        or session.get("awaiting_vitalsource_screen_confirm")
        or session.get("awaiting_class_access_clarification")
    ):
        return False
    # If both platform and issue type are already present, the message is specific
    # enough for RAG — no clarification needed.
    if extract_platform(message) is not None and extract_issue_type(message) is not None:
        return False
    return is_vague_message(message) or _is_platform_low_info_message(message)


def update_profile(profile: IntakeProfile, message: str) -> IntakeProfile:
    """
    Fill in any missing slots from the user's reply and increment turns_spent.
    Returns the mutated profile (in-place mutation for the dataclass).
    """
    if profile.platform is None:
        profile.platform = extract_platform(message)
    if profile.issue_type is None:
        profile.issue_type = extract_issue_type(message)
    if profile.material_type is None:
        profile.material_type = extract_material_type(message)
    if profile.course_code is None:
        profile.course_code = extract_course_code(message)
    profile.turns_spent += 1
    return profile


def next_question(profile: IntakeProfile) -> Optional[str]:
    """
    Return the next question to ask, or None when intake is complete / expired.
    Priority: platform → issue_type.
    """
    if profile.is_complete() or profile.is_expired():
        return None
    if profile.platform is None:
        return NEXT_QUESTION["platform"]
    if profile.issue_type is None:
        return NEXT_QUESTION["issue_type"]
    return None


def intake_is_complete(profile: IntakeProfile) -> bool:
    """True when we have enough slots to perform useful retrieval."""
    return profile.is_complete()


def intake_fallback_message() -> str:
    """Message sent when intake expires without completing."""
    return INTAKE_FALLBACK_MESSAGE
