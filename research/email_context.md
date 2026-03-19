## Current Work Status

- Issue focus: Case 007 (McGraw Hill "Read Now button" missing) response only returns PROBLEM line; similar behavior reported for Cengage.
- Root cause hypothesis: Instruction chunking splits problem vs resolution into separate chunks; top-1 retrieval returns the problem-only chunk.
- Data edit applied: `data/instructions/ia_mcgraw_hill_connect_access.txt` updated so "Resolution steps" is lowercase to keep steps in the same chunk.
- Ingestion: Re-ran `python -m app.rag.ingest` and restarted uvicorn; response still returns only PROBLEM line, suggesting stale index/chunk load or wrong context retrieval.
- Debug tooling: Added a new endpoint to return full retrieved context:
  - `POST /debug/retrieval-context` with optional `?platform=mcgraw` to inspect the exact chunk text.
  - Note: After multiple restarts, `/openapi.json` still does not list this new endpoint, and POST requests return 405. The running server appears to be loading an older app version despite restarts.

## Next Actions

- Restart the FastAPI server to load the new endpoint.
- Confirm the process bound to port 8000 is the newly started server and that it reflects the updated route list.
- Call `/debug/retrieval-context` for McGraw and Cengage queries to verify the exact chunk content being returned.
- If the chunk lacks steps, confirm the running server is loading the updated `data/instructions` path and re-ingest/restart as needed.
