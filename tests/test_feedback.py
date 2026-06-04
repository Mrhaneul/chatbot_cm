from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.admin as admin
import app.feedback as feedback
import app.main as main
from app.feedback import FeedbackReviewUpdate, FeedbackSubmission
from app.main import app
from app.schemas.chat import ChatResponse


@pytest.fixture
def feedback_env(tmp_path: Path, monkeypatch):
    feedback_dir = tmp_path / "feedback"
    feedback_file = feedback_dir / "feedback.jsonl"
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", feedback_dir)
    monkeypatch.setattr(feedback, "FEEDBACK_FILE", feedback_file)
    return feedback_file


def _payload(**overrides) -> dict:
    payload = {
        "response_id": "resp-123",
        "session_id": "session-abc",
        "rating": 2,
        "comment": "The answer missed the Cengage detail.",
        "original_user_message": "How do I access Cengage?",
        "lance_response": "Open Blackboard and select Cengage MindTap.",
        "source_label": "INSTR_CENGAGE",
        "retrieval_confidence": 0.82,
        "retrieved_source_file": "platforms/cengage/access.txt",
    }
    payload.update(overrides)
    return payload


def _json(response) -> dict:
    return json.loads(response.body)


def test_valid_feedback_is_persisted(feedback_env):
    client = TestClient(app)

    response = client.post("/feedback", json=_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    records = feedback.list_feedback_records()
    assert len(records) == 1
    assert records[0]["feedback_id"] == body["feedback_id"]
    assert records[0]["response_id"] == "resp-123"
    assert records[0]["rating"] == 2
    assert records[0]["reviewed"] is False
    assert records[0]["resolved"] is False


@pytest.mark.parametrize("rating", [0, 6])
def test_invalid_ratings_are_rejected(feedback_env, rating):
    client = TestClient(app)

    response = client.post("/feedback", json=_payload(rating=rating))

    assert response.status_code == 422
    assert not feedback_env.exists()


def test_missing_response_id_is_rejected(feedback_env):
    client = TestClient(app)
    payload = _payload()
    del payload["response_id"]

    response = client.post("/feedback", json=payload)

    assert response.status_code == 422
    assert not feedback_env.exists()


def test_empty_response_id_is_rejected(feedback_env):
    response = asyncio.run(
        feedback.submit_feedback(FeedbackSubmission(**_payload(response_id=" ")))
    )
    body = _json(response)

    assert response.status_code == 400
    assert body["success"] is False
    assert "must not be empty" in body["message"]


def test_optional_comment_is_accepted(feedback_env):
    record = feedback.save_feedback(FeedbackSubmission(**_payload(comment=None, rating=5)))

    assert record["comment"] is None
    assert feedback.list_feedback_records()[0]["rating"] == 5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("comment", "x" * (feedback.MAX_COMMENT_LENGTH + 1)),
        ("original_user_message", "x" * (feedback.MAX_MESSAGE_LENGTH + 1)),
        ("lance_response", "x" * (feedback.MAX_RESPONSE_LENGTH + 1)),
    ],
)
def test_oversized_feedback_fields_are_rejected(feedback_env, field, value):
    client = TestClient(app)

    response = client.post("/feedback", json=_payload(**{field: value}))

    assert response.status_code == 422
    assert not feedback_env.exists()


def test_admin_can_filter_feedback(feedback_env):
    feedback.save_feedback(FeedbackSubmission(**_payload(
        response_id="low-cengage",
        rating=1,
        source_label="INSTR_CENGAGE",
    )))
    feedback.save_feedback(FeedbackSubmission(**_payload(
        response_id="high-faq",
        rating=5,
        source_label="FAQ_SOURCE_14",
    )))

    response = asyncio.run(admin.list_feedback(low_rating=True, source_label="INSTR_CENGAGE"))
    body = _json(response)

    assert body["success"] is True
    assert body["count"] == 1
    assert body["feedback"][0]["response_id"] == "low-cengage"


def test_admin_listing_skips_corrupted_jsonl_lines(feedback_env):
    first = feedback.save_feedback(FeedbackSubmission(**_payload(response_id="valid-one")))
    second = feedback.save_feedback(FeedbackSubmission(**_payload(response_id="valid-two")))
    feedback_env.write_text(
        "\n".join([
            json.dumps(first),
            "{this is not valid json",
            json.dumps(second),
            "",
        ]),
        encoding="utf-8",
    )

    response = asyncio.run(admin.list_feedback())
    body = _json(response)

    assert response.status_code == 200
    assert body["success"] is True
    assert body["count"] == 2
    assert {item["response_id"] for item in body["feedback"]} == {"valid-one", "valid-two"}


