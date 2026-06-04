# Lance Manual QA Checklist

Run this checklist after production deployments, content migrations, hardware moves, or major configuration changes.

## Before Testing

- [ ] Backend is running.
- [ ] Ollama is running.
- [ ] Admin UI opens at `http://localhost:8000/admin`.
- [ ] Frontend points to the correct backend URL.
- [ ] `python -m app.rag.ingest` has been run after any content changes.
- [ ] Admin UI Apply Changes succeeds, or backend has been restarted.

## Automated Smoke Tests

Run from the project root:

```powershell
python -m pytest tests/test_safety_filter.py tests/test_chat_safety_integration.py tests/test_chat_lifecycle_safety.py -q
python -m pytest tests/test_config_loader.py tests/test_api_platforms.py -q
python -m pytest tests/test_intake.py -q
python -m pytest tests/test_recursive_content_dirs.py tests/test_admin_content_editing.py -q
python -m pytest tests/test_feedback.py -q
python -m pytest tests/test_metadata_filtering.py tests/test_retrieval_scoring.py tests/test_quick_help_routes.py tests/test_audit_quick_help.py -q
python scripts/audit_quick_help.py
```

Known acceptable warnings:

- FastAPI `on_event` deprecation warnings until the lifespan migration is done.
- Quick Help audit warnings marked as LLM stub / source routing only partially audited.
- Firestore positional filter warning from the Google client library.

## Student Chat Scenarios

Run these through the normal chat UI.

| Scenario | Example | Expected result |
|---|---|---|
| Greeting | `Hi` | Deterministic greeting |
| Quick Help FAQ | `What is Immediate Access?` | FAQ answer without platform clarification |
| Platform access | `How do I access my Cengage MindTap book?` | Cengage-specific instructions |
| Vague intake | `I don't have my textbook` | Lance asks for missing platform/issue context |
| Platform-only vague | `Cengage is not working` | Lance asks the issue follow-up and does not jump to FAQ |
| Browser cache | `My VitalSource page shows 0 courses` | Browser/cache troubleshooting path |
| Safety block | Payment bypass or hacking request | Safety refusal before retrieval/LLM |
| Out of scope | Housing or chapel question | Campus Store scope response or escalation |
| Low confidence | Unknown unsupported platform | Escalation to Campus Store contact |

## Admin UI Scenarios

- [ ] List FAQ and instruction files.
- [ ] Open a flat `.txt` file for editing.
- [ ] Open a nested `.txt` file for editing, if present.
- [ ] Validate a valid file.
- [ ] Confirm invalid YAML front matter is rejected.
- [ ] Save a minor edit and confirm a backup appears under `data/_archive/backups/`.
- [ ] Archive/remove a test file and confirm it appears under `data/_archive/removed/`.
- [ ] Click Apply Changes and confirm success.
- [ ] Submit a test feedback item through the API or UI path.
- [ ] Confirm it appears in the Feedback tab.
- [ ] Mark feedback reviewed and resolved.

## PDF Recommendation Scenarios

- [ ] Ask a question tied to a known PDF guide.
- [ ] Confirm PDF sidebar appears.
- [ ] Temporarily unavailable Firestore should not break the chat response; the sidebar may be empty.

## Fail/Pass Criteria

Pass only if:

- Safety blocks happen before retrieval or LLM.
- Admin edits create backups before overwrite.
- Removed content is archived, not permanently deleted.
- Feedback is stored for review only and does not trigger ingestion or model changes.
- No generated FAISS/index/cache artifacts are unintentionally staged.
