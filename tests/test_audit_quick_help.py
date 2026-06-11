from scripts.audit_quick_help import (
    KNOWN_EXPECTATIONS,
    QuickHelpExpectation,
    evaluate_audit_result,
    load_quick_help_prompts,
)


def test_audit_loads_quick_help_prompts_from_frontend_config():
    prompts = load_quick_help_prompts()

    assert "I can't access my McGraw Hill Connect textbook" in prompts
    assert "What is the refund policy for Immediate Access?" in prompts
    assert len(prompts) >= len(KNOWN_EXPECTATIONS)


def test_audit_evaluator_passes_known_expected_sources():
    expectation = QuickHelpExpectation(
        expected_source_files=("data/faqs/immediate_access/ia_opt_out_canvas.txt",),
        forbidden_source_files=("data/faqs/ia_access_issue.txt",),
    )

    result = evaluate_audit_result(
        prompt="How do I opt out of Immediate Access?",
        source="QUICK_HELP:immediate_access/ia_opt_out_canvas.txt",
        source_paths=["data/faqs/immediate_access/ia_opt_out_canvas.txt"],
        reply="Immediate Access has a 14-day opt-out period.",
        clarification_triggered=False,
        llm_calls=1,
        retrieval_time_ms=0,
        expectation=expectation,
    )

    assert result["status"] == "PASS"
    assert result["expected_source_match"] is True
    assert result["forbidden_source_found"] is False


def test_audit_evaluator_fails_for_forbidden_source():
    expectation = QuickHelpExpectation(
        expected_source_files=("data/faqs/immediate_access/ia_opt_out_canvas.txt",),
        forbidden_source_files=("data/faqs/ia_access_issue.txt",),
    )

    result = evaluate_audit_result(
        prompt="How do I opt out of Immediate Access?",
        source="FAQ_SOURCE_14",
        source_paths=["data/faqs/ia_access_issue.txt"],
        reply="Could you specify?",
        clarification_triggered=True,
        llm_calls=1,
        retrieval_time_ms=10,
        expectation=expectation,
    )

    assert result["status"] == "FAIL"
    assert result["expected_source_match"] is False
    assert result["forbidden_source_found"] is True
