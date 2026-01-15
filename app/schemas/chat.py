from pydantic import BaseModel  # pydantic is used for data validation and settings management

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str
