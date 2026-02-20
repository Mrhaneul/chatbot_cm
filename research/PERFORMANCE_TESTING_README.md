# Performance Testing & Model Comparison Guide

## Overview

Your chatbot now includes comprehensive performance tracking to help you compare different LLM models and optimize response times.

## What's New

### 1. Response Time Tracking in API

Every `/chat` response now includes timing metrics:

```json
{
  "reply": "Here's how to access...",
  "source": "INSTR_CENGAGE_SOURCE_0",
  "confidence": 0.66,
  "retrieval_time_ms": 12.45,    // ← NEW: RAG retrieval time
  "llm_time_ms": 1847.23,         // ← NEW: LLM generation time
  "total_time_ms": 1892.18        // ← NEW: Total request time
}
```

### 2. Console Performance Logs

The server now prints timing info for every request:

```
⏱️  PERFORMANCE METRICS:
   Retrieval: 12.45ms
   LLM: 1847.23ms
   Total: 1892.18ms
```

## Files Created

1. **`schemas_chat_updated.py`** - Updated ChatResponse model with timing fields
2. **`main_with_timing.py`** - Updated main.py with performance tracking
3. **`model_comparison.py`** - Script to compare different Ollama models
4. **`test_client.py`** - Simple client to test and display timing info

## Quick Start

### Step 1: Update Your Code

Replace these files in your project:

```bash
# Backup originals first
cp app/schemas/chat.py app/schemas/chat.py.backup
cp app/main.py app/main.py.backup

# Copy updated versions
cp schemas_chat_updated.py app/schemas/chat.py
cp main_with_timing.py app/main.py
```

### Step 2: Restart Your Server

```bash
# Stop current server (Ctrl+C)
# Restart
uvicorn app.main:app --reload
```

### Step 3: Test It!

```bash
# Simple test
python test_client.py "I can't access Cengage MindTap"

# Full test suite
python test_client.py
```

## Comparing Different Models

### Step 1: Pull Models You Want to Test

```bash
# Small and fast
ollama pull llama3.2:1b

# Medium (what you're using now)
ollama pull llama3.2

# Larger and more accurate
ollama pull llama3.1:8b
ollama pull mistral
ollama pull phi3
```

### Step 2: Run Comparison Test

```bash
# Full comparison (tests all available models)
python model_comparison.py

# Quick test of a specific model
python model_comparison.py quick llama3.2
python model_comparison.py quick mistral
```

### Step 3: Review Results

The script will output:
- Average response time for each model
- Tokens per second (throughput)
- Ranking from fastest to slowest
- Saves detailed results to `model_comparison_results.json`

Example output:
```
🏆 Models ranked by speed (fastest to slowest):

1. llama3.2:1b          -   845ms avg  (42.3 tokens/sec)
2. llama3.2             -  1847ms avg  (28.1 tokens/sec)
3. phi3                 -  2134ms avg  (24.7 tokens/sec)
4. mistral              -  2456ms avg  (21.2 tokens/sec)
5. llama3.1:8b          -  3892ms avg  (15.8 tokens/sec)

💡 RECOMMENDATIONS:
   Fastest: llama3.2:1b (845ms)
   Best Balance: llama3.2 (1847ms)
```

### Step 4: Switch Models

Edit `app/llm/llama_client.py`:

```python
class LlamaClient(LLMClient):
    def __init__(self):
        self.base_url = "http://localhost:11434"
        self.model = "llama3.2:1b"  # ← Change this
```

Then restart your server and test again!

## Debug Endpoints

Your API now has additional debug endpoints:

### 1. Test Retrieval Only
```bash
curl -X POST http://localhost:8000/debug/retrieval-only \
  -H "Content-Type: application/json" \
  -d '{"message": "I cant access Cengage MindTap"}'
```

Response:
```json
{
  "elapsed_ms": 12.45,
  "source": "INSTR_CENGAGE_SOURCE_0",
  "score": 0.66,
  "context_preview": "PROBLEM: Student is opted into..."
}
```

### 2. Test LLM Only
```bash
curl -X POST http://localhost:8000/debug/llm-only \
  -H "Content-Type: application/json" \
  -d '{"message": "I cant access Cengage MindTap"}'
```

Response:
```json
{
  "elapsed_ms": 1847.23,
  "reply_length": 342,
  "reply_preview": "Here's how to access Cengage MindTap..."
}
```

### 3. Session Stats
```bash
curl http://localhost:8000/sessions/stats
```

## Interpreting Results

### Good Performance Targets

- **Retrieval**: < 50ms (your system already achieves this!)
- **LLM Generation**: Varies by model
  - Small models (1B-3B): 500-1500ms
  - Medium models (7B-8B): 1500-3000ms
  - Large models (13B+): 3000-6000ms
- **Total**: < 2000ms for good user experience

### Speed vs Quality Tradeoff

| Model Size | Speed | Quality | Best For |
|------------|-------|---------|----------|
| 1B-3B | ⚡⚡⚡⚡ | ⭐⭐ | High-traffic, simple queries |
| 7B-8B | ⚡⚡⚡ | ⭐⭐⭐⭐ | **Production balance** |
| 13B+ | ⚡⚡ | ⭐⭐⭐⭐⭐ | Complex reasoning, low traffic |

### Recommendations

For your Campus Store chatbot:
1. **Start with**: `llama3.2` (3B) - Good balance
2. **If too slow**: Try `llama3.2:1b` - Faster but less accurate
3. **If quality issues**: Upgrade to `llama3.1:8b` or `mistral`

## Performance Optimization Tips

### 1. Monitor Your Bottlenecks

Look at the timing breakdown:
- If **retrieval is slow** (>100ms): Check FAISS index optimization
- If **LLM is slow** (>3000ms): Try a smaller model
- If **total is slow**: Check for network latency or memory issues

### 2. Test Under Load

```bash
# Install Apache Bench
sudo apt-get install apache2-utils

# Test 100 requests, 10 concurrent
ab -n 100 -c 10 -p query.json -T application/json http://localhost:8000/chat
```

### 3. Model Selection Strategy

```
User Traffic          Recommended Model
───────────────────────────────────────
< 10 users/hour    →  llama3.1:8b (quality)
10-50 users/hour   →  llama3.2 (balance)
50-200 users/hour  →  llama3.2:1b (speed)
200+ users/hour    →  Consider API service
```

## Example Workflow

```bash
# 1. Pull models to test
ollama pull llama3.2
ollama pull llama3.2:1b
ollama pull mistral

# 2. Run comparison
python model_comparison.py

# 3. Choose fastest model that meets quality needs
# Edit llama_client.py to use chosen model

# 4. Test with real queries
python test_client.py

# 5. Monitor in production
tail -f logs/chatbot.log | grep "PERFORMANCE METRICS"
```

## Troubleshooting

### Models Not Found
```bash
# List available models
ollama list

# Pull missing models
ollama pull llama3.2
```

### Slow Performance
1. Check system resources: `htop` or `top`
2. Verify GPU usage if available: `nvidia-smi`
3. Try smaller model: `llama3.2:1b`

### High Memory Usage
- Ollama keeps models in memory
- Unload unused models: `ollama rm <model>`
- Check memory: `free -h`

## Next Steps

1. ✅ Add timing to your API responses
2. ✅ Test different models
3. ⏭️ Monitor performance in production
4. ⏭️ Set up alerting for slow responses
5. ⏭️ Consider caching for common queries

## Questions?

- Check model documentation: https://ollama.com/library
- Ollama performance guide: https://github.com/ollama/ollama/blob/main/docs/faq.md
- Your RAG system is already optimized! 🎉
