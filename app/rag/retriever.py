"""
RETRIEVER MODULE  –  Refactored v5
───────────────────────────────────────────────────────────────────────────────
Changes from v4
  • Metadata schema + validation imported from metadata.py — no longer coupled
    to ingest.py; circular-import risk eliminated.
  • Embedding model imported from model.py via get_model() — single instance
    shared across the whole process; no duplicate initialisation.

Previous changes:
  v4 — config.py centralises all paths/constants; metadata round-trip validated.
  v3 — Singleton retriever via @lru_cache; platforms.yaml-driven routing;
       Python logging throughout.
───────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import re
from pathlib import Path

import faiss
import numpy as np
import yaml

from .config import cfg
from .context_expansion import expand_retrieval_context
from .ingest import discover_txt_files
from .metadata import (
    INSTRUCTION_META_SCHEMA,
    FAQ_META_SCHEMA,
    load_document_with_metadata,
    parse_and_validate,
)
from .metadata_filtering import apply_metadata_preference, classify_query_metadata
from .model import get_model

log = logging.getLogger(__name__)


# ── Helper: load one FAISS index + chunk list safely ─────────────────────────

def _load_index(index_path: str, chunks_path: str, label: str):
    """Returns (faiss.Index, list[str]) or (None, []) if files are missing."""
    try:
        index = faiss.read_index(index_path)
        with open(chunks_path, "r", encoding="utf-8") as fh:
            chunks = [c for c in fh.read().split(cfg.CHUNK_SEPARATOR) if c.strip()]
        log.info("[OK] Loaded index '%s'  (%d chunks)", label, len(chunks))
        return index, chunks
    except Exception as exc:
        log.warning("[WARN] Index '%s' not found — will fall back to general: %s", label, exc)
        return None, []


# ── FAQRetriever ──────────────────────────────────────────────────────────────

class FAQRetriever:
    """
    Retrieves the most relevant chunk for a query.

    All FAISS indexes and chunk lists are loaded once at construction time
    and kept in memory.  Use get_retriever() to obtain the singleton instance.
    """

    def __init__(self):
        log.info("Initialising FAQRetriever ...")

        # FAQ index
        self.faq_index, self.faq_chunks = _load_index(
            cfg.FAQ_INDEX_PATH, cfg.FAQ_CHUNKS_PATH, "faqs"
        )

        # General instructions index
        self.instructions_index, self.instruction_chunks = _load_index(
            cfg.INSTRUCTIONS_INDEX_PATH, cfg.INSTRUCTIONS_CHUNKS_PATH, "instructions_general"
        )
        self._source_metadata = self._load_source_metadata()

        # Platform-specific indexes — built from platforms.yaml
        platforms = self._load_platforms()
        self._platform_indexes: dict = {}

        for p in platforms:
            key     = p["key"]
            api_key = key.upper()
            idx, chunks = _load_index(
                cfg.platform_index_path(key),
                cfg.platform_chunks_path(key),
                f"instructions_{key}",
            )
            self._platform_indexes[api_key] = {"index": idx, "chunks": chunks}

        loaded = sum(1 for v in self._platform_indexes.values() if v["index"] is not None)
        log.info("FAQRetriever ready — %d platform index(es) loaded.", loaded)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _load_platforms() -> list:
        with open(cfg.PLATFORMS_CONFIG, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)["platforms"]

    @staticmethod
    def _load_source_metadata() -> dict[str, dict]:
        """Load optional front-matter metadata from source txt files."""
        source_metadata: dict[str, dict] = {}
        for directory, generated_prefixes in (
            (cfg.FAQ_DIR, ("faqs_chunks",)),
            (cfg.INSTRUCTIONS_DIR, ("instructions_chunks",)),
        ):
            if not os.path.isdir(directory):
                continue
            root = Path(directory)
            for path in discover_txt_files(directory, generated_prefixes):
                source_file = path.relative_to(root).as_posix()
                try:
                    metadata, _ = load_document_with_metadata(path)
                except Exception as exc:
                    log.warning("Could not load source metadata for %s: %s", path, exc)
                    continue
                metadata["source_file"] = source_file
                source_metadata[source_file] = metadata
        return source_metadata

    def _select_collection(self, query: str) -> str:
        """Route to 'instructions' or 'faqs' based on query keywords."""
        query_metadata = classify_query_metadata(query)
        if query_metadata.category == "platform_access":
            return "instructions"
        if query_metadata.category in {
            "immediate_access",
            "textbook_return",
            "merchandise_return",
        }:
            return "faqs"

        normalized = query.lower()
        if any(kw in normalized for kw in cfg.INSTRUCTIONS_KEYWORDS):
            return "instructions"
        return "faqs"

    @staticmethod
    def _search(index, chunks: list, query_vector, k: int) -> list[tuple[str, float, int]]:
        """Run FAISS search; return up to k (chunk, score, index) tuples, best first."""
        scores, indices = index.search(query_vector, k)
        results = []
        for i in range(min(k, len(indices[0]))):
            idx = int(indices[0][i])
            if 0 <= idx < len(chunks):
                results.append((chunks[idx], float(scores[0][i]), idx))
        return results

    @staticmethod
    def _extract_article_link(chunk: str):
        match = re.search(r'Article link:\s*"?([^"\n]+)"?', chunk)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_metadata(chunk: str, source_id: str) -> dict:
        """
        Parse and validate the [META:{...}] header from a stored chunk.
        Schema is chosen by source_id prefix (FAQ_ vs INSTR_).
        Returns an empty dict if no header is present (legacy chunks).
        Raises ValueError if the JSON is malformed or fails schema validation.
        """
        match = re.match(r"^\[META:(\{.*?\})\]", chunk)
        if not match:
            log.warning("No [META:...] header in chunk '%s'.", source_id)
            return {}

        schema = (
            FAQ_META_SCHEMA
            if source_id.startswith("FAQ_")
            else INSTRUCTION_META_SCHEMA
        )
        return parse_and_validate(match.group(1), schema, context=source_id)

    # ── Public API ────────────────────────────────────────────────────────────

    def _extract_enriched_metadata(self, chunk: str, source_id: str) -> dict:
        metadata = self._extract_metadata(chunk, source_id)
        source_file = metadata.get("source_file")
        if source_file and source_file in self._source_metadata:
            return {**metadata, **self._source_metadata[source_file]}
        return metadata

    def _build_candidates(
        self,
        results: list[tuple[str, float, int]],
        source_prefix: str,
    ) -> list[dict]:
        candidates = []
        for chunk, score, idx in results:
            source_id = f"{source_prefix}_SOURCE_{idx}"
            candidates.append({
                "context": chunk,
                "score": score,
                "idx": idx,
                "source_id": source_id,
                "article_link": self._extract_article_link(chunk),
                "metadata": self._extract_enriched_metadata(chunk, source_id),
            })
        return candidates

    def retrieve(
        self,
        query: str,
        k: int = None,
        collection: str = "auto",
        platform: str = None,
    ) -> dict:
        """
        Retrieve the most relevant chunk for *query*.

        Args:
            query:      User's question.
            k:          Candidates to search (defaults to cfg.RETRIEVAL_TOP_K).
            collection: "faqs" | "instructions" | "auto"
            platform:   Upper-case platform key e.g. "CENGAGE", "MCGRAW", or None.

        Returns:
            {
                "context":      str,
                "score":        float,
                "source_id":    str,
                "article_link": str | None,
                "metadata":     dict,
            }
        """
        if k is None:
            k = cfg.RETRIEVAL_TOP_K

        selected = (
            self._select_collection(query)
            if collection == "auto"
            else collection
        )
        log.info("retrieve()  query=%r  collection=%s  platform=%s", query, selected, platform)
        query_metadata = classify_query_metadata(query)
        search_k = max(k, 10) if query_metadata.has_filters() else k

        query_vector = get_model().encode([query], normalize_embeddings=True)
        query_vector = np.array(query_vector).astype("float32")

        # ── Instructions path ─────────────────────────────────────────────────
        if selected == "instructions":
            # Ensure platform lookup is case-insensitive
            plat_key = platform.upper() if platform else ""
            plat_data   = self._platform_indexes.get(plat_key, {})
            plat_index  = plat_data.get("index")
            plat_chunks = plat_data.get("chunks", [])

            if platform and plat_index:
                index         = plat_index
                chunks        = plat_chunks
                source_prefix = f"INSTR_{plat_key}"
            else:
                if platform:
                    log.warning("No index for platform '%s' (looked for '%s') — using general index.", platform, plat_key)
                index         = self.instructions_index
                chunks        = self.instruction_chunks
                source_prefix = "INSTR_GENERAL"

            if index is None:
                raise RuntimeError("General instructions index is not loaded.")

            results = self._search(index, chunks, query_vector, search_k)
            candidates = self._build_candidates(results, source_prefix)
            candidates, query_metadata = apply_metadata_preference(query, candidates)
            if query_metadata.has_filters():
                log.info(
                    "hybrid retrieval query=%s candidates=%d winner=%s score_breakdown=%s",
                    query_metadata,
                    len(candidates),
                    candidates[0]["source_id"] if candidates else None,
                    candidates[0].get("score_breakdown") if candidates else None,
                )
            selected_candidates = candidates[:k]
            winner = selected_candidates[0]
            chunk = winner["context"]
            score = winner["score"]
            idx = winner["idx"]
            source_id = winner["source_id"]
            log.info("  -> %s  score=%.4f  chunk_idx=%d", source_prefix, score, idx)

            expansion = expand_retrieval_context(selected_candidates)
            return {
                "context":      expansion.context or chunk,
                "score":        score,
                "source_id":    source_id,
                "article_link": winner["article_link"],
                "metadata":     winner["metadata"],
                "parent_sources": expansion.parent_sources,
                "expanded_context_chars": expansion.expanded_context_chars,
                "context_truncated": expansion.truncated,
            }

        # ── FAQ path ──────────────────────────────────────────────────────────
        if self.faq_index is None:
            raise RuntimeError("FAQ index is not loaded.")

        results = self._search(self.faq_index, self.faq_chunks, query_vector, search_k)
        candidates = self._build_candidates(results, "FAQ")
        candidates, query_metadata = apply_metadata_preference(query, candidates)
        if query_metadata.has_filters():
            log.info(
                "hybrid retrieval query=%s candidates=%d winner=%s score_breakdown=%s",
                query_metadata,
                len(candidates),
                candidates[0]["source_id"] if candidates else None,
                candidates[0].get("score_breakdown") if candidates else None,
            )
        selected_candidates = candidates[:k]
        winner = selected_candidates[0]
        chunk = winner["context"]
        score = winner["score"]
        idx = winner["idx"]
        source_id = winner["source_id"]
        log.info("  -> FAQ  score=%.4f  chunk_idx=%d", score, idx)

        expansion = expand_retrieval_context(selected_candidates)
        return {
            "context":      expansion.context or chunk,
            "score":        score,
            "source_id":    source_id,
            "article_link": winner["article_link"],
            "metadata":     winner["metadata"],
            "parent_sources": expansion.parent_sources,
            "expanded_context_chars": expansion.expanded_context_chars,
            "context_truncated": expansion.truncated,
        }


# ── Singleton accessor ────────────────────────────────────────────────────────

_retriever_instance: FAQRetriever | None = None


def get_retriever(force_reload: bool = False) -> FAQRetriever:
    """
    Return the application-wide FAQRetriever instance.

    The instance is created once and reused across requests.  Pass
    ``force_reload=True`` to discard the cached instance and rebuild it from
    disk — use this after adding or removing content via the admin UI so the
    new FAISS index is picked up without restarting uvicorn.

    FastAPI usage:
        from app.rag.retriever import get_retriever, FAQRetriever
        from fastapi import Depends

        @app.post("/chat")
        async def chat(
            body: ChatRequest,
            retriever: FAQRetriever = Depends(get_retriever),
        ):
            result = retriever.retrieve(body.query, platform=body.platform)
    """
    global _retriever_instance
    if _retriever_instance is None or force_reload:
        log.info("get_retriever() — %s FAQRetriever instance.",
                 "reloading" if force_reload and _retriever_instance else "creating")
        _retriever_instance = FAQRetriever()
    return _retriever_instance
