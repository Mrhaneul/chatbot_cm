"""
app/intake/questions.py

Static question strings and compiled vague-pattern regex.
NEXT_QUESTION maps the slot that is missing to the question Lance asks.
"""
from __future__ import annotations

import re

# -- Vague-pattern regex -------------------------------------------------------
# Matches clearly under-specified access/missing complaints.
# Platform-specific messages that also supply an issue type bypass intake via
# the should_enter_intake() platform+issue guard in flow.py.
_VAGUE_PATTERNS: list[str] = [
    r"i (don'?t|do not) have (my )?(text ?book|book|materials?|course materials?)",
    r"my (text ?book|book|ebook|e-book|materials?) (is |are )?(missing|not there|gone)",
    r"(it (doesn'?t|won'?t|is not|isn'?t) work|not working|won'?t work)",
    r"i'?m (confused|stuck|lost|not sure (what|where|how))",
    r"i (don'?t|do not) see (anything|it|my (course )?(book|text ?book|materials?))",
    r"i can'?t find (anything|it|my (book|text ?book|materials?))",
    r"^i need help\.?$",
    # "access" pattern: covers book/textbook/ebook and the grammatical "access to" variant.
    r"i can'?t access (to )?(my )?(course )?(text ?book|book|ebook|e-book|class )?materials?",
    r"i can'?t access (to )?(my )?(text ?book|book|ebook|e-book)",
    # "get to/into/open/load" pattern: expanded to include "get into" and ebook.
    r"(can'?t|cannot) (get (to|into)|open|load) (my )?(book|text ?book|ebook|e-book|materials?)",
    r"(having|i have) (an? )?(issue|problem|trouble) (with )?(my )?(book|text ?book|access|materials?)",
    # "don't have access" — covers "I don't have access" and "It says I don't have access".
    r"(i )?(don'?t|do not|can'?t) have access",
    # "course material" vague patterns — catch before the LLM planner so the
    # deterministic flow (platform -> issue) runs instead of ask_course_code.
    # Structure A: "I have a course material issue" (noun-issue order)
    r"i (have|had) (a |an? )?(course|class) (material|textbook|book|content)s? (issue|problem|trouble)",
    # Structure B: "I'm having an issue with my course material" (issue-with-noun order)
    r"(i )?(am having|having|need help with) (an? )?(issue|problem|trouble) with (my |the )?(course|class) (material|textbook|book|content)",
    # Structure C: "I need help with my course material"
    r"(i )?(need help|need assistance) with (my )?(course|class) (material|textbook|book|content)",
    # Structure D: "something is wrong" / "X is not working"
    r"something is wrong with (my )?(course|class) (material|textbook|book|content)",
    r"(my )?(course|class) (material|textbook|book|content) (is|are)? ?(not working|missing|gone|broken|unavailable)",
]

VAGUE_PATTERN_RE: re.Pattern = re.compile(
    "|".join(f"(?:{p})" for p in _VAGUE_PATTERNS),
    re.IGNORECASE,
)

# -- Slot questions ------------------------------------------------------------
# Keys are the slot that IS missing. Values are the questions Lance asks.
# Course code is intentionally optional in Phase 3. Platform + issue_type are
# enough to route to useful instructions, and asking for course code here would
# add friction without improving current retrieval quality.
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
