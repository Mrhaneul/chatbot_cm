"""
INGEST MODULE  –  Refactored v5
───────────────────────────────────────────────────────────────────────────────
Changes from v4
  • Metadata schema + validation moved to metadata.py — no more circular-import
    risk; retriever.py can import from metadata.py directly.
  • Embedding model moved to model.py — ingest.py and retriever.py now share
    a single SentenceTransformer instance via model.get_model().

Previous changes:
  v4 — config.py centralises all paths/constants; metadata round-trip validated.
  v3 — Secondary chunk split (MAX_CHUNK_TOKENS), embedded [META:{...}] headers,
       platforms.yaml-driven platform detection, Python logging.
───────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import re

import faiss
import numpy as np
import yaml

from config import cfg
from metadata import (
    INSTRUCTION_META_SCHEMA,
    FAQ_META_SCHEMA,
    build_and_validate,
)
from model import get_model

log = logging.getLogger(__name__)


# ── Platform config loader ────────────────────────────────────────────────────

def _load_platforms() -> list:
    """Return platform list from platforms.yaml (path from cfg)."""
    if not os.path.exists(cfg.PLATFORMS_CONFIG):
        raise FileNotFoundError(
            f"platforms.yaml not found at '{cfg.PLATFORMS_CONFIG}'. "
            "Please create it before running ingestion."
        )
    with open(cfg.PLATFORMS_CONFIG, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["platforms"]


# ── Chunking helpers ──────────────────────────────────────────────────────────

# Matches all-caps section headers like "PROBLEM:", "STEP-BY-STEP RESOLUTION:"
_INSTRUCTION_HEADER_RE = re.compile(r"^([A-Z][A-Z\s\-/]+):\s*$", re.MULTILINE)

# Matches FAQ bracket markers like "[FAQ_1]", "[FAQ_12]"
_FAQ_MARKER_RE = re.compile(r"^\[FAQ_\d+\]", re.MULTILINE)


def _approx_tokens(text: str) -> int:
    """Fast word-piece approximation: 1 token ~= 0.75 words."""
    return int(len(text.split()) / 0.75)


def _secondary_split(body: str, section_title: str, source_file: str) -> list:
    """
    If *body* exceeds cfg.MAX_CHUNK_TOKENS, split further on blank lines.
    Each sub-chunk inherits the parent title with a "[part N/total]" suffix.
    Returns a list of chunk dicts — always at least one entry.
    """
    if _approx_tokens(body) <= cfg.MAX_CHUNK_TOKENS:
        return [{"section_title": section_title, "body": body, "source_file": source_file}]

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]

    windows = []
    current_parts = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _approx_tokens(para)
        if current_parts and current_tokens + para_tokens > cfg.MAX_CHUNK_TOKENS:
            windows.append("\n\n".join(current_parts))
            current_parts  = [para]
            current_tokens = para_tokens
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        windows.append("\n\n".join(current_parts))

    total = len(windows)
    if total == 1:
        log.warning(
            "Section '%s' in '%s' is oversized (%d tokens) but cannot be split further.",
            section_title, source_file, _approx_tokens(body),
        )
        return [{"section_title": section_title, "body": body, "source_file": source_file}]

    log.info(
        "  Secondary split: '%s' -> %d sub-chunks (%d tokens total)",
        section_title, total, _approx_tokens(body),
    )
    return [
        {
            "section_title": f"{section_title} [part {i + 1}/{total}]",
            "body":          window,
            "source_file":   source_file,
        }
        for i, window in enumerate(windows)
    ]


def _split_instruction_file(text: str, file_name: str) -> list:
    """Split instruction file on all-caps headers, then apply secondary split."""
    matches = list(_INSTRUCTION_HEADER_RE.finditer(text))

    if not matches:
        return _secondary_split(text.strip(), "FULL_DOCUMENT", file_name)

    chunks = []
    for idx, match in enumerate(matches):
        section_title = match.group(1).strip()
        start = match.end()
        end   = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body  = text[start:end].strip()
        if body:
            chunks.extend(_secondary_split(body, section_title, file_name))
    return chunks


def _split_faq_file(text: str, file_name: str) -> list:
    """Split FAQ file on [FAQ_N] markers, then apply secondary split."""
    matches = list(_FAQ_MARKER_RE.finditer(text))

    if not matches:
        return _secondary_split(text.strip(), "FAQ_FULL", file_name)

    chunks = []
    for idx, match in enumerate(matches):
        faq_id = match.group(0).strip("[]")
        start  = match.end()
        end    = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if not body:
            continue
        for sc in _secondary_split(body, faq_id, file_name):
            chunks.append({
                "faq_id":      sc["section_title"],
                "body":        sc["body"],
                "source_file": sc["source_file"],
            })
    return chunks


# ── FAISS index builder ───────────────────────────────────────────────────────

def _build_and_save_index(chunks: list, index_path: str, chunks_path: str, label: str):
    """Embed *chunks*, build IndexFlatIP, persist both to disk."""
    if not chunks:
        log.warning("No chunks to index for '%s' — skipping.", label)
        return

    log.info("  Embedding %d chunks for '%s' ...", len(chunks), label)
    embeddings = get_model().encode(chunks, normalize_embeddings=True)

    if not isinstance(embeddings, np.ndarray):
        embeddings = np.array(embeddings)

    if embeddings.ndim != 2:
        raise ValueError(f"Unexpected embeddings shape {embeddings.shape} for '{label}'")

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings.astype("float32"))
    faiss.write_index(index, index_path)

    with open(chunks_path, "w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(chunk + cfg.CHUNK_SEPARATOR)

    log.info("  Saved index '%s'  (%d vectors, dim=%d)", label, len(chunks), embeddings.shape[1])


# ── FAQ ingestion ─────────────────────────────────────────────────────────────

def ingest_faqs():
    """
    Ingest FAQ documents into a FAISS index.
    Each [FAQ_N] entry (or secondary sub-chunk) becomes its own vector.
    """
    log.info("=== Ingesting FAQs ===")

    if not os.path.exists(cfg.FAQ_DIR):
        raise FileNotFoundError(f"FAQ directory not found: '{cfg.FAQ_DIR}'")

    file_names = sorted(
        f for f in os.listdir(cfg.FAQ_DIR)
        if f.lower().endswith(".txt") and not f.startswith("faqs_chunks")
    )
    log.info("Found %d FAQ file(s) in %s", len(file_names), cfg.FAQ_DIR)

    all_chunks = []

    for file_name in file_names:
        file_path = os.path.join(cfg.FAQ_DIR, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
        except Exception:
            log.exception("Failed to read %s", file_path)
            continue

        if not text:
            log.warning("Skipped empty file: %s", file_name)
            continue

        raw_chunks = _split_faq_file(text, file_name)
        log.info("  %s  ->  %d FAQ chunk(s)", file_name, len(raw_chunks))

        for rc in raw_chunks:
            context    = f"{file_name} / {rc.get('faq_id', '')}"
            meta_dict  = {
                "platform":    "faq",
                "source_file": rc["source_file"],
                "faq_id":      rc.get("faq_id", ""),
            }
            meta_str   = build_and_validate(meta_dict, FAQ_META_SCHEMA, context)
            chunk_text = f"[META:{meta_str}]\n{rc['body']}"
            all_chunks.append(chunk_text)

    _build_and_save_index(all_chunks, cfg.FAQ_INDEX_PATH, cfg.FAQ_CHUNKS_PATH, "FAQs")
    log.info("=== FAQ ingestion complete: %d total chunks ===\n", len(all_chunks))
    return all_chunks


# ── Instruction ingestion ─────────────────────────────────────────────────────

def ingest_instructions():
    """
    Ingest instruction documents and build a general index plus one
    platform-specific index per entry in platforms.yaml.
    """
    log.info("=== Ingesting Instructions ===")

    if not os.path.exists(cfg.INSTRUCTIONS_DIR):
        raise FileNotFoundError(f"Instructions directory not found: '{cfg.INSTRUCTIONS_DIR}'")

    platforms = _load_platforms()

    keyword_to_platform: dict = {}
    for p in platforms:
        for kw in p["keywords"]:
            keyword_to_platform[kw.lower()] = p["key"]

    file_names = sorted(
        f for f in os.listdir(cfg.INSTRUCTIONS_DIR)
        if f.lower().endswith(".txt") and not f.startswith("instructions_chunks")
    )
    log.info("Found %d instruction file(s) in %s", len(file_names), cfg.INSTRUCTIONS_DIR)

    all_chunks: list = []
    platform_chunks: dict = {p["key"]: [] for p in platforms}

    for file_name in file_names:
        file_path = os.path.join(cfg.INSTRUCTIONS_DIR, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
        except Exception:
            log.exception("Failed to read %s", file_path)
            continue

        if not text:
            log.warning("Skipped empty file: %s", file_name)
            continue

        combined = (text + " " + file_name).lower()
        matched_platforms = {
            plat_key
            for kw, plat_key in keyword_to_platform.items()
            if kw in combined
        }

        raw_chunks = _split_instruction_file(text, file_name)
        log.info("  %s  ->  %d section chunk(s)  [platforms: %s]",
                 file_name, len(raw_chunks),
                 ", ".join(matched_platforms) if matched_platforms else "general")

        for rc in raw_chunks:
            context   = f"{file_name} / {rc.get('section_title', '')}"
            meta_dict = {
                "platform":      list(matched_platforms) if matched_platforms else ["general"],
                "source_file":   rc["source_file"],
                "section_title": rc.get("section_title", ""),
            }
            meta_str   = build_and_validate(meta_dict, INSTRUCTION_META_SCHEMA, context)
            chunk_text = (
                f"[META:{meta_str}]\n"
                f"{rc['section_title']}:\n"
                f"{rc['body']}"
            )
            all_chunks.append(chunk_text)

            for plat_key in matched_platforms:
                if plat_key in platform_chunks:
                    platform_chunks[plat_key].append(chunk_text)

    # General index
    _build_and_save_index(
        all_chunks,
        cfg.INSTRUCTIONS_INDEX_PATH,
        cfg.INSTRUCTIONS_CHUNKS_PATH,
        "instructions_general",
    )

    # Platform-specific indices
    log.info("\nBuilding platform-specific indices ...")
    for p in platforms:
        key    = p["key"]
        chunks = platform_chunks[key]
        if chunks:
            _build_and_save_index(
                chunks,
                cfg.platform_index_path(key),
                cfg.platform_chunks_path(key),
                f"instructions_{key}",
            )
        else:
            log.warning("  No chunks found for platform '%s' — index skipped.", key)

    log.info("\n=== Instruction ingestion complete: %d total chunks ===", len(all_chunks))
    for p in platforms:
        count = len(platform_chunks[p["key"]])
        if count:
            log.info("  %-15s %d chunk(s)", p["key"], count)

    return all_chunks


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=== Running Ingestion Pipeline ===")
    ingest_faqs()
    ingest_instructions()
    log.info("=== Ingestion pipeline complete ===")