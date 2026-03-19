# Lance Instruction Content Guide

## 1. Overview

This guide explains how to add or update platform-specific instruction content for Lance. Use it when CBU adopts a new publisher platform, when an existing instruction file is outdated, or when a new issue type needs step-by-step resolution content.

## 2. When to Use This Guide

Use this guide when:
- A new publisher platform is being added to Immediate Access
- Existing instructions for a platform are outdated or incorrect
- A new issue type needs instructions, such as "no Read Now button" or "launch courseware button missing"

## 3. Step 1: Write the `.txt` Instruction File

Create a plain-text file using this required structure:

```text
PROBLEM:
<one sentence describing the student's issue>

APPLIES TO:
<platform name>

STEP-BY-STEP RESOLUTION:
1. Step one
2. Step two
3. Step three

EXPECTED RESULT:
<what the student should see when the issue is resolved>
```

File naming convention:

```text
ia_{platform}_{issue_type}.txt
```

Examples:
- `ia_mcgraw_no_read_now.txt`
- `ia_bedford_account_merge.txt`

Keep the filename aligned with the real platform name. This helps Lance place the content into the correct platform index.

## 4. Step 2: Submit Through the Admin UI

1. Go to `http://localhost:8000/admin`
2. Log in with your admin credentials
3. Select `Platform Instruction` as the content type
4. Upload your `.txt` file
5. Optionally attach PDF guides with labels
6. Click `Add Content to Lance`
7. Wait for all steps to show green checkmarks
8. Click `Apply Changes` to reload the index

The Admin UI saves the `.txt` file, rebuilds the FAISS index, uploads attached PDFs to Firebase Storage, and creates the `txt_to_pdf_map` entry in Firestore automatically.

## 5. Step 3: Test in the Chat

1. Open the Lance chat interface
2. Ask a question that matches the new instruction
3. Verify the correct steps are returned
4. If PDF guides were attached, verify they appear in the right-side recommendations panel

If the answer does not appear, first confirm the file format and filename are correct, then try the question again with clearer platform wording.

## 6. Adding a New Platform Entirely

Adding content for an existing platform does not require code changes. Adding a brand-new platform requires one extra technical step:

1. Edit `app/rag/platforms.yaml`
2. Add a new entry with:
   - `key`
   - `display_name`
   - `keywords`
3. Save the file
4. Then follow the normal content addition steps through the Admin UI

Example:

```yaml
- key: stukent
  display_name: Stukent
  keywords:
    - stukent
    - simternship
```

This step requires technical access to the server or repository.

## 7. CLI Alternative

Technical users can also use the CLI scripts instead of the Admin UI.

Examples:

```bash
python lance_add_content.py --type instruction --txt data/instructions/ia_platform_issue.txt
```

```bash
python lance_add_content.py --type instruction \
    --txt data/instructions/ia_platform_issue.txt \
    --pdf docs/guide1.pdf --pdf-label "Guide 1"
```

There is also a platform-focused helper script:

```bash
python add_instruction.py
```

The Admin UI is the preferred workflow for non-technical staff.

## 8. Troubleshooting

`Apply Changes failed`
- Restart the server and try again.
- If the page shows restart instructions, press `Enter` first, then `Ctrl + C`, then run `uvicorn app.main:app --reload`.

Instructions not appearing
- Check that the file contains the required headers: `PROBLEM:` and `STEP-BY-STEP RESOLUTION:`
- Confirm the file was uploaded as `Platform Instruction`
- Re-test with a query that clearly mentions the platform and issue

Wrong platform getting matched
- Check that the filename follows the `ia_{platform}_...` naming pattern
- Make sure the `APPLIES TO:` section names the correct platform
- If this is a new platform, confirm it was added to `app/rag/platforms.yaml`
