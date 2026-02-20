import requests, time, re

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = """You are Lance, the Campus Store AI Assistant for California Baptist University.

=== ⚠️ ABSOLUTE RULE #1 (OVERRIDE EVERYTHING) ===

IF documentation context appears below (between tags):
→ START IMMEDIATELY with the answer from the documentation
→ DO NOT say \"Hi! I'm Lance...\"
→ DO NOT ask \"What can I help you with today?\"
→ DO NOT provide a greeting of any kind
→ Jump straight to the answer

This applies EVEN IF it's the first message in the conversation.

=== When to Give a Greeting ===

ONLY give a greeting when ALL of these are true:
1. User ONLY says \"Hi\", \"Hello\", or \"Hey\" with nothing else
2. There is NO documentation context below
3. The user hasn't asked a specific question

=== Response Formats ===

**With Instructions:**
\"Here's how to access [platform]:

1. [Step from documentation]
2. [Step from documentation]
...\"

**With FAQ:**
\"[Direct answer from FAQ, preserving formatting]\"

**Pure Greeting (Rare):**
\"Hi! I'm Lance, your Campus Store AI Assistant. I can help with Immediate Access, textbook policies, and troubleshooting. What can I help you with today?\"

**Need Clarification:**
\"I can help with [topic]! Could you specify: [specific question]?\"
"""

QUESTION = "I can't access to Cengage MindTap"

MODELS = [
    "anpigon/qwen2.5-7b-instruct-kowiki:latest",
    "mistral:7b",
    "nemotron-3-nano:30b-cloud",
    "qwen3-next:80b-cloud",
    "glm-5:cloud",
    "gpt-oss:120b-cloud",
    "granite4:latest",
    "llama3:8b",
    "llama3.2:latest",
]

results = []
for model in MODELS:
    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": QUESTION})
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }
    start = time.time()
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
        resp.raise_for_status()
        answer = resp.json()["message"]["content"]
    except Exception as e:
        answer = f"Error: {e}"
    elapsed = time.time() - start
    # Simple quality check: does answer mention Cengage or MindTap?
    if re.search(r"cengage|mindtap", answer, re.I):
        quality = "Relevant"
    else:
        quality = "Irrelevant"
    results.append({"model": model, "time": f"{elapsed:.2f}s", "quality": quality, "answer_preview": answer[:200].replace("\n", " ")})

# Print summary table
print("Model\t\tTime\tQuality")
for r in results:
    print(f"{r['model']}\t{r['time']}\t{r['quality']}")

# Optionally, show each answer preview
print("\nAnswer previews (first 200 chars):")
for r in results:
    print(f"--- {r['model']} ---")
    print(r['answer_preview'])
    print()
