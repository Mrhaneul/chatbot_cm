# Lance — Troubleshooting Guide

> **Who this document is for:** Anyone dealing with a problem — Campus Store staff, IT, or developers. Find your symptom in the section headings below and follow the steps. If nothing here resolves the issue, use Section 11 to find the right person to contact.

---

## 1. How to use this guide

Find the section that matches what you are seeing. Each section lists the most likely causes first and the fix for each. Work through them in order — the first cause is the most common.

If a fix requires the terminal, contact IT. If a fix requires editing Python code, contact a developer.

---

## 2. Lance is completely unreachable — no response at all

**Symptom:** Students report the chat UI will not load, or loads but shows a connection error on every message.

### Cause A — ngrok tunnel is down (most common)
```powershell
# Check if ngrok is running
# Look for the ngrok terminal window on the server machine
# If it is not running, restart it:
ngrok http 8000
```
Check if the URL changed. If it did, update `ui/src/services/api.ts` and redeploy:
```powershell
cd ui && npm run build && firebase deploy --only hosting
```

### Cause B — uvicorn is not running
```powershell
# Test if the backend responds
curl http://localhost:8000/health

# If no response, restart uvicorn:
conda activate campus-store-bot
cd C:\Users\[username]\Desktop\chatbot_cm
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Cause C — machine was restarted and nothing came back up
Follow the full startup sequence in Section 10.

### Cause D — Firebase Hosting is down
Extremely rare. Check https://status.firebase.google.com. If Firebase has an active incident, wait for Google to resolve it — nothing on the Lance side can fix this.

---

## 3. Lance responds but gives wrong answers

**Symptom:** Students receive responses that are inaccurate, outdated, or completely unrelated to their question.

### Step 1 — Reproduce the issue
Go to the chat UI and type the exact question the student asked. Confirm you see the wrong response.

### Step 2 — Use debug mode to diagnose
Click the **Auto / LLM mode** pill in the top right of the chat UI to switch to LLM mode. Ask the same question again.

| Auto mode result | LLM mode result | Diagnosis | Fix |
|---|---|---|---|
| Wrong answer | Also wrong | **Content gap** — no relevant `.txt` file covers this topic | Write and upload a new content file via Admin UI |
| Wrong answer | Correct answer | **Routing bug** — content exists but routing sends the query elsewhere | Escalate to developer with the question and both responses |
| Correct answer | Different answer | Auto mode is working correctly — LLM variation is expected | No fix needed |
| Escalation shown | Correct answer | FAISS retrieval confidence too low for this query phrasing | Adjust content file wording, or add routing fix for this query type |

### Cause A — Content gap (most common)
The correct answer does not exist in any `.txt` file. Fix:
1. Write a new `.txt` file with the correct answer
2. Upload via Admin UI → Add Content
3. Click Apply Changes
4. Test the question again

### Cause B — Outdated content
The answer exists but contains old information (wrong deadline, old phone number, changed policy). Fix:
1. Remove the old file via Admin UI → Remove Content
2. Apply Changes
3. Upload the updated file via Admin UI → Add Content
4. Apply Changes again
5. Test the question again

### Cause C — Routing bug
The content exists and LLM mode returns the correct answer, but Auto mode does not. This means the routing logic is sending the query to the wrong detection path. Fix: escalate to a developer with:
- The exact question typed
- The Auto mode response
- The LLM mode response
- Which `.txt` file should have been retrieved

### Cause D — Wrong answer after recent content change
A recently added file may have incorrect formatting that prevents proper retrieval. Check:
1. Open the file and confirm it follows the `QUESTION:` / `ANSWER:` format
2. Re-run ingestion: `python -m app.rag.ingest`
3. Run validation: `python scripts/validate_indexes.py`
4. Apply Changes in Admin UI
5. Test again

---

## 4. Lance is very slow — responses take 30+ seconds

**Symptom:** Students wait a long time before seeing any response.

### Normal slow (not a bug)
LLM fallback responses on the current hardware (Ryzen 7 3800X) take 12–25 seconds. This is expected. FAQ direct answers should always be under 1 second. If only some queries are slow, the slow ones are hitting the LLM fallback path — this is normal behavior.

The permanent fix is the hardware upgrade to Mac mini M4 Pro 48GB which reduces LLM response time to 3–5 seconds.

### Abnormal slow (investigate)
If FAQ direct answers (store hours, return policy, browser cache steps) are also taking 10+ seconds, something is wrong.

**Check 1 — Is FAISS loaded?**
```powershell
curl http://localhost:8000/health
```
If the response itself is slow (>2 seconds), the backend may be overloaded or the FAISS index failed to load.

**Check 2 — Is the machine under load?**
Open Task Manager. If CPU or RAM is at 90%+, another process is competing with Lance. Identify and stop it if possible.

**Check 3 — Are multiple LLM requests queuing?**
Check the uvicorn terminal for `[QUEUE]` messages showing requests backing up. If several students sent messages at the same time, they queue behind each other. This is expected behavior — responses will arrive in order.

**Check 4 — Restart uvicorn**
If checks 1–3 show nothing unusual, restart uvicorn:
```powershell
# Stop with Ctrl+C, then:
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 5. Lance keeps asking "which platform?" for every message

