import faiss                  # for vector database
from sentence_transformers import SentenceTransformer   # to embed documents
import numpy as np

"""
RETRIEVER MODULE
This module defines a retriever class that utilizes a FAISS index created during the ingestion process
to find and return relevant FAQ chunks based on user queries.
Note: The llm module will use citation-style references to refer to these chunks in responses.
"""

INDEX_PATH = "data/faiss_index"  # Path to load the FAISS index
CHUNKS_PATH = "data/faqs_chunks.txt"  # Path to the FAQ chunks file

class FAQRetriever:
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')  # load embedding model
        self.index = faiss.read_index(INDEX_PATH)  # load FAISS index

        # Load FAQ chunks
        with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
            self.chunks = f.read().split("\n---\n")

    # Retrieve the most relevant FAQ chunk for a given query
    def retrieve(self, query: str, k: int = 1):
        # all-MiniLM-L6-v2 model normalizes embeddings by default
        query_embedding = self.model.encode(
            [query],
            normalize_embeddings=True
        )

        # Search the FAISS index
        scores, indices = self.index.search(
            np.array(query_embedding).astype("float32"), k
        )

        # Return the best matching chunk
        best_index = indices[0][0]
        best_score = float(scores[0][0])
        best_chunk = self.chunks[best_index]

        return {
            "context": best_chunk,
            "score": best_score,
            "source_id": f"SOURCE_{best_index}"
        }