"""
app/intake/slot_extractor.py

Pure functions that extract slot values from a user message.
Imports PLATFORM_ALIASES directly from app.config.loader — NOT from app.main —
to prevent circular imports.
"""
from __future__ import annotations

import re
from typing import Optional

from app.config.loader import PLATFORM_ALIASES

# -- Course code ---------------------------------------------------------------
_COURSE_CODE_RE = re.compile(
    r"\b([A-Z]{2,6})\s*[-]?\s*(\d{3,4}[A-Z]?)\b",
    re.IGNORECASE,
)

# -- Issue type keywords -------------------------------------------------------
_ACCESS_SIGNALS = [
    "can't access", "cannot access", "can't open", "cannot open",
    "won't load", "not loading", "access issue", "can't get in",
    "cannot get in", "won't let me in", "access denied",
    "don't have access", "do not have access", "can't have access",
    # Location / finding queries -- "where can I see/find/access my book?"
    # Patterns require an explicit material keyword to avoid false positives
    # on unrelated queries (e.g. "where can i see my schedule").
    "where can i see my book", "where do i see my book",
    "where can i find my book", "where do i find my book",
    "where can i see my textbook", "where do i see my textbook",
    "where can i find my textbook", "where do i find my textbook",
    "where do i find my digital textbook", "where can i find my digital textbook",
    "where do i see my digital textbook", "where can i see my digital textbook",
    "where can i see my ebook", "where can i find my ebook",
    "where do i find my ebook", "where do i see my ebook",
    "where is my book", "where are my books",
    "where is my textbook", "where is my ebook",
    "where is my digital textbook", "where is my digital book",
    "where can i access my book", "where do i access my book",
    "where can i access my textbook", "where do i access my textbook",
    "where can i access my digital textbook", "where do i access my digital textbook",
    "where can i access my material", "where do i access my material",
    "where do i get my book", "where do i get my textbook",
    "where can i get my book", "where can i get my textbook",
]
_MISSING_SIGNALS = [
    "missing", "not there", "disappeared", "gone", "don't see",
    "do not see", "can't find", "cannot find", "not showing",
    # No-content / zero-content / visibility patterns
    # (e.g. "0 Courses, 0 Materials" VitalSource error, "no content available")
    "0 courses",
    "0 materials",
    "no courses",
    "no materials",
    "no content",
    "nothing showing",
    "can't see",
    "cannot see",
]
_ACCOUNT_SIGNALS = [
    "login", "log in", "log-in", "password", "account", "sign in",
    "sign-in", "username", "credentials",
]


def extract_platform(message: str) -> Optional[str]:
    """
    Return the uppercase platform key if the message contains an unambiguous alias.
    Returns None when zero or multiple platforms are detected.
    """
    msg_lower = message.lower()
    matches: list[str] = []
    for key, aliases in PLATFORM_ALIASES.items():
        if any(alias.lower() in msg_lower for alias in aliases):
            matches.append(key)
    return matches[0] if len(matches) == 1 else None


def extract_issue_type(message: str) -> Optional[str]:
    """Return 'access', 'missing', or 'account' based on keyword signals."""
    msg_lower = message.lower()
    if any(s in msg_lower for s in _ACCOUNT_SIGNALS):
        return "account"
    if any(s in msg_lower for s in _ACCESS_SIGNALS):
        return "access"
    if any(s in msg_lower for s in _MISSING_SIGNALS):
        return "missing"
    return None


def extract_course_code(message: str) -> Optional[str]:
    """Return the first course-code pattern found (e.g. 'CS101', 'ENGL 1301')."""
    m = _COURSE_CODE_RE.search(message)
    if m:
        return f"{m.group(1).upper()}{m.group(2).upper()}"
    return None


def extract_material_type(message: str) -> Optional[str]:
    """Return 'textbook', 'workbook', or 'lab' based on keyword signals."""
    msg_lower = message.lower()
    if "workbook" in msg_lower:
        return "workbook"
    if "lab manual" in msg_lower or "lab book" in msg_lower:
        return "lab"
    if any(w in msg_lower for w in ("textbook", "text book", "ebook", "e-book", "book")):
        return "textbook"
    return None
