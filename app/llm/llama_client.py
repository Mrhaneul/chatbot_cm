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
            "stream": True
        }

        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()

        return response.json()["message"]["content"]
    
    def chat_with_context(self, user_message: str, context: str) -> str:
        payload = {
            "model": "llama3:8b",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Campus Store assistant. "
                        "You must answer using ONLY the information in the provided context. "
                        "Do NOT use prior knowledge. "
                        "Do NOT infer schedules, dates, or policies. "
                        "If the answer cannot be found verbatim in the context, reply exactly with: "
                        "'The information is not available in the FAQ.'\n\n"
                    )
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            "stream": False
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=180)
        response.raise_for_status()

        data = response.json()
        return data["message"]["content"]

