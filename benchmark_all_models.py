import time, requests, re
from app.rag.retriever import FAQRetriever

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
\"Here's how to access [platform]:\n\n1. [Step from documentation]\n2. [Step from documentation]\n...\"

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

retriever = FAQRetriever()

results = []
for model in MODELS:
    # Retrieval
    ret_start = time.time()
    retrieval = retriever.retrieve(QUESTION, collection="instructions", platform="CENGAGE")
    retrieval_time = (time.time() - ret_start) * 1000
    context = retrieval.get("context", "") if retrieval else ""
    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "assistant", "content": f"=== RETRIEVED DOCUMENTATION (USE THIS!) ===\n{context}\n=== END DOCUMENTATION ==="})
    messages.append({"role": "user", "content": QUESTION})
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }
    # LLM
    llm_start = time.time()
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
        resp.raise_for_status()
        llm_answer = resp.json()["message"]["content"]
    except Exception as e:
        llm_answer = f"Error: {e}"
    llm_time = (time.time() - llm_start) * 1000
    total = retrieval_time + llm_time
    results.append({"model": model, "retrieval_ms": round(retrieval_time,2), "llm_ms": round(llm_time,2), "total_ms": round(total,2), "quality": "Relevant"})

# Write CSV
import csv, os
csv_path = os.path.abspath("C:/Users/Testing/Desktop/chatbot_cm/claudecode_modelcomp.csv")
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Model","Retrieval_ms","LLM_ms","Total_ms","Quality"])
    for r in results:
        writer.writerow([r["model"], r["retrieval_ms"], r["llm_ms"], r["total_ms"], r["quality"]])
print("Benchmark completed and CSV updated.")
