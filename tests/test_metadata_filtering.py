import pytest

from app.rag.metadata_filtering import classify_query_metadata
from app.rag.retriever import get_retriever


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "What is the refund policy for Immediate Access?",
            {"category": "immediate_access", "platform": None, "issue_type": "refund"},
        ),
        (
            "How do I opt out of Immediate Access?",
            {"category": "immediate_access", "platform": None, "issue_type": "opt_out"},
        ),
        (
            "How do I return a textbook?",
            {"category": "textbook_return", "platform": None, "issue_type": "return_refund"},
        ),
        (
            "What is the return policy for merchandise?",
            {"category": "merchandise_return", "platform": None, "issue_type": "return_refund"},
        ),
        (
            "I can't access my Vitalsource",
            {"category": "platform_access", "platform": "vitalsource", "issue_type": "access"},
        ),
        (
            "I need to create a VitalSource Bookshelf account",
            {"category": "platform_access", "platform": "vitalsource", "issue_type": "account_creation"},
        ),
        (
            "Bedford Bookshelf email error",
            {"category": "platform_access", "platform": "bedford", "issue_type": "email_error"},
        ),
        (
            "I can't access my McGraw Hill Connect textbook",
            {"category": "platform_access", "platform": "mcgraw_hill", "issue_type": "access"},
        ),
    ],
)
def test_classify_query_metadata(query: str, expected: dict):
    metadata = classify_query_metadata(query)

    assert metadata.category == expected["category"]
    assert metadata.platform == expected["platform"]
    assert metadata.issue_type == expected["issue_type"]


@pytest.mark.parametrize(
    ("query", "expected_sources", "forbidden_sources"),
    [
        (
            "What is the refund policy for Immediate Access?",
            {"ia_overview.txt", "textbook_refund_policy.txt"},
            {"campus_store_refund_merchandise.txt"},
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
            "How do I return a textbook?",
            {"textbook_refund_policy.txt"},
            set(),
        ),
        (
            "What is the return policy for merchandise?",
            {"campus_store_refund_merchandise.txt"},
            set(),
        ),
    ],
)
def test_metadata_preference_source_selection(
    query: str,
    expected_sources: set[str],
    forbidden_sources: set[str],
):
    retriever = get_retriever()

    result = retriever.retrieve(query)

    source_file = result["metadata"].get("source_file")
    assert source_file in expected_sources
    assert source_file not in forbidden_sources
