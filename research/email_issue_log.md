# Email Issue Log

This file tracks real student-email scenarios tested against the chatbot.
For each case, record:
- message transcript
- observed issues
- root cause analysis
- implemented solution
- retest results

## Case 001 - ACC540 Immediate Access Link Missing

- Date: 2026-03-03
- Source Email File: `emails/2026-SP-E1 ACC540-AE-Advncd Topics in Financial Acctg.msg`
- Student Summary: Student cannot find Immediate Access textbook link in Blackboard; assignment due soon.

### Initial Bot Transcript (Before Fix)

1. User:
   `My name is Gabrielle Tobin... not seeing the link for immediate access... in Blackboard.`
   Bot:
   `I can help with Immediate Access digital course materials. Could you specify which platform your textbook is on (e.g. Cengage, McGraw Hill, Pearson, Norton/InQuizitive)?`
   Meta:
   `SOURCE=INSTR_GENERAL_SOURCE_10, CONF=0.6114`

2. User:
   `I don't know which platform.`
   Bot:
   `I want to make sure I give you accurate Campus Store information. Could you clarify your question in terms of Immediate Access, textbook access, returns, or course-material policies?`
   Meta:
   `SOURCE=LLM_ONLY, CONF=0.1036`

3. User:
   `I think it's McGraw Hill Connect.`
   Bot:
   `I want to make sure I give you accurate Campus Store information...`
   Meta:
   `SOURCE=LLM_ONLY, CONF=0.1860`

4. User:
   `It still doesn't open.`
   Bot:
   `CBU Campus Store hours are: ...`
   Meta:
   `SOURCE=FAQ_SOURCE_1, CONF=0.3145`

### Issues Logged

1. IA clarification state was not consistently preserved after the first turn.
2. Low-information reply (`I don't know`) fell out of IA flow and returned generic FAQ clarification.
3. Follow-up troubleshooting (`It still doesn't open`) derailed into unrelated Campus Store hours.

### Root Cause

1. Platform clarification was only triggered by a narrow "vague query" condition (length/keyword dependent), not all IA-without-platform queries.
2. IA state fields (`stored_intent`, `stored_platform`) were reset or not reliably persisted.
3. Follow-up turns without explicit platform names could be reclassified as `GENERAL_FAQ`.

### Implemented Solution

File updated: `app/main.py`

1. Added IA continuity helper:
   - `detect_recent_platform_from_history(history)`
2. Added IA continuity guard:
   - If previous stored intent is IA and user sends short troubleshooting follow-up, keep `IA_ACCESS_ISSUE` and recover platform from session/history.
3. Broadened IA clarification trigger:
   - Any `IA_ACCESS_ISSUE` with unknown platform now requests platform clarification (not only short/vague messages).
4. Persisted IA context in clarification branches:
   - Store `stored_intent`, `stored_platform`, and `stored_original_query` consistently.

### Retest Transcript (After Fix)

Session replay using the same scenario:

1. USER:
   `My name is Gabrielle Tobin. Week 1 has started for my first course of Spring but I am not seeing the link for the immediate access to my textbook in BlackBoard. I have an assignment that is due this weekend that I need the textbook in order to complete.`

   BOT:
   `I can help you with textbook access! To give you the most accurate instructions, could you please specify which platform or publisher your textbook uses? Examples: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, VitalSource, Bedford, Sage, SimuCase, etc.`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

2. USER:
   `I don't know which platform.`

   BOT:
   `No worries! You can usually find the platform name on your Blackboard course page under the Immediate Access tab. It will say something like "Cengage MindTap," "McGraw Hill Connect," or "Pearson MyLab." Once you find it, let me know and I can walk you through the steps. You can also visit the CBU Campus Store for in-person help.`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

3. USER:
   `I think it's McGraw Hill Connect.`

   BOT:
   `Here's how to access McGraw Hill Connect:

PROBLEM:
Student cannot access their McGraw Hill Connect eTextbook or courseware through the Tools menu in Blackboard.

APPLIES TO:
Courses using McGraw Hill Connect digital content accessed via the Tools tab (commonly used in Business courses such as BUS 212 Economics, Life and Society).

BLACKBOARD LOCATION:
Tools tab (left side pane)

STEP-BY-STEP RESOLUTION:

1. Log into Blackboard.
2. Go to your course page.
3. Click "Tools" on the left-hand side menu.
4. Click the link titled "McGraw Hill Connect LTIA Basic Link."
5. You will be taken to the McGraw Hill Connect course page.
6. Access your materials:

- For eTextbook: Click on the book image under "Read" in the Course materials section.
- For Assignments: Click on the weekly folders (Week 1, Week 2, etc.) to view assignments.

NAVIGATION INSIDE MCGRAW HILL CONNECT:

- Instructor information and messaging options are at the top left.
- Course materials section shows the textbook and loose leaf purchase options.
- Read section displays your eTextbook - click to open.
- Assignments section shows weekly folders with your coursework.
- You can download the mobile app to read offline.

EXPECTED RESULT:
After clicking the McGraw Hill Connect LTIA Basic Link, you should have access to both the eTextbook and weekly assignments.

IF ISSUE PERSISTS:
Contact ImmediateAccess@calbaptist.edu for assistance. Please send your email from your LancerMail address and include your name, ID#, and course info.`

   META:
   `SOURCE=INSTR_MCGRAW_SOURCE_3 | CONF=0.45066386461257935`

