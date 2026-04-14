# Lance — Seasonal Maintenance Guide

> **Who this document is for:** Campus Store staff responsible for keeping Lance's content accurate at the start of each semester. This checklist takes approximately 20 minutes to complete. IT and developers do not need to be involved unless the server is down.

---

## 1. When to run this checklist

Run this checklist **one week before the first day of classes** each Fall and Spring semester. Do not wait until the first day — students start asking about textbook access and return deadlines before classes begin.

**Semester schedule:**
| Semester | When to run checklist |
|---|---|
| Fall | One week before Fall classes begin (typically mid-August) |
| Spring | One week before Spring classes begin (typically early January) |
| Summer (if applicable) | One week before Summer session begins |

**Who is responsible:**
Campus Store staff — specifically whoever manages the Immediate Access program. This does not require IT or a developer unless the server is down when you try to make updates.

---

## 2. Required updates — every semester

These files contain date-sensitive information that becomes incorrect at the start of every new semester. They must be updated without exception.

---

### ✅ File 1: `textbook_refund_policy.txt`

This file contains three sections that need updating each semester.

**What to update:**

**FAQ_0** — The summary entry at the top. Update the current semester name and the no-penalty return deadline:
```
[FAQ_0]
0. How do I return a textbook?
...
For [Season 20XX] semester textbooks, the no-penalty return deadline is [DATE].
...
```

**FAQ_3** — The Fall semester return policy entry:
```
[FAQ_3]
3. What is the return policy for Fall 20XX semester textbooks?
- Returns and exchanges accepted without penalty until [DATE]
- Returns accepted with 25% restocking fee from [DATE] through [DATE]
- All sales are FINAL after [DATE]
```

**FAQ_4** — The Spring semester return policy entry:
```
[FAQ_4]
4. What is the return policy for Spring 20XX semester textbooks?
- Returns and exchanges accepted without penalty until [DATE]
- Returns accepted with 25% restocking fee from [DATE] through [DATE]
- All sales are FINAL after [DATE]
```

**How to update:**
1. Open `data/faqs/textbook_refund_policy.txt` on the server machine
2. Update the dates in FAQ_0, FAQ_3, and FAQ_4
3. Save the file
4. Go to Admin UI → Remove Content → select `textbook_refund_policy.txt` → Remove
5. Click Apply Changes
6. Admin UI → Add Content → upload the updated file
7. Click Apply Changes

---

### ✅ File 2: `campus_store_textbook_rentals.txt`

This file contains the rental return deadline at the bottom. Update it to the current semester's due date.

**What to update:**
```
CURRENT RENTAL RETURN DEADLINE:
[Season 20XX] rental books must be returned to the Campus Store by
[DATE] to avoid being charged the Replacement Cost Fee.
```

**How to update:**
1. Open `data/faqs/campus_store_textbook_rentals.txt` on the server machine
2. Update the season, year, and deadline date at the bottom of the file
3. Save the file
4. Admin UI → Remove Content → select `campus_store_textbook_rentals.txt` → Remove
5. Click Apply Changes
6. Admin UI → Add Content → upload the updated file
7. Click Apply Changes

---

## 3. Conditional updates — check each semester

These files may or may not need updating depending on what changed. Check each one and update if needed.

### `campus_store_hours.txt`
Check whether store hours have changed from the previous semester. Hours sometimes change between Fall/Spring and Summer sessions.

**How to check:** Compare the current hours in the file against the hours posted on the Campus Store website or confirmed by store management.

### Platform instruction files (`data/instructions/`)
Publisher platforms occasionally update their interfaces — button names change, navigation paths shift, new steps are added. At the start of each semester, spot-check the two highest-volume platforms:
- McGraw Hill Connect (`ia_mcgraw_hill_connect_access.txt`)
- Cengage MindTap (`ia_cengage_mindtap_access.txt`)

Log into each platform using a test account and follow the steps in the instruction file. If the steps no longer match the current interface, update the file.

### Browser cache instruction files
Browsers (Chrome, Firefox, Safari) occasionally release major updates that change where settings are located. At the start of each semester, quickly verify the cache-clearing steps still work in each browser:
- `ia_browser_cache_clear_chrome.txt`
- `ia_browser_cache_clear_firefox.txt`
- `ia_browser_cache_clear_safari.txt`
- `ia_browser_cache_clear_chrome_ipad.txt`

If the steps are still accurate, no update needed.

---

## 4. How to apply updates

Use the Admin UI for all content updates. Do not edit files directly on disk unless you are comfortable running ingestion manually from the terminal.

**Standard update workflow (Admin UI):**
1. Edit the `.txt` file on your computer with the updated information
2. Go to `http://localhost:8000/admin`
3. Click **Remove Content** → select the old file → click **Remove**
4. Click **Apply Changes** — wait for confirmation
5. Click **Add Content** → upload the updated file → click **Upload**
6. Click **Apply Changes** — wait for confirmation
7. Test the update (see Section 5)

**If the Admin UI is not accessible:**
Contact IT — the backend server is not running. Do not attempt updates until the server is back up.

---

## 5. How to verify the updates worked

After updating each file, go to the student-facing chat UI and ask these test questions. Verify the responses contain the correct new dates.

| File updated | Test question to ask Lance | What to verify |
|---|---|---|
| `textbook_refund_policy.txt` | "What is the return policy for this semester's textbooks?" | Response shows the current semester name and correct no-penalty deadline |
| `textbook_refund_policy.txt` | "When is the last day to return my textbook without a fee?" | Response shows the correct no-penalty deadline date |
| `campus_store_textbook_rentals.txt` | "When do I need to return my rental textbook?" | Response shows the correct rental return deadline for the current semester |
| `campus_store_hours.txt` (if updated) | "What are the Campus Store hours?" | Response shows updated hours |

**If the response still shows old dates:**
1. Confirm Apply Changes was clicked after both the Remove and Add steps
2. Hard refresh the browser (Ctrl+Shift+R) to clear any cached responses
3. If still wrong, restart uvicorn and try again:
   ```powershell
   # Stop uvicorn (Ctrl+C) then restart:
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

---

## 6. Semester maintenance log

Keep a record of when this checklist was completed each semester. This helps confirm the checklist was run if a student later reports receiving wrong deadline information.

| Semester | Date completed | Updated by | Notes |
|---|---|---|---|
| Spring 2026 | | | |
| Fall 2026 | | | |
| Spring 2027 | | | |
| Fall 2027 | | | |

Fill in the date and your name each time you complete the checklist.

---

## 7. Quick reference — files with date-sensitive content

| File | What changes | How often |
|---|---|---|
| `textbook_refund_policy.txt` | Semester return deadlines (FAQ_0, FAQ_3, FAQ_4) | Every semester |
| `campus_store_textbook_rentals.txt` | Rental return deadline date | Every semester |
| `campus_store_hours.txt` | Store hours | When hours change |
| Platform instruction files | Access steps if publisher UI changed | When publisher updates their platform |
| Browser cache files | Cache clearing steps if browser UI changed | When browsers release major updates |

---

> **Reminder:** The most common support issue at the start of every semester is students receiving wrong return deadline information from Lance. Running this checklist before classes begin prevents that entirely.
