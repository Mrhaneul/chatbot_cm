from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

import app.admin as admin


ARCHIVE_NAME_RE = re.compile(r"^[^.]+\.\d{8}T\d{12}Z\.[0-9a-f]{8}\.txt$")


def _valid_faq_content(source_id: str = "nested_faq") -> str:
    return f"""---
source_id: {source_id}
source_type: faq
category: immediate_access
platform: null
issue_type: overview
priority: canonical
---

QUESTION:
What is this?

ANSWER:
This is editable content.
"""


def _valid_instruction_content(source_id: str = "nested_instruction") -> str:
    return f"""---
source_id: {source_id}
source_type: instruction
category: platform_access
platform: cengage
issue_type: access
priority: canonical
---

PROBLEM:
Student cannot open Cengage.

STEP-BY-STEP RESOLUTION:
1. Open Blackboard.
2. Select Cengage MindTap.
"""


@pytest.fixture
def admin_content_env(tmp_path: Path, monkeypatch):
    faq_root = tmp_path / "faqs"
    instruction_root = tmp_path / "instructions"
    archive_root = tmp_path / "_archive"
    faq_root.mkdir()
    instruction_root.mkdir()
    monkeypatch.setattr(admin, "FAQ_DIR", faq_root)
    monkeypatch.setattr(admin, "INSTRUCTIONS_DIR", instruction_root)
    monkeypatch.setattr(admin, "ARCHIVE_DIR", archive_root)
    monkeypatch.setattr(admin, "_run_ingestion", lambda: "Index rebuilt successfully.")
    monkeypatch.setattr("app.firebase_config.get_firestore_client", lambda: None)
    return {
        "faq_root": faq_root,
        "instruction_root": instruction_root,
        "archive_root": archive_root,
    }


def _json(response) -> dict:
    return json.loads(response.body)


def test_get_content_reads_nested_file_for_editing(admin_content_env):
    path = admin_content_env["faq_root"] / "immediate-access" / "nested.txt"
    path.parent.mkdir(parents=True)
    path.write_text(_valid_faq_content(), encoding="utf-8")

    response = asyncio.run(
        admin.get_content(filename="immediate-access/nested.txt", content_type="faq")
    )
    payload = _json(response)

    assert payload["success"] is True
    assert payload["filename"] == "immediate-access/nested.txt"
    assert "QUESTION:" in payload["content"]
    assert payload["metadata"]["source_id"] == "nested_faq"


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.txt",
        "..\\escape.txt",
        "%2e%2e/escape.txt",
        "C:/temp/escape.txt",
    ],
)
def test_get_content_rejects_traversal_paths(admin_content_env, filename):
    response = asyncio.run(admin.get_content(filename=filename, content_type="faq"))
    payload = _json(response)

    assert response.status_code == 400
    assert payload["success"] is False


def test_save_content_creates_backup_then_reingests(admin_content_env, monkeypatch):
    calls = []
    monkeypatch.setattr(admin, "_run_ingestion", lambda: calls.append("ingest") or "rebuilt")
    path = admin_content_env["instruction_root"] / "platforms" / "cengage" / "edit.txt"
    path.parent.mkdir(parents=True)
    path.write_text(_valid_instruction_content("old_source"), encoding="utf-8")

    response = asyncio.run(
        admin.save_content(
            admin.ContentSaveRequest(
                filename="platforms/cengage/edit.txt",
                content_type="instruction",
                content=_valid_instruction_content("new_source"),
            )
        )
    )
    payload = _json(response)

    assert payload["success"] is True
    assert calls == ["ingest"]
    assert path.read_text(encoding="utf-8") == _valid_instruction_content("new_source")
    backup_path = Path(payload["backup_path"])
    assert backup_path.is_file()
    assert ARCHIVE_NAME_RE.match(backup_path.name)
    assert "old_source" in backup_path.read_text(encoding="utf-8")


