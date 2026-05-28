from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .config import cfg
from .metadata import load_document_with_metadata


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextExpansionResult:
    context: str
    parent_sources: list[dict]
    expanded_context_chars: int
    truncated: bool


def resolve_parent_source_path(metadata: dict) -> Path | None:
    source_file = metadata.get("source_file")
    if not source_file:
        return None

    source_type = metadata.get("source_type")
    candidate_dirs: list[str] = []
    if source_type == "faq":
        candidate_dirs.append(cfg.FAQ_DIR)
    elif source_type == "instruction":
        candidate_dirs.append(cfg.INSTRUCTIONS_DIR)
    candidate_dirs.extend([cfg.FAQ_DIR, cfg.INSTRUCTIONS_DIR])

    seen_dirs: set[str] = set()
    for directory in candidate_dirs:
        if directory in seen_dirs:
            continue
        seen_dirs.add(directory)
        path = Path(directory) / source_file
        if path.is_file():
            return path
    return None


def _fallback_context(candidate: dict) -> str:
    return str(candidate.get("context") or "").strip()


def _truncate_context(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    marker = "\n\n[Context truncated due to MAX_EXPANDED_CONTEXT_CHARS]\n"
    if max_chars <= len(marker):
        return text[:max_chars], True
    return text[: max_chars - len(marker)].rstrip() + marker, True


def expand_retrieval_context(
    candidates: list[dict],
    *,
    max_parent_sources: int | None = None,
    max_chars: int | None = None,
) -> ContextExpansionResult:
    """
    Expand selected retrieval chunks to their parent source documents.

    FAISS still selects chunks. This helper expands only after selection so the
    LLM receives complete policy/procedure context. It deduplicates repeated
    source_file values and falls back to the original chunk if the source file
    cannot be resolved.
    """
    max_parent_sources = cfg.MAX_PARENT_SOURCES if max_parent_sources is None else max_parent_sources
    max_chars = cfg.MAX_EXPANDED_CONTEXT_CHARS if max_chars is None else max_chars

    context_parts: list[str] = []
    parent_sources: list[dict] = []
    seen_keys: set[str] = set()

    for candidate in candidates:
        if len(parent_sources) >= max_parent_sources:
            break

        metadata = candidate.get("metadata", {}) or {}
        source_file = metadata.get("source_file")
        dedupe_key = str(source_file or candidate.get("source_id") or id(candidate))
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        source_path = resolve_parent_source_path(metadata)
        expanded = False
        if source_path is not None:
            try:
                _, body = load_document_with_metadata(source_path)
                context_text = body.strip()
                expanded = True
            except Exception as exc:
                log.warning("Failed to expand parent context for %s: %s", source_path, exc)
                context_text = _fallback_context(candidate)
        else:
            context_text = _fallback_context(candidate)

        parent_source = {
            "source_file": source_file,
            "source_path": os.fspath(source_path) if source_path else None,
            "expanded": expanded,
            "source_id": candidate.get("source_id"),
            "score": candidate.get("combined_score", candidate.get("score")),
        }
        parent_sources.append(parent_source)

        if expanded and source_path is not None:
            header = f"[PARENT_SOURCE:{source_path.as_posix()}]"
        else:
            header = f"[SELECTED_CHUNK:{candidate.get('source_id', 'unknown')}]"
        context_parts.append(f"{header}\n{context_text}")

    expanded_context = "\n\n---\n\n".join(part for part in context_parts if part.strip())
    expanded_context, truncated = _truncate_context(expanded_context, max_chars)
    log.info(
        "context expansion parent_sources=%d chars=%d truncated=%s sources=%s",
        len(parent_sources),
        len(expanded_context),
        truncated,
        [source.get("source_path") or source.get("source_file") for source in parent_sources],
    )

    return ContextExpansionResult(
        context=expanded_context,
        parent_sources=parent_sources,
        expanded_context_chars=len(expanded_context),
        truncated=truncated,
    )