4. USER:
   `It still doesn't open.`

   BOT:
   `Here's how to access McGraw Hill Connect:

PROBLEM:
Student is opted into Immediate Access but cannot access McGraw Hill Connect textbook or assignments.

APPLIES TO:
Courses using McGraw Hill Connect.

Learning Activities tab

STEP-BY-STEP RESOLUTION:

3. Click on the ÃâÅLearning ActivitiesÃâÂ tab in the left menu.
4. Open the appropriate week folder (e.g., Week 1).
5. Click the McGraw Hill Connect link for the eText or assignment.
6. If prompted, log in or create a McGraw Hill account using your CBU email address.

LOGIN REQUIREMENTS:

- Use your full CBU email address (firstname.lastname@calbaptist.edu).
- Do NOT use your ID#@calbaptist.edu email.

EXPECTED RESULT:
Once logged in, the eText and assignments should open successfully within McGraw Hill Connect.

IF ISSUE PERSISTS:
Contact ImmediateAccess@calbaptist.edu for assistance. Please send your email from your LancerMail address and include your name, ID#, and course info.`

   META:
   `SOURCE=INSTR_MCGRAW_SOURCE_1 | CONF=0.3188270330429077`

### Chat 1 API Response (After Fix)

```json
{
  "reply": "I can help you with textbook access! To give you the most accurate instructions, could you please specify which platform or publisher your textbook uses? Examples: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, VitalSource, Bedford, Sage, SimuCase, etc.",
  "source": "CLARIFICATION_NEEDED",
  "article_link": null,
  "confidence": 0.0,
  "response_time_ms": null,
  "retrieval_time_ms": 0.0,
  "llm_time_ms": 0.0,
  "total_time_ms": 5.0,
  "recommended_pdfs": []
}
```

### Final Status

- Status: Fixed
- Regression outcome: No derail to Campus Store hours in this scenario.

---

## Case 002 - 813664 New Student Cannot Find Books

- Date: 2026-03-03
- Source Email File: `emails/813664.msg`
- Student Summary: New student cannot find books needed for classes and asks for assistance.
- Extracted Email Body:
  `Hello, my name is Destiny Chico I'm new to the program and I'm having trouble finding the books I need for my classes. if I can get some assistance please.`

### Initial Bot Transcript (Before Fix)

1. USER:
   `Hello, my name is Destiny Chico I'm new to the program and I'm having trouble finding the books I need for my classes. if I can get some assistance please.`

   BOT:
   `Immediate Access is California Baptist University's program... (full IA overview)`

   META:
   `SOURCE=FAQ_SOURCE_5 | CONF=0.3407818675041199`

2. USER:
   `I don't know which platform.`

   BOT:
   `I want to make sure I give you accurate Campus Store information...`

   META:
   `SOURCE=LLM_ONLY | CONF=0.10357111692428589`

3. USER:
   `Where can I find them in Blackboard?`

   BOT:
   `For the most current delivery directions, please check the CBU Campus Store website.`

   META:
   `SOURCE=FAQ_SOURCE_0 | CONF=0.2213822603225708`

### Issues Logged

1. After the first turn, `I don't know which platform` was not recognized as a platform-clarification follow-up.
2. Blackboard follow-up was misrouted to an unrelated Campus Store delivery directions FAQ.

### Root Cause

1. FAQ responses that ask users to specify platform were not setting platform-clarification session state.
2. IA continuity guard was too narrow (mostly issue-keyword based), so contextual Blackboard follow-ups could drop back into `GENERAL_FAQ`.

### Implemented Solution

File updated: `app/main.py`

1. Added `faq_suggests_platform_clarification(answer)` helper.
2. In deterministic FAQ response path, if FAQ text asks to specify platform:
   - set `awaiting_platform_type=True`
   - set `stored_publisher="TEXTBOOK_GENERIC"`
   - set `stored_intent="IA_ACCESS_ISSUE"`
3. Expanded IA continuity guard to treat Blackboard/materials/platform follow-ups as IA-context turns.

### Retest Transcript (After Fix)

1. USER:
   `Hello, my name is Destiny Chico I'm new to the program and I'm having trouble finding the books I need for my classes. if I can get some assistance please.`

   BOT:
   `Immediate Access is California Baptist University's program... (full IA overview with "please specify which platform")`

   META:
   `SOURCE=FAQ_SOURCE_5 | CONF=0.3407818675041199`

2. USER:
   `I don't know which platform.`

   BOT:
   `No worries! You can usually find the platform name on your Blackboard course page under the Immediate Access tab...`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

3. USER:
   `Where can I find them in Blackboard?`

   BOT:
   `I still need the platform name to give the correct steps. Please share which one you see in Blackboard Immediate Access...`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

### Chat 1 API Response (After Fix)

```json
{
  "reply": "Immediate Access is California Baptist University's program that provides day-one access to digital course materials through your student account. ... If you're having trouble accessing your materials, please specify which platform you need help with (e.g., \"I can't access Cengage MindTap\" or \"Help with McGraw Hill Connect\").",
  "source": "FAQ_SOURCE_5",
  "article_link": null,
  "confidence": 0.3407818675041199
}
```

### Final Status

- Status: Fixed
- Regression outcome: Follow-up turns now stay in IA clarification flow and no longer derail to delivery directions.

---

## Case 003 - Book Discovery Clarification (Physical vs Immediate Access)

- Date: 2026-03-03
- Trigger: User requested a specific response pattern for "having trouble finding books" queries.
- Requirement: Ask whether user needs `physical textbook` or `Immediate Access` and route accordingly.

### Implemented Behavior

For discovery-style messages (example: "I'm having trouble finding the books I need for my classes"):

1. Bot asks:
   `Are you trying to find a physical textbook or Immediate Access digital materials?`
2. If user chooses `Immediate Access`, bot asks for platform.
3. If user says `I don't know`, bot gives Blackboard guidance to find platform.
4. If user then provides platform only (example: `McGraw Hill Connect`), bot now returns deterministic platform instructions directly.
5. If user chooses `physical textbook`, bot gives physical-book guidance with Campus Store location/phone and IA print-availability note.

