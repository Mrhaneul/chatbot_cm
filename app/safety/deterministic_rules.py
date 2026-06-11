from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import yaml

from app.safety.models import SafetyDecision

_RULES_PATH = Path(__file__).parent / "rules.yaml"


class _CompiledRules(NamedTuple):
    harmful_patterns: list[tuple[str, re.Pattern[str]]]
    abuse_patterns: list[tuple[str, re.Pattern[str]]]
    out_of_scope_keywords: list[str]
    allowlist_keywords: list[str]
    greeting_keywords: list[str]


def _load_rules() -> _CompiledRules:
    with open(_RULES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    harmful_patterns = [
        (p["id"], re.compile(p["regex"]))
        for p in data.get("harmful", {}).get("patterns", [])
    ]
    abuse_patterns = [
        (p["id"], re.compile(p["regex"]))
        for p in data.get("abuse", {}).get("patterns", [])
    ]
    out_of_scope_keywords = [
        kw.lower() for kw in data.get("out_of_scope", {}).get("keywords", [])
    ]
    allowlist_keywords = [
        kw.lower() for kw in data.get("campus_store_allowlist", {}).get("keywords", [])
    ]
    greeting_keywords = [
        kw.lower() for kw in data.get("greetings", {}).get("keywords", [])
    ]
    return _CompiledRules(
        harmful_patterns=harmful_patterns,
        abuse_patterns=abuse_patterns,
        out_of_scope_keywords=out_of_scope_keywords,
        allowlist_keywords=allowlist_keywords,
        greeting_keywords=greeting_keywords,
    )


_RULES: _CompiledRules = _load_rules()

_KNOWN_CACHE_ISSUE_RE = re.compile(
    r"""(?ix)
    (
        \b0\s+courses?\s*,?\s*0\s+materials?\b
        | \byou\s+currently\s+have\s+no\s+content\s+available\b
        | \bno\s+content\s+available\b
    )
    """
)


def check_deterministic(message: str) -> SafetyDecision | None:
    """
    Run rule-based safety checks.

    Returns a SafetyDecision if the message clearly matches a rule,
    or None if the result is ambiguous (caller should invoke the classifier).

    Decision priority:
      1. Harmful regex patterns  → HARMFUL_REFUSAL   (immediate, highest priority)
      2. Abuse/spam patterns     → ABUSE_REFUSAL      (immediate)
      3. Pure greeting           → ALLOW              (immediate, always safe)
      4. Evaluate OOS + allowlist together:
           OOS only              → OUT_OF_SCOPE_FALLBACK
           allowlist only        → ALLOW
           both OOS and allowlist → None  (classifier decides — message is mixed)
      5. No match               → None  (ambiguous, classifier decides)

    The critical fix in step 4: a message that contains BOTH a campus-store
    allowlist term (e.g. "Blackboard") AND an out-of-scope keyword
    (e.g. "password reset") is ambiguous — it could be a legitimate access
    question OR an IT-department question. We do NOT return ALLOW just because
    an allowlist term matched; the classifier resolves the ambiguity.
    """
    normalized = message.lower().strip()

    # 1. Hard-block harmful patterns
    for rule_id, pattern in _RULES.harmful_patterns:
        if pattern.search(message):
            return SafetyDecision(
                action="HARMFUL_REFUSAL",
                category="harmful",
                confidence=1.0,
                reason=f"Matched harmful rule: {rule_id}",
                matched_rules=[rule_id],
            )

    # 2. Abuse / spam patterns
    for rule_id, pattern in _RULES.abuse_patterns:
        if pattern.search(message):
            return SafetyDecision(
                action="ABUSE_REFUSAL",
                category="abuse",
                confidence=1.0,
                reason=f"Matched abuse rule: {rule_id}",
                matched_rules=[rule_id],
            )

    # 3. Greeting — always allow (handled downstream)
    # Known Immediate Access/VitalSource empty-content error strings are safe,
    # in-scope support issues even when the student omits platform context.
    if _KNOWN_CACHE_ISSUE_RE.search(message):
        return SafetyDecision(
            action="ALLOW",
            category="campus_store",
            confidence=0.98,
            reason="Known Immediate Access empty-content issue signature.",
            matched_rules=["known_cache_issue_signature"],
        )

    words = re.split(r"[\s,!?.]+", normalized)
    first_word = words[0] if words else ""
    if first_word in _RULES.greeting_keywords or normalized in _RULES.greeting_keywords:
        return SafetyDecision(
            action="ALLOW",
            category="greeting",
            confidence=1.0,
            reason="Greeting message",
            matched_rules=["greeting_allowlist"],
        )

    # 4. Compute allowlist and OOS matches simultaneously before deciding
    matched_allowlist = [kw for kw in _RULES.allowlist_keywords if kw in normalized]
    matched_oos = [kw for kw in _RULES.out_of_scope_keywords if kw in normalized]

    has_allowlist = bool(matched_allowlist)
    has_oos = bool(matched_oos)

    if has_allowlist and has_oos:
        # Mixed signal — e.g. "Blackboard password reset" or "library in Blackboard".
        # Do not allow. Return None so the classifier resolves the ambiguity.
        return None

    if has_oos:
        return SafetyDecision(
            action="OUT_OF_SCOPE_FALLBACK",
            category="out_of_scope",
            confidence=0.9,
            reason=f"Matched out-of-scope keywords: {matched_oos[:3]}",
            matched_rules=["out_of_scope_keywords"],
        )

    if has_allowlist:
        return SafetyDecision(
            action="ALLOW",
            category="campus_store",
            confidence=0.95,
            reason=f"Matched allowlist keywords: {matched_allowlist[:3]}",
            matched_rules=["campus_store_allowlist"],
        )

    # 5. No match — ambiguous
    return None
