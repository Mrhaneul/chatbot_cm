from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None

class ChatResponse(BaseModel):
    reply: str
    source: str
    article_link: Optional[str] = None
    confidence: float
    
    # ✨ NEW: Performance metrics
    response_time_ms: Optional[float] = None
    retrieval_time_ms: Optional[float] = None
    llm_time_ms: Optional[float] = None
    total_time_ms: Optional[float] = None