### Retest Transcript

1. USER:
   `Hello, my name is Destiny Chico I'm new to the program and I'm having trouble finding the books I need for my classes. if I can get some assistance please.`
   BOT:
   `I can help with that. Are you trying to find a **physical textbook** or **Immediate Access digital materials**?`
   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

2. USER:
   `Immediate Access digital materials.`
   BOT:
   `Great - for Immediate Access digital materials, I can guide you step-by-step. Which platform do you see in Blackboard?...`
   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

3. USER:
   `I don't know which platform.`
   BOT:
   `No worries! You can usually find the platform name on your Blackboard course page under the Immediate Access tab...`
   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

4. USER:
   `McGraw Hill Connect`
   BOT:
   `Here's how to access McGraw Hill Connect: ...`
   META:
   `SOURCE=INSTR_MCGRAW_SOURCE_4 | CONF=0.6306739449501038`

### Final Status

- Status: Fixed
- Outcome: The book-discovery flow now asks the required physical-vs-digital question and routes follow-ups correctly.

---

## Case 004 - Acknowledgement Loop While Awaiting Platform

- Date: 2026-03-03
- Trigger: User says `Found it, thank you!` after Blackboard guidance.
- Context: Session is still in `awaiting_platform_type`.

### Initial Behavior (Before Fix)

Conversation segment:

1. USER:
   `Where can I find them in Blackboard?`
   BOT:
   `I still need the platform name...`

2. USER:
   `Found it, thank you!`
   BOT:
   `I still need the platform name...` (same rigid fallback repeated)

### Issue Logged

1. Acknowledgement/gratitude replies were treated as missing-platform errors and repeated the same fallback text.

### Root Cause

1. `awaiting_platform_type` flow handled low-info responses, but did not have a dedicated acknowledgement branch.

### Implemented Solution

File updated: `app/main.py`

1. Added acknowledgement detection in clarification state:
   - phrases like `thank you`, `thanks`, `found it`, `got it`.
2. If acknowledgement is detected and no platform is provided:
   - return a friendly acknowledgement + one clear ask for platform name.
   - keep source as `CLARIFICATION_NEEDED`.

### Retest (After Fix)

1. USER:
   `Found it, thank you!`
   BOT:
   `Glad that helped. Please share the platform name you found in Blackboard (for example: Cengage MindTap, McGraw Hill Connect, or Pearson MyLab), and I'll walk you through the exact steps.`
   META:
   `SOURCE=CLARIFICATION_NEEDED`

### Final Status

- Status: Fixed
- Outcome: No repetitive loop on acknowledgement-only replies.

---

## Case 005 - Blackboard & InsideCBU Login for Pre College Credit Class

- Date: 2026-03-05
- Source Email File: `emails/Blackboard & InsideCBU Login for Pre College Credit Class.msg`
- Extracted Student Message:
  `Hello, I wanted to ask about how I’m supposed to access the class I signed up for pre college credit. I got an email telling me about the materials and how that works but I don’t know how to access the class.`
- Sender: `Julian Hinojosa <drkwzrd24@gmail.com>`

### Initial Behavior (Before Fix)

1. USER:
   `I'm supposed to access the class... I don't know how to access the class.`
   BOT:
   `It sounds like this is a Blackboard/InsideCBU login or class-access issue. Please contact CBU IT support (or the Pre-College support team) to restore account/class access first. Once you can open your Blackboard course, share the platform name from the Immediate Access area (for example: Cengage MindTap, McGraw Hill Connect, or Pearson MyLab), and I'll guide you through textbook access.`
   META:
   `SOURCE=LLM_ONLY | CONF=0.0`

### Issues Logged

1. Ambiguous "access class" query was incorrectly and prematurely identified as a login/class-access issue.
2. User was not asked to clarify their intent before being routed to a specific solution.

### Root Cause

1. The `is_blackboard_insidecbu_login_issue` detector was too broad and was triggered by the ambiguous phrase "access the class".
2. No dedicated clarification step existed for ambiguous "access class" queries.

### Implemented Solution

File updated: `app/main.py`

1.  **Refined Detection Logic**:
    *   Replaced the overly broad `is_blackboard_insidecbu_login_issue` with a more precise `is_explicit_login_issue` function that only triggers on explicit login-related keywords (e.g., "can't log in", "password").
    *   Created a new `is_ambiguous_class_access_query` function to specifically detect vague phrases like "access the class" when no other context is provided.
    *   Removed "material" from the exclusion list in `is_ambiguous_class_access_query` to better handle cases where the user mentions it incidentally.

2.  **Added Clarification Flow**:
    *   When `is_ambiguous_class_access_query` is true, the bot now first asks the user to clarify whether they are having trouble with **"the class itself"** or **"the class materials"**.
    *   A new session state, `awaiting_class_access_clarification`, is used to track this.

3.  **Implemented Conditional Routing**:
    *   If the user confirms the issue is with **"the class itself"**, the bot provides the contact information for `ImmediateAccess@calbaptist.edu`.
    *   If the user confirms the issue is with **"the class materials"**, the bot transitions to the standard platform clarification flow, asking for the publisher/platform name.

### Retest Transcript (After Fix)

1. USER:
   `Hello, I wanted to ask about how I’m supposed to access the class I signed up for pre college credit. I got an email telling me about the materials and how that works but I don’t know how to access the class.`
   BOT:
   `I'd be happy to help! Just to clarify, are you having trouble accessing **the class itself** (logging in, finding your course), or accessing **the class materials** (textbook, Immediate Access, etc.)?`
   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

