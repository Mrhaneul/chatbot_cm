import os

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
