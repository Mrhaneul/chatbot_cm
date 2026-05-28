import asyncio
import uuid

from app.main import (
    ambiguous_refund_clarification_reply,
    is_ambiguous_refund_policy_query,
    process_chat_request,
)
from app.schemas.chat import ChatRequest


def test_generic_refund_timeline_needs_clarification():
    assert is_ambiguous_refund_policy_query("Can I get a refund after 60 days?")


def test_refund_guarantee_needs_clarification():
    assert is_ambiguous_refund_policy_query("Can you guarantee I will get a refund?")


def test_scoped_refund_questions_do_not_trigger_ambiguous_guard():
    scoped_prompts = [
        "Can I get a refund for Immediate Access?",
        "Can I get a refund for my textbook?",
        "Can I return merchandise from the Campus Store?",
        "What is the return policy for technology?",
    ]
    for prompt in scoped_prompts:
        assert not is_ambiguous_refund_policy_query(prompt)


def test_ambiguous_refund_reply_asks_for_scope():
    reply = ambiguous_refund_clarification_reply().lower()

    assert "could you clarify" in reply
    assert "immediate access" in reply
    assert "textbooks" in reply
    assert "merchandise" in reply
    assert "technology" in reply
    assert "cannot confirm refund eligibility" in reply
    assert "guarantee" not in reply


def test_ambiguous_refund_chat_bypasses_retrieval_and_llm():
    response = asyncio.run(
        process_chat_request(
            ChatRequest(
                message="Can I get a refund after 60 days?",
                session_id=f"test-refund-{uuid.uuid4()}",
            )
        )
    )

    assert response.source == "CLARIFICATION_NEEDED"
    assert response.retrieval_time_ms == 0
    assert response.llm_time_ms == 0
    assert "could you clarify" in response.reply.lower()