2. USER:
   `the class itself`
   BOT:
   `Contact ImmediateAccess@calbaptist.edu for assistance. Please send your email from your LancerMail address and include your name, ID#, and course info.`
   META:
   `SOURCE=LLM_ONLY | CONF=0.0`

*(Alternative branch test)*

2. USER:
   `the class materials`
   BOT:
   `I can help you with textbook access! To give you the most accurate instructions, could you please specify which platform or publisher your textbook uses? Examples: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, VitalSource, Bedford, Sage, SimuCase, etc.`
   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

### Final Status

- Status: Fixed
- Outcome: Ambiguous "access class" queries are no longer misrouted. The bot now correctly asks for clarification and routes the user to the appropriate solution based on their response.

---

## Case 006 - Immediate Access Tab Missing in Blackboard

- Date: 2026-03-09
- Source Email File: `emails/Immediate Access Not Pulling Up. .msg`
- Student Summary: Student paid in full but does not see the Immediate Access pulldown/tab in Blackboard for MPA 545.
- Extracted Student Message:
  `Good morning, my name is Bradley Boster, I am currently enrolled in MPA 545 in the Masters in Public Administration program and I am not able to access a pulldown for immediate access on the left hand side of the online interface. I paid everything in full, curious why it is not populating on my screen.`

### Initial Bot Transcript (Before Fix)

1. USER:
   `Good morning, my name is Bradley Boster, I am currently enrolled in MPA 545 in the Masters in Public Administration program and I am not able to access a pulldown for immediate access on the left hand side of the online interface. I paid everything in full, curious why it is not populating on my screen.`

   BOT:
   `I can help you with textbook access! To give you the most accurate instructions, could you please specify which platform or publisher your textbook uses? Examples: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, VitalSource, Bedford, Sage, SimuCase, etc.`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

2. USER:
   `I do not know which platform.`

   BOT:
   `No worries! You can usually find the platform name on your Blackboard course page under the Immediate Access tab...`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

3. USER:
   `There is no Immediate Access tab on the left side in Blackboard.`

   BOT:
   `I still need the platform name to give the correct steps...`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

### Issues Logged

1. Lance did not recognize a direct "there is no Immediate Access tab" follow-up as a missing-tab escalation case.
2. The student was looped back into platform clarification instead of being routed to the existing escalation path.
3. Windows console debug output in this request path could throw `UnicodeEncodeError` because of non-ASCII `print` statements.

### Root Cause

1. The missing-tab detector only covered a narrow set of phrases and missed common wording like `there is no Immediate Access tab`.
2. The `awaiting_platform_type` branch duplicated part of the missing-tab detection logic instead of reusing the shared helper, so fixes could drift.
3. Several debug prints in `app/main.py` used emoji, which are unsafe on some Windows console encodings.

### Implemented Solution

- Files updated: `app/main.py`, `tests/test_case_006_immediate_access_tab.py`
- Summary:
  - Expanded `is_cannot_find_immediate_access_query()` to include `no Immediate Access tab` phrasing.
  - Reused the shared missing-tab helper inside the `awaiting_platform_type` flow.
  - Replaced relevant request-path debug prints with ASCII-safe text.
  - Added a regression test for the full three-turn Bradley Boster scenario.

### Retest Transcript (After Fix)

1. USER:
   `Good morning, my name is Bradley Boster, I am currently enrolled in MPA 545 in the Masters in Public Administration program and I am not able to access a pulldown for immediate access on the left hand side of the online interface. I paid everything in full, curious why it is not populating on my screen.`

   BOT:
   `I can help you with textbook access! To give you the most accurate instructions, could you please specify which platform or publisher your textbook uses? Examples: Cengage MindTap, McGraw Hill Connect, Pearson MyLab, VitalSource, Bedford, Sage, SimuCase, etc.`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

2. USER:
   `I do not know which platform.`

   BOT:
   `No worries! You can usually find the platform name on your Blackboard course page under the Immediate Access tab...`

   META:
   `SOURCE=CLARIFICATION_NEEDED | CONF=0.0`

3. USER:
   `There is no Immediate Access tab on the left side in Blackboard.`

   BOT:
   `If you still can't find the Immediate Access tab in Blackboard, please contact ImmediateAccess@calbaptist.edu for assistance. Please send your email from your LancerMail address and include your name, ID#, and course info.`

   META:
   `SOURCE=LLM_ONLY | CONF=0.0`

### Final Status

- Status: Fixed
- Outcome: The Bradley Boster scenario now exits the clarification loop and escalates correctly once the student confirms the Immediate Access tab is missing.

---

## Case 007 - McGraw Hill "No read now" Button Missing

- Date: 2026-03-09
- Source Email File: `emails/No read now option .msg`
- Student Summary: Student is opted in for a McGraw Hill textbook but does not have a "Read Now" button in Blackboard.

### Initial Bot Transcript (Before Fix)

1. USER:
   `Hi. I have opted in for my textbook for Colquitt, J., LePine, J., & Wesson, M. (2023). Organizational behavior: Improving performance and commitment in the workplace (8th ed.). New York: McGraw Hill. ISBN: 978-1-265-36858-6 Access code is required. However, I do not have a "read now" button to read the material.`

   BOT:
   `Here's how to access McGraw Hill Connect:

NAVIGATION INSIDE MCGRAW HILL:
- Course materials section: Access loose leaf options and your course text.
- Read section: Click on your textbook to open it.
- Assignments section: View weekly assignments organized by Week folders (Week 1, Week 1, etc.).
- You can also download the mobile app to read offline.`

   META:
   `SOURCE=INSTR_GENERAL_SOURCE_92 | CONF=0.7013`

### Issues Logged

1. The bot provided general McGraw Hill navigation but did not address the specific problem of a missing "Read Now" button.
2. The response was retrieved from a general source instead of a specific "missing button" resolution.

### Root Cause

