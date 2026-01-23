import faiss
import re
from sentence_transformers import SentenceTransformer
import numpy as np

"""
RETRIEVER MODULE (FIXED)
- Added missing FAQ retrieval branch (Bug #1)
- Uses pre-built platform-filtered indices (Bug #5 - performance fix)
- Switched to IndexFlatIP for cosine similarity
"""

FAQ_INDEX_PATH = "data/faqs/faiss_index"
FAQ_CHUNKS_PATH = "data/faqs/faqs_chunks.txt"
INSTRUCTIONS_INDEX_PATH = "data/instructions/faiss_index"
INSTRUCTIONS_CHUNKS_PATH = "data/instructions/instructions_chunks.txt"
INSTRUCTIONS_INDEX_CENGAGE_PATH = "data/instructions/faiss_index_cengage"
INSTRUCTIONS_INDEX_MCGRAW_PATH = "data/instructions/faiss_index_mcgraw"
INSTRUCTIONS_CHUNKS_CENGAGE_PATH = "data/instructions/instructions_chunks_cengage.txt"
INSTRUCTIONS_CHUNKS_MCGRAW_PATH = "data/instructions/instructions_chunks_mcgraw.txt"

INSTRUCTIONS_KEYWORDS = {
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
}


class FAQRetriever:
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Load FAQ index
        self.faq_index = faiss.read_index(FAQ_INDEX_PATH)
        with open(FAQ_CHUNKS_PATH, "r", encoding="utf-8") as f:
            self.faq_chunks = f.read().split("\n---\n")
        
        # Load general instructions index
        self.instructions_index = faiss.read_index(INSTRUCTIONS_INDEX_PATH)
        with open(INSTRUCTIONS_CHUNKS_PATH, "r", encoding="utf-8") as f:
            self.instruction_chunks = f.read().split("\n---\n")
        
        # Load platform-specific indices (if they exist)
        try:
            self.instructions_index_cengage = faiss.read_index(INSTRUCTIONS_INDEX_CENGAGE_PATH)
            with open(INSTRUCTIONS_CHUNKS_CENGAGE_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_cengage = f.read().split("\n---\n")
            print("✓ Loaded Cengage-specific instruction index")
        except Exception as e:
            print(f"⚠ Cengage index not found (will use general index): {e}")
            self.instructions_index_cengage = None
            self.instruction_chunks_cengage = []
        
        try:
            self.instructions_index_mcgraw = faiss.read_index(INSTRUCTIONS_INDEX_MCGRAW_PATH)
            with open(INSTRUCTIONS_CHUNKS_MCGRAW_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_mcgraw = f.read().split("\n---\n")
            print("✓ Loaded McGraw Hill-specific instruction index")
        except Exception as e:
            print(f"⚠ McGraw Hill index not found (will use general index): {e}")
            self.instructions_index_mcgraw = None
            self.instruction_chunks_mcgraw = []

    def _select_collection(self, query: str):
        """Heuristic to choose between FAQs and instructions."""
        normalized = query.lower()
        if any(keyword in normalized for keyword in INSTRUCTIONS_KEYWORDS):
            return "instructions"
        return "faqs"

    def retrieve(self, query: str, k: int = 1, collection: str = "auto", platform: str = None):
        """
        Retrieve the most relevant chunk for a given query.
        
        Args:
            query: User's question
            k: Number of results to return
            collection: "faqs", "instructions", or "auto"
            platform: "CENGAGE", "MCGRAW_HILL", or None
        
        Returns:
            dict with context, score, source_id, article_link
        """
        # Determine which collection to use
        selected_collection = (
            self._select_collection(query)
            if collection == "auto"
            else collection
        )

        # Encode query once
        query_embedding = self.model.encode([query], normalize_embeddings=True)
        query_vector = np.array(query_embedding).astype("float32")

        # === INSTRUCTIONS PATH ===
        if selected_collection == "instructions":
            # Select the appropriate index based on platform
            if platform == "CENGAGE" and self.instructions_index_cengage:
                index = self.instructions_index_cengage
                chunks = self.instruction_chunks_cengage
                source_prefix = "INSTR_CENGAGE"
            elif platform == "MCGRAW_HILL" and self.instructions_index_mcgraw:
                index = self.instructions_index_mcgraw
                chunks = self.instruction_chunks_mcgraw
                source_prefix = "INSTR_MCGRAW"
            else:
                # Fallback to general instructions index
                index = self.instructions_index
                chunks = self.instruction_chunks
                source_prefix = "INSTR_GENERAL"
            
            # Perform search on pre-built index (FAST!)
            scores, indices = index.search(query_vector, k)
            
            best_index = indices[0][0]
            best_score = float(scores[0][0])
            best_chunk = chunks[best_index]
            
            # Extract article link if present
            match = re.search(r'Article link:\s*"?([^"\n]+)"?', best_chunk)
            article_link = match.group(1).strip() if match else None
            
            return {
                "context": best_chunk,
                "score": best_score,
                "source_id": f"{source_prefix}_SOURCE_{best_index}",
                "article_link": article_link
            }
        
        # === FAQ PATH (FIXED - Bug #1) ===
        else:
            # Search FAQ index
            scores, indices = self.faq_index.search(query_vector, k)
            
            best_index = indices[0][0]
            best_score = float(scores[0][0])
            best_chunk = self.faq_chunks[best_index]
            
            # Extract article link if present
            match = re.search(r'Article link:\s*"?([^"\n]+)"?', best_chunk)
            article_link = match.group(1).strip() if match else None
            
            return {
                "context": best_chunk,
                "score": best_score,
                "source_id": f"FAQ_SOURCE_{best_index}",
                "article_link": article_link
            }