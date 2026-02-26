# Lance — Add New Platform Instruction Document

## Task Overview
You are helping maintain the **Lance chatbot** at CBU's Campus Store. When a new PDF containing platform-specific troubleshooting instructions arrives, your job is to:

1. **Parse the PDF** and extract its instructional content
2. **Write a clean `.txt` file** into `data/instructions/` following the naming convention
3. **Upload the PDF** to the Firestore database so it can be served as a recommendation

---

## Step 1 — Identify the PDF

The user will provide one or more PDF file paths. For each PDF:

- Read the filename and/or ask the user to confirm:
  - **Platform name** (e.g., `cengage`, `pearson`, `mcgrawhill`, `wileyplus`, `macmillan`, `sage`, `bedford`, `cliftonstrengths`, `simucace`, `zybooks`, `stukent`)
  - **Issue type** (e.g., `access`, `login`, `payment`, `opt_out`, `refund`, `technical`)
- The output `.txt` filename must follow this pattern exactly:
  ```
  ia_{platform}_{issue_type}.txt
  ```
  Example: `ia_cengage_access.txt`, `ia_pearson_login.txt`

---

## Step 2 — Parse the PDF

Use Python with `pdfplumber` or `pymupdf` (whichever is available) to extract all text from the PDF.

```python
import pdfplumber

with pdfplumber.open("path/to/file.pdf") as pdf:
    text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
```

Clean the extracted text:
- Remove excessive blank lines (max 2 consecutive newlines)
- Strip leading/trailing whitespace per line
- Preserve numbered steps and bullet points
- Do **not** remove headers — they provide context for the RAG system

---

## Step 3 — Write the `.txt` Instruction File

Save the cleaned text to:
```
data/instructions/ia_{platform}_{issue_type}.txt
```

Structure the file with this header block at the top (add it if not already present in the PDF):

```
Platform: {Platform Display Name}
Issue Type: {Issue Type Display Name}
Program: Immediate Access
Last Updated: {today's date YYYY-MM-DD}
---

{extracted and cleaned text content}
```

Confirm the file was written and print the first 20 lines for review.

---

## Step 4 — Upload to Firestore

Use the existing Firebase/Firestore setup in the project. Locate the Firebase config in:
- `src/firebase.js` or `backend/firebase_config.py` (use whichever exists)

Upload the **original PDF** to Firebase Storage and store a **metadata document** in Firestore.

### Firestore Document Structure

Collection: `instructions`  
Document ID: `ia_{platform}_{issue_type}` (same as the txt filename without extension)

```json
{
  "platform": "{platform}",
  "issue_type": "{issue_type}",
  "display_name": "{Platform Display Name} — {Issue Type Display Name}",
  "program": "Immediate Access",
  "filename": "ia_{platform}_{issue_type}.txt",
  "pdf_filename": "{original_pdf_filename}",
  "pdf_url": "{firebase_storage_download_url}",
  "last_updated": "{ISO 8601 timestamp}",
  "active": true
}
```

### Python Upload Script

```python
import firebase_admin
from firebase_admin import credentials, firestore, storage
from datetime import datetime, timezone
import os

# Initialize (skip if already initialized in the project)
if not firebase_admin._apps:
    cred = credentials.Certificate("path/to/serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {
        "storageBucket": "{your-project-id}.appspot.com"
    })

db = firestore.client()
bucket = storage.bucket()

def upload_instruction_pdf(pdf_path: str, platform: str, issue_type: str):
    filename = f"ia_{platform}_{issue_type}"
    pdf_filename = os.path.basename(pdf_path)
    storage_path = f"instructions/{filename}.pdf"

    # Upload PDF to Firebase Storage
    blob = bucket.blob(storage_path)
    blob.upload_from_filename(pdf_path, content_type="application/pdf")
    blob.make_public()
    pdf_url = blob.public_url

    # Write Firestore document
    doc_data = {
        "platform": platform,
        "issue_type": issue_type,
        "display_name": f"{platform.title()} — {issue_type.replace('_', ' ').title()}",
        "program": "Immediate Access",
        "filename": f"{filename}.txt",
        "pdf_filename": pdf_filename,
        "pdf_url": pdf_url,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }

    db.collection("instructions").document(filename).set(doc_data)
    print(f"✅ Firestore document written: instructions/{filename}")
    print(f"✅ PDF uploaded to: {pdf_url}")
    return pdf_url
```

---

## Step 5 — Rebuild the FAISS Index

After writing the new `.txt` file, re-run the ingestion script to update the vector index so Lance can retrieve from the new document immediately:

```bash
python backend/ingest.py
# or whatever the project's ingestion entrypoint is
```

Confirm the new file appears in the index output.

---

## Step 6 — Verification Checklist

Before finishing, confirm all of the following:

- [ ] `data/instructions/ia_{platform}_{issue_type}.txt` exists and has readable content
- [ ] First 20 lines of the `.txt` file look correct (header + content)
- [ ] Firestore document `instructions/ia_{platform}_{issue_type}` exists with correct fields
- [ ] PDF is publicly accessible via the `pdf_url`
- [ ] FAISS index was rebuilt successfully
- [ ] No existing document for this platform/issue_type was overwritten unintentionally (warn the user if it was)

---

## Supported Platforms Reference

| Platform Key      | Display Name         |
|-------------------|----------------------|
| `cengage`         | Cengage              |
| `mcgrawhill`      | McGraw Hill          |
| `pearson`         | Pearson              |
| `wileyplus`       | WileyPlus            |
| `macmillan`       | Macmillan            |
| `sage`            | Sage                 |
| `bedford`         | Bedford              |
| `cliftonstrengths`| CliftonStrengths     |
| `simucace`        | SimuCase             |
| `zybooks`         | ZyBooks              |
| `stukent`         | Stukent              |

---

## Notes for the Agent

- **FERPA compliance**: Do not log or print any student-identifiable information from PDFs.
- **Idempotency**: If a document for this platform/issue_type already exists in Firestore, prompt the user before overwriting.
- **Error handling**: If the PDF text extraction returns empty or very short text (< 100 chars), warn the user — the PDF may be image-based and require OCR (`pytesseract`).
- **File encoding**: Always write `.txt` files as UTF-8.
- **Service account key path**: If the path to `serviceAccountKey.json` is unknown, ask the user before proceeding.
