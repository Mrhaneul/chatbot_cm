"""
Updated Chat Schemas with PDF Recommendations
Add this to your app/schemas/chat.py or create it if it doesn't exist
"""

from pydantic import BaseModel
from typing import Optional, List, Dict

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class PDFRecommendation(BaseModel):
    """PDF recommendation metadata"""
    doc_id: str
    title: str
    description: str
    filename: str
    url: str
    pages: int
    relevance: str  # "Best Match", "Related", "Relevant"
    platform: str
    file_size_kb: float
    tags: List[str]

class ChatResponse(BaseModel):
    reply: str
    source: str
    article_link: Optional[str] = None
    confidence: float
    retrieval_time_ms: float
    llm_time_ms: float
    total_time_ms: float
    recommended_pdfs: List[PDFRecommendation] = []  # ← NEW FIELD
