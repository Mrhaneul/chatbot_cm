from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config.loader import METADATA_PLATFORM_ALIASES as PLATFORM_ALIASES


SCORING_WEIGHTS = {
    "keyword_score_max": 0.15,
    "phrase_boost_max": 0.15,
    "priority_canonical": 0.05,
    "priority_alternate": 0.02,
    "priority_specific_case_strong": 0.03,
    "conflict_penalty_max": 0.25,
}


@dataclass(frozen=True)
class QueryMetadata:
    category: str | None = None
    platform: str | None = None
    issue_type: str | None = None

    def has_filters(self) -> bool:
        return bool(self.category or self.platform or self.issue_type)


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def classify_query_metadata(query: str) -> QueryMetadata:
    """Rule-based metadata classifier used before final retrieval selection."""
    q = re.sub(r"\s+", " ", (query or "").lower()).strip()
    if not q:
        return QueryMetadata()

    platform = _classify_platform(q)
    category = _classify_category(q, platform)
    issue_type = _classify_issue_type(q)

    return QueryMetadata(category=category, platform=platform, issue_type=issue_type)


def _classify_platform(q: str) -> str | None:
    if _contains_phrase(q, "bedford"):
        return "bedford"
    if _contains_phrase(q, "vitalsource"):
        return "vitalsource"
    if _contains_phrase(q, "bookshelf"):
        # In Lance's current docs, standalone Bookshelf commonly means VitalSource.
        return "vitalsource"

    for platform, aliases in PLATFORM_ALIASES:
        if any(_contains_phrase(q, alias) for alias in aliases):
            return platform
    return None


def _classify_category(q: str, platform: str | None) -> str | None:
    if platform:
        return "platform_access"
    if any(term in q for term in ("merchandise", "hoodie", "apparel", "clothing", "trade book")):
        if any(term in q for term in ("return", "refund", "exchange", "policy")):
            return "merchandise_return"
    if any(term in q for term in ("textbook", "text book", "book")):
        if any(term in q for term in ("return", "refund", "policy")):
            return "textbook_return"
    if "immediate access" in q or " ia " in f" {q} ":
        return "immediate_access"
    return None


def _classify_issue_type(q: str) -> str | None:
    if "email" in q and any(term in q for term in ("error", "wrong", "incorrect", "verification")):
        return "email_error"
    if any(term in q for term in ("create account", "account creation", "create a", "set up account", "setup account")):
        return "account_creation"
    if "opt out" in q or "opt-out" in q:
        return "opt_out"
    if any(term in q for term in ("missing", "not showing", "doesn't show", "does not show", "not listed")):
        return "missing_book"
    if "refund" in q:
        return "refund"
    if "return" in q or "exchange" in q:
        return "return_refund"
    if any(term in q for term in ("can't access", "cannot access", "cant access", "unable to access", "access issue")):
        return "access"
    if any(term in q for term in ("what is", "overview", "how does")):
        return "overview"
    if "access" in q and "immediate access" in q:
        return "access_issue"
    return None


