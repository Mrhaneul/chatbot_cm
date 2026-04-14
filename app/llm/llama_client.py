import json
import re

import httpx
import requests

from app.llm.base import LLMClient

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4:e2b"


def strip_thinking_tags(text: str) -> str:
    """Remove Gemma 4 thought blocks from response text."""
    text = re.sub(r"<\|channel\>thought.*?<channel\|>", "", text, flags=re.DOTALL)
    text = re.sub(r"<\|channel\>.*?<channel\|>", "", text, flags=re.DOTALL)
    return text.strip()


def build_system_prompt(context: str = "", system_hint: str = "") -> str:
    """Build the system prompt used for grounded Lance responses."""
    system_content = """You are Lance, the Campus Store AI Assistant for California Baptist University.

=== ABSOLUTE RULE #1 (OVERRIDE EVERYTHING) ===

IF documentation context appears below (between tags):
-> START IMMEDIATELY with the answer from the documentation
-> DO NOT say "Hi! I'm Lance..."
-> DO NOT ask "What can I help you with today?"
-> DO NOT provide a greeting of any kind
-> Jump straight to the answer

This applies EVEN IF it's the first message in the conversation.

=== When to Give a Greeting ===

ONLY give a greeting when ALL of these are true:
1. User ONLY says "Hi", "Hello", or "Hey" with nothing else
2. There is NO documentation context below
3. The user hasn't asked a specific question

=== Response Formats ===

**With Instructions:**
"Here's how to access [platform]:

1. [Step from documentation]
2. [Step from documentation]
..."

**With FAQ:**
"[Direct answer from FAQ, preserving formatting]"

**Pure Greeting (Rare):**
"Hi! I'm Lance, your Campus Store AI Assistant. I can help with Immediate Access, textbook policies, and troubleshooting. What can I help you with today?"

**Need Clarification:**
"I can help with [topic]! Could you specify: [specific question]?"

=== OUTPUT SAFETY RULES ===
- Do NOT explain your internal reasoning.
- Do NOT write meta lines like "Since the user..." or "Based on the documentation...".
- Never mention instructions, prompts, rules, or context tags.
- Give only the final user-facing answer.
"""

    if system_hint:
        system_content += f"\n\n=== ADDITIONAL CONTEXT ===\n{system_hint}\n"

    if context:
        is_faq = "QUESTION:" in context and "ANSWER:" in context

        if is_faq:
            system_content += f"""

=== RETRIEVED FAQ (PROVIDE THIS ANSWER) ===
{context}
=== END FAQ ===

THIS IS A FAQ - NOT INSTRUCTIONS!
The user asked an informational question like "What is..." or "Tell me about..."
The FAQ above has the complete answer in the ANSWER section.

Your response should:
1. Start directly with the answer (no greeting)
2. Provide the complete ANSWER from the FAQ
3. Keep the formatting (bullet points, bold text, etc.)
4. DO NOT add step-by-step access instructions
5. DO NOT say "Here's how to access..."
6. If the FAQ appears unrelated to the user's message, ask a short clarification question instead of forcing the FAQ.

Example:
User: "What is Immediate Access?"
FAQ: "Immediate Access is California Baptist University's program..."
CORRECT: "Immediate Access is California Baptist University's program..."
WRONG: "Here's how to access Immediate Access: 1. Log into..."
"""
        else:
            system_content += f"""

=== RETRIEVED DOCUMENTATION (USE THIS!) ===
{context}
=== END DOCUMENTATION ===

CRITICAL REMINDER: These are step-by-step instructions!
- You MUST use this documentation to answer
- You MUST skip any greeting
- Start with: "Here's how to..."
- Provide the step-by-step instructions from the documentation
- If the user can't access to a textbook and provides the course code, ask which platform is the user using (e.g. Cengage MindTap).
- If documentation does not match the user's platform/topic, ask for clarification and do not invent platform steps.
"""
    else:
        system_content += """

No documentation was retrieved. Handle based on the query type:
- If just "Hi"/"Hello" -> Give greeting
- If specific question -> Answer from your knowledge or ask for details
"""

    system_content += """

BEFORE YOU RESPOND, ASK YOURSELF:
1. Is there FAQ documentation above?
   -> YES: Provide the FAQ ANSWER directly, NO GREETING
2. Is there instruction documentation above?
   -> YES: Provide those steps, NO GREETING
3. No documentation?
   -> Is it just "Hi"? Give greeting
   -> Otherwise: Answer or ask for clarification

Now respond:
"""
    return system_content


async def stream_llm_response(prompt: str, system: str = ""):
    """
    Async generator that streams tokens from Ollama one chunk at a time.
    Strips Gemma 4 thought blocks from the stream before yielding.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": True,
    }

    in_thought_block = False
    buffer = ""

    try:
        timeout = httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=120.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", OLLAMA_GENERATE_URL, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("done"):
                        break

                    token = chunk.get("response", "")
                    if not token:
                        continue

                    buffer += token

                    if "<|channel>" in buffer:
                        in_thought_block = True

                    if in_thought_block and "<channel|>" in buffer:
                        in_thought_block = False
                        buffer = buffer.split("<channel|>", 1)[-1]
                        clean = strip_thinking_tags(buffer)
                        if clean:
                            yield clean
                        buffer = ""
                        continue

                    if not in_thought_block and buffer:
                        if not buffer.endswith("<") and not buffer.endswith("<|"):
                            clean = strip_thinking_tags(buffer)
                            if clean:
                                yield clean
                            buffer = ""

                if buffer and not in_thought_block:
                    clean = strip_thinking_tags(buffer)
                    if clean:
                        yield clean

    except httpx.ConnectError:
        yield "[ERROR: Ollama is not running. Please start Ollama and try again.]"
    except httpx.ReadTimeout:
        yield "[ERROR: LLM response timed out.]"


class LlamaClient(LLMClient):
    def chat(
        self,
        message: str,
        context: str = "",
        history: list | None = None,
        system_hint: str = "",
    ) -> str:
        try:
            print("\n" + "=" * 50)
            print("[DEBUG] User Message:", message)
            if context:
                preview = context[:500] + "..." if len(context) > 500 else context
                print("[DEBUG] Context Preview:", preview)
            print("=" * 50 + "\n")

            messages = [{"role": "system", "content": build_system_prompt(context, system_hint)}]

            if history:
                for msg in history:
                    if "role" in msg and "content" in msg:
                        messages.append(msg)

            messages.append({"role": "user", "content": message})

            payload = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1024,
                },
            }

            response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=(5, 60))
            response.raise_for_status()

            return strip_thinking_tags(response.json()["message"]["content"])

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Ollama request failed: {e}")
            return "I'm having trouble connecting right now. Please try again in a moment."
