# Lancer: Bookstore and Policy Features Operations Handoff

This document covers the two website-driven features added to the Lancer chatbot: course-materials lookup and semester policy refresh for opt-out and return deadlines. It explains how they work, how to keep them running, and the procedure that must be done by hand each semester.

Audience: the person maintaining Lancer day to day and the stakeholder who owns infrastructure decisions. Routine tasks are single commands plus one config-file edit.

## 1. What These Features Do

**Course-materials lookup.** A student can ask the chatbot, "what materials do I need for ATR 511?" The bot asks for their section and session, then returns the required textbooks, software, lab materials, or access codes for that exact course, section, and term from a local snapshot of the bookstore website data.

**Policy and deadline answers.** A student can ask "when is the opt-out deadline?" or "when is the return deadline?" and the bot answers with the relevant date from the local policy cache. Broader return-policy and Immediate Access explanations are also refreshed for the bot's general answers.

Both features read from local data on the same machine that runs the chatbot. The bot does not call the bookstore website while a student is chatting. It reads a local snapshot that is refreshed on a schedule or at semester rollover.

## 2. How The Data Gets There

There are two refresh jobs. Both run on the machine that runs Lancer, call the bookstore website, and write results into local data files the chatbot reads.

| Job | What it refreshes | Normal timing | Command |
| --- | --- | --- | --- |
| Bookstore cache | Course materials for configured terms | Weekly, and at semester rollover | `python mbs_insite_probe.py --cache-configured` |
| Policy refresh | Opt-out dates, return dates, policy prose | At semester rollover, and whenever policy dates change | `python scripts/scrape_policy_info.py` |

The bookstore job stores data in `data/bookstore_cache.db`.

The policy job stores dates in `data/policy_cache.db`, rewrites policy text files under `data/faqs/`, and rebuilds the chatbot search index.

## 3. One Operational Rule

Only one refresh job should run at a time.

Both jobs write local data and both talk to the bookstore website. Running two refreshes at once can produce inconsistent local data or trip the bookstore site's bot protection. Before starting a manual run, make sure a scheduled refresh is not currently running.

Students chatting with the bot or a maintainer running lookup checks is safe. The rule is only about refresh jobs.

## 4. Weekly Bookstore Refresh

This should run automatically through the host machine's scheduler. On the current Windows setup, that means Windows Task Scheduler. On a future Mac mini, this should move to `launchd` or cron.

Reference behavior:

- Runs weekly, preferably off-hours.
- Runs `python mbs_insite_probe.py --cache-configured`.
- Reads which terms to cache from `config/bookstore_config.yaml`.
- Can take roughly 45 to 60 minutes depending on the number of configured terms and bookstore response time.

Manual run, when no scheduled refresh is already in progress:

```powershell
python mbs_insite_probe.py --cache-configured
```

## 5. Semester Rollover

This is the routine task most likely to break the bot if done partially. When the bookstore opens a new term and closes an old one, the chatbot config and local cache must be updated together.

If the active semester label is changed without refreshing the cache, the bot will look for the new term in old local data and return "not found" for course-material lookups.

Do these steps in one sitting.

### Step 1: Find Current Bookstore Term IDs

```powershell
python mbs_insite_probe.py --map-dropdowns
```

This prints the bookstore's current term labels and IDs. Note the term labels and IDs that should be cached, such as full term, session 1, and session 2. If the bookstore exposes additional open terms that should be searchable, include those too.

### Step 2: Update The Config

Open `config/bookstore_config.yaml` and update:

- `active_semester`, for example `"SUMMER"` to `"FALL"`.
- `active_year`, if the year changed.
- `active_terms`, replacing labels and IDs with the current terms from Step 1.

The chatbot uses `active_semester` and `active_year` to build the session labels it asks students about. The scraper uses `active_terms` to decide what to cache.

### Step 3: Refresh The Bookstore Cache

```powershell
python mbs_insite_probe.py --cache-configured
```

Wait for it to finish. It prints totals per term at the end.

### Step 4: Refresh Policy Dates And Prose

```powershell
python scripts/scrape_policy_info.py
```

This updates opt-out and return deadlines and rebuilds the policy search text. It refuses to update if the scraped data fails validation. If validation fails, the previous data stays in place.

## 6. Quick Checks After A Refresh

Check a known current course:

```powershell
python -c "from app.bookstore_cache import lookup_course_by_term; import json; print(json.dumps(lookup_course_by_term('ATR','511','A','<TERM LABEL>'), indent=2, default=str))"
```

Check policy dates:

```powershell
python -c "from app.policy_cache import get_opt_out_deadline; import json; print(json.dumps(get_opt_out_deadline(), indent=2, default=str))"
```

