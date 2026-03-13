# Immediate Bugs Report

Issues reviewed and actioned before deployment. Each entry covers the bug claim, investigation result, and current status.

---

## Bug 001 — [META:{...}] Prefix Leaking into Student-Facing Replies

**Claim:** The `[META:{...}]` chunk header was appearing in bot replies sent to students.

**Investigation:**
`strip_meta_prefix()` is called at every path where retrieved context flows into a reply:
- Line ~2441: after FAISS retrieval in the main retrieval block
- Line ~2455: in the fallback retrieval block
- Line ~2120: in the handoff context path
- `build_instruction_fallback_from_context()` also strips it independently as a secondary safety net

Tested against McGraw Hill Connect, Cengage, Pearson, and general FAQ queries. No `[META:` prefix appeared in any reply.

**Status:** Not reproducible. No fix required. `strip_meta_prefix()` is correctly applied upstream of all reply-generation paths.

---

## Bug 002 — Platform Key Mismatch: MCGRAW_HILL vs mcgraw

**Claim:** The internal platform key `MCGRAW_HILL` did not match the FAISS index filename `faiss_index_mcgraw`, causing retrieval to fail silently.

**Investigation:**
The retrieval key resolution logic at the point of FAISS lookup is:
```python
_plat_key = PLATFORM_RETRIEVAL_KEY.get(platform, platform.lower().split('_')[0] if platform else None)
```
For `platform = "MCGRAW_HILL"`:
- `PLATFORM_RETRIEVAL_KEY` has no entry for `MCGRAW_HILL`
- Falls back to: `"MCGRAW_HILL".lower().split('_')[0]` → `"mcgraw"`
- `faiss_index_mcgraw` exists and loads correctly

Tested live: "How do I access McGraw Hill Connect?" → `INSTR_MCGRAW_SOURCE_4`, correct response returned.

**Status:** Not a bug. The `.split('_')[0]` fallback handles this correctly. No fix required.

---

## Bug 003 — Blackboard Location Queries Returning Campus Store Address

**Claim:** Queries like "Where is Blackboard located?" or "What is the address for Blackboard?" were returning the CBU Campus Store physical address (8432 Magnolia Ave) instead of a correct response.

**Root Cause:**
Blackboard is a web platform with no physical address. The FAQs index has no Blackboard-specific location entry. FAISS matched location-signal words ("located", "address", "where") from these queries to `campus_store_location.txt`, which was the closest semantic match in the index.

All five tested variants produced the wrong response:
- "Where is Blackboard located?" → Campus Store address
- "What is the address for Blackboard?" → Campus Store address
- "Where can I find Blackboard?" → Campus Store address
- "What is the Blackboard website address?" → Campus Store address
- "How do I get to Blackboard?" → Campus Store address (FAQ_SOURCE_4, wrong but different)

**Fix Applied:**
Added `is_blackboard_location_query()` in `app/main.py` — detects queries combining a web platform name (Blackboard, InsideCBU, Canvas) with a location/URL term (address, where is, website, URL, etc.). Wired as a `GENERAL_FAQ` early-exit branch before FAISS retrieval runs.

Returns a deterministic safe response:
> "Blackboard is a web-based learning platform — it doesn't have a physical location. You can access it through your web browser by searching for 'CBU Blackboard' or through the InsideCBU portal. If you're having trouble logging in, please contact the CBU IT Help Desk for assistance."

**Verified:** All five previously failing queries now return the correct response. Existing non-Blackboard location queries (e.g. "Where is the Campus Store?") are unaffected.

**Status:** Fixed. `app/main.py` updated.

---

---

## Content Gap 001 — McGraw Hill Connect "Read Now" Button Missing

**Problem:**
Students reporting no "Read Now" button for McGraw Hill Connect in the Immediate Access tab had no accurate instruction content to retrieve. Existing McGraw Hill files covered general Connect access but never addressed the "no Read Now" scenario explicitly. When these queries fired, the bot fell through to the general Immediate Access tab instructions (VitalSource-specific, `INSTR_GENERAL_SOURCE_20`) — wrong platform, wrong steps.

**Root Causes (three separate issues):**

1. **No content** — No instruction file existed for the "no Read Now button + McGraw Hill" scenario.
2. **Wrong index** — The `is_missing_read_now_button()` routing block overrode the platform to `None` (general index) for ALL platforms, including McGraw Hill. McGraw Hill has its own index and its own access pattern.
3. **Intent misclassification** — Some phrasings (e.g. "There is no Read Now button for my McGraw Hill textbook") were classified as `GENERAL_FAQ` by `detect_intent()`, bypassing the Read Now routing block entirely. A fourth variant was intercepted by the ambiguous platform clarification check before routing could apply.

**Fixes Applied:**

1. **New file** — `data/instructions/ia_mcgraw_hill_connect_no_read_now.txt`:
   - Explains that McGraw Hill Connect does NOT use a "Read Now" button — this is expected behavior, not a bug.
   - Provides all three access methods: Immediate Access tab → Connect link, Learning Activities tab, and Tools tab.
   - Re-ingested; mcgraw FAISS index now has 9 vectors (was 8).

2. **Platform-aware routing** — In the Read Now override block in `app/main.py`, added a `MCGRAW_HILL` branch that routes to the mcgraw index with a targeted query instead of dropping to the general index.

3. **Intent override** — Added a post-`detect_intent()` guard: if `is_missing_read_now_button()` is True and a platform is already known, force `IA_ACCESS_ISSUE` regardless of what `detect_intent()` returned.

4. **Ambiguous check exclusion** — Added `and not is_missing_read_now_button(message)` to the ambiguous platform clarification gate so "no Read Now" queries are never intercepted there.

**Verified:** All four tested McGraw Hill "no Read Now" phrasings now return `INSTR_MCGRAW_SOURCE_4` (new file) at conf 0.740. Non-McGraw "no Read Now" queries (Cengage, no platform) continue to behave correctly.

**Files changed:**
- `data/instructions/ia_mcgraw_hill_connect_no_read_now.txt` (new)
- `app/main.py` (routing fixes)

**Status:** Fixed.

---

## Summary

| Issue | Was it real? | Fixed? |
|---|---|---|
| Bug 001 — META prefix leaking into replies | No — not reproducible | N/A |
| Bug 002 — MCGRAW_HILL / mcgraw key mismatch | No — `.split('_')[0]` handles it | N/A |
| Bug 003 — Blackboard location → campus store address | Yes — confirmed across 5 variants | Yes |
| Content Gap 001 — McGraw Hill Connect no Read Now button | Yes — no content + 3 routing issues | Yes |