**Symptom:** A student reports that Lance asks them to identify their platform on every message, even after they have already answered.

### Cause A — Student is using a new session
If the student refreshed the page or opened a new tab, their session ID changed and the stored platform was lost. This is expected — ask the student to continue in the same browser tab.

### Cause B — Session expired between messages
Sessions expire after a period of inactivity. If the student waited a long time between messages, the session may have expired. Expected behavior.

### Cause C — Routing bug (new detection function missing exclusion)
If this happens consistently for a specific question phrasing, a recently added detection function may be missing an exclusion from `is_confirmed_materials_issue()`. Escalate to a developer with:
- The exact conversation sequence (what was asked, what Lance replied, what was asked again)
- Confirmation that it happens in a fresh session, not just after a page refresh

---

## 6. PDF guides are not appearing in the sidebar

**Symptom:** A student asks a question and Lance responds correctly, but the right sidebar stays empty even though a PDF guide should be there.

Work through this checklist in order:

**Check 1 — Is the `.txt` file mapped in Firestore?**
Firebase console → Firestore → `txt_to_pdf_map` → look for a document with the `.txt` filename as the document ID.

**Check 2 — Does the `pdf_documents` entry exist?**
Firebase console → Firestore → `pdf_documents` → look for the document ID listed in the `txt_to_pdf_map` entry.

**Check 3 — Is the download URL valid?**
Open the `download_url` from the `pdf_documents` entry in a browser. It should open or download the PDF.

**Check 4 — Is Firestore reachable?**
Check the uvicorn terminal for `[WARN] PDF recommendation failed` — this indicates a Firestore timeout.

**Check 5 — Is the PDF in the hardcoded fallback?**
Open `app/pdf_recommendations.py` and check `TXT_TO_PDF_MAP`. If the file is there, PDFs should appear even without Firestore.

**Check 6 — Was the correct source file retrieved?**
In the uvicorn terminal, look for `[PDF] Recommending X PDFs` after the chat request. If it shows `0 PDFs`, the source file lookup found nothing — the mapping may be missing or the wrong source file was retrieved.

---

## 7. The Admin UI is not accessible

**Symptom:** Navigating to `http://localhost:8000/admin` gives a connection error or the page does not load.

### Cause A — uvicorn is not running
The Admin UI is served by the FastAPI backend. If the backend is down, the Admin UI is down.
```powershell
# Restart uvicorn:
conda activate campus-store-bot
cd C:\Users\[username]\Desktop\chatbot_cm
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Cause B — Wrong URL or port
Confirm you are accessing `http://localhost:8000/admin` (not HTTPS, not port 3000 or 5173).

### Cause C — Wrong credentials
If the login prompt appears but credentials are rejected, check the `.env` file for `LANCE_ADMIN_USER` and `LANCE_ADMIN_PASSWORD`. Contact IT if you do not have access to `.env`.

### Cause D — Browser cached old credentials
Clear browser cookies for localhost, or try a private/incognito window.

---

## 8. Validation script shows FAIL

**Symptom:** Running `python scripts/validate_indexes.py` shows one or more FAIL lines.

```powershell
conda activate campus-store-bot
python scripts/validate_indexes.py
```

| FAIL message | Likely cause | Fix |
|---|---|---|
| `FAQ index found and not empty` FAIL | No FAQ `.txt` files exist, or ingestion has not been run | Check `data/faqs/` has files, run `python -m app.rag.ingest` |
| `General instructions index` FAIL | No instruction `.txt` files, or ingestion not run | Check `data/instructions/` has files, run ingestion |
| `[Platform] index found and not empty` FAIL | Platform instruction file missing or ingestion not run | Restore missing file, run ingestion |
| `chunks only contain platform 'X' metadata` FAIL | Cross-platform contamination — wrong file in wrong folder | Check file platform tags, run ingestion |
| `Split browser cache file present` FAIL | One of four browser cache files is missing from `data/faqs/` | Restore missing file, run ingestion |
| `Legacy browser cache file absent` FAIL | Old `ia_browser_cache_clear.txt` still exists | Delete it from `data/faqs/`, run ingestion |

