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
    # Retrieval timing and confidence
    ret_start = time.time()
    retrieval = retriever.retrieve(QUESTION, collection="instructions", platform="CENGAGE")
    retrieval_time = (time.time() - ret_start) * 1000
    score = retrieval.get("score", 0.0) if retrieval else 0.0
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
    llm_time = (time.time() - llm_start) * 1000
    total = retrieval_time + llm_time
    # Determine quality descriptor based on retrieval confidence
    quality_percent = round(score * 100, 2)
    if quality_percent >= 80:
        quality_desc = "High"
    elif quality_percent >= 50:
        quality_desc = "Medium"
    else:
        quality_desc = "Low"
    results.append({
        "model": model,
        "retrieval_ms": round(retrieval_time, 2),
        "llm_ms": round(llm_time, 2),
        "total_ms": round(total, 2),
        "quality": "Relevant",
        "quality_percent": quality_percent,
        "quality_desc": quality_desc,
        "performance_summary": f"Retrieval: {retrieval_time:.2f}ms, LLM: {llm_time:.2f}ms, Total: {total:.2f}ms",
    })

# Write CSV with additional quality columns
csv_path = os.path.abspath("C:/Users/Testing/Desktop/chatbot_cm/cloud_modelcomp.csv")
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Model", "Retrieval_ms", "LLM_ms", "Total_ms", "Quality", "Quality_percent", "Quality_desc", "Performance_summary"])
    for r in results:
        writer.writerow([
            r["model"], r["retrieval_ms"], r["llm_ms"], r["total_ms"], r["quality"],
            r["quality_percent"], r["quality_desc"], r["performance_summary"]
        ])
print("Benchmark with quality metrics completed and CSV updated at", csv_path)
