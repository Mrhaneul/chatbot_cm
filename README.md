# Lance: CBU Campus Store Chatbot

## 1. Project Overview

Lance is a FastAPI-based Retrieval-Augmented Generation (RAG) chatbot developed for the CBU Campus Store. Its primary purpose is to assist students with common support inquiries, especially around Immediate Access digital textbook and courseware access issues.

Lance supports 12 publisher platforms:

| Platform | Display Name |
|---|---|
| `cengage` | Cengage MindTap |
| `mcgraw` | McGraw Hill Connect |
| `pearson` | Pearson MyLab / Mastering |
| `wiley` | WileyPLUS |
| `macmillan` | Macmillan Achieve |
| `sage` | SAGE Vantage |
| `bedford` | Bedford / VitalSource Bookshelf |
| `clifton` | CliftonStrengths |
| `simucase` | SimuCase |
| `zybooks` | ZyBooks |
| `inquizitive` | InQuizitive / Norton |
| `stukent` | Stukent |

Most responses are deterministic: the bot returns FAQ answers or instruction steps directly from retrieved chunks, without sending them through the LLM. The LLM (Ollama `llama3.2`) is only invoked when no high-confidence deterministic path is available.

---

## 2. Project Structure

```text
.
|-- app/
|   |-- main.py                     # FastAPI routes, chat logic, routing guards
|   |-- admin.py                    # Admin API router (add/remove content, reload index)
|   |-- admin_auth.py               # HTTP Basic Auth for admin routes
|   |-- firebase_config.py          # Firebase initialization (env-driven)
|   |-- pdf_recommendations.py      # Firestore PDF recommendation logic
|   |-- rag/
|   |   |-- __init__.py
|   |   |-- config.py               # Centralized config with env var overrides
|   |   |-- ingest.py               # Chunking + FAISS ingestion pipeline
|   |   |-- retriever.py            # FAISS retrieval + singleton get_retriever()
|   |   |-- model.py                # Lazy embedding model loader
|   |   |-- metadata.py             # Chunk metadata schemas + validation
|   |   `-- platforms.yaml          # Single source of truth for platform keywords
|   `-- utils/
|       `-- logging_config.py       # Centralized logging setup
|-- data/
|   |-- faqs/                       # FAQ .txt source files + compiled faiss_index
|   `-- instructions/               # Per-platform instruction .txt files + faiss indexes
|-- tests/
|   |-- test_api_platforms.py
|   |-- test_browser_cache.py
|   |-- test_case012.py
|   |-- test_case_006_immediate_access_tab.py
|   |-- test_ingest.py
|   `-- test_retriever.py
|-- research/
|   `-- email_issue_log.md          # Case-by-case log of real student email scenarios
|-- emails/                         # Source .msg email files used for testing
|-- scripts/
|   `-- validate_indexes.py         # CI/local index validation script
|-- .github/
|   `-- workflows/
|       `-- ci.yml
|-- lance_admin_ui.html             # Admin UI: Add/Remove content, Apply Changes
|-- lance_add_content.py            # CLI script for content addition (multi-PDF support)
|-- add_instruction.py              # CLI script for platform instruction addition
|-- requirements.txt
|-- pytest.ini
`-- README.md
```

---

## 3. Environment Setup

```bash
conda activate campus-store-bot
pip install -r requirements.txt
```

### .env setup

Required `.env` variables:

```env
LANCE_ADMIN_USER=admin
LANCE_ADMIN_PASSWORD=your_secure_password
FIREBASE_STORAGE_BUCKET=lance-cbu.firebasestorage.app
```

Optional `.env` overrides:

```env
FIREBASE_SERVICE_ACCOUNT_PATH=app/firebase-service-account.json
FAQ_DIR=data/faqs
INSTRUCTIONS_DIR=data/instructions
PLATFORMS_CONFIG=app/rag/platforms.yaml
MAX_CHUNK_TOKENS=400
RETRIEVAL_TOP_K=1
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

---

## 4. Running the System

1. Start Ollama (required for the LLM fallback path):
   ```bash
   ollama serve
   ollama run llama3.2
   ```

2. Start the API:
   ```bash
   uvicorn app.main:app --reload
   ```

3. Rebuild FAISS indexes manually if needed:
   ```bash
   python -m app.rag.ingest
   ```

`app/main.py` calls `load_dotenv()` at startup, so `.env` is loaded automatically.

Firebase credentials:
- Place your service account key at: `app/firebase-service-account.json`
- Or set `FIREBASE_SERVICE_ACCOUNT_PATH` in `.env` to override the path

---

## 5. Admin UI

Access at: `http://localhost:8000/admin`

