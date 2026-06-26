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
        "For example: Cengage MindTap, Pearson MyLab, "
        "McGraw Hill Connect, Bedford, Sage, or WileyPlus. "
        "If you're not sure, you can check the Immediate Access tab in Canvas."
    ),
    "ask_issue_for_platform": (
        "What kind of issue are you running into? "
        "For example: can't access the textbook, missing content, "
        "account or login problem, or something else?"
    ),
    # ask_course_code is redirected to a safe issue-type triage question.
    # Lance must never ask students for their course code, section, or other
    # personal/enrollment-specific details. If any code path resolves this key,
    # the student sees a safe question instead.
    "ask_course_code": (
        "What kind of course material issue are you running into? "
        "For example: you can't access your textbook, content is missing, "
        "you're having a login or account issue, or something else?"
    ),
    "ask_error_message": (
        "What error message or screen are you seeing? "
        "A screenshot or the exact wording helps us pinpoint the issue."
    ),
    "ask_material_type": (
        "Are you looking for a digital textbook, a workbook, or a lab manual?"
    ),
    "ask_blackboard_or_publisher_location": (
        "Are you trying to access the material through the Immediate Access tab in Canvas, "
        "or directly through the publisher's website?"
    ),
    "ask_course_or_material_when_platform_unknown": (
        "No problem. Please contact ImmediateAccess@calbaptist.edu for help with your "
        "textbook access issue. They can help identify the correct platform and material "
        "for your course. If possible, include a screenshot of what you are seeing when "
        "you email them."
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
    "ask_course_code": "issue_type",  # redirected: never collect course_code
    "ask_error_message": "error_message",
    "ask_material_type": "material_type",
    "ask_blackboard_or_publisher_location": "location",
    "ask_course_or_material_when_platform_unknown": "course_or_material",
}
