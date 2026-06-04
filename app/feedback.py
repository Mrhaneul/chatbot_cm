from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


FEEDBACK_DIR = Path(os.environ.get("FEEDBACK_DIR", "data/feedback"))
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.jsonl"

MAX_COMMENT_LENGTH = 2000
MAX_MESSAGE_LENGTH = 8000
MAX_RESPONSE_LENGTH = 12000
MAX_ID_LENGTH = 256
MAX_SOURCE_LABEL_LENGTH = 256
MAX_SOURCE_FILE_LENGTH = 512

# JSONL storage is acceptable for the MVP/single-process deployment. Admin
# PATCH rewrites the file and is not ideal for high-concurrency multi-worker
# deployment; future upgrade path is SQLite, Firestore, or another
# transactional store.


class FeedbackSubmission(BaseModel):
    response_id: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    session_id: Optional[str] = Field(default=None, max_length=MAX_ID_LENGTH)
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=MAX_COMMENT_LENGTH)
    original_user_message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    lance_response: str = Field(..., min_length=1, max_length=MAX_RESPONSE_LENGTH)
    source_label: str = Field(..., min_length=1, max_length=MAX_SOURCE_LABEL_LENGTH)
    retrieval_confidence: Optional[float] = None
    retrieved_source_file: Optional[str] = Field(default=None, max_length=MAX_SOURCE_FILE_LENGTH)


class FeedbackReviewUpdate(BaseModel):
    reviewed: Optional[bool] = None
    resolved: Optional[bool] = None
    admin_note: Optional[str] = Field(default=None, max_length=MAX_COMMENT_LENGTH)


feedback_router = APIRouter(tags=["feedback"])


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="microseconds") + "Z"


def _clean_text(value: Optional[str], max_length: int, *, required: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise ValueError("Required text field is missing.")
        return None
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError("Required text field must not be empty.")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def _feedback_file() -> Path:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    return FEEDBACK_FILE


def _read_feedback_records() -> list[dict]:
    path = _feedback_file()
    if not path.exists():
        return []
    records: list[dict] = []
    skipped = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            skipped += 1
            print(
                f"[WARN] Skipping malformed feedback JSONL line "
                f"{line_number} in {path}: {exc}"
            )
    if skipped:
        print(f"[WARN] Skipped {skipped} malformed feedback JSONL line(s)")
    return records


def _write_feedback_records(records: list[dict]) -> None:
    path = _feedback_file()
    temp_path = path.with_suffix(".jsonl.tmp")
    body = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    temp_path.write_text(body, encoding="utf-8", newline="\n")
    os.replace(temp_path, path)


def save_feedback(payload: FeedbackSubmission) -> dict:
    response_id = _clean_text(payload.response_id, MAX_ID_LENGTH, required=True)
    session_id = _clean_text(payload.session_id, MAX_ID_LENGTH)
    comment = _clean_text(payload.comment, MAX_COMMENT_LENGTH)
    original_user_message = _clean_text(
        payload.original_user_message,
        MAX_MESSAGE_LENGTH,
        required=True,
    )
    lance_response = _clean_text(
        payload.lance_response,
        MAX_RESPONSE_LENGTH,
        required=True,
    )
    source_label = _clean_text(payload.source_label, MAX_SOURCE_LABEL_LENGTH, required=True)
    retrieved_source_file = _clean_text(payload.retrieved_source_file, MAX_SOURCE_FILE_LENGTH)

    record = {
        "feedback_id": uuid4().hex,
        "response_id": response_id,
        "session_id": session_id,
        "rating": payload.rating,
        "comment": comment,
        "original_user_message": original_user_message,
        "lance_response": lance_response,
        "source_label": source_label,
        "retrieval_confidence": payload.retrieval_confidence,
        "retrieved_source_file": retrieved_source_file,
        "timestamp": _now_iso(),
        "reviewed": False,
        "resolved": False,
        "admin_note": None,
        "reviewed_at": None,
        "resolved_at": None,
    }
    path = _feedback_file()
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_feedback_records(
    *,
    low_rating: bool = False,
    source_label: Optional[str] = None,
    date: Optional[str] = None,
    reviewed: Optional[bool] = None,
    resolved: Optional[bool] = None,
) -> list[dict]:
    records = _read_feedback_records()
    if low_rating:
        records = [record for record in records if int(record.get("rating", 0)) <= 2]
    if source_label:
        expected = source_label.strip().lower()
        records = [
            record for record in records
            if str(record.get("source_label", "")).lower() == expected
        ]
    if date:
        records = [
            record for record in records
            if str(record.get("timestamp", "")).startswith(date)
        ]
    if reviewed is not None:
        records = [record for record in records if bool(record.get("reviewed")) is reviewed]
    if resolved is not None:
        records = [record for record in records if bool(record.get("resolved")) is resolved]
    return sorted(records, key=lambda record: str(record.get("timestamp", "")), reverse=True)


def update_feedback_review(feedback_id: str, payload: FeedbackReviewUpdate) -> dict:
    target_id = _clean_text(feedback_id, MAX_ID_LENGTH, required=True)
    records = _read_feedback_records()
    for record in records:
        if record.get("feedback_id") != target_id:
            continue
        now = _now_iso()
        if payload.reviewed is not None:
            record["reviewed"] = payload.reviewed
            record["reviewed_at"] = now if payload.reviewed else None
        if payload.resolved is not None:
            record["resolved"] = payload.resolved
            record["resolved_at"] = now if payload.resolved else None
            if payload.resolved:
                record["reviewed"] = True
                record["reviewed_at"] = record.get("reviewed_at") or now
        if payload.admin_note is not None:
            record["admin_note"] = _clean_text(payload.admin_note, MAX_COMMENT_LENGTH)
        _write_feedback_records(records)
        return record
    raise FileNotFoundError(f"Feedback '{feedback_id}' not found.")


@feedback_router.post("/feedback")
async def submit_feedback(payload: FeedbackSubmission):
    try:
        record = save_feedback(payload)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "success": False,
            "message": str(exc),
        })
    return JSONResponse(status_code=201, content={
        "success": True,
        "feedback_id": record["feedback_id"],
        "message": "Feedback saved for review.",
    })
