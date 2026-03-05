# Codex Context Handoff

## Project
Lance is a CBU Campus Store RAG chatbot (FastAPI backend) using:
- `app/main.py` for routing/session/intent/platform logic
- `app/rag/retriever.py` for FAISS retrieval
- `app/rag/ingest.py` for index build
- `app/llm/llama_client.py` for local LLM calls
- PDF recommendation logic in `app/pdf_recommendations.py`

## Major Work Completed

### 1) Edge-case stabilization and regression suite
- Edge-case suite file: `research/lance_edge_case_test_suite.csv`
- Tracking file: `research/edgecase_check.md`
- Added and maintained `response` + `response_notes` columns.
- Full suite currently expanded to **33 test cases** (`TC001`–`TC033`).

### 2) Platform detection and routing fixes
- Added/validated InQuizitive platform support and aliases.
- Added typo aliases for InQuizitive:
  - `inquizitve`
  - `inquiztive`
- Added Norton ambiguity behavior (like Cengage/McGraw/Pearson):
  - `Norton` alone -> clarification:
    - textbook vs InQuizitive
  - Clarification prompt source: `CLARIFICATION_NEEDED`

### 3) Clarification-branch improvements
- Low-info responses (`I don't know`, `not sure`, etc.) handled gracefully:
  - No retrieval
  - Helpful redirect to find platform in Blackboard
  - Keeps clarification state open
- Negation-aware platform correction implemented (e.g. "Cengage not McGraw").
- Clarification handling for textbook vs courseware improved (`Textbook not platform`, `Courseware not ebook`).

### 4) FAQ and out-of-scope handling
- Added FAQ direct-answer confidence threshold:
  - `FAQ_DIRECT_MIN_CONFIDENCE` in `app/main.py`
- Added out-of-scope keyword guard:
  - routes obvious non-store topics to `LLM_ONLY` redirect
- Forced `GENERAL_FAQ` retrieval to FAQ collection to avoid instruction misrouting.

### 5) Removed article links from responses/content
- Removed all `Article link: "..."` lines from `data/**/*.txt`.
- Re-ingested indexes.
- Added response sanitizer in `app/main.py`:
  - strips `Article link:` lines from outgoing responses.

### 6) Deterministic instruction response path
- For instruction retrieval (`INSTR_*`) in IA flows, Lance now returns context-derived responses directly in key branches to reduce LLM variability.
- This removed intermittent greeting/meta leakage on platform-specific queries (notably InQuizitive).
- `llm_time_ms` is often `0.0` on deterministic instruction responses.

### 7) Important ingestion/retrieval fix
- Root cause found: chunk delimiter collision (`---`) inside content.
- Changed chunk separator to unique token:
  - `\n<<<CHUNK_SEPARATOR>>>\n`
- Updated both:
  - `app/rag/ingest.py`
  - `app/rag/retriever.py`
- Re-ingested successfully after change.

### 8) TC021 requirement update
- New requirement: do **not** ask for course code first.
- Implemented platform/publisher-first clarification behavior.
- Updated expected values for TC021 in CSV accordingly.

## New Test Cases Added

### TC031
- Prompt: `I need help with Norton`
- Expected: clarification asking textbook vs InQuizitive
- Current: PASS

### TC032
- Precondition: after TC031 clarification prompt
- Prompt: `Textbook`
- Expected: general instruction branch (`INSTR_GENERAL_SOURCE_`)
- Current: PASS
- `response` in CSV currently contains **full** response text (explicitly requested).

### TC033
- Precondition: after TC031 clarification prompt
- Prompt: `InQuizitive`
- Expected: `INSTR_INQUIZITIVE_SOURCE_`
- Current: PASS

## Current Test Status
- Latest run: **33 PASS / 0 CHECK**
- File: `research/lance_edge_case_test_suite.csv` has fresh responses + notes.

## Key Behavior Notes
- InQuizitive typo queries now route correctly:
  - e.g. `How do I access to inquizitve?` -> `INSTR_INQUIZITIVE_SOURCE_0`
- Norton is now ambiguous unless user specifies textbook or InQuizitive.
- TC032 deterministic behavior removed "you asked twice" meta phrasing.

## Recent Files Touched (high signal)
- `app/main.py`
- `app/rag/ingest.py`
- `app/rag/retriever.py`
- `research/lance_edge_case_test_suite.csv`
- `research/edgecase_check.md`

## Operational Notes
- Ingest command used successfully:
  - `PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python app/rag/ingest.py`
- Uvicorn is expected to run with reload; changed Python files should auto-reload.

## Suggested next checks in new chat
1. Re-run focused Norton/InQuizitive flows (`TC031`–`TC033`) against live server.
2. Re-run full edge suite and ensure still `PASS=33`.
3. If response quality for textbook branch needs improvement, add dedicated Norton textbook instruction doc and platform-specific path.
