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
INSTRUCTIONS_INDEX_BEDFORD_PATH = "data/instructions/faiss_index_bedford"
INSTRUCTIONS_INDEX_PEARSON_PATH = "data/instructions/faiss_index_pearson"
INSTRUCTIONS_INDEX_CLIFTON_PATH = "data/instructions/faiss_index_clifton"
INSTRUCTIONS_INDEX_MACMILLAN_PATH = "data/instructions/faiss_index_macmillan"
INSTRUCTIONS_INDEX_SAGE_PATH = "data/instructions/faiss_index_sage"
INSTRUCTIONS_INDEX_SIMUCASE_PATH = "data/instructions/faiss_index_simucase"
INSTRUCTIONS_INDEX_WILEY_PATH = "data/instructions/faiss_index_wiley"
INSTRUCTIONS_INDEX_ZYBOOKS_PATH = "data/instructions/faiss_index_zybooks"
INSTRUCTIONS_CHUNKS_CENGAGE_PATH = "data/instructions/instructions_chunks_cengage.txt"
INSTRUCTIONS_CHUNKS_MCGRAW_PATH = "data/instructions/instructions_chunks_mcgraw.txt"
INSTRUCTIONS_CHUNKS_BEDFORD_PATH = "data/instructions/instructions_chunks_bedford.txt"
INSTRUCTIONS_CHUNKS_PEARSON_PATH = "data/instructions/instructions_chunks_pearson.txt"
INSTRUCTIONS_CHUNKS_CLIFTON_PATH = "data/instructions/instructions_chunks_clifton.txt"
INSTRUCTIONS_CHUNKS_MACMILLAN_PATH = "data/instructions/instructions_chunks_macmillan.txt"
INSTRUCTIONS_CHUNKS_SAGE_PATH = "data/instructions/instructions_chunks_sage.txt"
INSTRUCTIONS_CHUNKS_WILEY_PATH = "data/instructions/instructions_chunks_wiley.txt"
INSTRUCTIONS_CHUNKS_ZYBOOKS_PATH = "data/instructions/instructions_chunks_zybooks.txt"
INSTRUCTIONS_CHUNKS_SIMUCASE_PATH = "data/instructions/instructions_chunks_simucase.txt"


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

        try:
            self.instructions_index_bedford = faiss.read_index(INSTRUCTIONS_INDEX_BEDFORD_PATH)
            with open(INSTRUCTIONS_CHUNKS_BEDFORD_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_bedford = f.read().split("\n---\n")
            print("✓ Loaded Bedford-specific instruction index")
        except Exception as e:
            print(f"⚠ Bedford index not found (will use general index): {e}")
            self.instructions_index_bedford = None
            self.instruction_chunks_bedford = []

        try:
            self.instructions_index_pearson = faiss.read_index(INSTRUCTIONS_INDEX_PEARSON_PATH)
            with open(INSTRUCTIONS_CHUNKS_PEARSON_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_pearson = f.read().split("\n---\n")
            print("✓ Loaded Pearson-specific instruction index")
        except Exception as e:
            print(f"⚠ Pearson index not found (will use general index): {e}")
            self.instructions_index_pearson = None
            self.instruction_chunks_pearson = []

        try:
            self.instructions_index_clifton = faiss.read_index(INSTRUCTIONS_INDEX_CLIFTON_PATH)
            with open(INSTRUCTIONS_CHUNKS_CLIFTON_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_clifton = f.read().split("\n---\n")
            print("✓ Loaded Clifton-specific instruction index")
        except Exception as e:
            print(f"⚠ Clifton index not found (will use general index): {e}")
            self.instructions_index_clifton = None
            self.instruction_chunks_clifton = []

        try:
            self.instructions_index_macmillan = faiss.read_index(INSTRUCTIONS_INDEX_MACMILLAN_PATH)
            with open(INSTRUCTIONS_CHUNKS_MACMILLAN_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_macmillan = f.read().split("\n---\n")
            print("✓ Loaded MacMillan-specific instruction index")
        except Exception as e:
            print(f"⚠ MacMillan index not found (will use general index): {e}")
            self.instructions_index_macmillan = None
            self.instruction_chunks_macmillan = []

        try:
            self.instructions_index_sage = faiss.read_index(INSTRUCTIONS_INDEX_SAGE_PATH)
            with open(INSTRUCTIONS_CHUNKS_SAGE_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_sage = f.read().split("\n---\n")
            print("✓ Loaded SAGE-specific instruction index")
        except Exception as e:
            print(f"⚠ SAGE index not found (will use general index): {e}")
            self.instructions_index_sage = None
            self.instruction_chunks_sage = []

        try:
            self.instructions_index_simucase = faiss.read_index(INSTRUCTIONS_INDEX_SIMUCASE_PATH)
            with open(INSTRUCTIONS_CHUNKS_SIMUCASE_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_simucase = f.read().split("\n---\n")
            print("✓ Loaded SimuCase-specific instruction index")
        except Exception as e:
            print(f"⚠ SimuCase index not found (will use general index): {e}")
            self.instructions_index_simucase = None
            self.instruction_chunks_simucase = []

        try:
            self.instructions_index_wiley = faiss.read_index(INSTRUCTIONS_INDEX_WILEY_PATH)
            with open(INSTRUCTIONS_CHUNKS_WILEY_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_wiley = f.read().split("\n---\n")
            print("✓ Loaded Wiley-specific instruction index")
        except Exception as e:
            print(f"⚠ Wiley index not found (will use general index): {e}")
            self.instructions_index_wiley = None
            self.instruction_chunks_wiley = []

        try:
            self.instructions_index_zybooks = faiss.read_index(INSTRUCTIONS_INDEX_ZYBOOKS_PATH)
            with open(INSTRUCTIONS_CHUNKS_ZYBOOKS_PATH, "r", encoding="utf-8") as f:
                self.instruction_chunks_zybooks = f.read().split("\n---\n")
            print("✓ Loaded Zybooks-specific instruction index")
        except Exception as e:
            print(f"⚠ Zybooks index not found (will use general index): {e}")
            self.instructions_index_zybooks = None
            self.instruction_chunks_zybooks = []

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
            elif platform == "BEDFORD" and self.instructions_index_bedford:
                index = self.instructions_index_bedford
                chunks = self.instruction_chunks_bedford
                source_prefix = "INSTR_BEDFORD"
            elif platform == "PEARSON" and self.instructions_index_pearson:
                index = self.instructions_index_pearson
                chunks = self.instruction_chunks_pearson
                source_prefix = "INSTR_PEARSON"
            elif platform == "CLIFTON" and self.instructions_index_clifton:
                index = self.instructions_index_clifton
                chunks = self.instruction_chunks_clifton
                source_prefix = "INSTR_CLIFTON"
            elif platform == "MACMILLAN" and self.instructions_index_macmillan:
                index = self.instructions_index_macmillan
                chunks = self.instruction_chunks_macmillan
                source_prefix = "INSTR_MACMILLAN"
            elif platform == "SAGE" and self.instructions_index_sage:
                index = self.instructions_index_sage
                chunks = self.instruction_chunks_sage
                source_prefix = "INSTR_SAGE"
            elif platform == "SIMUCASE" and self.instructions_index_simucase:
                index = self.instructions_index_simucase
                chunks = self.instruction_chunks_simucase
                source_prefix = "INSTR_SIMUCASE"
            elif platform == "WILEY" and self.instructions_index_wiley:
                index = self.instructions_index_wiley
                chunks = self.instruction_chunks_wiley
                source_prefix = "INSTR_WILEY"
            elif platform == "ZYBOOKS" and self.instructions_index_zybooks:
                index = self.instructions_index_zybooks
                chunks = self.instruction_chunks_zybooks
                source_prefix = "INSTR_ZYBOOKS"
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