"""
Shared embedding model singleton.

The embedding model is loaded lazily so importing modules that depend on
retrieval does not trigger an immediate Hugging Face network call during test
collection or app startup. When possible, the loader prefers an existing local
cache first and only falls back to the default SentenceTransformer resolution
path if the local cache is unavailable.
"""

import logging
from typing import Optional

from sentence_transformers import SentenceTransformer

from .config import cfg

log = logging.getLogger(__name__)

_MODEL: Optional[SentenceTransformer] = None


def _load_model() -> SentenceTransformer:
    log.info("Loading embedding model '%s' from local cache if available...", cfg.EMBEDDING_MODEL)
    try:
        model = SentenceTransformer(cfg.EMBEDDING_MODEL, local_files_only=True)
        log.info("Embedding model ready from local cache.")
        return model
    except Exception as exc:
        log.warning("Local cached embedding model unavailable, falling back to default load: %s", exc)

    log.info("Loading embedding model '%s' via default SentenceTransformer resolution...", cfg.EMBEDDING_MODEL)
    model = SentenceTransformer(cfg.EMBEDDING_MODEL)
    log.info("Embedding model ready.")
    return model


def get_model() -> SentenceTransformer:
    """Return the shared SentenceTransformer instance."""
    global _MODEL
    if _MODEL is None:
        _MODEL = _load_model()
    return _MODEL
