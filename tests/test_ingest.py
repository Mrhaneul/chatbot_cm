import os
import pathlib

from app.rag.ingest import ingest_faqs, ingest_instructions


def test_ingest_faqs():
    # Run ingestion (this will rewrite indexes)
    chunks = ingest_faqs()
    # Expect non‑empty list of chunks
    assert chunks, "FAQ ingestion returned empty list"
    # Index file should exist
    index_path = pathlib.Path("data/faqs/faiss_index")
    assert index_path.is_file(), f"FAQ index not found at {index_path}"
    # Chunks file should exist
    chunks_path = pathlib.Path("data/faqs/faqs_chunks.txt")
    assert chunks_path.is_file(), f"FAQ chunks file not found at {chunks_path}"


def test_ingest_instructions():
    chunks = ingest_instructions()
    assert chunks, "Instruction ingestion returned empty list"
    # General index file
    index_path = pathlib.Path("data/instructions/faiss_index")
    assert index_path.is_file(), f"Instructions index not found at {index_path}"
    chunks_path = pathlib.Path("data/instructions/instructions_chunks.txt")
    assert chunks_path.is_file(), f"Instructions chunks file not found at {chunks_path}"