Chatbot smoke checks:

- "what materials do I need for <a current course>?"
- "when is the opt-out deadline?"
- "when is the return deadline?"
- "how do I opt out of immediate access?"

The deadline questions should use the policy date cache. The "how do I opt out" procedure question should still return Canvas opt-out instructions.

## 7. Policy Refresh Safety Gate

The policy script validates scraped data before overwriting anything. It checks that:

- Opt-out and welcome-email lists each have enough rows.
- Every scraped date parses to ISO format.
- At least one parsed date belongs to the current or future academic year.
- The return-policy page yields at least the `final_after` date.

If validation fails, no database, text, or index files are updated.

The script also keeps backup copies of policy text files and restores them if the FAISS ingest step fails.

Source pages:

- IA and opt-out dates: `https://bookstore.calbaptist.edu/ia`
- Return policy: `https://bookstore.calbaptist.edu/customerservice#returns`

## 8. Routing Behavior

- A course-code material question triggers bookstore lookup.
- The bot asks for section, then session, then answers from `data/bookstore_cache.db`.
- A section ending in two letters where the final letter is `E`, such as `AE`, is displayed as Online. Otherwise the bot displays Traditional. This is informational and does not filter results.
- A deadline question is answered from `data/policy_cache.db`.
- A procedure question like "how do I opt out" still uses the existing Immediate Access Canvas instructions.
- If a course, section, or term is not found, the bot points the student to the bookstore site and `ImmediateAccess@calbaptist.edu`; it does not scrape live during chat and does not guess.

## 9. Known Infrastructure Debt

These are not feature bugs. They are environment and deployment items to resolve before a durable production setup.

### OneDrive Path

The project currently lives under a OneDrive-synced Desktop path. Scheduled jobs writing SQLite databases inside a syncing folder are fragile because sync can collide with writes and machine-specific paths can change.

Production should use a local, non-synced project path, ideally on the planned host machine.

### Ngrok Dependency

The frontend resolves relative PDF links against `API_BASE_URL`. Today that value may point at an ngrok tunnel. Ngrok URLs rotate, so PDF links and API access can break when the tunnel changes.

The planned static IP, DNS, and HTTPS migration fixes both the frontend API endpoint and the PDF links.

### Search Index Tracking

`data/faqs/faiss_index` is currently tracked and still modified by ingest. The team needs to decide whether search indexes remain version-controlled or become generated deployment artifacts.

Until that deployment decision is made, do not casually remove or untrack the index.

### Local SQLite Databases

`data/bookstore_cache.db` and `data/policy_cache.db` are runtime data. They should not be committed unless there is an explicit deployment reason to version them. Check `.gitignore` behavior when these appear as untracked files.

## 10. File Map

| Item | Location |
| --- | --- |
| Bookstore scraper and cache CLI | `mbs_insite_probe.py` |
| Bookstore term config | `config/bookstore_config.yaml` |
| Bookstore cache helpers | `app/bookstore_cache.py` |
| Bookstore cache data | `data/bookstore_cache.db` |
| Policy scraper and refresh CLI | `scripts/scrape_policy_info.py` |
| Policy cache helpers | `app/policy_cache.py` |
| Policy cache data | `data/policy_cache.db` |
| IA overview RAG prose | `data/faqs/ia_overview.txt` |
| Textbook return RAG prose | `data/faqs/textbook_refund_policy.txt` |
| Chat routing | `app/main.py` |
| Frontend API base and PDF recommendation handling | `ui/src/App.tsx`, `ui/src/services/api.ts` |

## 11. Triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Bot says "not found" for every course | Active semester changed but cache was not refreshed | Run the semester rollover steps |
| Bot gives an outdated opt-out or return deadline | Policy refresh has not run since dates changed | Run `python scripts/scrape_policy_info.py` |
| Policy script validation fails | Bookstore page is stale or page shape changed | Check source pages, wait if dates are not posted, or inspect parser |
| Course answers seem stale | Weekly bookstore refresh did not run | Run `python mbs_insite_probe.py --cache-configured` manually |
| PDF links break | `API_BASE_URL` points at a rotated ngrok URL | Update API base, or complete static IP/DNS migration |
| Manual refresh errors midway | Another refresh may be running, or bookstore blocked a burst | Ensure only one refresh runs, then rerun |
| `data/bookstore_cache.db` appears untracked | Ignore rule is missing or malformed | Fix `.gitignore`; do not commit the DB by accident |

## 12. Handoff Notes

Keep this file with the project and update it in the same commit as future command or layout changes. The most important operational habit is to keep config labels, cached data, and policy dates aligned during semester rollover.
