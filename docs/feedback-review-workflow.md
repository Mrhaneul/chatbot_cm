# Lance Feedback Review Workflow

Phase 6 added student response feedback for evaluation and staff review. Feedback is review-only data. It does not automatically train the model, edit prompts, alter retrieval, or change content.

## What Students Can Submit

The feedback API accepts:

- response ID
- session ID, if available
- rating from 1 to 5
- optional comment
- original student message
- Lance response text
- source label
- retrieval confidence
- optional retrieved source file

Lance does not intentionally store IP addresses, browser fingerprints, request headers, or other unnecessary student identifiers for feedback.

## Where Feedback Is Stored

Default path:

```text
data/feedback/feedback.jsonl
```

Each line is one JSON record. Malformed lines are skipped during admin listing and update so a single bad line does not break the review queue.

This JSONL storage is an MVP for a single-process deployment. Future high-concurrency deployments should use SQLite, Firestore, or another transactional store.

## Admin Review Steps

1. Open the Admin UI:

   ```text
   http://localhost:8000/admin
   ```

2. Open the Feedback tab.
3. Use filters:
   - Low ratings only: ratings 1-2
   - Source label
   - Date
   - Unreviewed only
   - Unresolved only
4. Read the student message, Lance answer, source label, confidence, source file, and optional comment.
5. Mark the item reviewed once a staff member has looked at it.
6. Mark the item resolved after a content, routing, documentation, or no-action decision is made.

## Triage Guidelines

| Feedback pattern | Likely action |
|---|---|
| Low rating and wrong source file | Investigate retrieval/routing |
| Low rating and correct source file but stale answer | Edit the `.txt` content in Admin UI |
| Low rating and vague student message | Consider intake wording or add a regression test |
| High rating | Keep for examples of good behavior |
| Comment reports a policy change | Verify with Campus Store staff before editing content |
| Harmful or out-of-scope prompt got through | Add safety test and rule/classifier improvement |

## What Not To Do

- Do not feed raw feedback directly into fine-tuning.
- Do not automatically update prompts or content from feedback comments.
- Do not commit `data/feedback/feedback.jsonl` unless intentionally creating a sanitized test fixture.
- Do not store student names or ID numbers in admin notes.

## Review Cadence

Recommended during active terms:

- Check low ratings twice per week.
- Check unresolved feedback weekly.
- Before each semester, review unresolved items alongside the seasonal maintenance checklist.
