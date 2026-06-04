from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

import app.admin as admin
from app.pdf_recommendations import get_retrieval_source_filename
import app.rag.ingest as ingest
from app.rag.metadata import load_document_with_metadata


class _FakeModel:
    def encode(self, chunks, normalize_embeddings=True):
        vectors = []
        for idx, _chunk in enumerate(chunks):
            vectors.append([1.0, float(idx + 1)])
        arr = np.array(vectors, dtype="float32")
        if normalize_embeddings:
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            arr = arr / norms
        return arr


class _TempCfg:
    CHUNK_SEPARATOR = "\n<<<CHUNK_SEPARATOR>>>\n"
    MAX_CHUNK_TOKENS = 400

    def __init__(self, data_root: Path):
        self.FAQ_DIR = str(data_root / "faqs")
        self.INSTRUCTIONS_DIR = str(data_root / "instructions")
        self.PLATFORMS_CONFIG = str(data_root / "platforms.yaml")

    @property
    def FAQ_INDEX_PATH(self) -> str:
        return str(Path(self.FAQ_DIR) / "faiss_index")

    @property
    def FAQ_CHUNKS_PATH(self) -> str:
        return str(Path(self.FAQ_DIR) / "faqs_chunks.txt")

    @property
    def INSTRUCTIONS_INDEX_PATH(self) -> str:
        return str(Path(self.INSTRUCTIONS_DIR) / "faiss_index")

    @property
    def INSTRUCTIONS_CHUNKS_PATH(self) -> str:
        return str(Path(self.INSTRUCTIONS_DIR) / "instructions_chunks.txt")

    def platform_index_path(self, platform_key: str) -> str:
        return str(Path(self.INSTRUCTIONS_DIR) / f"faiss_index_{platform_key}")

    def platform_chunks_path(self, platform_key: str) -> str:
        return str(Path(self.INSTRUCTIONS_DIR) / f"instructions_chunks_{platform_key}.txt")


def _write_platforms_yaml(path: Path) -> None:
    path.write_text(
        """
platforms:
  - key: cengage
    keywords:
      - cengage
      - mindtap
  - key: mcgraw
    keywords:
      - mcgraw
      - connect
""".lstrip(),
        encoding="utf-8",
    )


def _write_faq(path: Path, question: str = "Nested FAQ") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
source_id: {path.stem}
source_type: faq
category: immediate_access
platform: null
issue_type: overview
priority: canonical
---

[FAQ_1]
QUESTION:
{question}

ANSWER:
Use the documented nested FAQ answer.
""",
        encoding="utf-8",
    )


def _write_instruction(path: Path, platform: str = "cengage") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
source_id: {path.stem}
source_type: instruction
category: platform_access
platform: {platform}
issue_type: access
priority: canonical
---

PROBLEM:
Student cannot access {platform}.

STEP-BY-STEP RESOLUTION:
1. Open Blackboard.
2. Select the {platform} link.
""",
        encoding="utf-8",
    )


