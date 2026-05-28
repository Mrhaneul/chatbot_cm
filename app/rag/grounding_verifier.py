"""
grounding_verifier.py — Lightweight post-generation grounding verifier.

Inspects LLM-generated answers for high-risk claims (emails, phone numbers,
URLs, dollar amounts, time periods, specific policy phrases) and checks whether
each claim is supported by the retrieved context.

Unsupported high-risk claims return a safe fallback response.
Call verify_answer_grounding(answer, context) after generation; check .passed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ── Safe fallback reply ───────────────────────────────────────────────────────

GROUNDING_SAFE_FALLBACK = (
    "I do not have enough information in the Campus Store documentation to answer "
    "that fully. Please contact the Campus Store or Immediate Access support with "
    "your course information."
)

# ── Regex patterns ────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_PHONE_RE = re.compile(
    r"(?:"
    r"\(\d{3}\)\s*\d{3}[\s.\-]\d{4}"          # (951) 343-4259
    r"|\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b"     # 951-343-4259
    r"|\b\d{10}\b"                             # 9513434259
    r")"
)

_URL_RE = re.compile(
    r"https?://[^\s\)\"'<>]+"
    r"|(?<!\S)www\.[A-Za-z0-9\-]+\.[^\s\)\"'<>]+"
)

# Explicit dollar amounts only — avoids false positives on generic percentages.
_DOLLAR_RE = re.compile(
    r"\$\s*\d+(?:\.\d{1,2})?"
)

# Numbered time periods: "14 days", "30-day", "2 weeks", etc.
_TIME_PERIOD_RE = re.compile(
    r"\b(\d+)\s*[\-]?\s*(day|week|month|hour)s?\b",
    re.IGNORECASE,
)

# Named month + day (e.g. "January 15", "December 1st")
_SPECIFIC_DATE_RE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?\b",
    re.IGNORECASE,
)

# High-specificity compound policy phrases — generic single words are intentionally excluded
# to prevent false positives on common campus-store vocabulary.
_POLICY_PHRASES: tuple[str, ...] = (
    "restocking fee",
    "final sale",
    "no refund",
    "non-refundable",
    "all sales are final",
    "not eligible for a refund",
    "not eligible for refund",
    "not returnable",
)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class UnsupportedClaim:
    claim_type: str
    claim_text: str


@dataclass
class GroundingVerificationResult:
    passed: bool
    unsupported_claims: list[UnsupportedClaim] = field(default_factory=list)
    fallback_triggered: bool = False
    verifier_enabled: bool = True


# ── Normalization helpers ─────────────────────────────────────────────────────

def _norm(text: str) -> str:
    """Lowercase and collapse whitespace for fuzzy containment checks."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


def _is_in_context(claim: str, context: str) -> bool:
    return _norm(claim) in _norm(context)


def _phone_in_context(phone: str, context: str) -> bool:
    """Match by last-10-digit core, tolerating formatting differences."""
    digits = _digits_only(phone)
    if len(digits) < 10:
        return False
    core = digits[-10:]
    return core in _digits_only(context)


def _dollar_amount_in_context(amount: str, context: str) -> bool:
    """Match dollar amounts while tolerating whitespace after the dollar sign."""
    normalized_amount = re.sub(r"\$\s+", "$", amount)
    normalized_context = re.sub(r"\$\s+", "$", context)
    return _is_in_context(normalized_amount, normalized_context)


def _time_period_in_context(period: str, context: str) -> bool:
    """Match "14 days" against context variants like "14-day" or "14 day"."""
    match = _TIME_PERIOD_RE.search(period)
    if not match:
        return _is_in_context(period, context)

    number = match.group(1)
    unit = match.group(2).lower().rstrip("s")
    context_pattern = re.compile(
        rf"\b{re.escape(number)}\s*[\-]?\s*{re.escape(unit)}s?\b",
        re.IGNORECASE,
    )
    return bool(context_pattern.search(context))


# ── Claim extractors ──────────────────────────────────────────────────────────

def _extract_emails(text: str) -> list[str]:
    return _EMAIL_RE.findall(text)


def _extract_phones(text: str) -> list[str]:
    return _PHONE_RE.findall(text)


def _extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text)


def _extract_dollar_amounts(text: str) -> list[str]:
    return _DOLLAR_RE.findall(text)


def _extract_time_periods(text: str) -> list[str]:
    return [m.group(0) for m in _TIME_PERIOD_RE.finditer(text)]


def _extract_specific_dates(text: str) -> list[str]:
    return [m.group(0) for m in _SPECIFIC_DATE_RE.finditer(text)]


def _extract_policy_phrases(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in _POLICY_PHRASES if phrase in lowered]


# ── Core verifier ─────────────────────────────────────────────────────────────

def verify_answer_grounding(
    answer: str,
    context: str,
    *,
    verifier_enabled: bool = True,
) -> GroundingVerificationResult:
    """
    Check a generated answer for high-risk claims not supported by retrieved context.

    Returns GroundingVerificationResult with .passed=False if any unsupported
    high-risk claim is found. An empty answer or empty context is treated as
    passing (nothing to verify).

    Args:
        answer:           The LLM-generated answer text.
        context:          The retrieved RAG context that was provided to the LLM.
        verifier_enabled: When False, skip all checks and return passed=True.
    """
    if not verifier_enabled:
        return GroundingVerificationResult(passed=True, verifier_enabled=False)

    if not answer or not context:
        return GroundingVerificationResult(passed=True, verifier_enabled=True)

    unsupported: list[UnsupportedClaim] = []

    for email in _extract_emails(answer):
        if not _is_in_context(email, context):
            unsupported.append(UnsupportedClaim("email", email))
            log.debug("[GROUNDING] Unsupported email: %s", email)

    for phone in _extract_phones(answer):
        if not _phone_in_context(phone, context):
            unsupported.append(UnsupportedClaim("phone_number", phone))
            log.debug("[GROUNDING] Unsupported phone: %s", phone)

    for url in _extract_urls(answer):
        if not _is_in_context(url, context):
            unsupported.append(UnsupportedClaim("url", url))
            log.debug("[GROUNDING] Unsupported URL: %s", url)

    for amount in _extract_dollar_amounts(answer):
        if not _dollar_amount_in_context(amount, context):
            unsupported.append(UnsupportedClaim("dollar_amount", amount))
            log.debug("[GROUNDING] Unsupported dollar amount: %s", amount)

    for period in _extract_time_periods(answer):
        if not _time_period_in_context(period, context):
            unsupported.append(UnsupportedClaim("time_period", period))
            log.debug("[GROUNDING] Unsupported time period: %s", period)

    for date in _extract_specific_dates(answer):
        if not _is_in_context(date, context):
            unsupported.append(UnsupportedClaim("specific_date", date))
            log.debug("[GROUNDING] Unsupported specific date: %s", date)

    for phrase in _extract_policy_phrases(answer):
        if not _is_in_context(phrase, context):
            unsupported.append(UnsupportedClaim("policy_phrase", phrase))
            log.debug("[GROUNDING] Unsupported policy phrase: %s", phrase)

    passed = len(unsupported) == 0
    return GroundingVerificationResult(
        passed=passed,
        unsupported_claims=unsupported,
        fallback_triggered=False,
        verifier_enabled=True,
    )
