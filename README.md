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

### Response paths

**Path 1 — Deterministic routing (70–90% of queries):**
Keyword detection + FAISS retrieval + direct answer. No LLM involved. Returns in 1–50ms. Handles all known platform access issues, FAQ questions, browser cache, returns policy, and Campus Store information.

**Path 2 — Grounded LLM fallback (10–30% of queries):**
When no deterministic route matches, Lance retrieves the top relevant FAISS chunks and passes them as grounded context to the LLM. The LLM answers only from that context. If no relevant context is found (confidence < 0.30), Lance escalates to the Campus Store contact instead of hallucinating.

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
|   |-- llm/
|   |   `-- llama_client.py         # Ollama LLM client
|   |-- rag/
|   |   |-- __init__.py
|   |   |-- config.py               # Centralized config with env var overrides
|   |   |-- ingest.py               # Chunking + FAISS ingestion pipeline
|   |   |-- retriever.py            # FAISS retrieval + singleton get_retriever()
|   |   |-- model.py                # Lazy embedding model loader
|   |   |-- metadata.py             # Chunk metadata schemas + validation
|   |   `-- platforms.yaml          # Single source of truth for platform keywords
|   |-- schemas/
|   |   `-- chat.py                 # ChatRequest / ChatResponse Pydantic models
|   `-- utils/
|       `-- logging_config.py       # Centralized logging setup
|-- data/
|   |-- faqs/                       # FAQ .txt source files + compiled faiss_index
|   `-- instructions/               # Per-platform instruction .txt files + faiss indexes
|-- ui/
|   |-- src/
|   |   |-- App.tsx                 # Main React app, session management, debug toggle
|   |   |-- faqConfig.ts            # FAQ sidebar content — edit this to update sidebar options
|   |   |-- components/
|   |   |   |-- ChatMessage.tsx     # Message rendering with linkify and LLM badge
|   |   |   |-- FAQSidebar.tsx      # Collapsible FAQ sidebar with auto-send
|   |   |   |-- ChatHeader.tsx
|   |   |   |-- ChatInput.tsx
|   |   |   |-- PDFSidebar.tsx
|   |   |   `-- WelcomeState.tsx
|   |   |-- utils/
|   |   |   `-- linkify.tsx         # Converts URLs and emails to clickable links
|   |   `-- services/
|   |       `-- api.ts              # API service layer
|   `-- firebase.json               # Firebase Hosting config
|-- tests/
|   |-- test_api_platforms.py
|   |-- test_browser_cache.py
|   |-- test_case012.py
|   |-- test_case_006_immediate_access_tab.py
|   |-- test_ingest.py
|   `-- test_retriever.py
|-- research/
|   |-- email_issue_log.md          # Case-by-case log of real student email scenarios
|   `-- lance_hardware_analysis.md  # Hardware procurement analysis and recommendation
|-- emails/                         # Source .msg email files used for testing
|-- scripts/
|   `-- validate_indexes.py         # CI/local index validation script
|-- .github/
|   `-- workflows/
|       `-- ci.yml
|-- lance_admin_ui.html             # Admin UI: Add/Remove content, Apply Changes, Debug Mode
|-- lance_add_content.py            # CLI script for content addition (multi-PDF support)
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
MAX_CONCURRENT_LLM_REQUESTS=2
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

3. Start the React frontend:
   ```bash
   cd ui
   npm install
   npm run dev
   ```

4. Rebuild FAISS indexes manually if needed:
   ```bash
   python -m app.rag.ingest
   ```

5. Validate indexes:
   ```bash
   python scripts/validate_indexes.py
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
- **Add Content**: Upload a `.txt` file and optional PDF guides. Saves the file, rebuilds the FAISS index, uploads PDFs to Firebase Storage, and creates the `txt_to_pdf_map` entry in Firestore automatically.
- **Remove Content**: Select an existing file from a dropdown and click Remove. Deletes the file, rebuilds the FAISS index, and cleans up the Firestore `txt_to_pdf_map` entry.
- **Debug Mode**: Toggle the global default debug mode for all new sessions. When enabled, new sessions skip deterministic routing and use the grounded LLM fallback for every query. Useful for quality testing and comparison.

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

## 6. FAQ Sidebar

The chat UI includes a collapsible FAQ sidebar that lets students browse predefined issue categories and select an option that auto-sends to Lance.

To update the sidebar options, edit `ui/src/faqConfig.ts`. This file is the single source of truth for all sidebar categories, subcategories, and options. No other files need to be changed.

After editing `faqConfig.ts`:
```bash
cd ui
npm run build
firebase deploy --only hosting
```

---

## 7. Debug Mode Toggle

A per-session debug toggle is available in the chat UI header ("Auto mode" / "LLM mode" pill).

- **Auto mode**: normal deterministic routing — fast, uses FAISS directly
- **LLM mode**: skips deterministic routing, every query goes through grounded RAG + LLM

Use this to diagnose response quality issues:
- If both modes give a wrong answer → content gap (no relevant `.txt` file exists)
- If LLM mode succeeds but auto mode fails → routing bug in `app/main.py`

The Admin UI can set the global default debug mode for all new sessions.

Session-level API:
```bash
# Get current debug mode for a session
GET /session/debug-mode?session_id=<id>

