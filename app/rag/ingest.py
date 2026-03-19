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
import time # Added this line
from pathlib import Path

import faiss
import numpy as np
import yaml

from .config import cfg
from .metadata import (
    INSTRUCTION_META_SCHEMA,
    FAQ_META_SCHEMA,
    build_and_validate,
)
from .model import get_model

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

# Matches horizontal rule separators between distinct instruction scenarios
_SCENARIO_SEPARATOR_RE = re.compile(r"\n[ \t]*---+[ \t]*\n", re.MULTILINE)

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
    """
    Split instruction file on '---' scenario boundaries, keeping each complete
    scenario (PROBLEM + RESOLUTION + all related sections) as one chunk.

    Previously the file was split on every ALL-CAPS header, which fragmented
    PROBLEM and STEP-BY-STEP RESOLUTION into separate vectors. Top-1 retrieval
    then returned only the PROBLEM chunk, omitting actionable resolution steps.

    Now each '---'-delimited block is one embeddable unit. Secondary splitting
    is applied only if a single scenario exceeds MAX_CHUNK_TOKENS.
    """
    scenarios = [s.strip() for s in _SCENARIO_SEPARATOR_RE.split(text) if s.strip()]

    if not scenarios:
        return _secondary_split(text.strip(), "FULL_DOCUMENT", file_name)

    chunks = []
    for i, scenario in enumerate(scenarios):
        title = f"SCENARIO_{i + 1}" if len(scenarios) > 1 else "FULL_DOCUMENT"
        chunks.extend(_secondary_split(scenario, title, file_name))
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


def _compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _content_keyword_regex(keyword: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])")


def _match_platforms_for_file(file_name: str, text: str, platforms: list[dict]) -> list[str]:
    """
    Assign a file to platform-specific indexes conservatively.

    Priority:
      1. Filename matches win outright because filenames are curated.
      2. Content matches use word/phrase boundaries only.
      3. Ambiguous multi-platform content matches fall back to general indexing.
    """
    filename_compact = _compact_text(Path(file_name).stem)
    filename_matches: list[str] = []

    for platform in platforms:
        for keyword in platform["keywords"]:
            keyword_compact = _compact_text(keyword)
            if keyword_compact and keyword_compact in filename_compact:
                filename_matches.append(platform["key"])
                break

    if filename_matches:
        return sorted(set(filename_matches))

    content_matches: list[str] = []
    lowered_text = text.lower()
    for platform in platforms:
        for keyword in platform["keywords"]:
            if _content_keyword_regex(keyword).search(lowered_text):
                content_matches.append(platform["key"])
                break

    unique_content_matches = sorted(set(content_matches))
    if len(unique_content_matches) == 1:
        return unique_content_matches

    if len(unique_content_matches) > 1:
        log.warning(
            "Ambiguous content-only platform match for %s -> %s. Indexing as general only.",
            file_name,
            ", ".join(unique_content_matches),
        )

    return []


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

        matched_platforms = _match_platforms_for_file(file_name, text, platforms)

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
            # Body already contains all section headers (PROBLEM:, STEP-BY-STEP
            # RESOLUTION:, etc.) — do not prepend section_title again.
            chunk_text = f"[META:{meta_str}]\n{rc['body']}"
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
    from app.utils.logging_config import configure_logging
    configure_logging() # Ensure logging is configured for CLI execution

    log.info("=== Running Ingestion Pipeline ===")
    
    start_time = time.time() # Add this line to measure execution time

    faq_chunks_count = len(ingest_faqs())
    instruction_chunks_count = len(ingest_instructions())

    end_time = time.time() # Add this line to measure execution time
    duration = end_time - start_time # Add this line

    log.info(f"Ingestion pipeline complete in {duration:.2f} seconds.") # Modify this line
    print(f"\n--- Ingestion Summary ---")
    print(f"  Processed {faq_chunks_count} FAQ chunks.")
    print(f"  Processed {instruction_chunks_count} instruction chunks.")
    print(f"  Total execution time: {duration:.2f} seconds.")
    print(f"--- Remember to restart the FastAPI app for changes to take effect. ---")
