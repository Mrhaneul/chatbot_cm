from sentence_transformers import SentenceTransformer
import faiss
import os
import numpy as np

"""
INGEST MODULE (FIXED v2)
- Better error handling for empty directories
- Validates embeddings shape before creating index
- Supports multiple platform-specific indices
"""

FAQ_DIR = "data/faqs"
INSTRUCTIONS_DIR = "data/instructions"
FAQ_INDEX_PATH = "data/faqs/faiss_index"
FAQ_CHUNKS_PATH = "data/faqs/faqs_chunks.txt"
INSTRUCTIONS_INDEX_PATH = "data/instructions/faiss_index"
INSTRUCTIONS_CHUNKS_PATH = "data/instructions/instructions_chunks.txt"


def _ingest_directory(source_dir: str, index_path: str, chunks_path: str, label: str):
    """
    Ingest text files from a directory into a FAISS index.
    Each file becomes one chunk (no splitting by \\n\\n).
    """
    raw_chunks = []
    chunks_file_name = os.path.basename(chunks_path)
    
    # Check if directory exists
    if not os.path.exists(source_dir):
        print(f"⚠️  Directory not found: {source_dir}")
        return []
    
    file_names = sorted(
        [
            name for name in os.listdir(source_dir)
            if name.lower().endswith(".txt")
        ]
    )
    
    # Filter out generated chunk files
    file_names = [f for f in file_names if not f.startswith("faqs_chunks") 
                  and not f.startswith("instructions_chunks")]

    print(f"Found {len(file_names)} .txt files in {source_dir}")

    if len(file_names) == 0:
        print(f"⚠️  No .txt files found in {source_dir}")
        return []

    for file_name in file_names:
        file_path = os.path.join(source_dir, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            
            if text:  # Only add non-empty files
                raw_chunks.append((file_name, text))
                print(f"  ✓ Read: {file_name} ({len(text)} chars)")
            else:
                print(f"  ⚠️  Skipped empty file: {file_name}")
        except Exception as e:
            print(f"  ✗ Error reading {file_name}: {e}")

    if len(raw_chunks) == 0:
        print(f"⚠️  No valid content found in {source_dir}")
        return []

    # Add source identifiers
    chunks = []
    for i, (file_name, chunk) in enumerate(raw_chunks):
        chunks.append(f"[SOURCE_{i}] [FILE:{file_name}]\n{chunk}")

    print(f"Processing {len(chunks)} chunks for embedding...")

    # Embed and build index
    model = SentenceTransformer('all-MiniLM-L6-v2')
    embeddings = model.encode(chunks, normalize_embeddings=True)
    
    # Convert to numpy array if needed
    if not isinstance(embeddings, np.ndarray):
        embeddings = np.array(embeddings)
    
    # Validate embeddings shape
    if len(embeddings.shape) != 2:
        print(f"⚠️  Invalid embeddings shape: {embeddings.shape}")
        print(f"    Expected 2D array (n_chunks, embedding_dim)")
        return []
    
    print(f"Embeddings shape: {embeddings.shape} (chunks × dimensions)")

    # Use IndexFlatIP for cosine similarity (better than L2)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings.astype('float32'))

    faiss.write_index(index, index_path)

    # Save chunks to disk
    with open(chunks_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk + "\n---\n")

    print(f"✓ Ingested {len(chunks)} {label} chunks.\n")
    return chunks


def ingest_faqs():
    """Ingest FAQ documents."""
    print("=== Ingesting FAQs ===")
    return _ingest_directory(FAQ_DIR, FAQ_INDEX_PATH, FAQ_CHUNKS_PATH, "FAQ")


def ingest_instructions():
    """
    Ingest instruction documents and create platform-specific indices.
    This pre-filtering eliminates the need for runtime re-embedding.
    """
    print("=== Ingesting Instructions ===")
    
    # Read all instruction files
    raw_chunks = []
    
    if not os.path.exists(INSTRUCTIONS_DIR):
        print(f"⚠️  Directory not found: {INSTRUCTIONS_DIR}")
        return []
    
    file_names = sorted(
        [
            name for name in os.listdir(INSTRUCTIONS_DIR)
            if name.lower().endswith(".txt") 
            and not name.startswith("instructions_chunks")
        ]
    )
    
    print(f"Found {len(file_names)} instruction files")

    if len(file_names) == 0:
        print(f"⚠️  No instruction files found")
        return []

    for file_name in file_names:
        file_path = os.path.join(INSTRUCTIONS_DIR, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                raw_chunks.append((file_name, text))
                print(f"  ✓ Read: {file_name}")
        except Exception as e:
            print(f"  ✗ Error reading {file_name}: {e}")

    if len(raw_chunks) == 0:
        print(f"⚠️  No valid instruction content found")
        return []

    # Categorize chunks by platform
    all_chunks = []
    platform_data = {
        'cengage': [],
        'mcgraw': [],
        'pearson': [],
        'wiley': [],
        'macmillan': [],
        'sage': [],
        'bedford': [],
        'clifton': [],
        'simucase': [],
        'zybooks': []
    }

    for i, (file_name, text) in enumerate(raw_chunks):
        chunk = f"[SOURCE_{i}] [FILE:{file_name}]\n{text}"
        all_chunks.append(chunk)
        
        # Platform detection (case-insensitive)
        text_lower = text.lower()
        file_lower = file_name.lower()
        
        # Check each platform
        if "cengage" in text_lower or "mindtap" in text_lower or "cengage" in file_lower:
            platform_data['cengage'].append(chunk)
        if "mcgraw" in text_lower or "connect" in text_lower or "mcgraw" in file_lower:
            platform_data['mcgraw'].append(chunk)
        if "pearson" in text_lower or "mylab" in text_lower or "mastering" in text_lower or "pearson" in file_lower:
            platform_data['pearson'].append(chunk)
        if "wiley" in text_lower or "wileyplus" in text_lower or "wiley" in file_lower:
            platform_data['wiley'].append(chunk)
        if "macmillan" in text_lower or "achieve" in text_lower or "macmillan" in file_lower:
            platform_data['macmillan'].append(chunk)
        if "sage" in text_lower or "vantage" in text_lower or "sage" in file_lower:
            platform_data['sage'].append(chunk)
        if "bedford" in text_lower or "bookshelf" in text_lower or "bedford" in file_lower:
            platform_data['bedford'].append(chunk)
        if "clifton" in text_lower or "strengthsquest" in text_lower or "clifton" in file_lower:
            platform_data['clifton'].append(chunk)
        if "simucase" in text_lower or "simucase" in file_lower:
            platform_data['simucase'].append(chunk)
        if "zybook" in text_lower or "zybook" in file_lower:
            platform_data['zybooks'].append(chunk)

    # Load embedding model
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # === Build general instructions index ===
    print(f"\n  Building general index ({len(all_chunks)} chunks)...")
    embeddings = model.encode(all_chunks, normalize_embeddings=True)
    
    if not isinstance(embeddings, np.ndarray):
        embeddings = np.array(embeddings)
    
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings.astype('float32'))
    faiss.write_index(index, INSTRUCTIONS_INDEX_PATH)
    
    with open(INSTRUCTIONS_CHUNKS_PATH, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(chunk + "\n---\n")
    print(f"  ✓ Saved general instructions index")

    # === Build platform-specific indices ===
    platform_summary = {}
    
    for platform_name, chunks in platform_data.items():
        if chunks:
            try:
                print(f"\n  Building {platform_name} index ({len(chunks)} chunks)...")
                
                embeddings_p = model.encode(chunks, normalize_embeddings=True)
                
                if not isinstance(embeddings_p, np.ndarray):
                    embeddings_p = np.array(embeddings_p)
                
                index_p = faiss.IndexFlatIP(embeddings_p.shape[1])
                index_p.add(embeddings_p.astype('float32'))
                
                index_path = f"data/instructions/faiss_index_{platform_name}"
                chunks_path = f"data/instructions/instructions_chunks_{platform_name}.txt"
                
                faiss.write_index(index_p, index_path)
                
                with open(chunks_path, "w", encoding="utf-8") as f:
                    for chunk in chunks:
                        f.write(chunk + "\n---\n")
                
                print(f"  ✓ Saved {platform_name}-specific index")
                platform_summary[platform_name] = len(chunks)
            except Exception as e:
                print(f"  ✗ Error building {platform_name} index: {e}")
        else:
            print(f"  ⚠️  No {platform_name} chunks found")

    print(f"\n✓ Total instructions ingested: {len(all_chunks)}")
    for platform, count in platform_summary.items():
        print(f"  - {platform.capitalize()}: {count}")
    
    return all_chunks


if __name__ == "__main__":
    print("=== Running Ingestion Pipeline ===\n")
    ingest_faqs()
    print()
    ingest_instructions()
    print("\n✓ Ingestion complete!")