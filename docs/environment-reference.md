# Lance Environment Reference

This document lists the environment variables Lance reads at runtime. Keep real values in `.env`; do not commit secrets or service account keys.

## Required For Admin Access

| Variable | Purpose | Example |
|---|---|---|
| `LANCE_ADMIN_USER` | Admin UI username. Defaults to `admin` if omitted. | `admin` |
| `LANCE_ADMIN_PASSWORD` | Admin UI password. Must be set before using `/admin`. | `change-me` |

## LLM And Ollama

| Variable | Purpose | Default |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama API base URL. Keep local unless IT changes the deployment topology. | `http://127.0.0.1:11434` |
| `PRIMARY_LLM_MODEL` | Primary Ollama model for normal generation. | `gemma4:e4b` |
| `FALLBACK_LLM_MODEL` | Fallback Ollama model. | `gemma4:e2b` |
| `RAG_TEMPERATURE` | LLM temperature for grounded answers. | `0.1` |
| `RAG_NUM_PREDICT` | Maximum generated tokens for grounded answers. | `1024` |
| `MAX_CONCURRENT_LLM_REQUESTS` | LLM concurrency cap. Keep conservative on local hardware. | `2` |

## Retrieval And Indexing

| Variable | Purpose | Default |
|---|---|---|
| `FAQ_DIR` | FAQ source and index directory. | `data/faqs` |
| `INSTRUCTIONS_DIR` | Instruction source and index directory. | `data/instructions` |
| `PLATFORMS_CONFIG` | Ingest/retrieval platform keyword file. | `app/rag/platforms.yaml` |
| `MAX_CHUNK_TOKENS` | Approximate chunk size during ingestion. | `400` |
| `RETRIEVAL_TOP_K` | Number of initial retrieval hits. | `1` |
| `GROUNDING_TOP_K` | Number of chunks used by grounding context helpers. | `3` |
| `MAX_PARENT_SOURCES` | Maximum parent documents expanded from retrieved chunks. | `3` |
| `MAX_EXPANDED_CONTEXT_CHARS` | Context expansion character cap. | `12000` |
| `EMBEDDING_MODEL` | Sentence transformer model name. | `all-MiniLM-L6-v2` |
| `FAQ_DIRECT_MIN_CONFIDENCE` | Minimum confidence for direct FAQ responses. | `0.2` |
| `ENABLE_GROUNDING_VERIFIER` | Enables post-generation grounding verifier. | `true` |

## Safety

| Variable | Purpose | Default |
|---|---|---|
| `ENABLE_SAFETY_FILTER` | Enables the Phase 1 safety gate. Keep enabled in production. | `true` |
| `ENABLE_SAFETY_CLASSIFIER` | Enables optional LLM safety classifier after deterministic checks. | `true` |

## Admin Content And Feedback Storage

| Variable | Purpose | Default |
|---|---|---|
| `CONTENT_ARCHIVE_DIR` | Timestamped backups and removed content archive. | `data/_archive` |
| `FEEDBACK_DIR` | Local JSONL feedback storage directory. | `data/feedback` |

The JSONL feedback store is an MVP for a single-process deployment. For high-concurrency or multi-worker production, migrate feedback to SQLite, Firestore, or another transactional store.

## Firebase

| Variable | Purpose | Default |
|---|---|---|
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Path to the Firebase service account key. | `app/firebase-service-account.json` |
| `FIREBASE_STORAGE_BUCKET` | Firebase Storage bucket for PDF guides. | `lance-cbu.firebasestorage.app` |

`app/firebase-service-account.json` must never be committed.

## HTTP And Debug

| Variable | Purpose | Default |
|---|---|---|
| `CORS_ORIGINS` | Comma-separated allowed frontend origins. | `http://localhost:3000` |
| `ENABLE_DEBUG_ROUTES` | Enables developer-only debug endpoints. Keep disabled in production. | `false` |

## Production Defaults

Recommended production values:

```env
ENABLE_SAFETY_FILTER=true
ENABLE_SAFETY_CLASSIFIER=true
ENABLE_GROUNDING_VERIFIER=true
ENABLE_DEBUG_ROUTES=false
MAX_CONCURRENT_LLM_REQUESTS=2
```