@pytest.fixture
def recursive_ingest_env(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    (data_root / "faqs").mkdir(parents=True)
    (data_root / "instructions").mkdir(parents=True)
    _write_platforms_yaml(data_root / "platforms.yaml")
    monkeypatch.setattr(ingest, "cfg", _TempCfg(data_root))
    monkeypatch.setattr(ingest, "get_model", lambda: _FakeModel())
    return data_root


def test_discover_txt_files_keeps_flat_order_and_finds_nested(recursive_ingest_env: Path):
    flat = recursive_ingest_env / "faqs" / "ia_overview.txt"
    nested = recursive_ingest_env / "faqs" / "immediate-access" / "ia_nested.txt"
    generated = recursive_ingest_env / "faqs" / "faqs_chunks.txt"
    _write_faq(flat, "Flat FAQ")
    _write_faq(nested, "Nested FAQ")
    generated.write_text("generated", encoding="utf-8")

    discovered = [
        path.relative_to(recursive_ingest_env / "faqs").as_posix()
        for path in ingest.discover_txt_files(recursive_ingest_env / "faqs", ("faqs_chunks",))
    ]

    assert discovered == ["ia_overview.txt", "immediate-access/ia_nested.txt"]


def test_ingest_faqs_embeds_flat_and_nested_files(recursive_ingest_env: Path):
    _write_faq(recursive_ingest_env / "faqs" / "ia_overview.txt", "Flat FAQ")
    _write_faq(
        recursive_ingest_env / "faqs" / "immediate-access" / "ia_nested.txt",
        "Nested FAQ",
    )

    chunks = ingest.ingest_faqs()
    chunks_text = "\n".join(chunks)

    assert len(chunks) == 2
    assert '"source_file": "ia_overview.txt"' in chunks_text
    assert '"source_file": "immediate-access/ia_nested.txt"' in chunks_text
    assert '"source_id": "ia_overview"' in chunks_text
    assert '"source_id": "ia_nested"' in chunks_text
    assert (recursive_ingest_env / "faqs" / "faiss_index").is_file()
    assert (recursive_ingest_env / "faqs" / "faqs_chunks.txt").is_file()


def test_ingest_instructions_embeds_nested_platform_files(recursive_ingest_env: Path):
    _write_instruction(
        recursive_ingest_env / "instructions" / "platforms" / "cengage" / "ia_cengage_nested.txt",
        "cengage",
    )

    chunks = ingest.ingest_instructions()
    chunks_text = "\n".join(chunks)

    assert len(chunks) == 1
    assert '"source_file": "platforms/cengage/ia_cengage_nested.txt"' in chunks_text
    assert '"source_id": "ia_cengage_nested"' in chunks_text
    assert (recursive_ingest_env / "instructions" / "faiss_index").is_file()
    assert (recursive_ingest_env / "instructions" / "faiss_index_cengage").is_file()
    platform_chunks = (
        recursive_ingest_env / "instructions" / "instructions_chunks_cengage.txt"
    ).read_text(encoding="utf-8")
    assert "platforms/cengage/ia_cengage_nested.txt" in platform_chunks


def test_nested_document_without_front_matter_keeps_filename_stem_source_id(tmp_path: Path):
    document = tmp_path / "data" / "instructions" / "platforms" / "plain_nested.txt"
    document.parent.mkdir(parents=True)
    document.write_text("PROBLEM:\nPlain\n\nRESOLUTION:\nPlain", encoding="utf-8")

    metadata, _body = load_document_with_metadata(document)

    assert metadata["source_file"] == "plain_nested.txt"
    assert metadata["source_id"] == "plain_nested"
    assert metadata["source_type"] == "instruction"


def test_admin_copy_list_and_remove_support_nested_relative_paths(tmp_path: Path, monkeypatch):
    faq_root = tmp_path / "faqs"
    instruction_root = tmp_path / "instructions"
    monkeypatch.setattr(admin, "FAQ_DIR", faq_root)
    monkeypatch.setattr(admin, "INSTRUCTIONS_DIR", instruction_root)
    monkeypatch.setattr(admin, "ARCHIVE_DIR", tmp_path / "_archive")
    monkeypatch.setattr(admin, "_run_ingestion", lambda: "Index rebuilt successfully.")
    monkeypatch.setattr("app.firebase_config.get_firestore_client", lambda: None)

    copied = admin._copy_txt(
        b"QUESTION:\nHow?\n\nANSWER:\nUse nested folders.",
        "nested_upload.txt",
        "instruction",
        "platforms/cengage",
    )

    assert copied == instruction_root / "platforms" / "cengage" / "nested_upload.txt"
    assert admin._list_txt_files(instruction_root) == [
        "platforms/cengage/nested_upload.txt"
    ]

    response = asyncio.run(
        async_remove_content("platforms/cengage/nested_upload.txt", "instruction")
    )
    payload = json.loads(response.body)

    assert payload["success"] is True
    assert not copied.exists()


async def async_remove_content(filename: str, content_type: str):
    return await admin.remove_content(filename=filename, content_type=content_type)


def test_admin_rejects_traversal_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(admin, "INSTRUCTIONS_DIR", tmp_path / "instructions")

    with pytest.raises(ValueError):
        admin._copy_txt(b"x", "escape.txt", "instruction", "../outside")


def test_pdf_lookup_prefers_flat_metadata_source_file():
    result = {
        "metadata": {"source_file": "ia_cengage_mindtap_access.txt"},
        "context": "[META:{\"source_file\": \"wrong.txt\"}]\nBody",
    }

    assert get_retrieval_source_filename(result) == "ia_cengage_mindtap_access.txt"


def test_pdf_lookup_prefers_nested_metadata_source_file():
    result = {
        "metadata": {"source_file": "platforms/cengage/foo.txt"},
        "context": "[META:{\"source_file\": \"wrong.txt\"}]\nBody",
    }

    assert get_retrieval_source_filename(result) == "platforms/cengage/foo.txt"


def test_pdf_lookup_falls_back_to_context_meta_when_metadata_missing():
    result = {
        "context": "[META:{\"source_file\": \"ia_zybooks_access.txt\"}]\nBody",
    }

    assert get_retrieval_source_filename(result) == "ia_zybooks_access.txt"


def test_pdf_lookup_falls_back_to_legacy_file_marker_when_metadata_missing():
    result = {
        "context": "[SOURCE_0]\n[FILE:ia_mcgraw_access.txt]\nBody",
    }

    assert get_retrieval_source_filename(result) == "ia_mcgraw_access.txt"


def test_pdf_lookup_works_with_expanded_parent_context_and_metadata_source_file():
    result = {
        "metadata": {"source_file": "platforms/cengage/foo.txt"},
        "context": "[PARENT_SOURCE:data/instructions/platforms/cengage/foo.txt]\nExpanded body",
    }

    assert get_retrieval_source_filename(result) == "platforms/cengage/foo.txt"
