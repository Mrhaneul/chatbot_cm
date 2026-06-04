# Lance Backup And Restore Procedure

This procedure is for IT staff or developers maintaining the Campus Store Lance deployment.

## What To Back Up

Back up these paths before any production deployment, content migration, hardware move, or semester-start maintenance:

| Path | Why it matters |
|---|---|
| `data/faqs/**/*.txt` | FAQ source content |
| `data/instructions/**/*.txt` | Platform instruction source content |
| `data/_archive/` | Admin edit backups and archived removals |
| `data/feedback/feedback.jsonl` | Student feedback review queue |
| `config/*.yaml` | Routing, safety, keyword, and response configuration |
| `app/firebase-service-account.json` | Firebase service account key, if used |
| `.env` | Runtime configuration and admin credentials |

Do not back up generated FAISS files as the only source of truth. They can be rebuilt from `.txt` files with:

```powershell
python -m app.rag.ingest
```

## Manual Backup

From the project root:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dest = "backups/lance-backup-$stamp"
New-Item -ItemType Directory -Force -Path $dest
Copy-Item -Recurse -Force data/faqs "$dest/faqs"
Copy-Item -Recurse -Force data/instructions "$dest/instructions"
if (Test-Path data/_archive) { Copy-Item -Recurse -Force data/_archive "$dest/_archive" }
if (Test-Path data/feedback) { Copy-Item -Recurse -Force data/feedback "$dest/feedback" }
Copy-Item -Recurse -Force config "$dest/config"
if (Test-Path .env) { Copy-Item -Force .env "$dest/.env" }
if (Test-Path app/firebase-service-account.json) { Copy-Item -Force app/firebase-service-account.json "$dest/firebase-service-account.json" }
```

Store the backup outside the project folder after creating it. `.env` and Firebase service account files contain secrets.

## Restore Content

1. Stop the backend.
2. Copy the backed-up `faqs`, `instructions`, `_archive`, and `feedback` folders back under `data/`.
3. Copy `config/` back if configuration changed.
4. Restore `.env` and Firebase service account key if needed.
5. Rebuild indexes:

```powershell
python -m app.rag.ingest
```

6. Start the backend:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

7. Run the manual QA checklist in `docs/manual-qa-checklist.md`.

## Restore A Single Admin Edit

Admin saves create backups under:

```text
data/_archive/backups/<content-root>/<relative-folder>/<name>.<timestamp>.<uuid>.txt
```

To restore one file:

1. Find the desired backup.
2. Copy it back to the matching location under `data/faqs/` or `data/instructions/`.
3. Rename it back to the original filename.
4. Run `python -m app.rag.ingest`.
5. In the Admin UI, click Apply Changes or restart the backend.

## Restore Archived Removed Content

Removed files are moved under:

```text
data/_archive/removed/<content-root>/<relative-folder>/<name>.<timestamp>.<uuid>.txt
```

To restore:

1. Copy the archived file back into the correct `data/faqs/` or `data/instructions/` folder.
2. Rename it back to the original filename.
3. Rebuild indexes and reload the backend index.

## Concurrency Limitation

`data/feedback/feedback.jsonl` and filesystem content archives are appropriate for the current single-process deployment. If Lance moves to multiple backend workers or multiple machines, migrate feedback and content version tracking to SQLite, Firestore, or another transactional store before increasing write concurrency.
