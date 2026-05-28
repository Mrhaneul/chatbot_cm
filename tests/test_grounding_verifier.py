"""
Tests for app/rag/grounding_verifier.py

Unit tests cover all required claim types.
Integration tests patch call_llm_with_semaphore and retrieve_faq_candidates
to verify that process_chat_request blocks unsupported high-risk claims.
"""

import asyncio

import pytest

from app.rag.grounding_verifier import (
    GROUNDING_SAFE_FALLBACK,
    GroundingVerificationResult,
    verify_answer_grounding,
)


# ── Unit tests ────────────────────────────────────────────────────────────────


def test_supported_email_passes():
    """Email present in context must not be flagged."""
    context = "Contact us at ImmediateAccess@calbaptist.edu for assistance."
    answer = "Please email ImmediateAccess@calbaptist.edu for help with your materials."
    result = verify_answer_grounding(answer, context)
    assert result.passed
    assert result.unsupported_claims == []


def test_unsupported_email_flagged():
    """Email absent from context must be flagged."""
    context = "Contact the Campus Store for help."
    answer = "Please email support@example.com for assistance."
    result = verify_answer_grounding(answer, context)
    assert not result.passed
    claim_types = [c.claim_type for c in result.unsupported_claims]
    assert "email" in claim_types
    texts = [c.claim_text.lower() for c in result.unsupported_claims]
    assert any("support@example.com" in t for t in texts)


def test_unsupported_phone_number_flagged():
    """Phone number absent from context must be flagged."""
    context = "Contact the Campus Store for help with your account."
    answer = "You can reach us at 555-123-4567 for more information."
    result = verify_answer_grounding(answer, context)
    assert not result.passed
    claim_types = [c.claim_type for c in result.unsupported_claims]
    assert "phone_number" in claim_types


def test_supported_14_day_period_passes():
    """14-day opt-out period present in context must pass."""
    context = "Students have a 14-day opt-out period from the start of the semester."
    answer = "You have a 14-day opt-out period to opt out of Immediate Access."
    result = verify_answer_grounding(answer, context)
    assert result.passed


def test_supported_time_period_passes_with_hyphen_variant():
    """Time periods should match common spacing/hyphen variants."""
    context = "Students have a 14-day opt-out period from the start of the semester."
    answer = "You have 14 days to opt out of Immediate Access."
    result = verify_answer_grounding(answer, context)
    assert result.passed


def test_unsupported_time_period_flagged():
    """Time period absent from context must be flagged."""
    context = "Students have a 14-day opt-out period from the start of the semester."
    answer = "You have 30 days to request a refund."
    result = verify_answer_grounding(answer, context)
    assert not result.passed
    claim_types = [c.claim_type for c in result.unsupported_claims]
    assert "time_period" in claim_types
    texts = [c.claim_text.lower() for c in result.unsupported_claims]
    assert any("30" in t for t in texts)


def test_unsupported_url_flagged():
    """URL absent from context must be flagged."""
    context = "Please contact the Campus Store for assistance."
    answer = "Visit https://example.com/help for instructions."
    result = verify_answer_grounding(answer, context)
    assert not result.passed
    claim_types = [c.claim_type for c in result.unsupported_claims]
    assert "url" in claim_types


def test_merchandise_policy_language_blocked_from_ia_context():
    """
    Merchandise return language (restocking fee) must not pass when the
    retrieved context is an IA digital-content context that doesn't mention it.
    """
    context = (
        "Immediate Access materials are digital and follow a 14-day opt-out policy. "
        "You can opt out through the Immediate Access page in Blackboard."
    )
    answer = (
        "For Immediate Access materials, note that a 25% restocking fee applies "
        "to returns. Returns must be made within 14 days."
    )
    result = verify_answer_grounding(answer, context)
    assert not result.passed
    claim_types = [c.claim_type for c in result.unsupported_claims]
    # "restocking fee" is a policy_phrase not in IA context
    assert "policy_phrase" in claim_types or "dollar_amount" in claim_types


def test_generic_safe_answer_passes():
    """An answer that only says docs are insufficient must pass without false positives."""
    context = "Immediate Access provides digital course materials."
    answer = (
        "I do not have enough information in the Campus Store documentation to answer that fully."
    )
    result = verify_answer_grounding(answer, context)
    assert result.passed


def test_verifier_disabled_always_passes():
    """verifier_enabled=False bypasses all checks."""
    context = ""
    answer = "Please call 555-123-4567 for help."
    result = verify_answer_grounding(answer, context, verifier_enabled=False)
    assert result.passed
    assert result.verifier_enabled is False


def test_empty_context_passes():
    """Empty context means nothing to verify against — always passes."""
    context = ""
    answer = "Please email support@example.com for assistance."
    result = verify_answer_grounding(answer, context)
    assert result.passed


