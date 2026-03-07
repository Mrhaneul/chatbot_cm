"""
model.py  –  Shared embedding model singleton
───────────────────────────────────────────────────────────────────────────────
Owns the one SentenceTransformer instance for the entire process.

Both ingest.py and retriever.py import _MODEL from here, so the model is
loaded exactly once regardless of import order — no duplicate initialisation,
no wasted RAM, no extra startup latency.

    from model import get_model

    embeddings = get_model().encode(texts, normalize_embeddings=True)
───────────────────────────────────────────────────────────────────────────────
"""

import logging

from sentence_transformers import SentenceTransformer

from .config import cfg

log = logging.getLogger(__name__)


def _load_model() -> SentenceTransformer:
    log.info("Loading embedding model '%s' ...", cfg.EMBEDDING_MODEL)
    model = SentenceTransformer(cfg.EMBEDDING_MODEL)
    log.info("Embedding model ready.")
    return model


# Module-level singleton — loaded once on first import.
_MODEL: SentenceTransformer = _load_model()


def get_model() -> SentenceTransformer:
    """
    Return the shared SentenceTransformer instance.

    Prefer calling get_model() over importing _MODEL directly so that
    future changes (e.g. swapping to a different model mid-session) only
    need to update this module.
    """
    return _MODEL