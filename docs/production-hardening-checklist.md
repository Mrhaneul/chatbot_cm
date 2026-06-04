# Phase 7 Production Hardening Checklist

Phase 7 is a stabilization and handoff phase. It should produce documentation, scripts, checklists, and small stability fixes only. Avoid new major behavior until the Phase 1-6 refactor has been operated and reviewed.

## Goals

- Verify the full system after Phase 1-6 changes.
- Document admin workflows for non-technical staff.
- Document backup and restore procedures.
- Document feedback review workflow.
- Verify environment variables.
- Prepare blade-server deployment assumptions.
- Create a manual QA scenario checklist.
- Document known limitations.

## Current Milestone State

Completed:

1. Safety Gate
2. Config Externalization
3. Interactive Intake / Slot-Filling
4. Recursive Knowledge Directory Support
5. Admin Content Editing Workflow
6. Feedback Review Workflow

## Production Readiness Checklist

### Repository

- [ ] `master` is clean and up to date with `origin/master`.
- [ ] Phase 1-6 backup branch exists locally.
- [ ] No secrets or generated artifacts are staged.
- [ ] `.env` and Firebase service account are present on the production machine but not committed.

### Backend

- [ ] `uvicorn app.main:app --host 0.0.0.0 --port 8000` starts without errors.
- [ ] `/healthz` returns `{"status": "ok"}`.
- [ ] `/readyz` returns ready after Ollama and indexes are loaded.
- [ ] Ollama model names in `.env` match `ollama list`.
- [ ] `ENABLE_SAFETY_FILTER=true`.
- [ ] `ENABLE_SAFETY_CLASSIFIER=true`.
- [ ] `ENABLE_DEBUG_ROUTES=false`.

### Retrieval And Content

- [ ] `python -m app.rag.ingest` completes.
- [ ] Recursive FAQ and instruction discovery works.
- [ ] Existing flat production files remain in place unless a separate migration is planned.
- [ ] Quick Help audit passes with only known warnings.
- [ ] Admin Apply Changes reloads indexes.

### Admin Operations

- [ ] Admin credentials are set.
- [ ] Admin UI opens locally.
- [ ] Add Content works for a test file.
- [ ] Edit Content validates YAML front matter before save.
- [ ] Save creates a timestamped backup.
- [ ] Remove archives content instead of deleting permanently.
- [ ] Feedback tab lists and updates review status.

### Backup And Restore

- [ ] Backup procedure in `docs/backup-restore-procedure.md` has been tested on a non-production copy.
- [ ] Restore of one archived content file has been tested.
- [ ] Feedback JSONL backup location is known.
- [ ] Firebase service account recovery path is documented for IT.

### Blade Server Assumptions

- [ ] OS, Python, Conda, Ollama, and Git install steps are documented.
- [ ] GPU/CPU expectations are documented.
- [ ] Auto-start plan exists for Ollama and backend.
- [ ] Static IP / DNS / TLS plan is owned by IT.
- [ ] Firewall rules are documented.
- [ ] Backup destination is outside the project working tree.

## Known Limitations To Carry Forward

- Vision-only harmful image content is not fully safety-classified.
- Feedback JSONL storage is MVP/single-process oriented.
- Existing production TXT files have not yet been moved into nested directories.
- Some procedural routing logic remains in `main.py`.
- `app/rag/platforms.yaml` remains for ingest/retrieval compatibility.
- FastAPI `@app.on_event` startup/shutdown emits deprecation warnings until a lifespan migration is done.
