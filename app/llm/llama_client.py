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

        # Build system message with embedded context (more authoritative)
        system_content = (
            "You are a Campus Store assistant for California Baptist University.\n\n"
            f"{system_hint}\n\n"
        )
        
        # FIXED: Inject context into system message (more authoritative than assistant message)
        if context:
            system_content += (
                "=== OFFICIAL INSTRUCTIONS (FOLLOW EXACTLY) ===\n"
                f"{context}\n"
                "=== END OFFICIAL INSTRUCTIONS ===\n\n"
                "CRITICAL: You MUST follow the step-by-step instructions above EXACTLY as written. "
                "Do NOT add steps, change steps, or provide alternative instructions. "
                "If the instructions mention Blackboard, you MUST tell the user to use Blackboard. "
                "Do NOT suggest accessing materials directly from publisher websites unless the instructions explicitly say so. "
                "Do NOT mention platforms or publishers that are not explicitly listed in the instructions above.\n\n"
            )
        
        system_content += (
            "If relevant information is provided in the context above, use it to answer accurately.\n"
            "If required information is missing (such as a course code), ask the user for it.\n"
            "If no context is provided, respond helpfully and ask clarifying questions.\n"
            "Do NOT invent policies, dates, or procedures.\n"
            "Do NOT assume course platforms, policies, or outcomes unless explicitly stated.\n\n"
            "Use recent conversation history for continuity, but prioritize the current user message and official instructions.\n\n"
            "Only reply with 'The information is not available in the FAQ.' if:\n"
            "- The context contains no relevant information AND\n"
            "- No reasonable clarifying question can move the conversation forward.\n"
        )

        system_message = {
            "role": "system",
            "content": system_content
        }

        messages = [system_message]

        # Conversation history (defensive)
        if history:
            for msg in history:
                if "role" in msg and "content" in msg:
                    messages.append(msg)

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