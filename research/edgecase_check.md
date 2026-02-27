# Edge Case Check

Latest full retest result: **30 PASS / 0 CHECK**

This file tracks previously failing edge cases and their fixes.
Latest full re-run of `research/lance_edge_case_test_suite.csv` confirms all cases are now passing.

## TC002
- Precondition: (none)
- Student Message: `Hello there can you help?`
- Test Type: `greeting_with_extra`
- Expected Intent: `GENERAL_FAQ`
- Expected Platform: ``
- Expected Source Prefix: `LLM_ONLY`
- Expects Clarification: `No`
- Expects No Retrieval: `No`
- Notes: Not pure greeting so model may answer generally

**Actual Response**
Since the user only said "Hi" with nothing else, I'll provide a greeting response:  Hi! I'm Lance, your Campus Store AI Assistant. I can help with Immediate Access, textbook policies, and troubleshooting. What can I help you with today?

**Evaluation Details**
CHECK | source=FAQ_SOURCE_0 expected_prefix=LLM_ONLY MISMATCH; confidence=0.068

**Proposed Solution**
- Root cause: After adding deterministic FAQ handling, this greeting-like query had a very low FAQ similarity and should not force a direct FAQ answer.
- Code changes:
  - Added FAQ direct-answer confidence gate in `app/main.py` (`FAQ_DIRECT_MIN_CONFIDENCE`).
  - When confidence is below threshold, route to clarification-style `LLM_ONLY` instead of direct FAQ.
  - Updated `research/lance_edge_case_test_suite.csv` expectation for `TC002` to `LLM_ONLY` to match intended behavior.
- Retest result: PASS (`source=LLM_ONLY`, confidence low as expected).

## TC004
- Precondition: (none)
- Student Message: `How do I opt out of Immediate Access?`
- Test Type: `faq_policy`
- Expected Intent: `GENERAL_FAQ`
- Expected Platform: ``
- Expected Source Prefix: `FAQ_SOURCE_`
- Expects Clarification: `No`
- Expects No Retrieval: `No`
- Notes: Policy/FAQ retrieval path

**Actual Response**
Unfortunately, you cannot opt out of using the Immediate Access platform. It is a required service provided by the Campus Store to support students in accessing their textbooks and course materials.  However, if you are experiencing issues with the platform or have concerns about your data privacy, you can contact our IT department for assistance. They can help you troubleshoot any technical issues and provide guidance on how to manage your cookie settings in Chrome.  Alternatively, you can reach out to us directly at ImmediateAccess@calbaptist.edu for further assistance. Please note that you will need to include your name, ID#, and course information in your email so we can better assist you.

**Evaluation Details**
CHECK | source=INSTR_GENERAL_SOURCE_3 expected_prefix=FAQ_SOURCE_ MISMATCH; confidence=0.410

**Proposed Solution**
- Root cause: Query "How do I opt out of Immediate Access?" is routed to **instructions** instead of FAQ because `app/rag/retriever.py` includes `"how do i"` in `INSTRUCTIONS_KEYWORDS`. In `app/main.py`, this query gets `intent=GENERAL_FAQ` and calls `retriever.retrieve(message)` with `collection="auto"`; auto-selection then picks instructions and retrieves `INSTR_GENERAL_SOURCE_3` (cookie troubleshooting), producing an incorrect opt-out answer.
- Code changes: In `app/main.py`, forced FAQ retrieval when `intent == "GENERAL_FAQ"` (`collection="faqs"`) to prevent auto-route to instructions for "how do I" policy questions.
- Retest result: PASS (`source=FAQ_SOURCE_0`).

## TC020
- Precondition: After previous turn about another platform
- Student Message: `Actually it's Cengage not McGraw`
- Test Type: `topic_switch`
- Expected Intent: `IA_ACCESS_ISSUE`
- Expected Platform: `CENGAGE`
- Expected Source Prefix: `INSTR_CENGAGE_SOURCE_`
- Expects Clarification: `No`
- Expects No Retrieval: `No`
- Notes: Should switch platform and not stay on stale previous platform

**Actual Response**
I notice you mentioned multiple platforms. To give you the most accurate troubleshooting steps, could you please clarify which platform you're having trouble with? (e.g., McGraw Hill Connect, Cengage MindTap, etc.)

**Evaluation Details**
CHECK | source=CLARIFICATION expected_prefix=INSTR_CENGAGE_SOURCE_ MISMATCH; confidence=0.000

**Proposed Solution**
- Root cause: `detect_platform_and_check_ambiguity()` in `app/main.py` flags the message as ambiguous whenever it sees multiple platform aliases. For `"Actually it's Cengage not McGraw"`, both `cengage` and `mcgraw` are present, so early ambiguity logic returns `CLARIFICATION` before topic-switch handling can resolve the intended target platform. The detector does not handle negation patterns like `not McGraw` / `instead of McGraw`.
- Code changes: Added negation-aware platform correction handling in `detect_platform_and_check_ambiguity()` and `is_ambiguous_platform_query()` using `resolve_platform_correction()`. Added session-aware correction tie-break in `detect_topic_switch(...)`. Added correction-intent heuristic in `detect_intent(...)` so correction phrases with platform mentions stay in IA troubleshooting flow.
- Retest result: PASS for routing. Repro (`InQuizitive` -> `Actually it's Cengage not McGraw`) now returns `source=INSTR_CENGAGE_SOURCE_0` instead of clarification.

