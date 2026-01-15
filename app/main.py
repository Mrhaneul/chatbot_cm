from fastapi import FastAPI, HTTPException
from app.schemas.chat import ChatRequest, ChatResponse
from app.llm.llama_client import LlamaClient
from app.rag.retriever import FAQRetriever

# 1. Create FastAPI app FIRST
app = FastAPI(title="Campus Store Chatbot (RAG Test Mode)")

# 2. Initialize services
llm = LlamaClient()
retriever = FAQRetriever()

# 3. Define routes AFTER app exists
@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    try:
        context = retriever.retrieve(payload.message)
        reply = llm.chat_with_context(payload.message, context)
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# Will be used later when enabling the API
# app = FastAPI(title="Campus Store Chatbot (Local LLaMA)")

# llm = LlamaClient()

# @app.post("/chat", response_model=ChatResponse)
# def chat(payload: ChatRequest):
#     try:
#         reply = llm.chat(payload.message)
#         return ChatResponse(reply=reply)
#     except Exception as e:
#         traceback.print_exc()
#         raise HTTPException(status_code=500, detail=str(e))