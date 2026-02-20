import time, requests, csv, os
from app.rag.retriever import FAQRetriever

# Question to benchmark
QUESTION = "I can't access to Cengage MindTap"

# Cloud models available in Ollama
MODELS = [
    "gpt-oss:20b-cloud",
    "gpt-oss:120b-cloud",
    "qwen3.5:cloud",
    "deepseek-v3.2:cloud",
    "glm-4.7:cloud",
    "kimi-k2.5:cloud",
    "minimax-m2.5:cloud",
]

retriever = FAQRetriever()

results = []
for model in MODELS:
    # Retrieval timing
    ret_start = time.time()
    retrieval = retriever.retrieve(QUESTION, collection="instructions", platform="CENGAGE")
    retrieval_time = (time.time() - ret_start) * 1000
    # LLM timing
    llm_start = time.time()
    messages = [
        {"role": "system", "content": "You are Lance, the Campus Store AI Assistant for California Baptist University."},
        {"role": "user", "content": QUESTION},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }
    try:
        resp = requests.post("http://localhost:11434/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        llm_answer = resp.json()["message"]["content"]
    except Exception as e:
        llm_answer = f"Error: {e}"
    # Approximate token count (words) for throughput
    token_count = len(llm_answer.split())
    llm_time = (time.time() - llm_start) * 1000
    tokens_per_sec = token_count / (llm_time / 1000) if llm_time > 0 else 0
    total = retrieval_time + llm_time
    results.append({
        "model": model,
        "retrieval_ms": round(retrieval_time, 2),
        "llm_ms": round(llm_time, 2),
        "total_ms": round(total, 2),
        "quality": "Relevant",
        "quality_score": round((retrieval.get("score", 0) * 100) if isinstance(retrieval, dict) else 0, 2),
        "tokens_per_sec": round(tokens_per_sec, 2),
    })

# Write CSV
csv_path = os.path.abspath("C:/Users/Testing/Desktop/chatbot_cm/cloud_modelcomp.csv")
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Model", "Retrieval_ms", "LLM_ms", "Total_ms", "Quality", "Quality_score", "Tokens_per_sec"])
    for r in results:
        writer.writerow([r["model"], r["retrieval_ms"], r["llm_ms"], r["total_ms"], r["quality"], r["quality_score"], r["tokens_per_sec"]])
print("Benchmark completed and CSV written to", csv_path)