## TC023
- Precondition: After bot asks textbook vs platform
- Student Message: `Textbook not platform`
- Test Type: `clarification_branch`
- Expected Intent: `IA_ACCESS_ISSUE`
- Expected Platform: ``
- Expected Source Prefix: `INSTR_GENERAL_SOURCE_`
- Expects Clarification: `No`
- Expects No Retrieval: `No`
- Notes: Should route to ebook/general textbook instructions

**Actual Response**
Here's how to access your Cengage textbook:  1. Log in to Blackboard. 2. Open the correct course. 3. Click on the “Course Materials” tab in the left menu. 4. Click the Cengage MindTap registration or access link. 5. Open the appropriate week folder. 6. Select the Cengage chapter or assignment link. 7. Log in using your full CBU email address (firstname.lastname@calbaptist.edu).   LOGIN REQUIREMENTS: - Use your full CBU email address (firstname.lastname@calbaptist.edu). - Do NOT use your ID#@calbaptist.edu email.  EXPECTED RESULT: After logging in, the Cengage eText should be accessible.

**Evaluation Details**
CHECK | source=INSTR_CENGAGE_SOURCE_0 expected_prefix=INSTR_GENERAL_SOURCE_ MISMATCH; confidence=0.276

**Proposed Solution**
- Root cause: In the `awaiting_platform_type` handler (`app/main.py`), the branch that assigns `platform = publisher` is triggered when message contains keywords including `"platform"`. For input `"Textbook not platform"`, the word `platform` matches, so it is misclassified as courseware and forces Cengage retrieval (`INSTR_CENGAGE_SOURCE_0`) instead of ebook/general textbook instructions. The logic does not handle negation (`not platform`) for this clarification reply.
- Code changes:
  - Added negation-first clarification classifier logic to resolve replies like `textbook not platform` correctly.
  - Updated awaiting-platform-type branch to use classifier result instead of naive substring matching.
  - Added `explicit_textbook_selection` handling to prevent re-clarification loops.
- Retest result: PASS (`source=INSTR_GENERAL_SOURCE_10`).

## TC024
- Precondition: After bot asks textbook vs platform
- Student Message: `Courseware not ebook`
- Test Type: `clarification_branch`
- Expected Intent: `IA_ACCESS_ISSUE`
- Expected Platform: ``
- Expected Source Prefix: `INSTR_`
- Expects Clarification: `No`
- Expects No Retrieval: `No`
- Notes: Should route to platform courseware instructions if prior platform known

**Actual Response**
I still need the platform name to give the correct steps. Please share which one you see in Blackboard Immediate Access (for example: Cengage MindTap, McGraw Hill Connect, or Pearson MyLab).

**Evaluation Details**
CHECK | source=CLARIFICATION_NEEDED expected_prefix=INSTR_ MISMATCH; confidence=0.000

**Proposed Solution**
- Root cause: Clarification branch previously required explicit platform name even when user confirmed courseware intent tied to prior publisher context.
- Code changes:
  - Reused the same clarification classifier and prior-context routing path so `courseware not ebook` uses known publisher context.
  - Kept unknown fallback prompt only for truly ambiguous replies.
- Retest result: PASS (`source=INSTR_CENGAGE_SOURCE_0`, matches expected `INSTR_`).

## TC030
- Precondition: (none)
- Student Message: `Can you help me with parking permits?`
- Test Type: `out_of_scope`
- Expected Intent: `GENERAL_FAQ`
- Expected Platform: ``
- Expected Source Prefix: `LLM_ONLY`
- Expects Clarification: `No`
- Expects No Retrieval: `No`
- Notes: Should politely decline or redirect to campus resources

**Actual Response**
**Parking Permits**  * To purchase a parking permit, visit the Campus Store website and click on "Parking Permits" under the "Campus Services" tab. * Permits are available for purchase online or in-store during business hours. * A valid permit is required to park on campus.

**Evaluation Details**
CHECK | source=FAQ_SOURCE_1 expected_prefix=LLM_ONLY MISMATCH; confidence=0.104

**Proposed Solution**
- Root cause: Out-of-scope questions still enter `GENERAL_FAQ` retrieval. After the deterministic FAQ response change, any `FAQ_SOURCE_*` hit is returned directly regardless of low confidence. For `"parking permits"`, nearest FAQ match is low-confidence (`~0.10`) but still accepted, causing unrelated answers instead of a polite redirect. No out-of-domain guard or confidence threshold is applied to FAQ direct responses.
- Code changes:
  - Added `FAQ_DIRECT_MIN_CONFIDENCE` threshold in `app/main.py` for deterministic FAQ direct responses.
  - Added `is_out_of_scope_query(...)` with a small keyword list for obvious non-store topics.
  - Added early out-of-scope guard in `process_chat_request(...)` so out-of-scope `GENERAL_FAQ` messages return `LLM_ONLY` redirect without retrieval.
  - Added low-confidence FAQ fallback path: if FAQ hit is below threshold, return clarification-style `LLM_ONLY` response instead of forcing direct FAQ content.
- Retest result: PASS. Live `/chat` check for `Can you help me with parking permits?` now returns `source=LLM_ONLY`, `confidence=0.0`, `retrieval_time_ms=0.0`, `llm_time_ms=0.0` with a campus-resource redirect response.
