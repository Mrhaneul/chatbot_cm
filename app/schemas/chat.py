from typing import Optional
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None  # optional for per-session state

class ChatResponse(BaseModel):
    reply: str
    source: str
    article_link: Optional[str]
    confidence: float
