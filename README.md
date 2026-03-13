# Lance: CBU Campus Store Chatbot

## 1. Project Overview

Lance is a FastAPI-based Retrieval-Augmented Generation (RAG) chatbot developed for the CBU Campus Store. Its primary purpose is to assist students with common support inquiries, especially around Immediate Access digital textbook and courseware access issues.

Lance supports 11 publisher platforms:

| Platform | Display Name |
|---|---|
| `cengage` | Cengage MindTap / Cengage Unlimited |
| `mcgraw` | McGraw Hill Connect / ALEKS |
| `pearson` | Pearson MyLab / Mastering |
| `wiley` | WileyPlus |
| `macmillan` | Macmillan Achieve |
| `sage` | Sage Vantage |
| `bedford` | Bedford / VitalSource Bookshelf |
| `clifton` | CliftonStrengths |
| `simucase` | SimuCase |
| `zybooks` | ZyBooks |
| `inquizitive` | InQuizitive (Norton) |

Most responses are **deterministic**: the bot returns FAQ answers or instruction steps directly from retrieved chunks, without sending them through the LLM. The LLM (Ollama `llama3.2`) is only invoked when no high-confidence deterministic path is available.

---

## 2. Project Structure

```
.
├── app/
│   ├── main.py                     # FastAPI routes, chat logic, routing guards (~2700+ lines)
│   ├── pdf_recommendations.py      # Firestore PDF recommendation logic
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── config.py               # Centralized config with env var overrides
│   │   ├── ingest.py               # Chunking + FAISS ingestion pipeline
│   │   ├── retriever.py            # FAISS retrieval + singleton get_retriever()
│   │   ├── model.py                # SentenceTransformer singleton (shared)
│   │   ├── metadata.py             # Chunk metadata schemas + validation
│   │   └── platforms.yaml          # Single source of truth for platform keywords
│   └── utils/
│       └── logging_config.py       # Centralized logging setup
├── data/
│   ├── faqs/                       # FAQ .txt source files + compiled faiss_index
│   │   ├── campus_store_hours.txt
│   │   ├── campus_store_location.txt
│   │   ├── campus_store_delivery_directions.txt
│   │   ├── campus_store_merchandise.txt
│   │   ├── ia_overview.txt
│   │   ├── ia_access_issue.txt
│   │   ├── ia_opt_out_physical_textbooks.txt
│   │   ├── ia_bundle_missing_textbook.txt
│   │   └── textbook_refund_policy.txt
│   └── instructions/               # Per-platform instruction .txt files + faiss indexes
├── tests/
│   ├── test_ingest.py
│   ├── test_retriever.py
│   ├── test_api_platforms.py
│   ├── test_case012.py
│   └── test_case_006_immediate_access_tab.py
├── research/
│   └── email_issue_log.md          # Case-by-case log of real student email scenarios
├── emails/                         # Source .msg email files used for testing
├── scripts/
│   └── validate_indexes.py         # CI index validation script
├── .github/
│   └── workflows/
│       └── ci.yml
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## 3. Environment Setup

```bash
conda activate campus-store-bot
pip install -r requirements.txt
```

---

## 4. Environment Variable Overrides

| Variable | Default | Description |
|---|---|---|
| `FAQ_DIR` | `data/faqs` | Directory of FAQ `.txt` files |
| `INSTRUCTIONS_DIR` | `data/instructions` | Directory of instruction `.txt` files |
| `PLATFORMS_CONFIG` | `app/rag/platforms.yaml` | Path to platform YAML config |
| `MAX_CHUNK_TOKENS` | `400` | Max tokens per chunk before secondary split |
| `RETRIEVAL_TOP_K` | `1` | Top-k FAISS results per query |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model for embeddings |

**Example (PowerShell):**
```powershell
$env:MAX_CHUNK_TOKENS="300"; uvicorn app.main:app --reload
```

---

## 5. Running the System

1. **Start Ollama** (required for LLM fallback path):
   ```bash
   ollama serve
   ollama run llama3.2
   ```

2. **Start the API**:
   ```bash
   uvicorn app.main:app
   ```

3. **Rebuild FAISS indexes** — run after adding or editing any `.txt` file in `data/`:
   ```bash
   python -m app.rag.ingest
   ```

---

## 6. Running Tests

```bash
pytest -q
```

Individual scenario tests (not part of the pytest suite — run directly):
```bash
python tests/test_case012.py
```

---

## 7. Routing & Guardrail Logic

`app/main.py` uses a layered deterministic routing system before falling back to the LLM. Key logic layers, in order of evaluation:

1. **`is_confirmed_materials_issue()`** — Early exit for clear IA access troubleshooting. Skipped for informational/definition queries (e.g. "What is Immediate Access?").
2. **`detect_intent()`** — Classifies message as `IA_ACCESS_ISSUE`, `GENERAL_FAQ`, or falls through. Contains inline guards for opt-out policy, bundle admin, and Blackboard login queries.
3. **IA continuity guard** — In multi-turn sessions with established IA context, follow-up messages are kept on the `IA_ACCESS_ISSUE` path. Excluded for store location, opt-out policy, bundle admin, and merchandise queries.
4. **Special-case GENERAL_FAQ branches** — Deterministic handlers for: store hours, store location, vague campus store queries, book discovery (physical vs. IA), Blackboard/InsideCBU login.
5. **Enhanced retrieval queries** — For certain query types, a rewritten query is sent to FAISS instead of the raw message to improve retrieval accuracy (e.g. "What is Immediate Access?" uses an overview-focused query to pin `ia_overview.txt`).
6. **`is_missing_read_now_button()` + `is_launch_courseware()`** — Separate retrieval paths for "Read Now button missing" vs. "Launch Courseware button" scenarios, with platform-specific FAISS index routing.

---

## 8. How to Add a New Platform

For a standard new platform with its own unique index, no code changes are required:

1. **Edit `app/rag/platforms.yaml`** — add an entry with `key`, `display_name`, and `keywords`.
2. **Add instruction files** — place `.txt` files in `data/instructions/` with platform keywords in the filename or content.
3. **Re-ingest**:
   ```bash
   python -m app.rag.ingest
   ```

**Exception — shared indexes:** If the new platform shares an existing FAISS index with another platform (e.g. VitalSource shares Bedford's index), you must also add a mapping to `PLATFORM_RETRIEVAL_KEY` in `app/main.py`:

```python
PLATFORM_RETRIEVAL_KEY: Dict[str, str] = {
    "VITALSOURCE": "bedford",   # existing
    "NEWPLATFORM": "existing_key",  # add here
}
```

This tells the retriever to look up the correct index when the detected platform name differs from the FAISS index key.

---

## 9. How to Add a New FAQ

1. Create a `.txt` file in `data/faqs/` using the format:
   ```
   QUESTION:
   <question text>

   ANSWER:
   <answer text>
   ```
2. Re-run ingestion:
   ```bash
   python -m app.rag.ingest
   ```
3. If the FAQ covers a query type that FAISS may not retrieve correctly (due to embedding dilution on long chunks), add an enhanced query override in the `GENERAL_FAQ` retrieval block in `app/main.py`.

---

## 10. Email Case Log

Real student email scenarios have been extracted, replayed against the chatbot, and logged in `research/email_issue_log.md`. Cases 001–013 are complete. Each entry includes the transcript, root cause, fix applied, and retest result.

---

## 11. How to Update Merchandise Information

Merchandise query handling is fully wired. To make changes:

| What you want to change | Where to make the change |
|---|---|
| The answer content (product types, hours, contact info) | `data/faqs/campus_store_merchandise.txt` |
| The keywords that trigger merchandise detection (e.g. add "poster", "pennant") | `is_merchandise_query()` in `app/main.py` — add to `phrase_signals` (safe for substring match) or `word_signals` (short words that need whole-word matching to avoid false positives like "hat" inside "what") |
| The FAISS retrieval query used to find the merchandise chunk | `app/main.py` — update the `faq_query` string inside the `if is_merchandise_query(message):` block in the `GENERAL_FAQ` retrieval section |

After editing `campus_store_merchandise.txt`, always re-run ingestion to rebuild the FAISS index:
```bash
python -m app.rag.ingest
```

---

## 12. Key Architectural Decisions

- **FAISS IndexFlatIP** — Chosen over IVF/HNSW because the corpus (~1,000 vectors) is too small for approximate indexes. Revisit as content grows.
- **Deterministic-first** — The bot avoids LLM generation wherever possible. FAQ answers are returned directly from retrieved chunks; the LLM is only used for complex multi-signal IA troubleshooting with no clean FAQ match.
- **Local LLM** — Eliminates vendor dependency and API costs. Hardware upgrade to Mac Studio M4 Max is planned to support concurrent users.
- **Single source of truth** — `platforms.yaml` drives both ingestion and retrieval routing. Platform additions require only a YAML edit and re-index.