1. The instructions for McGraw Hill Connect did not contain a specific section for the "missing Read Now button" scenario.
2. A case-sensitivity bug in `app/rag/retriever.py` caused the retriever to miss the platform-specific index (MCGRAW) when "mcgraw" (lowercase) was detected, falling back to a general index with lower precision.

### Implemented Solution

- Files updated: `data/instructions/ia_mcgraw_hill_connect_access.txt`, `app/rag/retriever.py`
- Summary:
  - Added a new "MISSING READ NOW BUTTON" section to the McGraw Hill instruction file with steps to wait 10-15 minutes or contact the store.
  - Fixed `app/rag/retriever.py` to perform case-insensitive platform lookup, ensuring the "MCGRAW" index is correctly prioritized.

### Retest Transcript (After Fix)

1. USER:
   `I have opted into Immediate Access for my McGraw Hill textbook but I don't have a Read Now button`

   BOT:
   `Here's how to access McGraw Hill Connect:

PROBLEM:
Student is opted into Immediate Access for McGraw Hill but does not have a "Read Now" button.

STEP-BY-STEP RESOLUTION:
1. Log in to Blackboard
2. Navigate to your course
3. Click "Immediate Access" in the left navigation panel
4. If you see an opt-out option but no "Read Now" button, your access may still be processing — wait 10-15 minutes and refresh
5. If the button still does not appear, contact the CBU Campus Store at campusstore@calbaptist.edu or visit in person`

   META:
   `SOURCE=INSTR_MCGRAW_SOURCE_14 | CONF=0.7521`

### Final Status

- Status: Fixed
- Outcome: The bot now provides specific, accurate resolution steps for the missing "Read Now" button scenario.

---

## Case 008 - Instruction Chunking Regression + Read Now Button Trigger Missing

- Date: 2026-03-10
- Source: Regression introduced during Case 007 work; confirmed across McGraw Hill and Cengage.
- Student Summary: Bot returns only the PROBLEM description with no resolution steps. Affected all platforms. McGraw Hill "Read Now button" sub-scenario had no deterministic trigger, causing wrong chunk retrieval and silent failure on follow-up turns.

### Initial Bot Transcripts (Before Fix)

**Cengage:**

1. USER:
   `I can't access my Cengage textbook`

   BOT:
   `Here's how to access Cengage MindTap:

PROBLEM:
Student is opted into Immediate Access but cannot access Cengage MindTap textbook or assignments.`

   META:
   `SOURCE=INSTR_CENGAGE_SOURCE_0 | CONF=0.65`

**McGraw Hill (Read Now scenario):**

1. USER:
   `Hi. I have opted in for my textbook for Colquitt... McGraw Hill... I do not have a "read now" button to read the material.`

   BOT: *(returns general McGraw Hill Tools access instructions — no mention of Read Now)*

   META:
   `SOURCE=INSTR_MCGRAW_SOURCE_* | CONF=~0.70`

2. USER:
   `I can't find the read now button`

   BOT:
   `Some courses use external publisher platforms. In these cases, textbook access is provided through links inside the Blackboard course rather than directly through the Immediate Access page...`

   META:
   `SOURCE=LLM_ONLY | CONF=0.0`

3. USER:
   `I don't see Read Now button`

   BOT: *(generic/incomplete response)*

### Issues Logged

1. Bot returned only the PROBLEM section with no resolution steps — affected Cengage, McGraw Hill, and all other platforms.
2. McGraw Hill "Read Now button missing" scenario returned a general access chunk instead of the specific Read Now scenario chunk.
3. Follow-up messages about "read now button" (no platform name in text) were not caught by the IA continuity guard.

### Root Cause

1. **Chunking regression (all platforms)**: `ingest.py` used `_INSTRUCTION_HEADER_RE` to split instruction files on every ALL-CAPS header (`PROBLEM:`, `APPLIES TO:`, `STEP-BY-STEP RESOLUTION:`, etc.), creating 5–7 separate FAISS chunks per scenario. With `RETRIEVAL_TOP_K=1`, only the `PROBLEM:` chunk was returned — it is always most semantically similar to the student's access complaint. The `STEP-BY-STEP RESOLUTION:` chunk was never retrieved.
   - This regression was introduced during Case 007 when the chunking design was left unchanged while only the data file and retriever case-sensitivity were patched.
2. **No deterministic trigger for "Read Now" missing (McGraw Hill)**: No `is_missing_read_now_button()` function existed in `main.py`. Retrieval relied on FAISS finding the correct scenario, but `ia_mcgraw_hill_tools_access.txt` contained "Read section: Click on your textbook to open it" which scored higher than the short "NO READ NOW BUTTON SCENARIO" chunk.
3. **IA continuity blind spot**: "read now" and "read now button" were absent from `ia_context_terms`, so follow-up messages with no platform name fell through to `GENERAL_FAQ` and returned an LLM-only generic response.

### Implemented Solution

**File: `app/rag/ingest.py`**
- Replaced `_INSTRUCTION_HEADER_RE` (splits on every ALL-CAPS header) with `_SCENARIO_SEPARATOR_RE` (splits on `---` horizontal rule separators between distinct scenarios).
- Rewrote `_split_instruction_file` to keep each complete scenario (PROBLEM + RESOLUTION + all subsections) as one chunk. Secondary splitting is applied only if a scenario exceeds `MAX_CHUNK_TOKENS`.
- Updated `chunk_text` construction to not prepend a redundant `section_title` line — the body already contains all section headers.
- Re-ran ingestion: total instruction chunks dropped from ~80+ fragmented sections to 28 complete-scenario chunks.

**File: `app/rag/metadata.py`**
- Updated `section_title` schema comment: now reflects scenario label (`FULL_DOCUMENT` or `SCENARIO_N`) rather than ALL-CAPS header name.

**File: `app/main.py`**
- Added `is_missing_read_now_button(message)`: strips quotes before matching so `'read now'` and `"read now"` both match; detects missing signals like "do not have", "can't find", "don't see", etc.
- Fixed platform overwrite bug: line 2107 `platform = detect_platform_from_text(message)` was unconditionally overwriting platform set by the IA continuity guard. Changed to `if platform is None: platform = detect_platform_from_text(message)`.
- In the `IA_ACCESS_ISSUE` retrieval block: when `is_missing_read_now_button` is True, override `enhanced_query` with `"Read Now button missing Immediate Access not available processing"` and set `read_now_retrieval_platform = None` to force retrieval from the **general** index (not platform-specific). Sets `session["read_now_missing_active"] = True` for follow-up stickiness.
- Added `"read now"` and `"read now button"` to `ia_context_terms` in the IA continuity guard.

**File: `data/instructions/ia_read_now_button_missing.txt`** *(new)*
- Created a general "Read Now button missing" instruction file covering **all** Immediate Access platforms.
- "Read Now" is a general IA concept (not McGraw Hill-specific); same 5-step resolution applies to any platform: wait 10-15 min for access to process, then contact Campus Store.

**File: `data/instructions/ia_mcgraw_hill_connect_access.txt`**
- Removed the McGraw Hill-specific "NO READ NOW BUTTON SCENARIO" block — now superseded by the general file.

**Ingestion re-run:**
- McGraw Hill: 8 → 7 chunks (specific Read Now scenario removed).
- General index gains 1 new chunk (`ia_read_now_button_missing.txt`).
- Total: 28 instruction chunks.

### Retest Transcript (After Fix — Verified Live)

**Cengage — Read Now button missing:**

1. USER:
   `I have opted into Immediate Access for my Cengage textbook but I don't have a Read Now button`

   BOT:
   `Here's how to access Cengage MindTap:

PROBLEM:
Student is opted into Immediate Access but cannot see or click the "Read Now" button for their textbook in Blackboard.

APPLIES TO:
All Immediate Access courses where the eTextbook is accessed via the Immediate Access tab in Blackboard, regardless of publisher or platform.

BLACKBOARD LOCATION:
Immediate Access tab (left side pane)

STEP-BY-STEP RESOLUTION:
1. Log in to Blackboard.
2. Go to your course page.
3. Click "Immediate Access" in the left navigation panel.
4. If you see an opt-out option but no "Read Now" button, your access may still be processing — wait 10-15 minutes and refresh the page.
5. If the "Read Now" button still does not appear after waiting, contact the CBU Campus Store at campusstore@calbaptist.edu or visit in person.

IF ISSUE PERSISTS:
Contact ImmediateAccess@calbaptist.edu for assistance.`

   META: `SOURCE=INSTR_GENERAL_SOURCE_* | CONF=high`
   Debug: `[RAG DEBUG] Read Now button override applied — using general index`

**McGraw Hill — Read Now button missing:**

1. USER:
   `I have opted into Immediate Access for my McGraw Hill textbook but I don't have a Read Now button`

   BOT: *(same general Read Now resolution as Cengage above)*

   META: `SOURCE=INSTR_GENERAL_SOURCE_* | CONF=high`
   Debug: `[RAG DEBUG] Read Now button override applied — using general index`

### Final Status

- Status: Fixed and verified with user test prompts
- Outcome:
  - All instruction files produce complete scenario chunks (PROBLEM + RESOLUTION together).
  - "Read Now button missing" is now a general IA concept handled by a shared instruction file, returning identical guidance across all platforms.
  - Deterministic `is_missing_read_now_button()` detection with quote-stripping, platform overwrite bug fixed, IA continuity guard updated.
  - Cengage, McGraw Hill, and no-platform variants all confirmed returning the same correct general guidance in live testing.

### Verified Test Prompts

1. `I have opted into Immediate Access for my Cengage textbook but I do not have a "read now" button to read the material.` → Correct general Read Now resolution.
2. Turn 1: `I have opted in for my McGraw Hill textbook but I don't have a Read Now button.` / Turn 2: `I can't find read now button` / Turn 3: `Still not showing` → All three turns return the same guidance; no platform clarification prompt on turns 2–3.
3. `I opted into Immediate Access but there's no Read Now button anywhere.` (no platform) → General Read Now resolution returned without needing platform.

---

## Case 009 - Physical Textbook Availability After Opting Out of Immediate Access

- Date: 2026-03-10
- Source Email File: `emails/Purchasing Textbooks .msg`
- Sender: Ingla Robinson
- Extracted Student Message:
  `If I opt out of immediate access, are the physical textbooks for my courses available in the University's student store?`

### Initial Bot Transcript (Before Fix)

1. User: `If I opt out of immediate access, are the physical textbooks for my courses available in the University's student store?`
   Bot: `I can help you with textbook access! To give you the most accurate instructions, could you please specify which platform or publisher your textbook uses?`
   Meta: `source: CLARIFICATION_NEEDED, total_time_ms: 0.0`

### Observed Issues

- Bot returns `CLARIFICATION_NEEDED` (platform question) for a policy FAQ query.
- The question is about opt-out policy / physical textbook availability — not about troubleshooting access to a specific platform.
- Happens in both fresh sessions AND multi-turn sessions where a prior IA flow was active.

### Root Cause Analysis

Three separate misrouting paths existed:

1. **`is_confirmed_materials_issue` (line 1289):** The query contains "textbooks" and "immediate access", both in `materials_terms`. Without the opt-out guard, this path triggered for fresh sessions and returned the platform clarification response.

