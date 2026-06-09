"""
app/intake/question_templates.py

Controlled question strings keyed by the slot that is missing.
The LLM planner selects a next_question_key; the backend resolves it here.
This ensures the student always sees a human-authored question, never
LLM-generated text.
"""
from __future__ import annotations

QUESTION_TEMPLATES: dict[str, str] = {
    "ask_platform_for_book_access": (
        "Which platform or publisher is your textbook on? "
        "For example: VitalSource, Cengage MindTap, Pearson MyLab, "
        "McGraw Hill Connect, Bedford, Sage, or WileyPlus. "
        "If you're not sure, you can check the Immediate Access tab in Blackboard."
    ),
    "ask_issue_for_platform": (
        "What kind of issue are you running into? "
        "For example: can't access the textbook, missing content, "
        "account or login problem, or something else?"
    ),
    "ask_course_code": (
        "Do you know your course code? "
        "For example: ENGL1301 or BIOL2401. "
        "You can find it in Blackboard under My Courses."
    ),
    "ask_error_message": (
        "What error message or screen are you seeing? "
        "A screenshot or the exact wording helps us pinpoint the issue."
    ),
    "ask_material_type": (
        "Are you looking for a digital textbook, a workbook, or a lab manual?"
    ),
    "ask_blackboard_or_publisher_location": (
        "Are you trying to access the material through the Immediate Access tab in Blackboard, "
        "or directly through the publisher's website?"
    ),
    "ask_course_or_material_when_platform_unknown": (
        "No problem. If you do not know the platform, can you tell me your course code, "
        "course name, instructor, or the name of the book or material that is locked?"
    ),
}

FALLBACK_QUESTION = (
    "Could you tell me more about what you're trying to access? "
    "For example, which platform your textbook is on, or what error you're seeing?"
)

# Maps a question key to the slot it is requesting.
QUESTION_KEY_TO_SLOT: dict[str, str] = {
    "ask_platform_for_book_access": "platform",
    "ask_issue_for_platform": "issue_type",
    "ask_course_code": "course_code",
    "ask_error_message": "error_message",
    "ask_material_type": "material_type",
    "ask_blackboard_or_publisher_location": "location",
    "ask_course_or_material_when_platform_unknown": "course_or_material",
}
