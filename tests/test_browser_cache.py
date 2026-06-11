import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.main import is_browser_cache_issue, is_confirmed_materials_issue


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("When I try to access Immediate Access it says You currently have no content available", True),
        ("I see 0 courses 0 materials in my Immediate Access tab", True),
        ("Blackboard shows no content available for my class", True),
        ("The page is blank when I open Immediate Access", True),
        ("Nothing shows up on my Immediate Access tab", True),
        ("I'm trying to access my IA but it says that I currently don't have content available", True),
        ("I see 0 courses 0 materials and I use Firefox", True),
        ("No content available on my iPad", True),
        ("I can't access my McGraw Hill textbook", False),
        ("How do I opt out of Immediate Access", False),
        ("Where is the campus store", False),
        ("My Cengage MindTap won't load", False),
        ("I need help with my textbook", False),
    ],
)
def test_is_browser_cache_issue(message: str, expected: bool) -> None:
    assert is_browser_cache_issue(message) is expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Quickbooks", False),
        ("QuickBooks Online", False),
        ("my textbook", True),
        ("my book", True),
        ("I need access to my materials", True),
    ],
)
def test_is_confirmed_materials_issue_word_boundaries(message: str, expected: bool) -> None:
    assert is_confirmed_materials_issue(message) is expected


# ---------------------------------------------------------------------------
# Source file content tests — guard the grounding context for the 0 Courses
# cache response so the LLM always has specific browser steps available.
# ---------------------------------------------------------------------------

_CACHE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "data/faqs/immediate_access/ia_zero_courses_zero_materials_cache.txt"
)


def test_cache_source_includes_chrome_steps() -> None:
    """Chrome-specific steps must be in the grounding context."""
    text = _CACHE_SOURCE.read_text(encoding="utf-8")
    assert "Chrome" in text
    assert "Clear browsing data" in text or "Clear data" in text


def test_cache_source_includes_firefox_steps() -> None:
    """Firefox-specific steps must be in the grounding context."""
    text = _CACHE_SOURCE.read_text(encoding="utf-8")
    assert "firefox" in text.lower()
    assert "Clear Recent History" in text


def test_cache_source_includes_safari_steps() -> None:
    """Safari-specific steps must be in the grounding context."""
    text = _CACHE_SOURCE.read_text(encoding="utf-8")
    assert "Safari" in text
    assert "Empty Caches" in text or "Clear History" in text


def test_cache_source_includes_ipad_steps() -> None:
    """iPad Chrome steps must be in the grounding context."""
    text = _CACHE_SOURCE.read_text(encoding="utf-8")
    assert "iPad" in text
    assert "Clear Browsing Data" in text


def test_cache_source_email_not_concatenated_with_following_word() -> None:
    """
    The email address must be followed by a sentence-ending punctuation mark,
    not a bare word. This prevents the LLM from generating concatenations like
    'ImmediateAccess@calbaptist.eduwith' when paraphrasing the source.
    """
    text = _CACHE_SOURCE.read_text(encoding="utf-8")
    # The email must appear in the file
    assert "ImmediateAccess@calbaptist.edu" in text
    # It must NOT be directly followed by a word character (letter/digit)
    bad_pattern = re.compile(r"ImmediateAccess@calbaptist\.edu\w")
    assert not bad_pattern.search(text), (
        "Email address is immediately followed by a word character — "
        "add punctuation after the email to prevent LLM concatenation."
    )


# ---------------------------------------------------------------------------
# Firestore nested source_file sanitization test
# ---------------------------------------------------------------------------


def test_pdf_recommendations_nested_source_file_no_firestore_path_error() -> None:
    """
    source_file values like 'immediate_access/ia_zero_courses_zero_materials_cache.txt'
    must not cause a Firestore 'even number of path elements' error.
    The '/' must be replaced before the document() call.
    """
    from app.pdf_recommendations import get_pdf_recommendations

    nested_retrieval = {
        "context": "QUESTION:\nI see 0 Courses, 0 Materials.\n\nANSWER:\nClear browser cache.",
        "source_id": "ia_zero_courses_zero_materials_cache",
        "score": 0.95,
        "article_link": None,
        "metadata": {"source_file": "immediate_access/ia_zero_courses_zero_materials_cache.txt"},
    }

    captured_doc_ids: list[str] = []

    def fake_document(doc_id: str):
        captured_doc_ids.append(doc_id)
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_get = MagicMock(return_value=mock_doc)
        mock_ref = MagicMock()
        mock_ref.get = mock_get
        return mock_ref

    fake_collection = MagicMock()
    fake_collection.document = fake_document

    with patch("app.pdf_recommendations.db") as mock_db:
        mock_db.collection.return_value = fake_collection
        get_pdf_recommendations(nested_retrieval, platform=None)

    assert captured_doc_ids, "document() was never called"
    for doc_id in captured_doc_ids:
        assert "/" not in doc_id, (
            f"Firestore document ID contains '/': {doc_id!r} — "
            "sanitize nested source_file paths before passing to document()."
        )
