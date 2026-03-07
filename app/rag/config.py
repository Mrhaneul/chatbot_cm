"""
config.py  –  Lance RAG configuration
───────────────────────────────────────────────────────────────────────────────
Single source of truth for every path, constant, and tunable parameter used
across ingest.py and retriever.py.

All values can be overridden at runtime via environment variables, which makes
Docker / different deployment targets trivial — no code edits needed.

Usage:
    from config import cfg

    print(cfg.FAQ_DIR)           # "data/faqs"  (or $FAQ_DIR if set)
    print(cfg.MAX_CHUNK_TOKENS)  # 400          (or $MAX_CHUNK_TOKENS if set)
───────────────────────────────────────────────────────────────────────────────
"""

import os
from dataclasses import dataclass, field

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

@dataclass(frozen=True)
class Config:
    """
    Immutable configuration object.  All fields read from environment
    variables with sensible defaults for local development.

    frozen=True means accidental mutation raises an AttributeError —
    safer than a plain module-level dict or mutable class.
    """

    # ── Directory paths ───────────────────────────────────────────────────────
    FAQ_DIR:          str = field(default_factory=lambda: os.getenv("FAQ_DIR",          "data/faqs"))
    INSTRUCTIONS_DIR: str = field(default_factory=lambda: os.getenv("INSTRUCTIONS_DIR", "data/instructions"))
    PLATFORMS_CONFIG: str = field(default_factory=lambda: os.getenv("PLATFORMS_CONFIG", os.path.join(_CURRENT_DIR, "platforms.yaml")))

    # ── Derived index / chunk paths  (computed as properties below) ───────────
    # These are not fields so they stay in sync with FAQ_DIR / INSTRUCTIONS_DIR
    # automatically.

    # ── Chunking ──────────────────────────────────────────────────────────────
    # all-MiniLM-L6-v2 has a 256 word-piece hard limit.  400 tokens (~300 words)
    # is a safe ceiling that guarantees no tail truncation during embedding.
    MAX_CHUNK_TOKENS: int = field(
        default_factory=lambda: int(os.getenv("MAX_CHUNK_TOKENS", "400"))
    )

    # ── Retrieval ─────────────────────────────────────────────────────────────
    # Number of chunks returned per query.  Currently only top-1 is used by
    # the LLM prompt, but raising this enables multi-chunk context in future.
    RETRIEVAL_TOP_K: int = field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_TOP_K", "1"))
    )

    # ── Embedding model ───────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )

    # ── Internal separator written between chunks on disk ────────────────────
    CHUNK_SEPARATOR: str = "\n<<<CHUNK_SEPARATOR>>>\n"

    # ── Instruction-collection routing keywords ───────────────────────────────
    # A query matching any of these is routed to the instructions index instead
    # of the FAQ index.  Add new triggers here without touching retriever.py.
    INSTRUCTIONS_KEYWORDS: frozenset = field(default_factory=lambda: frozenset({
        "how do i",
        "step by step",
        "steps",
        "log in to",
        "where do i find",
        "can't access",
        "cannot access",
        "unable to access",
        "trouble accessing",
        "access issue",
        "access problem",
        "not working",
        "doesn't work",
    }))

    # ── Derived path helpers ──────────────────────────────────────────────────
    # Using properties keeps derived paths in sync with base dirs automatically.

    @property
    def FAQ_INDEX_PATH(self) -> str:
        return os.path.join(self.FAQ_DIR, "faiss_index")

    @property
    def FAQ_CHUNKS_PATH(self) -> str:
        return os.path.join(self.FAQ_DIR, "faqs_chunks.txt")

    @property
    def INSTRUCTIONS_INDEX_PATH(self) -> str:
        return os.path.join(self.INSTRUCTIONS_DIR, "faiss_index")

    @property
    def INSTRUCTIONS_CHUNKS_PATH(self) -> str:
        return os.path.join(self.INSTRUCTIONS_DIR, "instructions_chunks.txt")

    def platform_index_path(self, platform_key: str) -> str:
        """e.g. cfg.platform_index_path('cengage') → 'data/instructions/faiss_index_cengage'"""
        return os.path.join(self.INSTRUCTIONS_DIR, f"faiss_index_{platform_key}")

    def platform_chunks_path(self, platform_key: str) -> str:
        """e.g. cfg.platform_chunks_path('cengage') → 'data/instructions/instructions_chunks_cengage.txt'"""
        return os.path.join(self.INSTRUCTIONS_DIR, f"instructions_chunks_{platform_key}.txt")


# ── Module-level singleton — import this everywhere ───────────────────────────
cfg = Config()