def test_repeated_saves_create_distinct_backups_without_overwrite(admin_content_env, monkeypatch):
    calls = []
    monkeypatch.setattr(admin, "_run_ingestion", lambda: calls.append("ingest") or "rebuilt")
    path = admin_content_env["instruction_root"] / "platforms" / "cengage" / "edit.txt"
    path.parent.mkdir(parents=True)
    version_one = _valid_instruction_content("version_one")
    version_two = _valid_instruction_content("version_two")
    version_three = _valid_instruction_content("version_three")
    path.write_text(version_one, encoding="utf-8")

    first_response = asyncio.run(
        admin.save_content(
            admin.ContentSaveRequest(
                filename="platforms/cengage/edit.txt",
                content_type="instruction",
                content=version_two,
            )
        )
    )
    second_response = asyncio.run(
        admin.save_content(
            admin.ContentSaveRequest(
                filename="platforms/cengage/edit.txt",
                content_type="instruction",
                content=version_three,
            )
        )
    )
    first_payload = _json(first_response)
    second_payload = _json(second_response)
    first_backup = Path(first_payload["backup_path"])
    second_backup = Path(second_payload["backup_path"])

    assert first_payload["success"] is True
    assert second_payload["success"] is True
    assert calls == ["ingest", "ingest"]
    assert first_backup != second_backup
    assert first_backup.is_file()
    assert second_backup.is_file()
    assert ARCHIVE_NAME_RE.match(first_backup.name)
    assert ARCHIVE_NAME_RE.match(second_backup.name)
    assert first_backup.read_text(encoding="utf-8") == version_one
    assert second_backup.read_text(encoding="utf-8") == version_two
    assert path.read_text(encoding="utf-8") == version_three


def test_validate_content_rejects_malformed_front_matter(admin_content_env):
    response = asyncio.run(
        admin.validate_content(
            admin.ContentValidationRequest(
                content_type="faq",
                content="---\nsource_id ia_missing_colon\n---\nQUESTION:\nQ\nANSWER:\nA",
            )
        )
    )
    payload = _json(response)

    assert response.status_code == 400
    assert payload["success"] is False
    assert "Malformed YAML front matter" in payload["message"]


def test_validate_content_rejects_missing_required_metadata(admin_content_env):
    response = asyncio.run(
        admin.validate_content(
            admin.ContentValidationRequest(
                content_type="faq",
                content="""---
source_id: incomplete
source_type: faq
---

QUESTION:
Q

ANSWER:
A
""",
            )
        )
    )
    payload = _json(response)

    assert response.status_code == 400
    assert payload["success"] is False
    assert "Missing required front-matter field" in payload["message"]


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.txt",
        "..\\escape.txt",
        "%2e%2e/escape.txt",
        "C:/temp/escape.txt",
    ],
)
def test_save_content_rejects_traversal_paths(admin_content_env, filename):
    response = asyncio.run(
        admin.save_content(
            admin.ContentSaveRequest(
                filename=filename,
                content_type="faq",
                content=_valid_faq_content(),
            )
        )
    )
    payload = _json(response)

    assert response.status_code == 400
    assert payload["success"] is False


def test_remove_content_archives_file_instead_of_permanent_delete(admin_content_env):
    path = admin_content_env["instruction_root"] / "platforms" / "cengage" / "remove.txt"
    path.parent.mkdir(parents=True)
    path.write_text(_valid_instruction_content(), encoding="utf-8")

    response = asyncio.run(
        admin.remove_content(filename="platforms/cengage/remove.txt", content_type="instruction")
    )
    payload = _json(response)

    assert payload["success"] is True
    assert not path.exists()
    archive_path = Path(payload["archive_path"])
    assert archive_path.is_file()
    assert ARCHIVE_NAME_RE.match(archive_path.name)
    assert "nested_instruction" in archive_path.read_text(encoding="utf-8")


def test_repeated_removes_create_distinct_archives_without_overwrite(admin_content_env):
    path = admin_content_env["instruction_root"] / "platforms" / "cengage" / "remove.txt"
    path.parent.mkdir(parents=True)
    first_version = _valid_instruction_content("remove_version_one")
    second_version = _valid_instruction_content("remove_version_two")
    path.write_text(first_version, encoding="utf-8")

    first_response = asyncio.run(
        admin.remove_content(filename="platforms/cengage/remove.txt", content_type="instruction")
    )
    path.write_text(second_version, encoding="utf-8")
    second_response = asyncio.run(
        admin.remove_content(filename="platforms/cengage/remove.txt", content_type="instruction")
    )
    first_payload = _json(first_response)
    second_payload = _json(second_response)
    first_archive = Path(first_payload["archive_path"])
    second_archive = Path(second_payload["archive_path"])

    assert first_payload["success"] is True
    assert second_payload["success"] is True
    assert first_archive != second_archive
    assert first_archive.is_file()
    assert second_archive.is_file()
    assert ARCHIVE_NAME_RE.match(first_archive.name)
    assert ARCHIVE_NAME_RE.match(second_archive.name)
    assert first_archive.read_text(encoding="utf-8") == first_version
    assert second_archive.read_text(encoding="utf-8") == second_version
