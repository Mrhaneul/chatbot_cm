from pathlib import Path

import pytest

from app.rag.metadata import load_document_with_metadata
from app.rag.metadata_filtering import classify_query_metadata, score_retrieval_candidate
from app.rag.retriever import get_retriever


def _candidate(source_path: str, semantic_score: float = 0.5) -> dict:
    metadata, body = load_document_with_metadata(source_path)
    return {
        "context": body,
        "score": semantic_score,
        "source_id": metadata["source_id"],
        "metadata": metadata,
    }


def _score(query: str, source_path: str) -> float:
    candidate = _candidate(source_path)
    breakdown = score_retrieval_candidate(
        query,
        candidate,
        classify_query_metadata(query),
    )
    return breakdown["final_score"]


@pytest.mark.parametrize(
    ("query", "preferred", "other"),
    [
        (
            "What is the refund policy for Immediate Access?",
            "data/faqs/ia_overview.txt",
            "data/faqs/campus_store_refund_merchandise.txt",
        ),
        (
            "What is the refund policy for Immediate Access?",
            "data/faqs/textbook_refund_policy.txt",
            "data/faqs/campus_store_refund_merchandise.txt",
        ),
        (
            "How do I return a textbook?",
            "data/faqs/textbook_refund_policy.txt",
            "data/faqs/campus_store_refund_merchandise.txt",
        ),
        (
            "What is the return policy for merchandise?",
            "data/faqs/campus_store_refund_merchandise.txt",
            "data/faqs/textbook_refund_policy.txt",
        ),
        (
            "I can't access my Vitalsource",
            "data/instructions/ia_vitalsource_bookshelf_account_creation.txt",
            "data/instructions/ia_bedford_bookshelf_email_error_access.txt",
        ),
        (
            "Bedford Bookshelf email error",
            "data/instructions/ia_bedford_bookshelf_email_error_access.txt",
            "data/instructions/ia_vitalsource_bookshelf_account_creation.txt",
        ),
        (
            "I can't access my McGraw Hill Connect textbook",
            "data/instructions/ia_mcgraw_hill_connect_access.txt",
            "data/instructions/ia_vitalsource_bookshelf_account_creation.txt",
        ),
    ],
)
def test_hybrid_score_prefers_expected_high_risk_source(
    query: str,
    preferred: str,
    other: str,
):
    assert _score(query, preferred) > _score(query, other)


def test_score_breakdown_is_explainable():
    query = "Bedford Bookshelf email error"
    breakdown = score_retrieval_candidate(
        query,
        _candidate("data/instructions/ia_bedford_bookshelf_email_error_access.txt"),
        classify_query_metadata(query),
    )

    assert set(breakdown) >= {
        "semantic_score",
        "metadata_score",
        "keyword_score",
        "priority_score",
        "conflict_penalty",
        "final_score",
        "matched_terms",
        "metadata",
    }
    assert breakdown["keyword_score"] > 0
    assert "phrase:bedford email" in breakdown["matched_terms"]


@pytest.mark.parametrize(
    ("query", "expected_sources", "forbidden_sources"),
    [
        (
            "What is the refund policy for Immediate Access?",
            {"ia_overview.txt", "textbook_refund_policy.txt"},
            {"campus_store_refund_merchandise.txt"},
        ),
        (
            "How do I return a textbook?",
            {"textbook_refund_policy.txt"},
            set(),
        ),
        (
            "What is the return policy for merchandise?",
            {"campus_store_refund_merchandise.txt"},
            set(),
        ),
        (
            "I can't access my Vitalsource",
            {"ia_vitalsource_bookshelf_account_creation.txt"},
            {"ia_bedford_bookshelf_email_error_access.txt"},
        ),
        (
            "Bedford Bookshelf email error",
            {"ia_bedford_bookshelf_email_error_access.txt"},
            set(),
        ),
        (
            "I can't access my McGraw Hill Connect textbook",
            {"ia_mcgraw_hill_connect_access.txt", "ia_mcgraw_hill_tools_access.txt"},
            set(),
        ),
        (
            "How do I opt out of Immediate Access?",
            {"ia_overview.txt", "ia_opt_out_canvas.txt"},
            {"ia_access_issue.txt"},
        ),

    ],
)
def test_hybrid_retrieval_source_selection(
    query: str,
    expected_sources: set[str],
    forbidden_sources: set[str],
):
    result = get_retriever().retrieve(query)
    source_file = Path(result["metadata"]["source_file"]).name

    assert source_file in expected_sources
    assert source_file not in forbidden_sources
