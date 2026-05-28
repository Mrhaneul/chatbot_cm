from app.rag.context_expansion import expand_retrieval_context
from app.rag.metadata import load_document_with_metadata
from app.rag.retriever import get_retriever


def _candidate(source_path: str, source_id: str = "TEST_SOURCE", score: float = 1.0) -> dict:
    metadata, body = load_document_with_metadata(source_path)
    return {
        "context": body[:200],
        "metadata": metadata,
        "source_id": source_id,
        "score": score,
        "combined_score": score,
    }


def test_expansion_loads_full_source_body_and_strips_front_matter():
    result = expand_retrieval_context([
        _candidate("data/faqs/textbook_refund_policy.txt")
    ])

    assert "Textbook Refund Policy" in result.context
    assert "[FAQ_1]" in result.context
    assert "[FAQ_11]" in result.context
    assert not result.context.lstrip().startswith("---")
    assert "source_id: textbook_refund_policy" not in result.context
    assert result.parent_sources[0]["expanded"] is True


def test_expansion_deduplicates_same_source_file():
    candidate_one = _candidate("data/faqs/textbook_refund_policy.txt", "FAQ_SOURCE_1")
    candidate_two = _candidate("data/faqs/textbook_refund_policy.txt", "FAQ_SOURCE_2")

    result = expand_retrieval_context([candidate_one, candidate_two])

    assert len(result.parent_sources) == 1
    assert result.context.count("Textbook Refund Policy") == 1


def test_expansion_respects_max_parent_sources():
    result = expand_retrieval_context(
        [
            _candidate("data/faqs/ia_overview.txt", "FAQ_SOURCE_1"),
            _candidate("data/faqs/textbook_refund_policy.txt", "FAQ_SOURCE_2"),
            _candidate("data/faqs/campus_store_refund_merchandise.txt", "FAQ_SOURCE_3"),
        ],
        max_parent_sources=2,
    )

    assert len(result.parent_sources) == 2
    assert "campus_store_refund_merchandise.txt" not in result.context


def test_expansion_respects_max_chars_and_marks_truncation():
    result = expand_retrieval_context(
        [_candidate("data/faqs/textbook_refund_policy.txt")],
        max_chars=300,
    )

    assert result.truncated is True
    assert result.expanded_context_chars <= 300
    assert "Context truncated" in result.context


def test_missing_source_file_falls_back_to_original_chunk():
    result = expand_retrieval_context([
        {
            "context": "Original fallback chunk",
            "metadata": {"source_file": "missing_source.txt", "source_type": "faq"},
            "source_id": "FAQ_SOURCE_MISSING",
            "score": 0.1,
        }
    ])

    assert result.context.endswith("Original fallback chunk")
    assert result.parent_sources[0]["expanded"] is False


def test_textbook_return_retrieval_expands_full_policy_context():
    result = get_retriever().retrieve("How do I return a textbook?")

    assert result["metadata"]["source_file"] == "textbook_refund_policy.txt"
    assert "Textbook Refund Policy" in result["context"]
    assert "[FAQ_1]" in result["context"]
    assert "[FAQ_11]" in result["context"]
    assert result["parent_sources"][0]["source_file"] == "textbook_refund_policy.txt"


def test_immediate_access_refund_can_expand_relevant_parent_context_without_merchandise():
    result = get_retriever().retrieve("What is the refund policy for Immediate Access?", k=2)
    source_files = {source["source_file"] for source in result["parent_sources"]}

    assert source_files & {"ia_overview.txt", "textbook_refund_policy.txt"}
    assert "campus_store_refund_merchandise.txt" not in source_files


def test_vitalsource_access_expands_vitalsource_not_bedford_email_error():
    result = get_retriever().retrieve("I can't access my Vitalsource")
    source_files = {source["source_file"] for source in result["parent_sources"]}

    assert "ia_vitalsource_bookshelf_account_creation.txt" in source_files
    assert "ia_bedford_bookshelf_email_error_access.txt" not in source_files
