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
                
                print("\n" + "="*50)
                print("[DEBUG] User Message:", message)
                if context:
                    print("[DEBUG] Context Preview:", context[:500] + "..." if len(context) > 500 else context)
                print("="*50 + "\n")

                # Build system prompt with clear hierarchy
                system_content = """You are Lance, the Campus Store AI Assistant for California Baptist University.

            === CRITICAL INSTRUCTION HIERARCHY ===

            PRIORITY 1: If documentation context exists below, USE IT IMMEDIATELY
            - Provide step-by-step instructions from the documentation
            - Format as a numbered list
            - DO NOT ask clarifying questions when you have the full solution

            PRIORITY 2: Detect the query type
            - Simple greeting ("Hi", "Hello" alone) → Give warm introduction
            - Access issue with context → Provide steps from documentation
            - Access issue without context → Ask for specific information needed
            - General question → Answer helpfully

            PRIORITY 3: Response formatting
            - Use clear numbered steps for instructions
            - Be direct and helpful
            - Stay focused on Campus Store and Immediate Access

            === RESPONSE TEMPLATES ===

            Template 1 - Access Issue WITH Documentation:
            "Here's how to access [platform]:
            1. [Step 1 from documentation]
            2. [Step 2 from documentation]
            3. [Step 3 from documentation]
            ..."

            Template 2 - Simple Greeting:
            "Hi! I'm Lance, your Campus Store AI Assistant. I can help with Immediate Access, textbook policies, and troubleshooting. What can I help you with today?"

            Template 3 - Need More Info:
            "I can help with [platform]! Could you specify: [what specific info is needed]?"

            === CRITICAL EXAMPLES ===

            Example A (HAS CONTEXT):
            User: "I can't access Cengage MindTap"
            Context: [Full MindTap access steps 1-6]
            ✓ CORRECT: "Here's how to access Cengage MindTap: 1. Log in to Blackboard..."
            ✗ WRONG: "Hi! I'm Lance... What's not working?" ← NEVER when you have context!

            Example B (NO CONTEXT - GREETING):
            User: "Hi"
            Context: None
            ✓ CORRECT: "Hi! I'm Lance, your Campus Store AI Assistant..."

            Example C (NO CONTEXT - UNCLEAR):
            User: "Help with Cengage"
            Context: None
            ✓ CORRECT: "I can help with Cengage! Are you trying to access a textbook or MindTap?"
            """
                
                # Add system hint if provided
                if system_hint:
                    system_content += f"\n{system_hint}\n"
                
                # Add context if available
                if context:
                    system_content += f"""
            === RETRIEVED DOCUMENTATION (USE THIS!) ===
            {context}
            === END DOCUMENTATION ===

            INSTRUCTION: The documentation above contains the solution to the user's question.
            Extract the step-by-step instructions and present them clearly.
            DO NOT ignore this documentation.
            DO NOT ask "what's not working" when steps are provided.
            Format as: "Here's how to [action]: 1. [step] 2. [step]..."
            """
                
                system_content += """
            FINAL CHECK BEFORE RESPONDING:
            1. Is there documentation above? → If YES, provide those steps
            2. Is user just saying "Hi"? → If YES, give greeting
            3. Otherwise → Ask for needed information

            Now respond appropriately:
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
        
        # except requests.exceptions.RequestException as e:
        #     print(f"[ERROR] Ollama request failed: {e}")
        #     return "I'm having trouble connecting right now. Please try again in a moment."     except requests.exceptions.RequestException as e: