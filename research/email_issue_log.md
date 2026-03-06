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

## Template For Next Cases

Copy and fill:

```md
## Case XXX - <short title>

- Date:
- Source Email File:
- Student Summary:

### Initial Bot Transcript (Before Fix)
1. User:
   Bot:
   Meta:

### Issues Logged
1.

### Root Cause
1.

### Implemented Solution
- Files updated:
- Summary:

### Retest Transcript (After Fix)
1. User:
   Bot:
   Meta:

### Final Status
- Status: Fixed / Partially Fixed / Open
- Notes:
```
