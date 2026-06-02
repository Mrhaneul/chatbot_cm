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


def is_vague_message(message: str) -> bool:
    """True when the message matches a vague-complaint pattern."""
    return bool(VAGUE_PATTERN_RE.search(message.strip()))


def should_enter_intake(message: str, session: dict) -> bool:
    """
    True when this message should start a new intake session.

    Returns False when:
    - An intake_profile is already active (mid-intake).
    - Any legacy clarification flag is active.
    - The message contains an unambiguous platform signal (bypass intake).
    - The message is not vague.
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
    if extract_platform(message) is not None:
        return False
    return is_vague_message(message)


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
