# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

**Backend (Python FastAPI)**
- `uvicorn app.main:app` – Run the FastAPI server locally (default host `127.0.0.1:8000`).
- `uvicorn app.main:app --reload` – Run with auto‑reload for rapid development (use on non‑Windows platforms).
- `pytest` – Execute the test suite (`app/test_*.py`).
- `pip install -r requirements.txt` – Install Python dependencies (if a `requirements.txt` is added in the future). Currently the project expects the following packages to be available: `fastapi`, `uvicorn`, `pydantic`, `requests` and any Firebase SDKs used.

**Frontend (React + Vite)**
- `npm install` – Install UI dependencies.
- `npm run dev` – Start the Vite development server (http://localhost:5173 by default).
- `npm run build` – Produce a production‑ready static bundle in `dist/`.
- `npx vite preview` – Preview the production build locally.

**LLM Runtime**
- `ollama pull llama3:8b` – Download the 8B LLaMA model.
- `ollama serve` – Ensure the Ollama API is running on `http://localhost:11434`.
- `curl http://localhost:11434/api/chat -d '{"model":"llama3:8b","messages":[{"role":"user","content":"Hello"}],"stream":false}'` – Verify the Ollama endpoint.

**Docker**
- `docker compose up --build` – Build and run the full stack (backend, UI, and Ollama) via the provided `docker‑compose.yml`.
- `docker compose down` – Stop and clean up containers.

## High‑Level Architecture

- **Client Layer** – A React UI served by Vite (`ui/`). It communicates with the backend via HTTP endpoints defined in the FastAPI service.
- **API Layer** – FastAPI (`app/main.py`) exposes a `/chat` endpoint. The backend is deliberately API‑first, making it easy to replace the UI or migrate to a cloud‑hosted service.
- **LLM Abstraction** – `app/llm/base.py` defines an abstract `LLMClient` interface. The concrete implementation (`app/llm/llama_client.py`) talks to a locally hosted Ollama instance. This design isolates model‑specific details and enables future substitution (e.g., OpenAI, Azure).
- **Data Layer** – Currently minimal; the backend interacts with Firebase via the service‑account JSON (`app/firebase-service-account.json`). Future extensions may add a persistence layer.
- **Deployment** – The project can be run locally, containerised via Docker, or deployed on Railway (`railway.toml`). All components are orchestrated through `docker‑compose.yml` and Nixpacks (`nixpacks.toml`).

## Important Files & Directories

- `app/` – Python backend source code.
  - `main.py` – FastAPI entry point.
  - `llm/` – LLM client abstraction and Ollama implementation.
  - `schemas/` – Pydantic request/response models.
  - `test_*.py` – Pytest test suite.
- `ui/` – React frontend.
  - `package.json` – npm scripts and dependencies.
  - `vite.config.ts` – Vite configuration.
- `.firebase/` – Firebase hosting configuration.
- `docker-compose.yml` – Multi‑container development environment.
- `README.md` – Full project overview, setup instructions, and design rationale.

## Extensibility Notes

- The **LLM abstraction layer** makes swapping the underlying model straightforward: implement a new subclass of `LLMClient` and adjust the import in `app/main.py`.
- The **API‑first design** allows other clients (mobile apps, CLI tools) to consume the same `/chat` endpoint without modifications.
- Adding persistent storage (e.g., a database) can be done by extending the FastAPI routes and injecting a repository layer, keeping the existing LLM client untouched.

---

# Claude Handoff Prompt - Campus Store Chatbot Continuation

You are continuing active maintenance on a FastAPI-based Campus Store chatbot in this repo.
Focus on preserving deterministic, non-hallucinated behavior and improving email-derived edge-case handling.

## Project Context

- Repo: `C:\Users\Testing\Desktop\chatbot_cm`
- Main backend file: `app/main.py`
- RAG data:
  - FAQs: `data/faqs/*.txt`
  - Instructions: `data/instructions/*.txt`
- Ingestion script: `app/rag/ingest.py`
- Issue log: `research/email_issue_log.md`

## Current Goals

1. Make chatbot behavior robust for real student support conversations extracted from `.msg` emails.
2. Prevent hallucinations and wrong-topic drift.
3. Keep responses deterministic when retriever has relevant context.
4. Maintain a case-by-case log with:
   - transcript
   - issue
   - root cause
   - fix
   - retest

## What Has Already Been Implemented

### 1) Store-hours hallucination prevention

- Added strict guardrails in `app/main.py`:
  - Detect store-hours queries.
  - Do not answer hours unless retrieved context contains schedule-like evidence.
  - Fail closed with safe response when evidence is missing.
- Added safer FAQ fallback behavior: avoid LLM freeform when FAQ retrieval exists but answer is not verified/parseable.

### 2) Campus Store FAQ data split

- Split combined store info into:
  - `data/faqs/campus_store_hours.txt`
  - `data/faqs/campus_store_location.txt`
  - `data/faqs/campus_store_delivery_directions.txt`
- Added vague general query clarification for bare `Campus Store`.

### 3) IA clarification/state continuity fixes

- Improved handling where users say:
  - `I don't know which platform`
  - short follow-up troubleshooting
- Added IA continuity safeguards so conversations do not derail into unrelated FAQ answers.
- Added helper(s) for recovering likely platform from session history.
- Added acknowledgment handling (e.g. `Found it, thank you!`) to avoid repetitive fallback loops while still awaiting platform.

### 4) Book-discovery intent routing (new deterministic branch)

- For user messages like:
  - `I'm having trouble finding books`
- Bot now asks:
  - `Are you trying to find a physical textbook or Immediate Access digital materials?`
- If user chooses Immediate Access:
  - ask for platform
  - if unknown platform, provide Blackboard location guidance
- If user chooses physical:
  - provide physical textbook guidance + store contact details + IA print-note context.

### 5) Blackboard/InsideCBU login issue routing

- Added dedicated detection for account/class-access-first issues:
  - `can't log into Blackboard/InsideCBU`
  - `can't access class`
- These now route to login/class access support guidance (IT/Pre-College first), instead of platform troubleshooting loops.

### 6) Mojibake cleanup

- Fixed broken encodings in many `data/*.txt` files (`â`, `Ã`, `ï»¿`, etc.).
- Rebuilt indices after cleanup via:
  - `python app/rag/ingest.py`

## Known Important File Changes

- `app/main.py` (multiple routing/guard fixes)
- `data/faqs/*.txt` (store files + encoding cleanup)
- `data/instructions/*.txt` and generated chunks (encoding cleanup/reingest)
- `research/email_issue_log.md` (Cases 001-005 logged)

## Current Log Status

`research/email_issue_log.md` currently contains:

- Case 001: ACC540 IA link missing
- Case 002: 813664 new student cannot find books
- Case 003: Book discovery clarification (physical vs IA)
- Case 004: Acknowledgement loop while awaiting platform
- Case 005: Blackboard/InsideCBU pre-college login issue

## What To Do Next

1. Continue processing remaining `emails/*.msg` one by one.
2. For each email:
   - extract core user issue text
   - replay realistic multi-turn chat against `/chat`
   - detect misroutes/hallucinations/repetition loops
   - patch `app/main.py` (or data files) deterministically
   - retest
   - append a new case to `research/email_issue_log.md`
3. Prefer deterministic logic over prompt-only fixes.
4. Re-run ingestion if any FAQ/instruction text data changes.

## Validation Checklist Per Fix

1. `python -m py_compile app/main.py`
2. Replay scenario via local API:
   - `POST http://localhost:8000/chat`
3. Confirm:
   - relevant source id (`FAQ_SOURCE_*` / `INSTR_*` / `CLARIFICATION_NEEDED`)
   - no unrelated-topic drift
   - no repeated rigid loop
4. Update `research/email_issue_log.md`.

## Guardrails / Style Requirements

- Avoid hallucinated operational facts.
- If data is missing, return safe clarifying response (do not fabricate).
- Preserve concise, practical student-facing support language.
- Keep single-turn and multi-turn state behavior stable.

## Suggested Immediate Next Email

Continue from remaining files in `emails/`, starting with the next unprocessed `.msg` after:
- `2026-SP-E1 ACC540-AE-Advncd Topics in Financial Acctg.msg`
- `813664.msg`
- `Blackboard & InsideCBU Login for Pre College Credit Class.msg`

*Generated by Claude Code.*

## Claude Handoff Prompt - Campus Store Chatbot Continuation

You are continuing active maintenance on a FastAPI-based Campus Store chatbot in this repo.
Focus on preserving deterministic, non-hallucinated behavior and improving email-derived edge-case handling.

### Project Context

- Repo: `C:\Users\Testing\Desktop\chatbot_cm`
- Main backend file: `app/main.py`
- RAG data:
  - FAQs: `data/faqs/*.txt`
  - Instructions: `data/instructions/*.txt`
- Ingestion script: `app/rag/ingest.py`
- Issue log: `research/email_issue_log.md`

### Current Goals

1. Make chatbot behavior robust for real student support conversations extracted from `.msg` emails.
2. Prevent hallucinations and wrong‑topic drift.
3. Keep responses deterministic when retriever has relevant context.
4. Maintain a case‑by‑case log with:
   - transcript
   - issue
   - root cause
   - fix
   - retest

### What Has Already Been Implemented

#### 1) Store‑hours hallucination prevention
- Added strict guardrails in `app/main.py` to detect store‑hours queries and only answer when evidence is present.
- Safer FAQ fallback behavior when retrieval exists but answer is unverified.

#### 2) Campus Store FAQ data split
- Split combined store info into separate files for hours, location, and delivery directions.

#### 3) IA clarification/state continuity fixes
- Improved handling of ambiguous platform queries and added safeguards to avoid derailment.

#### 4) Book‑discovery intent routing (new deterministic branch)
- Distinguish between physical textbook and Immediate Access requests, guiding the user accordingly.

#### 5) Blackboard/InsideCBU login issue routing
- Dedicated detection for account/class‑access issues, routing to IT/Pre‑College guidance.

#### 6) Mojibake cleanup
- Fixed broken encodings in many `data/*.txt` files and rebuilt indices.

### Known Important File Changes
- `app/main.py` (routing/guard fixes)
- `data/faqs/*.txt` (store files + encoding cleanup)
- `data/instructions/*.txt` (encoding cleanup/re‑ingest)
- `research/email_issue_log.md` (cases 001‑005 logged)

### Current Log Status
- Cases documented: 001‑005 covering various edge cases.

### What To Do Next
1. Continue processing remaining `emails/*.msg` one by one.
2. For each email:
   - extract core issue text
   - replay realistic multi‑turn chat against `/chat`
   - detect misroutes/hallucinations/repetition loops
   - patch `app/main.py` or data files deterministically
   - retest
   - append a new case to `research/email_issue_log.md`
3. Prefer deterministic logic over prompt‑only fixes.
4. Re‑run ingestion if any FAQ/instruction text data changes.

### Validation Checklist Per Fix
1. `python -m py_compile app/main.py`
2. Replay scenario via local API:
   - `POST http://localhost:8000/chat`
3. Confirm:
   - relevant source id (`FAQ_SOURCE_*`, `INSTR_*`, `CLARIFICATION_NEEDED`)
   - no unrelated‑topic drift
   - no repeated rigid loop
4. Update `research/email_issue_log.md`.

### Guardrails / Style Requirements
- Avoid hallucinated operational facts.
- If data is missing, return a safe clarifying response (do not fabricate).
- Preserve concise, practical student‑facing support language.
- Keep single‑turn and multi‑turn state behavior stable.

### Suggested Immediate Next Email
Continue from remaining files in `emails/`, starting after the last processed ones listed.

---