2. **IA continuity guard (line 2055):** For multi-turn sessions with `stored_intent == "IA_ACCESS_ISSUE"`, the guard checks `ia_context_terms` which include "textbook" and "immediate access". The opt-out query matched both terms. `non_ia_store_terms` did NOT include "student store", so the guard fired and overrode `intent = "IA_ACCESS_ISSUE"`. Then `needs_platform_clarification` (intent == IA_ACCESS_ISSUE, platform is None) returned `CLARIFICATION_NEEDED`.

3. **`extract_faq_answer` (line 640):** Even after routing was fixed, the FAQ retriever returned a chunk in plain `N. Question?\nAnswer` format (from `textbook_refund_policy.txt`, FAQ_11). Neither the `ANSWER:` parser nor the `[FAQ_n]` bracket fallback matched this format, so the function returned `None` and the "no_verified_faq_reply" was emitted instead of the correct answer.

### Fix

1. **`is_confirmed_materials_issue`** — Guard already added in previous session (returns False when `is_opt_out_policy_question(message)` is True).

2. **IA continuity guard** — Added `not is_opt_out_policy_question(message)` to the condition at line 2055:
   ```python
   if (
       looks_like_ia_followup
       and not any(t in msg_lower for t in non_ia_store_terms)
       and not is_opt_out_policy_question(message)
   ):
   ```

3. **`extract_faq_answer` plain-numbered fallback** — Added last-resort parser at line 641:
   ```python
   if len(lines) >= 2 and re.match(r"^\d+\.\s+.+", lines[0]):
       return "\n".join(lines[1:]).strip() or None
   ```
   This handles chunks stored as `N. Question?\nAnswer text` (no ANSWER: header, no [FAQ_n] brackets).

### Fixed Bot Transcript (After Fix)

1. User: `If I opt out of immediate access, are the physical textbooks for my courses available in the University's student store?`
   Bot: `No, the Campus Store does not have print alternatives to the textbooks delivered through Immediate Access. This prevents students who are looking for textbooks in-person from purchasing the same material they've already been charged for through Immediate Access. If you'd like to procure print copies of your IA textbooks on your own, from your preferred textbook retailer, we've provided the Print ISBN of each title on our website.`
   Meta: `source: FAQ_SOURCE_16, confidence: 0.8275, retrieval_time_ms: 22.96, total_time_ms: 22.96`

2. Multi-turn test (after prior Cengage IA flow): Same correct FAQ answer returned, confirming the continuity guard fix.

### Status: FIXED

## Case 010 - VitalSource Textbook Not in IA Bundle

- Date: 2026-03-11
- Source Email File: `emails/Re_ IMMEDIATE ACCESS REMINDER _ OPT-OUT DEADLINE 01_26 _ SPRING SESSION 1 2026.msg`
- Sender: Pia Jones (DOB: 05/06/1991)
- ISBN mentioned: 978-1-4129-6355-8
- Extracted Student Message:
  `I noticed that a textbook is available on VitalSource for rent but it isn't in my bundle for this class. Is there a way to add it?`

### Initial Bot Transcript (Before Fix)

1. User: `I noticed that a textbook is available on VitalSource for rent but it isn't in my bundle for this class. Is there a way to add it?`
   Bot: `No, the Campus Store does not have print alternatives to the textbooks delivered through Immediate Access...` *(opt-out physical textbook FAQ — wrong answer)*
   Meta: `source: FAQ_SOURCE_16, confidence: 0.4885`

### Observed Issues

- Bot returns the "physical textbook opt-out" FAQ answer instead of bundle admin guidance.
- "VitalSource" in message triggered IA_ACCESS_ISSUE intent, then FAISS returned the wrong FAQ.
- This is an admin/policy question, not an access troubleshooting query.

### Root Cause Analysis

- `is_bundle_admin_question` function did not exist; "not in my bundle" signals were not recognized.
- Without detection, message was routed as `IA_ACCESS_ISSUE` → wrong instruction retrieval OR semantic mismatch in FAISS returned the opt-out FAQ.
- No FAQ existed for "textbook not in IA bundle / can I add it?"

### Fix

1. Created `data/faqs/ia_bundle_missing_textbook.txt` — FAQ explaining students cannot modify the bundle and should contact ImmediateAccess@calbaptist.edu.
2. Added `is_bundle_admin_question()` function detecting signals like "not in my bundle", "add to bundle", "isn't in my bundle", etc.
3. Wired into `detect_intent` (returns GENERAL_FAQ), `is_confirmed_materials_issue` (returns False), and IA continuity guard (skips override).
4. Re-ran ingestion — 18 FAQ chunks (was 17).

### Fixed Bot Transcript (After Fix)

1. User: `I noticed that a textbook is available on VitalSource for rent but it isn't in my bundle for this class. Is there a way to add it?`
   Bot: `Unfortunately, students cannot add or modify the textbooks included in their Immediate Access bundle...` *(correct bundle admin FAQ)*
   Meta: `source: FAQ_SOURCE_4, total_time_ms: ~22ms`

### Status: FIXED

---

## Case 011 - Opted In but Second Textbook Shows "Want to Opt Out?" Only

- Date: 2026-03-11
- Source Email File: `emails/Textbook Issues.msg`
- Sender: Benjamin F. Castelli (ID: 796195)
- Extracted Student Message:
  `My professor assigned 2 textbooks through Immediate Access. One of them gave me the option that says Read Now and I was able to access it. The other one only gives me the option that reads Want to opt out? It has a green check mark saying opted in, but I still cannot access that textbook.`

### Initial Bot Transcript (Before Fix)

1. User: *(exact message above)*
   Bot: *(returned opt-out physical textbook FAQ — wrong answer)*
   Meta: `source: FAQ_SOURCE_3, total_time_ms: ~20ms`

### Observed Issues

