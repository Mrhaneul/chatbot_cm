# Lance Chatbot — Critical Reminders

## ⚠️ Hardware Alone Won't Fix the Problem

Upgrading hardware is necessary but **not sufficient**. You must also implement a **request queue** in FastAPI to prevent GPU saturation when multiple users send requests simultaneously.

Without it, 25+ users will all compete for the GPU at once — and everyone gets slow, unpredictable responses regardless of how powerful the hardware is.

### What to implement: `asyncio.Semaphore`

Estimated time: **2–4 hours of work**

```python
# In your FastAPI app (e.g., app/main.py)
import asyncio

# Limit to 2 concurrent LLM requests at a time (adjust based on hardware)
llm_semaphore = asyncio.Semaphore(2)

# Wrap your LLM call with the semaphore
async def call_llm(prompt):
    async with llm_semaphore:
        return await your_existing_llm_call(prompt)
```

Consider adding a queue position indicator in the API response so the frontend can show students a "please wait" message instead of a frozen UI.

---

## 📋 Post-Internship Handoff Priorities

These are just as important as the hardware upgrade for long-term sustainability.

### 1. Move off ngrok
- ngrok tunnels reset on restart, the URL changes, and the free tier has limits
- Options: deploy on a CBU IT-assigned static IP, or containerize and host on Railway/Render
- **Action:** Document whatever hosting solution is chosen so staff can restart it without you

### 2. Dockerize the backend
- Package the FastAPI backend in Docker so any IT staff can restart with one command:
  ```bash
  docker compose up -d
  ```
- This removes the dependency on your specific machine setup and Python environment

### 3. Document the Ollama update procedure
- Staff need to know how to update the model:
  ```bash
  ollama pull llama3.2
  ```
- Document where Ollama is installed, how to restart it, and how to verify it's running

### 4. Firebase access
- Ensure at least one CBU staff member (not just you) has admin access to the `lance-cbu` Firebase project
- Document the Firestore collection structure (`pdf_documents`) and Storage bucket

### 5. Health check page
- The `/sessions/stats` endpoint already exists — consider wrapping it in a simple admin page so staff can verify the system is running without needing to use the terminal

---

*Last updated: February 2026*
