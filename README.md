# Lance: CBU Campus Store Chatbot

## 1. Project Overview

Lance is a FastAPI-based Retrieval-Augmented Generation (RAG) chatbot developed for the CBU Campus Store. Its primary purpose is to assist students with troubleshooting common inquiries, particularly regarding Immediate Access digital textbook and courseware access issues across 11 platforms: Cengage MindTap, McGraw Hill Connect, Pearson MyLab/Mastering, WileyPlus, Macmillan Achieve, Sage Vantage, Bedford Bookshelf, CliftonStrengths, SimuCase, ZyBooks, and InQuizitive.

## 2. Project Structure

```
.
├── app/
│   ├── main.py                     # FastAPI routes and chat logic (2600+ lines)
│   ├── pdf_recommendations.py      # Firestore PDF recommendation logic
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── config.py               # Centralized config with env var overrides
│   │   ├── ingest.py               # PDF-to-FAISS ingestion pipeline
│   │   ├── retriever.py            # FAISS retrieval + singleton get_retriever()
│   │   ├── model.py                # SentenceTransformer singleton
│   │   ├── metadata.py             # Chunk metadata schemas + validation
│   │   └── platforms.yaml          # Single source of truth for platform keywords
│   └── utils/
│       └── logging_config.py       # Centralized logging setup
├── tests/
│   ├── test_ingest.py
│   ├── test_retriever.py
│   └── test_api_platforms.py
├── scripts/
│   └── validate_indexes.py         # CI index validation script
├── data/
│   ├── faqs/                       # FAQ .txt files + faiss_index
│   └── instructions/               # Platform instruction .txt files + faiss indexes
├── .github/
│   └── workflows/
│       └── ci.yml
├── requirements.txt
├── pytest.ini
└── README.md
```

## 3. Environment Setup

It is recommended to use a Conda environment for consistent dependency management.

```bash
conda activate campus-store-bot
```

To install Python dependencies:

```bash
pip install -r requirements.txt
```

## 4. Environment Variable Overrides

The chatbot's behavior and underlying RAG components can be configured using environment variables. This allows for flexible deployment and easy adjustments without modifying code.

| Variable           | Default Value                | Description                                                                  |
| :----------------- | :--------------------------- | :--------------------------------------------------------------------------- |
| `FAQ_DIR`          | `data/faqs`                  | Directory containing FAQ `.txt` files for ingestion.                         |
| `INSTRUCTIONS_DIR` | `data/instructions`          | Directory containing instruction `.txt` files for ingestion.                 |
| `PLATFORMS_CONFIG` | `app/rag/platforms.yaml`     | Path to the YAML file defining platform configurations. (Auto-resolved relative to `app/rag/config.py`.) |
| `MAX_CHUNK_TOKENS` | `400`                        | Maximum tokens per chunk before secondary split during ingestion.            |
| `RETRIEVAL_TOP_K`  | `1`                          | Number of top-k FAISS results to return per query.                           |
| `EMBEDDING_MODEL`  | `all-MiniLM-L6-v2`           | Name of the SentenceTransformer model used for embeddings.                   |

**Example Override (PowerShell):**
```powershell
$env:MAX_CHUNK_TOKENS="300"; $env:FAQ_DIR="custom/faqs"; uvicorn app.main:app --reload
```

## 5. Running the System

Ensure Ollama is running and the `llama3.2` model is available locally before starting the API.

1.  **Start Ollama**:
    ```bash
    ollama serve
    ollama run llama3.2
    ```
2.  **Start the API**:
    ```bash
    uvicorn app.main:app --reload
    ```
3.  **Rebuild FAISS Indexes**: Run this command after adding or editing any `.txt` files in `data/`.
    ```bash
    python -m app.rag.ingest
    ```

## 6. Running Tests

Execute the full test suite with `pytest`:

```bash
pytest -q
```

## 7. How to Add a New Platform

Adding support for a new academic platform is straightforward and requires no code changes:

1.  **Edit `app/rag/platforms.yaml`**: Add a new entry to the `platforms` list. Each entry requires a `key` (internal identifier), `display_name` (human-readable), and a list of `keywords` associated with the platform.
2.  **Add Instruction Files**: Place `.txt` files containing step-by-step instructions for the new platform into the `data/instructions/` directory, ensuring platform keywords appear in the filenames or content for proper routing.
3.  **Re-run Ingestion**: Execute `python -m app.rag.ingest` to rebuild all FAISS indexes, including the new platform's index.
    *   No code changes are needed anywhere else in the application.

## 8. Continuous Integration (CI)

A GitHub Actions workflow is configured in `.github/workflows/ci.yml`. This workflow automatically runs the ingestion pipeline, validates all FAISS indexes, and executes unit tests on every `push` and `pull_request` to `main` without needing to manually set PYTHON_PATH.

## 9. Key Architectural Decisions

*   **FAISS IndexFlatIP**: Chosen over IVF/HNSW because the current corpus (~1,000 vectors) is too small for approximate indexes to be beneficial. Revisit after several semesters of content growth.
*   **Local LLM**: Eliminates vendor dependency and API costs. Hardware upgrade to Mac Studio M4 Max is planned to support 25-30 simultaneous users.
*   **Single Source of Truth**: `platforms.yaml` drives both ingestion and retrieval. Adding a platform requires only a YAML edit + re-index.
