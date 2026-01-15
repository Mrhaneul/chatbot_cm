import faiss                  # for vector database
from sentence_transformers import SentenceTransformer   # to embed documents
import numpy as np

"""
RETRIEVER MODULE
This module defines a retriever class that utilizes a FAISS index created during the ingestion process
to find and return relevant FAQ chunks based on user queries.
"""

INDEX_PATH = "data/faiss_index"  # Path to load the FAISS index
FAQ_PATH = "data/faqs.txt"  # Path to the FAQ document

class FAQRetriever:
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')  # load embedding model
        self.index = faiss.read_index(INDEX_PATH)  # load FAISS index

        with open(FAQ_PATH, "r", encoding="utf-8") as f:
            self.chunks = [c.strip() for c in f.read().split('\n\n') if c.strip()]  # load FAQ chunks

    def retrieve(self, query: str, k: int = 3) -> str: # retrieve top-k relevant FAQ chunks
        query_embedding = self.model.encode([query]) # embed the query
        distances, indices = self.index.search(np.array(query_embedding.astype('float32')), k) # search the index

        results = [self.chunks[i] for i in indices[0]]  # get the corresponding FAQ chunks
        return "\n".join(results)   # return as a single string