**One-command fix for most FAIL cases:**
```powershell
conda activate campus-store-bot
python -m app.rag.ingest
python scripts/validate_indexes.py
```
If FAIL persists after re-ingestion, the source `.txt` file itself may be missing or incorrectly formatted — check `data/faqs/` and `data/instructions/` for the relevant file.

---

## 9. Tests are failing

**Symptom:** Running `pytest -q` shows failures or errors.

### Check 1 — Wrong conda environment
```powershell
conda activate campus-store-bot
conda run -n campus-store-bot pytest -q
```

### Check 2 — Missing dependencies
```powershell
conda activate campus-store-bot
pip install -r requirements.txt --break-system-packages
```

### Check 3 — FAISS indexes missing
Some tests require the indexes to exist. Run ingestion first:
```powershell
python -m app.rag.ingest
pytest -q
```

### Check 4 — Port conflict
If tests fail with connection errors, another process may be using port 8000. The test suite spins up a test instance of the app — if something else is on port 8000, tests will fail.
```powershell
netstat -ano | findstr :8000
taskkill /F /PID [PID]
pytest -q
```

### Expected baseline
27 tests should pass. If all 27 pass, the system is healthy. If fewer pass after a code change, the change introduced a regression — review what changed and fix or revert.

---

## 10. After a machine restart, nothing works

**Symptom:** The server machine was restarted (planned or unplanned) and Lance is not responding.

Follow this startup sequence in order:

**Step 1 — Start Ollama:**
```powershell
ollama serve
```
Wait for: `msg="Listening on 127.0.0.1:11434"`

**Step 2 — Start uvicorn:**
```powershell
conda activate campus-store-bot
cd C:\Users\[username]\Desktop\chatbot_cm
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Wait for: `Application startup complete`

**Step 3 — Start ngrok:**
```powershell
ngrok http 8000
```
Note the forwarding URL: `https://xxxx.ngrok-free.app`

**Step 4 — Check if the ngrok URL changed:**
Compare the new URL to the one in `ui/src/services/api.ts`. If they differ, update the file and redeploy:
```powershell
cd ui && npm run build && firebase deploy --only hosting
```

**Step 5 — Run a health check:**
```powershell
curl http://localhost:8000/health
```
Expected: `{"status": "ok"}`

**Step 6 — Send a test message:**
Open the chat UI and send "What are the Campus Store hours?" — should respond in under 1 second with the correct hours.

> **Tip for IT:** Configure Ollama and uvicorn as Windows startup services using Task Scheduler so Steps 1 and 2 happen automatically after any restart. See `01_IT_handoff.md` Section 10 for setup instructions.

---

## 11. Who to contact

Use this decision tree to find the right person before escalating.

**The chat UI will not load at all:**
→ IT — server or ngrok is down

**Lance responds but the answer is wrong:**
→ Campus Store staff — check for content gap using debug mode (Section 3)
→ If debug mode shows correct answer but Auto mode does not → Developer — routing bug

**Lance is very slow:**
→ Normal if LLM fallback queries — no action needed
→ Abnormal if FAQ answers are slow → IT — server performance issue

**The Admin UI is not accessible:**
→ IT — backend is not running

**A student cannot access their textbook:**
→ Direct the student to ImmediateAccess@calbaptist.edu
→ If Lance gave incorrect instructions → Campus Store staff to fix the content

**Something in `app/main.py` is broken:**
→ Developer — do not attempt to edit this file without developer guidance

**Firebase Storage or Firestore issues:**
→ Developer — check Firebase console and `pdf_recommendations.py`

**A new semester started and deadlines are wrong:**
→ Campus Store staff — see `11_seasonal_maintenance.md` for the update checklist

| Issue type | Contact |
|---|---|
| Server down, ngrok, hardware | IT |
| Wrong answers, content gaps, seasonal updates | Campus Store staff |
| Routing bugs, Python code, new features | Developer |
| Student textbook access problems | ImmediateAccess@calbaptist.edu |
| Firebase / Firestore access | Developer + Firebase console |