Protected by HTTP Basic Auth. Set `LANCE_ADMIN_USER` and `LANCE_ADMIN_PASSWORD` in `.env`.

Tabs:
- Add Content: Upload a `.txt` file and optional PDF guides. Saves the file, rebuilds the FAISS index, uploads PDFs to Firebase Storage, and creates the `txt_to_pdf_map` entry in Firestore automatically.
- Remove Content: Select an existing file from a dropdown and click Remove. Deletes the file, rebuilds the FAISS index, and cleans up the Firestore `txt_to_pdf_map` entry.

Apply Changes button (bottom bar):
- Hot-reloads the FAISS index into the running process without restarting `uvicorn`.
- If hot-reload fails, on-screen instructions guide staff through a manual restart.

CLI alternative (`lance_add_content.py`):

```bash
python lance_add_content.py --type faq --txt data/faqs/your_file.txt

python lance_add_content.py --type faq \
    --txt data/faqs/your_file.txt \
    --pdf docs/guide1.pdf --pdf-label "Guide 1 Title" \
    --pdf docs/guide2.pdf --pdf-label "Guide 2 Title"
```

---

## 6. Running Tests

```bash
pytest -q
```

`tests/test_browser_cache.py` is part of the normal pytest suite and is collected automatically.

Scenario coverage such as `tests/test_case_006_immediate_access_tab.py` also runs through pytest and is no longer a standalone-only check.

---

## 7. How to Add a New Platform

For a standard new platform with its own unique index, no code changes are required:

1. Edit `app/rag/platforms.yaml` and add an entry with `key`, `display_name`, and `keywords`.
2. Add instruction files in `data/instructions/` with platform keywords in the filename or content.
3. Re-ingest:
   ```bash
   python -m app.rag.ingest
   ```

Exception: shared indexes. If the new platform shares an existing FAISS index with another platform, add a mapping to `PLATFORM_RETRIEVAL_KEY` in `app/main.py`.

---

## 8. How to Add a New FAQ

1. Create a `.txt` file in `data/faqs/` using the format:
   ```text
   QUESTION:
   <question text>

   ANSWER:
   <answer text>
   ```
2. Re-run ingestion:
   ```bash
   python -m app.rag.ingest
   ```
3. If the FAQ covers a query type that FAISS may not retrieve correctly, add or adjust the enhanced query override in `app/main.py`.

---

## 9. Email Case Log

Real student email scenarios have been extracted, replayed against the chatbot, and logged in `research/email_issue_log.md`. Cases 001-013 are complete.

The browser cache case for Devina Robles, where VitalSource showed `0 Courses, 0 Materials`, was resolved and content was added through the admin UI as four browser-specific FAQ files.

---

## 10. How to Update Merchandise Information

Merchandise query handling is fully wired. To make changes:

| What you want to change | Where to make the change |
|---|---|
| The answer content (product types, hours, contact info) | `data/faqs/campus_store_merchandise.txt` |
| The keywords that trigger merchandise detection | `is_merchandise_query()` in `app/main.py` |
| The FAISS retrieval query used to find the merchandise chunk | `app/main.py` inside the `GENERAL_FAQ` merchandise retrieval block |

After editing `campus_store_merchandise.txt`, re-run ingestion:

```bash
python -m app.rag.ingest
```

---

## 11. Key Architectural Decisions

- FAISS `IndexFlatIP`: chosen over IVF/HNSW because the corpus is still small enough that exact search is simple and reliable.
- Deterministic-first responses: the bot avoids LLM generation wherever possible.
- Local LLM: avoids vendor dependency and API costs for the fallback path.
- Single source of truth: `platforms.yaml` drives both ingestion and retrieval routing.
- Admin UI + hot-reload: non-technical staff can add or remove content and reload the FAISS index without touching the terminal. The admin UI writes to both the local filesystem and Firestore automatically.
- Lazy model loading: the embedding model loads on first use, not at import time, so test collection and app startup are faster.
