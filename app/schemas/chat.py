from pydantic import BaseModel
from typing import Dict, List, Optional

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    image_base64: str | None = None
    image_media_type: str | None = None

class ChatResponse(BaseModel):
    reply: str
    source: str
    article_link: Optional[str] = None
    confidence: float
    response_id: Optional[str] = None
    session_id: Optional[str] = None
    retrieved_source_file: Optional[str] = None

    # Performance metrics
    response_time_ms: Optional[float] = None
    retrieval_time_ms: Optional[float] = None
    llm_time_ms: Optional[float] = None
    total_time_ms: Optional[float] = None
    recommended_pdfs: List[Dict] = []

    # Debug mode flag — True when session is in LLM-only mode
    # Used by the frontend to show the LLM badge on responses
    debug_mode: bool = False
