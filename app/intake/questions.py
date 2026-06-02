"""
app/intake/questions.py

Static question strings and compiled vague-pattern regex.
NEXT_QUESTION maps the slot that is missing to the question Lance asks.
"""
from __future__ import annotations

import re

# -- Vague-pattern regex -------------------------------------------------------
# Conservative: only clearly under-specified complaints with no platform signal.
# Platform-specific messages (e.g. "I can't access Cengage") bypass intake entirely.
_VAGUE_PATTERNS: list[str] = [
    r"i (don'?t|do not) have (my )?(text ?book|book|materials?|course materials?)",
    r"my (text ?book|book|materials?) (is |are )?(missing|not there|gone)",
    r"(it (doesn'?t|won'?t|is not|isn'?t) work|not working|won'?t work)",
    r"i'?m (confused|stuck|lost|not sure (what|where|how))",
    r"i (don'?t|do not) see (anything|it|my (book|text ?book|materials?))",
    r"i can'?t find (anything|it|my (book|text ?book|materials?))",
    r"^i need help\.?$",
    r"i can'?t access (my )?(class )?materials?",
    r"(can'?t|cannot) (get to|open|load) (my )?(book|text ?book|materials?)",
    r"(having|i have) (an? )?(issue|problem|trouble) (with )?(my )?(book|text ?book|access|materials?)",
]

VAGUE_PATTERN_RE: re.Pattern = re.compile(
    "|".join(f"(?:{p})" for p in _VAGUE_PATTERNS),
    re.IGNORECASE,
)

# -- Slot questions ------------------------------------------------------------
# Keys are the slot that IS missing. Values are the questions Lance asks.
PLATFORM_QUESTION = (
    "Which platform or publisher is your textbook on? "
    "For example: VitalSource, Cengage MindTap, Pearson MyLab, "
    "McGraw Hill Connect, Bedford, Sage, or WileyPlus. "
    "If you're not sure, you can check the Immediate Access tab in Blackboard."
)

ISSUE_TYPE_QUESTION = (
    "What kind of issue are you running into? "
    "For example: can't access the textbook, missing content, "
    "account or login problem, or something else?"
)

# Maps missing slot -> question to ask next (platform takes priority).
NEXT_QUESTION: dict[str, str] = {
    "platform": PLATFORM_QUESTION,
    "issue_type": ISSUE_TYPE_QUESTION,
}

# Fallback when intake expires without completion.
INTAKE_FALLBACK_MESSAGE = (
    "No problem — let me connect you with general information about Immediate Access. "
    "If you can share which platform your textbook is on, I can give you more specific steps!"
)
