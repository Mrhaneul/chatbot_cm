from sentence_transformers import SentenceTransformer   # to embed documents
import faiss                   # for vector database

"""
INGEST MODULE
This module handles the ingestion of FAQ documents, embedding them using a pre-trained model,
and storing the embeddings in a FAISS index for efficient retrieval.
Retriever module uses this index to find relevant FAQ chunks based on user queries.
Note: The llm module will use citation-style references to refer to these chunks in responses.
"""

FAQ_PATH = "data/faqs.txt"  # Path to the FAQ document
INDEX_PATH = "data/faiss_index"  # Path to store/load the FAISS index
CHUNKS_PATH = "data/faqs_chunks.txt"

def ingest_faqs():
    with open(FAQ_PATH, 'r', encoding='utf-8') as f: # read the FAQ file
        text = f.read() # read the entire content

    raw_chunks = [c.strip() for c in text.split("\n\n") if c.strip()]

    chunks = []
    # Split the text into chunks based on double newlines
    for i, chunk in enumerate(raw_chunks):
        chunks.append(f"[SOURCE_{i}]\n{chunk}")

    model = SentenceTransformer('all-MiniLM-L6-v2') # load a pre-trained embedding model
    embeddings = model.encode(chunks) # generate embeddings for each chunk

    index = faiss.IndexFlatL2(embeddings.shape[1]) # create a FAISS index
    index.add(embeddings) # add embeddings to the index

    faiss.write_index(index, INDEX_PATH) # save the index to disk

    # For each chunk so it has a stable identifier (Citation style)
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk + "\n---\n")

    print(f"Ingested {len(chunks)} FAQ chunks.")
    return chunks

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