def test_admin_can_mark_feedback_reviewed_and_resolved(feedback_env):
    record = feedback.save_feedback(FeedbackSubmission(**_payload()))

    response = asyncio.run(
        admin.update_feedback(
            record["feedback_id"],
            FeedbackReviewUpdate(reviewed=True, resolved=True, admin_note="Added to review queue."),
        )
    )
    body = _json(response)

    assert body["success"] is True
    updated = body["feedback"]
    assert updated["reviewed"] is True
    assert updated["resolved"] is True
    assert updated["admin_note"] == "Added to review queue."
    assert updated["reviewed_at"]
    assert updated["resolved_at"]


def test_admin_update_works_with_unrelated_corrupted_jsonl_line(feedback_env):
    first = feedback.save_feedback(FeedbackSubmission(**_payload(response_id="valid-one")))
    second = feedback.save_feedback(FeedbackSubmission(**_payload(response_id="valid-two")))
    feedback_env.write_text(
        "\n".join([
            json.dumps(first),
            "not-json",
            json.dumps(second),
            "",
        ]),
        encoding="utf-8",
    )

    response = asyncio.run(
        admin.update_feedback(second["feedback_id"], FeedbackReviewUpdate(reviewed=True))
    )
    body = _json(response)

    assert response.status_code == 200
    assert body["success"] is True
    assert body["feedback"]["response_id"] == "valid-two"
    assert body["feedback"]["reviewed"] is True


def test_invalid_feedback_id_returns_404(feedback_env):
    response = asyncio.run(
        admin.update_feedback("missing-feedback", FeedbackReviewUpdate(reviewed=True))
    )
    body = _json(response)

    assert response.status_code == 404
    assert body["success"] is False
    assert "not found" in body["message"]


def test_reviewed_resolved_and_date_filters_work(feedback_env):
    reviewed = feedback.save_feedback(FeedbackSubmission(**_payload(
        response_id="reviewed-item",
        rating=1,
    )))
    resolved = feedback.save_feedback(FeedbackSubmission(**_payload(
        response_id="resolved-item",
        rating=3,
    )))
    open_item = feedback.save_feedback(FeedbackSubmission(**_payload(
        response_id="open-item",
        rating=4,
    )))
    reviewed["reviewed"] = True
    reviewed["reviewed_at"] = "2026-06-04T10:00:00Z"
    resolved["reviewed"] = True
    resolved["resolved"] = True
    resolved["reviewed_at"] = "2026-06-04T10:00:00Z"
    resolved["resolved_at"] = "2026-06-04T10:01:00Z"
    reviewed["timestamp"] = "2026-06-04T10:00:00Z"
    resolved["timestamp"] = "2026-06-04T11:00:00Z"
    open_item["timestamp"] = "2026-06-05T10:00:00Z"
    feedback_env.write_text(
        "".join(json.dumps(item) + "\n" for item in [reviewed, resolved, open_item]),
        encoding="utf-8",
    )

    reviewed_response = asyncio.run(admin.list_feedback(reviewed=True))
    resolved_response = asyncio.run(admin.list_feedback(resolved=True))
    date_response = asyncio.run(admin.list_feedback(date="2026-06-04"))

    reviewed_body = _json(reviewed_response)
    resolved_body = _json(resolved_response)
    date_body = _json(date_response)

    assert {item["response_id"] for item in reviewed_body["feedback"]} == {
        "reviewed-item",
        "resolved-item",
    }
    assert {item["response_id"] for item in resolved_body["feedback"]} == {
        "resolved-item",
    }
    assert {item["response_id"] for item in date_body["feedback"]} == {
        "reviewed-item",
        "resolved-item",
    }


def test_feedback_does_not_trigger_content_or_model_changes(feedback_env, monkeypatch):
    called = False

    def fail_if_called():
        nonlocal called
        called = True
        raise AssertionError("Feedback must not trigger ingestion or training.")

    monkeypatch.setattr(admin, "_run_ingestion", fail_if_called)

    response = asyncio.run(feedback.submit_feedback(FeedbackSubmission(**_payload())))

    assert response.status_code == 201
    assert called is False


def test_chat_endpoint_adds_response_id_for_feedback(monkeypatch):
    async def fake_process_chat_request(payload):
        return ChatResponse(
            reply="Use Blackboard.",
            source="INSTR_CENGAGE",
            confidence=0.9,
        )

    monkeypatch.setattr(main, "process_chat_request", fake_process_chat_request)
    client = TestClient(app)

    response = client.post("/chat", json={
        "message": "How do I access Cengage?",
        "session_id": "feedback-session",
    })
    body = response.json()

    assert response.status_code == 200
    assert body["response_id"]
    assert body["session_id"] == "feedback-session"
