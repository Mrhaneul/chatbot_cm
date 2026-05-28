"""
Chunk and document metadata helpers.

Lance stores chunk metadata in `[META:{...}]` headers inside generated chunk
files. Source `.txt` documents may also include optional YAML-style front
matter:

---
source_id: ia_overview
source_type: faq
category: immediate_access
platform: null
issue_type: overview
priority: canonical
---

Supported front-matter fields are intentionally simple and staff-editable:
source_id, source_type, category, platform, issue_type, and priority. The
parser accepts `key: value` lines only and converts `null` to Python None.
Files without front matter still receive fallback source_file, source_id, and
source_type metadata.
"""

from __future__ import annotations

import json
from pathlib import Path


FRONT_MATTER_DELIMITER = "---"


# Each schema maps field_name -> expected Python type.
# Add a field here whenever ingest.py embeds a new required key in [META:{...}].
INSTRUCTION_META_SCHEMA: dict = {
    # Legacy chunks store platform as a list of matched index keys, e.g. ["cengage"].
    # New front-matter-aware chunks may store a canonical string, e.g. "mcgraw_hill".
    "platform": (list, str, type(None)),
    "source_file": str,
    "section_title": str,
}

FAQ_META_SCHEMA: dict = {
    # Legacy FAQ chunks store "faq"; new front matter can use null for non-platform docs.
    "platform": (str, type(None)),
    "source_file": str,
    "faq_id": str,
}


def _expected_type_name(expected_type) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(t.__name__ for t in expected_type)
    return expected_type.__name__


def _parse_front_matter_value(raw_value: str):
    value = raw_value.strip()
    if value.lower() in {"null", "none", "~"}:
        return None
    if (
        len(value) >= 2
        and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'"))
    ):
        return value[1:-1]
    return value


def parse_front_matter_text(text: str) -> tuple[dict, str]:
    """
    Parse optional YAML-style front matter from a source document.

    Returns `(metadata, body)`. If no front matter exists, metadata is empty and
    body is returned unchanged except for BOM removal. The returned body never
    includes the front-matter block.
    """
    cleaned = (text or "").replace("\ufeff", "")
    lines = cleaned.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        return {}, cleaned

    metadata: dict = {}
    body_start_idx = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONT_MATTER_DELIMITER:
            body_start_idx = idx + 1
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Invalid front-matter line: {line!r}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid empty front-matter key in line: {line!r}")
        metadata[key] = _parse_front_matter_value(raw_value)

    if body_start_idx is None:
        raise ValueError("Front matter starts with '---' but has no closing '---'")

    body = "\n".join(lines[body_start_idx:])
    return metadata, body


def infer_source_type(path: str | Path) -> str:
    """Infer source_type from the parent folder name."""
    parent = Path(path).parent.name.lower()
    if parent == "faqs":
        return "faq"
    if parent == "instructions":
        return "instruction"
    return "document"


def load_document_with_metadata(path: str | Path) -> tuple[dict, str]:
    """
    Load a source `.txt` file and return `(metadata, body_without_front_matter)`.

    Fallback metadata is always included:
    - source_file: filename with extension
    - source_id: filename stem
    - source_type: faq, instruction, or document based on folder
    """
    document_path = Path(path)
    raw_text = document_path.read_text(encoding="utf-8")
    front_matter, body = parse_front_matter_text(raw_text)
    metadata = {
        "source_file": document_path.name,
        "source_id": document_path.stem,
        "source_type": infer_source_type(document_path),
    }
    metadata.update(front_matter)
    return metadata, body.strip()


def validate_metadata(meta_dict: dict, schema: dict, context: str = "") -> None:
    """
    Assert that *meta_dict* contains every key in *schema* with the correct type.

    Extra metadata keys are allowed so source front matter can evolve without
    requiring a database migration or breaking old chunks.
    """
    for key, expected_type in schema.items():
        if key not in meta_dict:
            raise ValueError(
                f"Metadata missing required key '{key}' [{context}]. "
                f"Got keys: {list(meta_dict.keys())}"
            )
        if not isinstance(meta_dict[key], expected_type):
            raise ValueError(
                f"Metadata key '{key}' expected {_expected_type_name(expected_type)}, "
                f"got {type(meta_dict[key]).__name__} [{context}]."
            )


def build_and_validate(meta_dict: dict, schema: dict, context: str) -> str:
    """
    Serialize *meta_dict* to JSON, then immediately round-trip validate it.

    Guarantees that:
    1. The dict is JSON-serializable.
    2. The parsed-back dict satisfies *schema*.
    3. The string stored on disk will parse cleanly at retrieval time.
    """
    try:
        meta_str = json.dumps(meta_dict, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Failed to serialise metadata [{context}]: {exc}") from exc

    reparsed = json.loads(meta_str)
    validate_metadata(reparsed, schema, context)
    return meta_str


def parse_and_validate(meta_json: str, schema: dict, context: str) -> dict:
    """
    Parse a JSON string from a stored [META:{...}] header and validate it.

    Used by retriever.py when reading chunks back from disk.
    """
    try:
        meta = json.loads(meta_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Malformed [META:...] JSON in chunk '{context}': {exc}"
        ) from exc

    validate_metadata(meta, schema, context)
    return meta
