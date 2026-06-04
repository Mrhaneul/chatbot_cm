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
]
_MISSING_SIGNALS = [
    "missing", "not there", "disappeared", "gone", "don't see",
    "do not see", "can't find", "cannot find", "not showing",
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
