from pathlib import Path

import pytest

from app.rag.metadata import load_document_with_metadata, parse_front_matter_text


HIGH_RISK_METADATA = {
    "data/instructions/ia_mcgraw_hill_connect_access.txt": {
        "source_id": "ia_mcgraw_hill_connect_access",
        "source_type": "instruction",
        "category": "platform_access",
        "platform": "mcgraw_hill",
        "issue_type": "access",
        "priority": "canonical",
    },
    "data/instructions/ia_mcgraw_hill_tools_access.txt": {
        "source_id": "ia_mcgraw_hill_tools_access",
        "source_type": "instruction",
        "category": "platform_access",
        "platform": "mcgraw_hill",
        "issue_type": "access",
        "priority": "alternate",
    },
    "data/instructions/ia_vitalsource_bookshelf_account_creation.txt": {
        "source_id": "ia_vitalsource_bookshelf_account_creation",
        "source_type": "instruction",
        "category": "platform_access",
        "platform": "vitalsource",
        "issue_type": "account_creation",
        "priority": "canonical",
    },
    "data/instructions/ia_bedford_bookshelf_email_error_access.txt": {
        "source_id": "ia_bedford_bookshelf_email_error_access",
        "source_type": "instruction",
        "category": "platform_access",
        "platform": "bedford",
        "issue_type": "email_error",
        "priority": "specific_case",
    },
    "data/faqs/ia_bundle_missing_textbook.txt": {
        "source_id": "ia_bundle_missing_textbook",
        "source_type": "faq",
        "category": "immediate_access",
        "platform": None,
        "issue_type": "missing_book",
        "priority": "canonical",
    },
    "data/faqs/ia_overview.txt": {
        "source_id": "ia_overview",
        "source_type": "faq",
        "category": "immediate_access",
        "platform": None,
        "issue_type": "overview",
        "priority": "canonical",
    },
    "data/faqs/textbook_refund_policy.txt": {
        "source_id": "textbook_refund_policy",
        "source_type": "faq",
        "category": "textbook_return",
        "platform": None,
        "issue_type": "return_refund",
        "priority": "canonical",
    },
    "data/faqs/campus_store_refund_merchandise.txt": {
        "source_id": "campus_store_refund_merchandise",
        "source_type": "faq",
        "category": "merchandise_return",
        "platform": None,
        "issue_type": "return_refund",
        "priority": "canonical",
    },
    "data/faqs/ia_access_issue.txt": {
        "source_id": "ia_access_issue",
        "source_type": "faq",
        "category": "immediate_access",
        "platform": None,
        "issue_type": "access_issue",
        "priority": "specific_case",
    },
}


def test_parse_front_matter_text_parses_metadata_and_strips_body():
    text = """---
source_id: ia_overview
source_type: faq
category: immediate_access
platform: null
issue_type: overview
priority: canonical
---

QUESTION:
What is Immediate Access?
"""

    metadata, body = parse_front_matter_text(text)

    assert metadata == {
        "source_id": "ia_overview",
        "source_type": "faq",
        "category": "immediate_access",
        "platform": None,
        "issue_type": "overview",
        "priority": "canonical",
    }
    assert body.startswith("\nQUESTION:")
    assert "source_id:" not in body


def test_load_document_without_front_matter_uses_fallback_metadata(tmp_path: Path):
    document = tmp_path / "faqs" / "plain_faq.txt"
    document.parent.mkdir()
    document.write_text("QUESTION:\nPlain FAQ\n\nANSWER:\nPlain answer", encoding="utf-8")

    metadata, body = load_document_with_metadata(document)

    assert metadata == {
        "source_file": "plain_faq.txt",
        "source_id": "plain_faq",
        "source_type": "faq",
    }
    assert body == "QUESTION:\nPlain FAQ\n\nANSWER:\nPlain answer"


@pytest.mark.parametrize(("source_path", "expected"), HIGH_RISK_METADATA.items())
def test_high_risk_files_have_expected_front_matter(source_path: str, expected: dict):
    metadata, body = load_document_with_metadata(source_path)

    for key, value in expected.items():
        assert metadata[key] == value
    assert metadata["source_file"] == Path(source_path).name
    assert body
    assert not body.startswith("---")
    assert "source_id:" not in body.splitlines()[:8]
