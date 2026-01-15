Campus Store Chatbot

A Zero-Budget, Local LLM–Based FAQ System

Abstract

This project implements a Campus Store FAQ chatbot using a local Large Language Model (LLM) deployed through an API-first architecture. The system is designed to operate under zero budget constraints, ensuring no dependency on paid cloud APIs while preserving modularity, privacy, and future extensibility.

The chatbot leverages LLaMA 3 (8B) served locally via Ollama, integrated with a FastAPI backend. The architecture intentionally mirrors cloud-based LLM workflows, enabling seamless migration to hosted models (e.g., GPT-4-class systems) if funding becomes available.

1. System Architecture

The system follows a layered, service-oriented design:

Client (Swagger / Web UI)
        ↓
FastAPI Backend (Python)
        ↓
Local LLM API (Ollama)
        ↓
LLaMA 3 (8B)

Key Architectural Properties

API-first design (LLM treated as an external service)

Fully local inference

No operational or usage cost

No external data transmission

Model-agnostic backend abstraction

2. Technology Stack
Component	Technology
Programming Language	Python 3.11
Backend Framework	FastAPI
ASGI Server	Uvicorn
LLM Runtime	Ollama
Language Model	LLaMA 3 (8B)
HTTP Client	Requests
Environment Management	Conda
3. Environment Setup
3.1 Conda Environment
conda create -n campus-store-bot python=3.11
conda activate campus-store-bot

3.2 Python Dependencies
pip install fastapi uvicorn requests pydantic

4. Local LLM Setup (Ollama)
4.1 Install Ollama

Ollama is used to host and serve the LLM locally.

Download and install from:

https://ollama.com/download


Verify installation:

ollama --version

4.2 Install LLaMA 3 Model
ollama pull llama3:8b


Verify installation:

ollama list


Expected output:

llama3:8b    4.7 GB

4.3 Verify Ollama API
curl http://localhost:11434/api/chat -Method POST -Body '
{
  "model": "llama3:8b",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": false
}'


A valid JSON response confirms successful local inference.

5. Project Structure
campus-store-chatbot/
│
├── app/
│   ├── main.py
│   ├── llm/
│   │   ├── base.py
│   │   └── llama_client.py
│   └── schemas/
│       └── chat.py
│
└── README.md

6. LLM Abstraction Layer

To support future model substitution, the chatbot uses an abstract LLM interface.

app/llm/base.py
from abc import ABC, abstractmethod

class LLMClient(ABC):

    @abstractmethod
    def chat(self, user_message: str) -> str:
        pass


This abstraction ensures:

Model independence

Clean separation of concerns

Minimal refactoring when switching LLM providers

7. LLaMA 3 Client Implementation
app/llm/llama_client.py
import requests
from app.llm.base import LLMClient

OLLAMA_URL = "http://localhost:11434/api/chat"

class LlamaClient(LLMClient):

    def chat(self, user_message: str) -> str:
        payload = {
            "model": "llama3:8b",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Campus Store assistant. "
                        "Only answer questions related to store hours, "
                        "returns, products, and general policies. "
                        "If you do not know, say you do not know."
                    )
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            "stream": False
        }

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=180
        )
        response.raise_for_status()

        data = response.json()

        if "message" not in data or "content" not in data["message"]:
            raise RuntimeError(f"Malformed Ollama response: {data}")

        return data["message"]["content"]

8. FastAPI Backend
app/main.py
from fastapi import FastAPI, HTTPException
from app.schemas.chat import ChatRequest, ChatResponse
from app.llm.llama_client import LlamaClient

app = FastAPI(title="Campus Store Chatbot (Local LLaMA)")

llm = LlamaClient()

@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    try:
        reply = llm.chat(payload.message)
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

9. Running the Application

Note: On Windows, run without --reload to ensure proper error visibility.

uvicorn app.main:app


The server runs at:

http://127.0.0.1:8000

10. API Testing (Swagger)

Open the interactive API documentation:

http://127.0.0.1:8000/docs


Example request to POST /chat:

{
  "message": "What is your return policy?"
}


A successful response confirms end-to-end operation.

11. Current Capabilities

Local LLaMA 3 inference

API-based chatbot service

Zero operational cost

No external data exposure

Deterministic, scope-restricted responses

12. Planned Extensions

Retrieval-Augmented Generation (RAG) using Campus Store FAQ documents

Conversation memory management

Usage analytics and logging

Optional migration to cloud-hosted LLMs if funding permits

13. Design Rationale

This system demonstrates that production-style LLM architectures can be developed without paid APIs, while still adhering to best practices in:

modularity,

abstraction,

security,

and scalability.

The project emphasizes engineering discipline over model size, making it suitable for academic evaluation and real-world institutional deployment.