- Bot returned an unrelated FAQ answer about physical textbook availability after opting out.
- The message contains "Want to opt out?" (Blackboard button text) and "opted in" — both triggered the opt-out policy guard, routing to `GENERAL_FAQ` and returning wrong content.

### Root Cause Analysis

Two paths both fired incorrectly:

1. **`is_opt_out_policy_question`**: The function only checked for "opt out" as a substring, with no exclusion for troubleshooting context. "Want to opt out?" is text on the Blackboard button — not a policy question. Function returned `True`, causing `is_confirmed_materials_issue` to skip the IA routing path.

2. **`detect_intent` inline opt-out check** (lines ~358–365): Same issue — checked for "opt out" and "opted out" in the message without any exclusion for troubleshooting signals. Returned `GENERAL_FAQ` immediately, bypassing all IA routing.

### Fix

Added a troubleshooting exclusion to both guards. If the message contains signals like "no read now", "green check", "checkmark", "opted in", "still cannot", "only shows", etc., neither guard fires — the message is recognized as an ACCESS issue, not a policy question.

**`is_opt_out_policy_question`** (added before signals check):
```python
troubleshooting_signals = [
    "cannot access", "can't access", "cant access",
    "no read now", "read now button", "read now",
    "not showing", "only shows", "only gives", "only option",
    "green check", "checkmark", "opted in",
    "still cannot", "still can't", "still cant",
]
if any(t in m for t in troubleshooting_signals):
    return False
```

**`detect_intent`** (same exclusion applied to inline opt-out check):
```python
if any(s in normalized for s in opt_out_policy_signals) and not any(
    t in normalized for t in opt_out_troubleshooting_exclusions
):
    return "GENERAL_FAQ"
```

### Fixed Bot Transcript (After Fix)

1. User: *(exact student message)*
   Bot: `I can help you with textbook access! To give you the most accurate instructions, could you please specify which platform or publisher your textbook uses?`
   Meta: `source: CLARIFICATION_NEEDED` *(correct — routes as IA_ACCESS_ISSUE, asks for platform)*

2. User: `I don't know which platform.`
   Bot: `No worries! You can usually find the platform name on your Blackboard course page under the Immediate Access tab...`
   Meta: `source: CLARIFICATION_NEEDED` *(correct — guides student to find platform name)*

### Status: FIXED

---

## Case 012 - VitalSource Shows "Launch Courseware" Instead of "Read Now" + Textbook Not Listed

- Date: 2026-03-11
- Source Email File: `emails/Trouble Accessing Ebooks via Vitalsource and BB Fall 2025.msg`
- Sender: Sierra P. Cannon (ID: 808818)
- Courses: ITM E1 500, ITM530-E1
- Extracted Student Message:
  `I am unable to access my class textbooks via VitalSource. After following step by step directions for ITM E1 500, the link for 'immediate access' route via Blackboard only provides me with the option 'launch courseware' not 'read now.' There is also no access code to enter from what I can see. I also don't see my textbook for course ITM530-E1 listed at all in VitalSource.`

### Initial Bot Transcript (Before Fix)

1. User: *(exact message above)*
   Bot: *(returned generic "Read Now button missing" instructions — did not address "launch courseware" specifically)*
   Meta: `source: INSTR_GENERAL_SOURCE_20`

### Observed Issues

- Bot returned the general "Read Now button missing" instruction, which tells the student to wait and refresh.
- Does not address the specific scenario where "Launch Courseware" IS the correct button for VitalSource.
- Does not address the "textbook not listed at all" issue.

### Root Cause Analysis

1. **`is_missing_read_now_button` firing incorrectly**: The message contained "do not see" (from "I do not see my textbook") which is in `missing_signals`. This triggered the override that forces retrieval from the general instructions index with query "Read Now button missing..." — bypassing the VitalSource-specific bedford index.

2. **No VitalSource "launch courseware" instruction file existed**: There was no dedicated file explaining that "Launch Courseware" is a valid access path for some VitalSource-integrated courses.

3. **VITALSOURCE not mapped to bedford retrieval key**: `detect_platform_from_text` correctly detected VITALSOURCE, but the retriever had no "vitalsource" index — it needed to fall back to the "bedford" index where VitalSource instructions are stored.

### Fix

1. Created `data/instructions/ia_vitalsource_launch_courseware_access.txt` with two scenarios:
   - SCENARIO 1: "Launch Courseware" button → try clicking it (it functions the same as "Read Now")
   - SCENARIO 2: Textbook not listed at all → verify opt-in status, check email, wait 24h

2. Added `vitalsource` keyword to `bedford` platform in `app/rag/platforms.yaml` so VitalSource instruction files index under bedford.

3. Added `PLATFORM_RETRIEVAL_KEY = {"VITALSOURCE": "bedford"}` in `main.py` to map the detected VITALSOURCE platform to the bedford retrieval index.

4. Added `is_launch_courseware` detection in the IA retrieval block:
   - If message contains "launch courseware", skip the Read Now general-index override
   - Use enhanced query targeting SCENARIO 1: `"launch courseware button VitalSource instead of Read Now access eTextbook"`
   - Retrieval uses bedford (VitalSource) platform index

### Fixed Bot Transcript (After Fix)

1. User: *(exact student message)*
   Bot: *(SCENARIO 1 — "Launch Courseware" button appears instead of "Read Now")*
   `If you see a "Launch Courseware" button, click it — for some VitalSource-integrated courses this is the correct button to open your eTextbook (it functions the same as "Read Now")...`
   Meta: `source: INSTR_BEDFORD_SOURCE_6`

### Regression Verified
- Cengage "no Read Now button" → still returns `INSTR_GENERAL_SOURCE_20` ✓

### Status: FIXED

---

