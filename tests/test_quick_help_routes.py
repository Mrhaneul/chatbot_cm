from app.quick_help_routes import build_quick_help_match, find_quick_help_route


EXPECTED_QUICK_HELP_SOURCES = {
    "I can't access my McGraw Hill Connect textbook": (
        "data/instructions/ia_mcgraw_hill_connect_access.txt",
        "data/instructions/ia_mcgraw_hill_tools_access.txt",
    ),
    "I can't access my Vitalsource": (
        "data/instructions/ia_vitalsource_bookshelf_account_creation.txt",
    ),
    "My book is not showing up in Immediate Access": (
        "data/faqs/ia_bundle_missing_textbook.txt",
    ),
    "How do I opt out of Immediate Access?": (
        "data/faqs/ia_overview.txt",
    ),
    "Where do I opt out from Immediate Access?": (
        "data/faqs/ia_overview.txt",
    ),
    "How do I return a textbook?": (
        "data/faqs/textbook_refund_policy.txt",
    ),
    "What is the refund policy for Immediate Access?": (
        "data/faqs/ia_overview.txt",
        "data/faqs/textbook_refund_policy.txt",
    ),
}


def test_known_failing_quick_help_prompts_route_to_canonical_sources():
    for prompt, expected_sources in EXPECTED_QUICK_HELP_SOURCES.items():
        route = find_quick_help_route(prompt)

        assert route is not None
        assert route.source_paths == expected_sources


def test_known_failing_quick_help_prompts_build_deterministic_answers():
    for prompt, expected_sources in EXPECTED_QUICK_HELP_SOURCES.items():
        match = build_quick_help_match(prompt)

        assert match is not None
        assert match.source_paths == expected_sources
        assert match.source.startswith("QUICK_HELP:")
        assert "CLARIFICATION_NEEDED" not in match.source
        assert "could you specify" not in match.reply.lower()
        assert match.reply.strip()


def test_immediate_access_refund_does_not_route_to_general_merchandise_refund():
    match = build_quick_help_match("What is the refund policy for Immediate Access?")

    assert match is not None
    assert "data/faqs/campus_store_refund_merchandise.txt" not in match.source_paths
    assert "campus_store_refund_merchandise" not in match.context
    assert "14-day opt-out period" in match.reply
    assert "digital content" in match.reply.lower()


def test_mcgraw_quick_help_includes_both_blackboard_locations():
    match = build_quick_help_match("I can't access my McGraw Hill Connect textbook")

    assert match is not None
    assert "Learning Activities tab" in match.reply
    assert "Tools tab" in match.reply
    assert "may depend on how your instructor set up the course" in match.reply


def test_normal_typed_query_does_not_match_quick_help_routes():
    assert find_quick_help_route("Can you help me find a blue CBU hoodie?") is None
