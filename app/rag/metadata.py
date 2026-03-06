"""
metadata.py  –  Chunk metadata schemas and validation
───────────────────────────────────────────────────────────────────────────────
Extracted from ingest.py so that both ingest.py and retriever.py can import
validation logic without creating a circular dependency between them.

This module has zero imports from the rest of the Lance codebase — it depends
only on the Python standard library, so it can be imported anywhere safely.
───────────────────────────────────────────────────────────────────────────────
"""

import json


# ── Schemas ───────────────────────────────────────────────────────────────────
# Each schema maps field_name -> expected Python type.
# Add a field here whenever ingest.py embeds a new key in [META:{...}].

INSTRUCTION_META_SCHEMA: dict = {
    "platform":      list,   # list of matched platform keys, e.g. ["cengage"]
    "source_file":   str,    # original filename, e.g. "ia_cengage_mindtap_access.txt"
    "section_title": str,    # all-caps header, e.g. "STEP-BY-STEP RESOLUTION"
}

FAQ_META_SCHEMA: dict = {
    "platform":    str,   # always "faq"
    "source_file": str,   # original filename
    "faq_id":      str,   # e.g. "FAQ_3" or "FAQ_3 [part 1/2]"
}


# ── Validation ────────────────────────────────────────────────────────────────

def validate_metadata(meta_dict: dict, schema: dict, context: str = "") -> None:
    """
    Assert that *meta_dict* contains every key in *schema* with the correct type.

    Args:
        meta_dict: Parsed metadata dict to check.
        schema:    Mapping of field_name -> expected_type.
        context:   Human-readable label included in error messages
                   (e.g. "ia_cengage_mindtap_access.txt / STEP-BY-STEP RESOLUTION").

    Raises:
        ValueError: with a descriptive message on the first failing field.
    """
    for key, expected_type in schema.items():
        if key not in meta_dict:
            raise ValueError(
                f"Metadata missing required key '{key}' [{context}]. "
                f"Got keys: {list(meta_dict.keys())}"
            )
        if not isinstance(meta_dict[key], expected_type):
            raise ValueError(
                f"Metadata key '{key}' expected {expected_type.__name__}, "
                f"got {type(meta_dict[key]).__name__} [{context}]."
            )


def build_and_validate(meta_dict: dict, schema: dict, context: str) -> str:
    """
    Serialise *meta_dict* to JSON, then immediately round-trip validate it.

    Guarantees that:
      1. The dict is JSON-serialisable.
      2. The parsed-back dict satisfies *schema*.
      3. The string stored on disk will parse cleanly at retrieval time.

    Args:
        meta_dict: Metadata to serialise.
        schema:    Expected schema (INSTRUCTION_META_SCHEMA or FAQ_META_SCHEMA).
        context:   Label for error messages.

    Returns:
        Validated JSON string ready to embed in a [META:{...}] header.

    Raises:
        ValueError: on serialisation failure or schema mismatch.
    """
    try:
        meta_str = json.dumps(meta_dict, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Failed to serialise metadata [{context}]: {exc}"
        ) from exc

    reparsed = json.loads(meta_str)
    validate_metadata(reparsed, schema, context)
    return meta_str


def parse_and_validate(meta_json: str, schema: dict, context: str) -> dict:
    """
    Parse a JSON string from a stored [META:{...}] header and validate it.

    Used by retriever.py when reading chunks back from disk.

    Args:
        meta_json: Raw JSON string extracted from the chunk header.
        schema:    Expected schema.
        context:   Label for error messages (typically the source_id).

    Returns:
        Validated metadata dict.

    Raises:
        ValueError: on JSON parse failure or schema mismatch.
    """
    try:
        meta = json.loads(meta_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Malformed [META:...] JSON in chunk '{context}': {exc}"
        ) from exc

    validate_metadata(meta, schema, context)
    return meta