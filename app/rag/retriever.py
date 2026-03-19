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
import re

import faiss
import numpy as np
import yaml

from .config import cfg
from .metadata import (
    INSTRUCTION_META_SCHEMA,
    FAQ_META_SCHEMA,
    parse_and_validate,
)
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

    def _select_collection(self, query: str) -> str:
        """Route to 'instructions' or 'faqs' based on query keywords."""
        normalized = query.lower()
        if any(kw in normalized for kw in cfg.INSTRUCTIONS_KEYWORDS):
            return "instructions"
        return "faqs"

    @staticmethod
    def _search(index, chunks: list, query_vector, k: int):
        """Run FAISS search; return (best_chunk, best_score, best_index)."""
        scores, indices = index.search(query_vector, k)
        best_idx   = int(indices[0][0])
        best_score = float(scores[0][0])
        return chunks[best_idx], best_score, best_idx

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

            chunk, score, idx = self._search(index, chunks, query_vector, k)
            source_id = f"{source_prefix}_SOURCE_{idx}"
            log.info("  -> %s  score=%.4f  chunk_idx=%d", source_prefix, score, idx)

            return {
                "context":      chunk,
                "score":        score,
                "source_id":    source_id,
                "article_link": self._extract_article_link(chunk),
                "metadata":     self._extract_metadata(chunk, source_id),
            }

        # ── FAQ path ──────────────────────────────────────────────────────────
        if self.faq_index is None:
            raise RuntimeError("FAQ index is not loaded.")

        chunk, score, idx = self._search(self.faq_index, self.faq_chunks, query_vector, k)
        source_id = f"FAQ_SOURCE_{idx}"
        log.info("  -> FAQ  score=%.4f  chunk_idx=%d", score, idx)

        return {
            "context":      chunk,
            "score":        score,
            "source_id":    source_id,
            "article_link": self._extract_article_link(chunk),
            "metadata":     self._extract_metadata(chunk, source_id),
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