# Set debug mode for a session
POST /session/debug-mode?session_id=<id>&enabled=true
```

---

## 8. Running Tests

```bash
conda run -n campus-store-bot pytest -q
```

All 27 tests should pass. Run from the project root.

---

## 9. How to Add a New Platform

For a standard new platform with its own unique index, no code changes are required:

1. Edit `app/rag/platforms.yaml` and add an entry with `key`, `display_name`, and `keywords`.
2. Add instruction files in `data/instructions/` with platform keywords in the filename or content.
3. Re-ingest:
   ```bash
   python -m app.rag.ingest
   ```

Exception: shared indexes. If the new platform shares an existing FAISS index with another platform, add a mapping to `PLATFORM_RETRIEVAL_KEY` in `app/main.py`.

---

## 10. How to Add a New FAQ

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
3. If the FAQ covers a query type that FAISS may not retrieve correctly, add or adjust the enhanced query override in `app/main.py` in the `GENERAL_FAQ` retrieval block.

---

## 11. Routing Functions Reference

Key detection functions in `app/main.py` and what they do:

| Function | Purpose |
|---|---|
| `is_browser_cache_issue()` | Detects "0 Courses, 0 Materials" / cache symptoms |
| `is_vague_books_missing_query()` | Detects vague "my books aren't showing" → VitalSource clarification |
| `is_blank_page_query()` | Detects blank page / broken link symptoms → VitalSource clarification |
| `is_general_ia_question()` | Detects general IA program questions with no platform → LLM fallback |
| `is_access_code_question()` | Detects access code questions → LLM fallback |
| `is_login_account_issue()` | Detects account/login issues → platform clarification |
| `is_ia_enrollment_query()` | Detects "is my book free / included in IA?" → deterministic escalation |
| `is_textbook_return_query()` | Routes textbook return questions to correct FAQ |
| `is_merchandise_return_query()` | Routes merchandise return questions to correct FAQ |
| `is_technology_return_query()` | Routes technology return questions to correct FAQ |
| `is_out_of_scope_query()` | Detects non-Campus-Store queries (library, financial aid, etc.) → escalation |
| `is_opt_out_policy_question()` | Routes opt-out policy questions to FAQ |
| `retrieve_grounding_context()` | Retrieves top FAISS chunks for LLM fallback grounding |
| `build_grounded_prompt()` | Builds strict grounded prompt for LLM fallback |

---

## 12. Content Files Reference

### FAQ files (`data/faqs/`)

| File | Covers |
|---|---|
| `ia_overview.txt` | What is Immediate Access |
| `ia_access_issue.txt` | IA opt-out but can't access textbook |
| `ia_opt_out_physical_textbooks.txt` | Physical textbook availability after opt-out |
| `ia_bundle_missing_textbook.txt` | Textbook missing from IA bundle |
| `ia_browser_cache_clear_chrome.txt` | Chrome cache clearing steps |
| `ia_browser_cache_clear_chrome_ipad.txt` | Chrome on iPad cache clearing |
| `ia_browser_cache_clear_firefox.txt` | Firefox cache clearing steps |
| `ia_browser_cache_clear_safari.txt` | Safari cache clearing steps |
| `textbook_refund_policy.txt` | Full textbook return policy with semester deadlines |
| `campus_store_hours.txt` | Store hours |
| `campus_store_location.txt` | Address and location |
| `campus_store_delivery_directions.txt` | Delivery and mailing address |
| `campus_store_merchandise.txt` | What the store sells |
| `campus_store_ordering.txt` | How to place orders |
| `campus_store_shipping_policy.txt` | Shipping rates and delivery times |
| `campus_store_instore_pickup.txt` | Pickup window and extension policy |
| `campus_store_digital_codes.txt` | Digital code licensing terms |
| `campus_store_textbook_purchasing_terms.txt` | HEOA compliance and pricing terms |
| `campus_store_refund_merchandise.txt` | Merchandise return policy |
| `campus_store_refund_technology.txt` | Technology and Apple return policy |
| `campus_store_refund_process.txt` | General return process and mailing instructions |
| `campus_store_textbook_rentals.txt` | Rental agreement and return deadlines |

### Instruction files (`data/instructions/`)

Platform-specific step-by-step access instructions for all 12 supported platforms, plus general browser cookie/popup fix guides and in-store digital code redemption instructions.

---

## 13. Email Case Log

Real student email scenarios have been extracted, replayed against the chatbot, and logged in `research/email_issue_log.md`. Cases 001-014 are logged.

Use these cases for regression testing — replay them against Lance and verify responses match expected outcomes before deployment.

---

## 14. Key Architectural Decisions

- **FAISS `IndexFlatIP`**: chosen over IVF/HNSW because the corpus is small enough that exact search is simple and reliable.
- **Deterministic-first responses**: Lance avoids LLM generation wherever possible. The LLM only fires on genuine edge cases.
- **Grounded LLM fallback (Option 3)**: when the LLM does fire, it is constrained to answer only from FAISS-retrieved context. No outside knowledge. Low-confidence retrievals escalate instead of hallucinating.
- **Score gap filtering**: if the top FAISS chunk scores >0.15 above the second chunk, the weaker chunk is dropped before passing context to the LLM to prevent topic contamination.
- **Local LLM**: avoids vendor dependency, API costs, and FERPA concerns for the fallback path.
- **Single source of truth**: `platforms.yaml` drives both ingestion and retrieval routing.
- **Admin UI + hot-reload**: non-technical staff can add or remove content and reload the FAISS index without touching the terminal.
- **FAQ sidebar (`faqConfig.ts`)**: all sidebar content is data-driven from a single config file. Non-technical staff can update options by editing one file.
- **Debug mode toggle**: per-session toggle allows staff to compare deterministic vs LLM responses for any query without affecting other users.
- **Lazy model loading**: the embedding model loads on first use, not at import time, so test collection and app startup are faster.
- **`data/` not in git**: FAQ and instruction `.txt` files live only on the deployment machine. Always run `python -m app.rag.ingest` after pulling to a new machine or after any content changes.