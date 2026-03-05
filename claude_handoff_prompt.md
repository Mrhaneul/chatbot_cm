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

### 6) Immediate Access tab-missing escalation

- Added deterministic handling for users who still cannot find Immediate Access in Blackboard:
  - examples: `I don't see Immediate Access`, `What do I do if I can't find it?`
- Bot now escalates to:
  - `ImmediateAccess@calbaptist.edu`
  - asks student to include LancerMail sender, name, ID#, and course info.
- Added sticky follow-up guard so these messages do not drift into unrelated FAQ answers.

### 7) Mojibake cleanup

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

Use `research/email_issue_log.md` as source of truth for full transcripts and exact before/after behavior.

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
   - for IA-tab-missing scenarios, verify escalation email response remains sticky on follow-up turns
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
