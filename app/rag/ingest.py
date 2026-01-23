from sentence_transformers import SentenceTransformer
import faiss
import os

"""
INGEST MODULE (FIXED)
- Now creates platform-specific indices for instructions (Bug #5 fix)
- Switched to IndexFlatIP for cosine similarity (better than L2)
- Pre-filters during ingestion (no runtime re-embedding needed)
"""

FAQ_DIR = "data/faqs"
INSTRUCTIONS_DIR = "data/instructions"
FAQ_INDEX_PATH = "data/faqs/faiss_index"
FAQ_CHUNKS_PATH = "data/faqs/faqs_chunks.txt"
INSTRUCTIONS_INDEX_PATH = "data/instructions/faiss_index"
INSTRUCTIONS_CHUNKS_PATH = "data/instructions/instructions_chunks.txt"
INSTRUCTIONS_INDEX_CENGAGE_PATH = "data/instructions/faiss_index_cengage"
INSTRUCTIONS_INDEX_MCGRAW_PATH = "data/instructions/faiss_index_mcgraw"
INSTRUCTIONS_CHUNKS_CENGAGE_PATH = "data/instructions/instructions_chunks_cengage.txt"
INSTRUCTIONS_CHUNKS_MCGRAW_PATH = "data/instructions/instructions_chunks_mcgraw.txt"


def _ingest_directory(source_dir: str, index_path: str, chunks_path: str, label: str):
    """
    Ingest text files from a directory into a FAISS index.
    Each file becomes one chunk (no splitting by \\n\\n).
    """
    raw_chunks = []
    chunks_file_name = os.path.basename(chunks_path)
    file_names = sorted(
        [
            name for name in os.listdir(source_dir)
            if name.lower().endswith(".txt")
        ]
    )

    for file_name in file_names:
        if file_name == chunks_file_name:
            continue
        file_path = os.path.join(source_dir, file_name)
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        # Keep entire file as one chunk
        file_chunks = [text.strip()]
        for chunk in file_chunks:
            raw_chunks.append((file_name, chunk))

    # Add source identifiers
    chunks = []
    for i, (file_name, chunk) in enumerate(raw_chunks):
        chunks.append(f"[SOURCE_{i}] [FILE:{file_name}]\n{chunk}")

    # Embed and build index
    model = SentenceTransformer('all-MiniLM-L6-v2')
    embeddings = model.encode(chunks, normalize_embeddings=True)

    # Use IndexFlatIP for cosine similarity (better than L2)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    faiss.write_index(index, index_path)

    # Save chunks to disk
    with open(chunks_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk + "\n---\n")

    print(f"✓ Ingested {len(chunks)} {label} chunks.")
    return chunks


def ingest_faqs():
    """Ingest FAQ documents."""
    return _ingest_directory(FAQ_DIR, FAQ_INDEX_PATH, FAQ_CHUNKS_PATH, "FAQ")


def ingest_instructions():
    """
    Ingest instruction documents and create platform-specific indices.
    This pre-filtering eliminates the need for runtime re-embedding.
    """
    print("\n=== Ingesting Instructions ===")
    
    # Read all instruction files
    raw_chunks = []
    file_names = sorted(
        [
            name for name in os.listdir(INSTRUCTIONS_DIR)
            if name.lower().endswith(".txt") and name != os.path.basename(INSTRUCTIONS_CHUNKS_PATH)
        ]
    )

    for file_name in file_names:
        file_path = os.path.join(INSTRUCTIONS_DIR, file_name)
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        raw_chunks.append((file_name, text))

    # Categorize chunks by platform
    all_chunks = []
    cengage_chunks = []
    mcgraw_chunks = []

    for i, (file_name, text) in enumerate(raw_chunks):
        chunk = f"[SOURCE_{i}] [FILE:{file_name}]\n{text}"
        all_chunks.append(chunk)
        
        # Platform detection (case-insensitive)
        text_lower = text.lower()
        if "cengage" in text_lower or "mindtap" in text_lower:
            cengage_chunks.append(chunk)
        if "mcgraw" in text_lower or "connect" in text_lower:
            mcgraw_chunks.append(chunk)

    # Load embedding model
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # === Build general instructions index ===
    print(f"  Building general index ({len(all_chunks)} chunks)...")
    embeddings = model.encode(all_chunks, normalize_embeddings=True)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    faiss.write_index(index, INSTRUCTIONS_INDEX_PATH)
    
    with open(INSTRUCTIONS_CHUNKS_PATH, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(chunk + "\n---\n")
    print(f"  ✓ Saved general instructions index")

    # === Build Cengage-specific index ===
    if cengage_chunks:
        print(f"  Building Cengage index ({len(cengage_chunks)} chunks)...")
        embeddings_c = model.encode(cengage_chunks, normalize_embeddings=True)
        index_c = faiss.IndexFlatIP(embeddings_c.shape[1])
        index_c.add(embeddings_c)
        faiss.write_index(index_c, INSTRUCTIONS_INDEX_CENGAGE_PATH)
        
        with open(INSTRUCTIONS_CHUNKS_CENGAGE_PATH, "w", encoding="utf-8") as f:
            for chunk in cengage_chunks:
                f.write(chunk + "\n---\n")
        print(f"  ✓ Saved Cengage-specific index")
    else:
        print(f"  ⚠ No Cengage chunks found")

    # === Build McGraw Hill-specific index ===
    if mcgraw_chunks:
        print(f"  Building McGraw Hill index ({len(mcgraw_chunks)} chunks)...")
        embeddings_m = model.encode(mcgraw_chunks, normalize_embeddings=True)
        index_m = faiss.IndexFlatIP(embeddings_m.shape[1])
        index_m.add(embeddings_m)
        faiss.write_index(index_m, INSTRUCTIONS_INDEX_MCGRAW_PATH)
        
        with open(INSTRUCTIONS_CHUNKS_MCGRAW_PATH, "w", encoding="utf-8") as f:
            for chunk in mcgraw_chunks:
                f.write(chunk + "\n---\n")
        print(f"  ✓ Saved McGraw Hill-specific index")
    else:
        print(f"  ⚠ No McGraw Hill chunks found")

    print(f"\n✓ Total instructions ingested: {len(all_chunks)}")
    print(f"  - Cengage: {len(cengage_chunks)}")
    print(f"  - McGraw Hill: {len(mcgraw_chunks)}")
    print(f"  - General: {len(all_chunks)}")
    
    return all_chunks


if __name__ == "__main__":
    print("=== Running Ingestion Pipeline ===\n")
    ingest_faqs()
    ingest_instructions()
    print("\n✓ Ingestion complete!")

"""
Dictionary for conceptual clarity (tools used in this file):

    Faiss (Facebook AI Similarity Search): 
        A library for efficient similarity search and clustering of dense vectors, 
        often used for tasks like nearest neighbor search in large datasets.
            Note: Faiss indexes can be stored on disk and loaded back into memory as needed.

    SentenceTransformer:
        A Python library that provides an easy way to compute dense vector representations 
        (embeddings) for sentences and paragraphs using pre-trained transformer models.
            Note: all-MiniLM-L6-v2 is a specific model within this library known for its balance 
            between performance and computational efficiency.
"""
