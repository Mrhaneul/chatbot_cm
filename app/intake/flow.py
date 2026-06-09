"""
app/intake/flow.py

Stateless functions that drive the intake / slot-filling conversation turn.
All mutable state lives in the caller (session["intake_profile"]).
"""
from __future__ import annotations

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

# Maximum number of distinct slots the student can say they don't know before
# the bot stops asking clarifying questions and escalates to a generic answer.
MAX_UNKNOWN_ATTEMPTS = 2

INTAKE_ESCALATION_MESSAGE = (
    "No worries! Here is some general guidance: log in to Blackboard, go to your course, "
    "and look for the Immediate Access tab or link to access your digital materials. "
    "If you continue to have trouble, please contact the Campus Store directly at "
    "ImmediateAccess@calbaptist.edu with your course information and they can assist you."
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


def is_unknown_answer(message: str) -> bool:
    """True when the user signals they cannot supply the requested slot value."""
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in _UNKNOWN_ANSWER_PHRASES)


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