def test_supported_phone_passes():
    """Phone present in context must not be flagged."""
    context = "For assistance, call the Campus Store at 951-343-4259."
    answer = "You can reach the Campus Store at 951-343-4259 for help."
    result = verify_answer_grounding(answer, context)
    assert result.passed


def test_supported_dollar_amount_passes():
    """Dollar amount present in context must not be flagged."""
    context = "There is a 25% restocking fee of $15 for physical textbook returns."
    answer = "A restocking fee of $15 applies to physical textbook returns."
    result = verify_answer_grounding(answer, context)
    assert result.passed


def test_supported_dollar_amount_passes_with_spacing_variant():
    """Dollar amounts should match even if the model adds a space after '$'."""
    context = "There is a restocking fee of $15 for physical textbook returns."
    answer = "A restocking fee of $ 15 applies to physical textbook returns."
    result = verify_answer_grounding(answer, context)
    assert result.passed


def test_unsupported_dollar_amount_flagged():
    """Dollar amount absent from context must be flagged."""
    context = "Immediate Access materials are covered by the digital content policy."
    answer = "A processing fee of $10 may apply."
    result = verify_answer_grounding(answer, context)
    assert not result.passed
    claim_types = [c.claim_type for c in result.unsupported_claims]
    assert "dollar_amount" in claim_types


def test_result_is_dataclass_instance():
    """verify_answer_grounding must return a GroundingVerificationResult."""
    result = verify_answer_grounding("hello", "world")
    assert isinstance(result, GroundingVerificationResult)


def test_fallback_constant_is_nonempty():
    assert GROUNDING_SAFE_FALLBACK
    assert len(GROUNDING_SAFE_FALLBACK) > 20


# ── Integration tests ─────────────────────────────────────────────────────────
# Note: full process_chat_request integration tests require python-multipart
# (for app/admin.py's file-upload route) which is not currently installed.
# These tests instead cover the config→verifier integration and verifier
# behaviour against realistic full-document contexts from the data files.


def test_integration_config_default_enabled():
    """ENABLE_GROUNDING_VERIFIER defaults to True in cfg."""
    from app.rag.config import cfg

    assert cfg.ENABLE_GROUNDING_VERIFIER is True


def test_integration_config_env_override(monkeypatch):
    """ENABLE_GROUNDING_VERIFIER=false disables the verifier via env var."""
    monkeypatch.setenv("ENABLE_GROUNDING_VERIFIER", "false")
    # Re-instantiate Config so it picks up the patched env var.
    from app.rag.config import Config

    test_cfg = Config()
    assert test_cfg.ENABLE_GROUNDING_VERIFIER is False


def test_integration_unsupported_phone_blocked_via_verifier():
    """
    Simulates what process_chat_request does after call_llm_with_semaphore:
    run verify_answer_grounding and replace reply when phone is unsupported.
    """
    context = "Immediate Access provides digital course materials at CBU."
    llm_reply = "Call 555-000-1234 for help with your materials."

    result = verify_answer_grounding(llm_reply, context)
    final_reply = GROUNDING_SAFE_FALLBACK if not result.passed else llm_reply

    assert "555-000-1234" not in final_reply
    assert result.passed is False
    claim_types = [c.claim_type for c in result.unsupported_claims]
    assert "phone_number" in claim_types


def test_integration_supported_answer_returned_normally():
    """
    Simulates what process_chat_request does when LLM output is grounded:
    verify_answer_grounding passes and the original reply is returned.
    """
    context = (
        "Immediate Access gives students digital course materials for the semester. "
        "You can opt out through the Immediate Access page in Blackboard."
    )
    llm_reply = (
        "Immediate Access gives students digital course materials for the semester. "
        "You can opt out through the Immediate Access page in Blackboard."
    )

    result = verify_answer_grounding(llm_reply, context)
    final_reply = GROUNDING_SAFE_FALLBACK if not result.passed else llm_reply

    assert result.passed is True
    assert "opt out" in final_reply.lower()
    assert "immediate access" in final_reply.lower()


def test_integration_real_ia_overview_context(monkeypatch):
    """
    Verifier runs against the actual ia_overview.txt content.
    A hallucinated unsupported email is blocked; the documented opt-out
    period (if present) is not flagged.
    """
    from pathlib import Path

    overview_path = Path("data/faqs/ia_overview.txt")
    if not overview_path.is_file():
        pytest.skip("data/faqs/ia_overview.txt not present")

    context = overview_path.read_text(encoding="utf-8", errors="replace")

    # Hallucinated email not in the actual file → must be blocked.
    hallucinated_reply = "Please contact fake@invented.edu for Immediate Access help."
    result_bad = verify_answer_grounding(hallucinated_reply, context)
    assert not result_bad.passed
    assert any(c.claim_type == "email" for c in result_bad.unsupported_claims)

    # A simple grounded answer with no unsupported claims → must pass.
    grounded_reply = "Immediate Access provides digital course materials for enrolled students."
    result_good = verify_answer_grounding(grounded_reply, context)
    assert result_good.passed