def _normalize_platform(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        values = [_normalize_platform(item) for item in value]
        values = [item for item in values if item]
        if "mcgraw_hill" in values:
            return "mcgraw_hill"
        return values[0] if values else None
    value = str(value).strip().lower()
    if value in {"mcgraw", "mcgrawhill", "mcgraw_hill"}:
        return "mcgraw_hill"
    if value == "clifton":
        return "cliftonstrengths"
    return value or None


def _issue_matches(query_issue: str, doc_issue: str | None) -> bool:
    if not doc_issue:
        return False
    if query_issue == doc_issue:
        return True
    compatible = {
        ("refund", "return_refund"),
        ("return_refund", "refund"),
        ("access", "access_issue"),
        ("access_issue", "access"),
    }
    return (query_issue, doc_issue) in compatible


def metadata_match_score(query_meta: QueryMetadata, document_meta: dict) -> float:
    """
    Return an explainable score adjustment for metadata-aware source selection.

    Positive values boost matching metadata. Negative values penalize conflicts.
    Missing metadata is neutral, which preserves fallback behavior for older docs.
    """
    if not query_meta.has_filters() or not document_meta:
        return 0.0

    score = 0.0
    doc_platform = _normalize_platform(document_meta.get("platform"))
    doc_category = document_meta.get("category")
    doc_issue = document_meta.get("issue_type")

    if query_meta.platform:
        if doc_platform == query_meta.platform:
            score += 0.25
        elif doc_platform:
            score -= 0.30

    if query_meta.category:
        if doc_category == query_meta.category:
            score += 0.18
        elif doc_category:
            # IA refund can reasonably use the textbook digital-content policy,
            # but should still lose to a direct IA metadata match.
            if not (
                query_meta.category == "immediate_access"
                and doc_category == "textbook_return"
                and query_meta.issue_type == "refund"
            ):
                score -= 0.25

    if query_meta.issue_type:
        if _issue_matches(query_meta.issue_type, doc_issue):
            score += 0.22
        elif doc_issue:
            score -= 0.20

    return score


HIGH_VALUE_TERMS: tuple[str, ...] = (
    "immediate access",
    "opt out",
    "opt-out",
    "refund",
    "return",
    "textbook",
    "merchandise",
    "access code",
    "digital content",
    "vitalsource",
    "bookshelf",
    "bedford",
    "mcgraw hill",
    "connect",
    "cengage",
    "mindtap",
    "pearson",
    "mylab",
    "wileyplus",
    "zybooks",
)


def _metadata_text(document_meta: dict) -> str:
    values = [
        document_meta.get("source_file"),
        document_meta.get("source_id"),
        document_meta.get("category"),
        document_meta.get("platform"),
        document_meta.get("issue_type"),
        document_meta.get("priority"),
    ]
    return " ".join(str(value).replace("_", " ") for value in values if value is not None).lower()


def _candidate_search_text(candidate: dict) -> str:
    metadata_text = _metadata_text(candidate.get("metadata", {}))
    chunk_text = str(candidate.get("context", "")).lower()
    return f"{metadata_text} {chunk_text}"


def keyword_term_score(query: str, candidate: dict) -> tuple[float, list[str]]:
    query_text = re.sub(r"\s+", " ", (query or "").lower()).strip()
    candidate_text = _candidate_search_text(candidate)
    matched_terms: list[str] = []

    for term in HIGH_VALUE_TERMS:
        if _contains_phrase(query_text, term) and _contains_phrase(candidate_text, term):
            matched_terms.append(term)

    if not matched_terms:
        return 0.0, []

    score = min(SCORING_WEIGHTS["keyword_score_max"], 0.025 * len(matched_terms))
    return score, matched_terms


def phrase_boost_score(query: str, candidate: dict) -> tuple[float, list[str]]:
    query_text = re.sub(r"\s+", " ", (query or "").lower()).strip()
    metadata = candidate.get("metadata", {})
    source_id = str(metadata.get("source_id", "")).lower()
    source_file = str(metadata.get("source_file", "")).lower()
    category = metadata.get("category")
    platform = _normalize_platform(metadata.get("platform"))
    issue_type = metadata.get("issue_type")
    matched: list[str] = []
    score = 0.0

    def add(label: str, amount: float) -> None:
        nonlocal score
        matched.append(label)
        score += amount

    if _contains_phrase(query_text, "immediate access") and (
        category == "immediate_access" or "ia_" in source_id
    ):
        add("phrase:immediate access", 0.04)
    if ("opt out" in query_text or "opt-out" in query_text) and (
        issue_type == "opt_out" or source_id == "ia_overview"
    ):
        add("phrase:opt out", 0.08)
    if (
        "return a textbook" in query_text or "textbook return" in query_text
    ) and source_id == "textbook_refund_policy":
        add("phrase:textbook return", 0.12)
    if "merchandise return" in query_text and source_id == "campus_store_refund_merchandise":
        add("phrase:merchandise return", 0.12)
    if "merchandise" in query_text and category == "merchandise_return":
        add("phrase:merchandise", 0.08)
    if "bedford" in query_text and "email" in query_text and issue_type == "email_error":
        add("phrase:bedford email", 0.14)
    if "vitalsource" in query_text and "account" in query_text and issue_type == "account_creation":
        add("phrase:vitalsource account", 0.14)
    if "vitalsource" in query_text and platform == "vitalsource":
        add("phrase:vitalsource", 0.06)
    if "mcgraw hill connect" in query_text and (
        source_id == "ia_mcgraw_hill_connect_access" or "connect_access" in source_file
    ):
        add("phrase:mcgraw hill connect", 0.14)

    return min(SCORING_WEIGHTS["phrase_boost_max"], score), matched


def priority_score(query_meta: QueryMetadata, document_meta: dict) -> float:
    priority = document_meta.get("priority")
    if priority == "canonical":
        return SCORING_WEIGHTS["priority_canonical"]
    if priority == "alternate":
        return SCORING_WEIGHTS["priority_alternate"]
    if priority == "specific_case":
        doc_platform = _normalize_platform(document_meta.get("platform"))
        doc_issue = document_meta.get("issue_type")
        strong_match = (
            (query_meta.platform and query_meta.platform == doc_platform)
            and (query_meta.issue_type and _issue_matches(query_meta.issue_type, doc_issue))
        )
        return SCORING_WEIGHTS["priority_specific_case_strong"] if strong_match else 0.0
    return 0.0


def conflict_penalty(query: str, query_meta: QueryMetadata, document_meta: dict) -> tuple[float, list[str]]:
    query_text = re.sub(r"\s+", " ", (query or "").lower()).strip()
    category = document_meta.get("category")
    platform = _normalize_platform(document_meta.get("platform"))
    issue_type = document_meta.get("issue_type")
    conflicts: list[str] = []
    penalty = 0.0

    def add(label: str, amount: float) -> None:
        nonlocal penalty
        conflicts.append(label)
        penalty += amount

    if query_meta.category == "immediate_access" and query_meta.issue_type == "refund" and category == "merchandise_return":
        add("conflict:ia refund vs merchandise_return", 0.25)
    if query_meta.category == "merchandise_return" and category == "textbook_return":
        add("conflict:merchandise return vs textbook_return", 0.20)
    if query_meta.category == "textbook_return" and category == "merchandise_return":
        add("conflict:textbook return vs merchandise_return", 0.20)
    if query_meta.platform == "vitalsource" and platform == "bedford":
        add("conflict:vitalsource vs bedford", 0.25)
    if query_meta.platform == "bedford" and "email" in query_text and platform == "vitalsource" and issue_type == "account_creation":
        add("conflict:bedford email vs vitalsource account_creation", 0.25)
    if query_meta.issue_type == "opt_out" and issue_type == "access_issue":
        add("conflict:opt_out vs access_issue", 0.18)

    return min(SCORING_WEIGHTS["conflict_penalty_max"], penalty), conflicts


def score_retrieval_candidate(query: str, candidate: dict, query_meta: QueryMetadata | None = None) -> dict:
    query_meta = query_meta or classify_query_metadata(query)
    semantic_score = float(candidate.get("score", 0.0))
    metadata_score = metadata_match_score(query_meta, candidate.get("metadata", {}))
    keyword_score, matched_terms = keyword_term_score(query, candidate)
    phrase_score, phrase_matches = phrase_boost_score(query, candidate)
    combined_keyword_score = min(
        SCORING_WEIGHTS["keyword_score_max"] + SCORING_WEIGHTS["phrase_boost_max"],
        keyword_score + phrase_score,
    )
    source_priority_score = priority_score(query_meta, candidate.get("metadata", {}))
    penalty, conflicts = conflict_penalty(query, query_meta, candidate.get("metadata", {}))
    final_score = (
        semantic_score
        + metadata_score
        + combined_keyword_score
        + source_priority_score
        - penalty
    )

    return {
        "semantic_score": semantic_score,
        "metadata_score": metadata_score,
        "keyword_score": combined_keyword_score,
        "priority_score": source_priority_score,
        "conflict_penalty": penalty,
        "final_score": final_score,
        "matched_terms": matched_terms + phrase_matches,
        "conflicts": conflicts,
        "metadata": candidate.get("metadata", {}),
    }


def apply_metadata_preference(
    query: str,
    candidates: list[dict],
) -> tuple[list[dict], QueryMetadata]:
    """Return candidates sorted by semantic + metadata + keyword hybrid score."""
    query_meta = classify_query_metadata(query)
    if not query_meta.has_filters() or not candidates:
        return candidates, query_meta

    scored_candidates = []
    for candidate in candidates:
        score_breakdown = score_retrieval_candidate(query, candidate, query_meta)
        scored_candidates.append(
            {
                **candidate,
                "semantic_score": score_breakdown["semantic_score"],
                "metadata_score": score_breakdown["metadata_score"],
                "keyword_score": score_breakdown["keyword_score"],
                "priority_score": score_breakdown["priority_score"],
                "conflict_penalty": score_breakdown["conflict_penalty"],
                "matched_terms": score_breakdown["matched_terms"],
                "score_breakdown": score_breakdown,
                "combined_score": score_breakdown["final_score"],
            }
        )

    scored_candidates.sort(key=lambda item: item["combined_score"], reverse=True)
    return scored_candidates, query_meta
