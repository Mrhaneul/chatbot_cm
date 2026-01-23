import requests
from app.llm.base import LLMClient

OLLAMA_URL = "http://localhost:11434/api/chat"

class LlamaClient(LLMClient):

    def chat(
        self,
        message: str,
        context: str = "",
        history: list | None = None,
        system_hint: str = ""
    ) -> str:

        system_message = {
            "role": "system",
            "content": (
                "You are a Campus Store assistant.\n\n"
                f"{system_hint}\n\n"
                "If relevant information is provided in the context, use it to answer accurately.\n"
                "If required information is missing (such as a course code), ask the user for it.\n"
                "If no context is provided, respond helpfully and ask clarifying questions.\n"
                "Do NOT invent policies, dates, or procedures.\n"
                "Do NOT assume course platforms, policies, or outcomes unless explicitly stated.\n\n"
                "Use recent conversation history for continuity, but prioritize the current user message.\n\n"
                "Only reply with 'The information is not available in the FAQ.' if:\n"
                "- The context contains no relevant information AND\n"
                "- No reasonable clarifying question can move the conversation forward.\n"
            )
        }

        messages = [system_message]

        # Conversation history (defensive)
        if history:
            for msg in history:
                if "role" in msg and "content" in msg:
                    messages.append(msg)

        # Reference context (optional)
        if context:
            messages.append({
                "role": "assistant",  # safer than system
                "content": f"Reference information:\n{context}"
            })

        # Current user message
        messages.append({
            "role": "user",
            "content": message
        })

        payload = {
            "model": "llama3:8b",
            "messages": messages,
            "stream": False
        }

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=180
        )
        response.raise_for_status()

        return response.json()["message"]["content"]
