# Phase 8 Required Knowledge Files

The `data/` directory is intentionally gitignored in this project. Do not force-add
these knowledge files to git. Add them through the admin UI or the deployment data
process, then rebuild the FAISS indexes on the target machine.

## Required Files

### `data/faqs/immediate_access/ia_opt_out_canvas.txt`

`source_id`: `ia_opt_out_canvas`

Purpose: answers "How do I opt out of Immediate Access?"

This source should include Canvas opt-out steps and the support email
`optout@calbaptist.edu`.

Recommended content:

```text
---
source_id: ia_opt_out_canvas
source_type: faq
category: immediate_access
platform: canvas
issue_type: opt_out
priority: canonical
---

QUESTION:
How do I opt out of Immediate Access?

ANSWER:
To opt out of Immediate Access in Canvas:

1. Log in to your CBU Canvas account using your student email and password.
2. Click Courses on the global navigation menu.
3. Open the homepage of the course using Immediate Access.
4. Click Immediate Access from the course menu on the left-hand side.
5. Locate the Immediate Access title or titles you wish to opt out of.
6. Click the "Want to Opt-Out" button.
7. Select the reason for opting out in the confirmation box.
8. Click Opt Out.
9. Verify that you have opted out of the materials. In the IA content block, confirm that the red caution symbol and "Opted Out" are visible.

Repeat these steps for every Immediate Access course you wish to opt out of.

If you are still having issues opting out, email optout@calbaptist.edu.
```

### `data/faqs/immediate_access/ia_zero_courses_zero_materials_cache.txt`

`source_id`: `ia_zero_courses_zero_materials_cache`

Purpose: answers "0 Courses, 0 Materials", "You currently have no content available",
and the VitalSource screenshot variant "You currently have no content available, please
contact your faculty or digital program manager for assistance."

**Important:** VitalSource displays "please contact your faculty or digital program manager
for assistance" on the same screen. The source must direct the LLM to treat this screen as
the known 0 Courses / 0 Materials issue and answer with the cache-clearing steps first —
without making faculty/program manager contact the primary advice.

The source now includes full browser-specific cache clearing steps inline (Chrome, Firefox,
Safari, Chrome on iPad) so the LLM has all guidance in a single grounding context.

Recommended content:

```text
---
source_id: ia_zero_courses_zero_materials_cache
source_type: faq
category: immediate_access
platform: null
issue_type: browser_cache
priority: canonical
---

QUESTION:
I see "0 Courses, 0 Materials" or "You currently have no content available" or "You currently have no content available, please contact your faculty or digital program manager for assistance." What should I do?

ANSWER:
CBU IMMEDIATE ACCESS SUPPORT NOTE: VitalSource may also display "please contact your faculty or digital program manager for assistance" on this screen. For CBU Immediate Access troubleshooting, treat this screen as the known 0 Courses / 0 Materials issue. First clear your browser cache, cookies, and history using the documented steps below. If the issue continues, contact ImmediateAccess@calbaptist.edu with a screenshot.

If you see "0 Courses, 0 Materials" or "You currently have no content available" when trying to access Immediate Access materials, this is caused by stale browser data. Clear your browser cache, cookies, and history, then try again.

Note: After clearing your browsing data, you will be signed out of most websites and will need to sign back in.

[Full Chrome/Firefox/Safari/iPad cache-clearing steps — see local data file for complete content]

If the issue continues, contact Immediate Access support at ImmediateAccess@calbaptist.edu. Include a screenshot of what you are seeing.
```

## Publish Steps

1. Add both files through the admin UI or deployment data process.
2. Confirm the four existing browser-specific cache files are still present:
   `ia_browser_cache_clear_chrome.txt`,
   `ia_browser_cache_clear_chrome_ipad.txt`,
   `ia_browser_cache_clear_firefox.txt`, and
   `ia_browser_cache_clear_safari.txt`.
3. Rebuild the knowledge indexes:

```bash
python -m app.rag.ingest
```

4. Restart the backend so the retriever reloads the updated FAISS indexes and
   chunk metadata.

## Manual Verification Prompts

- `How do I opt out of Immediate Access?`
- `I see 0 Courses, 0 Materials on VitalSource`
- `How do I create a VitalSource Bookshelf account?`
- `VitalSource issue`
- `My book is locked`
- `It says You currently have no content available` (with VitalSource screenshot attached)
  - Expected: route_type=KNOWN_ISSUE_LLM, answer gives cache/cookies guidance
  - Must NOT say: "contact your faculty or digital program manager"
  - Must NOT say: "the screenshot differs from the standard issue"
