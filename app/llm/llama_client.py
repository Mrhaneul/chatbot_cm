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
        
        try:
            print("\n" + "="*50)
            print("[DEBUG] User Message:", message)
            if context:
                print("[DEBUG] Context Preview:", context[:500] + "..." if len(context) > 500 else context)
            print("="*50 + "\n")

            # Build system prompt with clear hierarchy
            system_content = """You are Lance, the Campus Store AI Assistant for California Baptist University.

=== ⚠️ ABSOLUTE RULE #1 (OVERRIDE EVERYTHING) ===

IF documentation context appears below (between tags):
→ START IMMEDIATELY with the answer from the documentation
→ DO NOT say "Hi! I'm Lance..."
→ DO NOT ask "What can I help you with today?"
→ DO NOT provide a greeting of any kind
→ Jump straight to the answer

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
"""
            
            # Add system hint if provided
            if system_hint:
                system_content += f"\n\n=== ADDITIONAL CONTEXT ===\n{system_hint}\n"
            
            # Add context if available - WITH STRONG REMINDER
            if context:
                # Detect if context is FAQ or instructions
                is_faq = "QUESTION:" in context and "ANSWER:" in context
                
                if is_faq:
                    system_content += f"""

=== RETRIEVED FAQ (PROVIDE THIS ANSWER) ===
{context}
=== END FAQ ===

⚠️ THIS IS A FAQ - NOT INSTRUCTIONS!
The user asked an informational question like "What is..." or "Tell me about..."
The FAQ above has the complete answer in the ANSWER section.

Your response should:
1. Start directly with the answer (no greeting)
2. Provide the complete ANSWER from the FAQ
3. Keep the formatting (bullet points, bold text, etc.)
4. DO NOT add step-by-step access instructions
5. DO NOT say "Here's how to access..."

Example:
User: "What is Immediate Access?"
FAQ: "Immediate Access is California Baptist University's program..."
✓ CORRECT: "Immediate Access is California Baptist University's program..."
✗ WRONG: "Here's how to access Immediate Access: 1. Log into..."
"""
                else:
                    system_content += f"""

=== RETRIEVED DOCUMENTATION (USE THIS!) ===
{context}
=== END DOCUMENTATION ===

⚠️ CRITICAL REMINDER: These are step-by-step instructions!
- You MUST use this documentation to answer
- You MUST skip any greeting
- Start with: "Here's how to..." 
- Provide the step-by-step instructions from the documentation
"""
            else:
                system_content += """

No documentation was retrieved. Handle based on the query type:
- If just "Hi"/"Hello" → Give greeting
- If specific question → Answer from your knowledge or ask for details
"""
            
            system_content += """

BEFORE YOU RESPOND, ASK YOURSELF:
1. Is there FAQ documentation above? 
   → YES: Provide the FAQ ANSWER directly, NO GREETING
2. Is there instruction documentation above?
   → YES: Provide those steps, NO GREETING
3. No documentation?
   → Is it just "Hi"? Give greeting
   → Otherwise: Answer or ask for clarification

Now respond:
"""

            messages = [{"role": "system", "content": system_content}]

            # Add history
            if history:
                for msg in history:
                    if "role" in msg and "content" in msg:
                        messages.append(msg)

            # Add current message
            messages.append({"role": "user", "content": message})

            payload = {
                "model": "llama3.2",
                "messages": messages,
                "stream": False
            }

            response = requests.post(OLLAMA_URL, json=payload, timeout=180)
            response.raise_for_status()

            return response.json()["message"]["content"]
        
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Ollama request failed: {e}")
            return "I'm having trouble connecting right now. Please try again in a moment."