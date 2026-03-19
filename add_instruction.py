#!/usr/bin/env python3
"""
Lance — Add New Platform Instruction
Usage: python add_instruction.py <pdf_path> <platform> <issue_type>

Example:
    python add_instruction.py pdfs/cengage/cengage_access.pdf cengage access

Supported platforms:
    cengage, mcgrawhill, pearson, wileyplus, macmillan, sage,
    bedford, cliftonstrengths, simucace, zybooks, stukent

# Basic usage
python add_instruction.py pdfs/cengage/cengage_access.pdf cengage access

# Other examples
python add_instruction.py pdfs/pearson/pearson_mylab_access.pdf pearson access
python add_instruction.py pdfs/wiley/wiley_access.pdf wileyplus access

"""

import sys
import os
import re
import argparse
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from app.platform_registry import load_registry, save_registry, canonical_platform_key

load_dotenv()

# ── Path setup ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
DATA_INSTRUCTIONS = PROJECT_ROOT / "data" / "instructions"
_service_account_value = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "app/firebase-service-account.json")
SERVICE_ACCOUNT   = Path(_service_account_value)
if not SERVICE_ACCOUNT.is_absolute():
    SERVICE_ACCOUNT = PROJECT_ROOT / SERVICE_ACCOUNT
INGEST_SCRIPT     = PROJECT_ROOT / "app" / "rag" / "ingest.py"

PLATFORM_DISPLAY = {
    "cengage":          "Cengage",
    "mcgrawhill":       "McGraw Hill",
    "pearson":          "Pearson",
    "wileyplus":        "WileyPlus",
    "macmillan":        "Macmillan",
    "sage":             "Sage",
    "bedford":          "Bedford",
    "cliftonstrengths": "CliftonStrengths",
    "simucace":         "SimuCase",
    "zybooks":          "ZyBooks",
    "stukent":          "Stukent",
}

ISSUE_DISPLAY = {
    "access":    "Access",
    "login":     "Login",
    "payment":   "Payment",
    "opt_out":   "Opt Out",
    "refund":    "Refund",
    "technical": "Technical",
}


# ── Step 1: Parse arguments ───────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Add a new Lance instruction PDF.")
    parser.add_argument("pdf_path",   help="Path to the PDF file")
    parser.add_argument("platform",   help="Platform key (e.g. cengage, pearson)")
    parser.add_argument("issue_type", help="Issue type key (e.g. access, login)")
    parser.add_argument(
        "--aliases",
        default="",
        help="Comma-separated aliases for platform detection (e.g. \"inquizitive,inquisitive,norton\")",
    )
    return parser.parse_args()


# ── Step 2: Extract text from PDF ────────────────────────────────────────────
def extract_pdf_text(pdf_path: Path) -> str:
    try:
        import pdfplumber
        print(f"  Using pdfplumber...")
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = [page.extract_text() for page in pdf.pages]
            text = "\n".join(p for p in pages if p)
    except ImportError:
        try:
            import fitz  # pymupdf
            print(f"  pdfplumber not found, using pymupdf...")
            doc = fitz.open(str(pdf_path))
            text = "\n".join(page.get_text() for page in doc)
        except ImportError:
            print("ERROR: Neither pdfplumber nor pymupdf is installed.")
            print("  Run: pip install pdfplumber")
            sys.exit(1)

    if not text or len(text.strip()) < 100:
        print("WARNING: Extracted text is very short or empty.")
        print("  The PDF may be image-based and require OCR (pytesseract).")
        print(f"  Extracted {len(text.strip())} characters.")
        confirm = input("  Continue anyway? (y/n): ").strip().lower()
        if confirm != "y":
            sys.exit(0)

    return text


# ── Step 3: Clean extracted text ─────────────────────────────────────────────
def clean_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(line.strip())

    # Collapse more than 2 consecutive blank lines into 2
    cleaned = []
    blank_count = 0
    for line in lines:
        if line == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


# ── Step 4: Write .txt instruction file ──────────────────────────────────────
def write_txt_file(text: str, platform: str, issue_type: str,
                   platform_display: str, issue_display: str) -> Path:
    filename = f"ia_{platform}_{issue_type}.txt"
    out_path = DATA_INSTRUCTIONS / filename

    # Warn if overwriting
    if out_path.exists():
        confirm = input(f"\nWARNING: {filename} already exists. Overwrite? (y/n): ").strip().lower()
        if confirm != "y":
            print("  Skipping file write.")
            return out_path

    header = (
        f"Platform: {platform_display}\n"
        f"Issue Type: {issue_display}\n"
        f"Program: Immediate Access\n"
        f"Last Updated: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"---\n\n"
    )

    # Only add header if not already present
    if not text.startswith("Platform:"):
        full_content = header + text
    else:
        full_content = text

    out_path.write_text(full_content, encoding="utf-8")
    print(f"\n✅ Written: {out_path}")

    # Preview first 20 lines
    print("\n── First 20 lines preview ──────────────────────────────────")
    for i, line in enumerate(full_content.splitlines()[:20], 1):
        print(f"  {i:02d}  {line}")
    print("────────────────────────────────────────────────────────────")

    return out_path


# ── Step 5: Upload to Firebase ───────────────────────────────────────────────
def upload_to_firebase(pdf_path: Path, platform: str, issue_type: str,
                       platform_display: str, issue_display: str) -> str:
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, storage
    except ImportError:
        print("\nWARNING: firebase-admin not installed. Skipping Firebase upload.")
        print("  Run: pip install firebase-admin")
        return ""

    if not SERVICE_ACCOUNT.exists():
        print(f"\nWARNING: Service account key not found at {SERVICE_ACCOUNT}")
        print("  Skipping Firebase upload.")
        return ""

    # Read storage bucket — try firebase_config.py first, then prompt user
    import json
    sa_data = json.loads(SERVICE_ACCOUNT.read_text())
    project_id = sa_data.get("project_id", "")

    # Match app/firebase_config.py defaults unless env overrides them.
    storage_bucket = os.environ.get("FIREBASE_STORAGE_BUCKET", "lance-cbu.firebasestorage.app")
    print(f"  Using storage bucket: {storage_bucket}")

    # Initialize Firebase (only once)
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT))
        firebase_admin.initialize_app(cred, {"storageBucket": storage_bucket})

    db     = firestore.client()
    bucket = storage.bucket()

    doc_id       = f"ia_{platform}_{issue_type}"
    storage_path = f"instructions/{doc_id}.pdf"
    pdf_filename = pdf_path.name

    # Check for existing Firestore doc
    existing = db.collection("instructions").document(doc_id).get()
    if existing.exists:
        confirm = input(f"\nWARNING: Firestore doc 'instructions/{doc_id}' already exists. Overwrite? (y/n): ").strip().lower()
        if confirm != "y":
            print("  Skipping Firestore upload.")
            return ""

    # Upload PDF to Firebase Storage
    print(f"\n  Uploading PDF to Firebase Storage: {storage_path} ...")
    blob = bucket.blob(storage_path)
    blob.upload_from_filename(str(pdf_path), content_type="application/pdf")
    blob.make_public()
    pdf_url = blob.public_url
    print(f"  ✅ PDF uploaded: {pdf_url}")

    # Write Firestore document
    doc_data = {
        "platform":     platform,
        "issue_type":   issue_type,
        "display_name": f"{platform_display} — {issue_display}",
        "program":      "Immediate Access",
        "filename":     f"{doc_id}.txt",
        "pdf_filename": pdf_filename,
        "pdf_url":      pdf_url,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "active":       True,
    }
    db.collection("instructions").document(doc_id).set(doc_data)
    print(f"  ✅ Firestore document written: instructions/{doc_id}")

    return pdf_url


# ── Step 6: Rebuild FAISS index ───────────────────────────────────────────────
def rebuild_index():
    if not INGEST_SCRIPT.exists():
        print(f"\nWARNING: Ingest script not found at {INGEST_SCRIPT}")
        print("  Skipping index rebuild.")
        return

    print(f"\n  Rebuilding FAISS index via {INGEST_SCRIPT} ...")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(INGEST_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        capture_output=False
    )
    if result.returncode == 0:
        print("  ✅ FAISS index rebuilt successfully.")
    else:
        print(f"  ⚠️  Ingest script exited with code {result.returncode}.")


# ── Step 7: Verification checklist ───────────────────────────────────────────
def print_checklist(txt_path: Path, pdf_url: str, platform: str, issue_type: str):
    doc_id = f"ia_{platform}_{issue_type}"
    print("\n── Verification Checklist ───────────────────────────────────")
    print(f"  [{'✅' if txt_path.exists() else '❌'}] {txt_path} exists")
    print(f"  [{'✅' if txt_path.exists() and txt_path.stat().st_size > 100 else '❌'}] .txt file has readable content")
    print(f"  [{'✅' if pdf_url else '⚠️ '}] Firestore doc '{doc_id}' written {'(skipped)' if not pdf_url else ''}")
    print(f"  [{'✅' if pdf_url else '⚠️ '}] PDF publicly accessible {'(skipped)' if not pdf_url else ''}")
    print("────────────────────────────────────────────────────────────\n")


def update_dynamic_registry(platform: str, issue_type: str, platform_display: str, aliases: list[str]):
    """
    Persist platform detection + PDF recommendation mappings used at runtime.
    """
    registry = load_registry()

    platform_key = canonical_platform_key(platform)
    issue_key = canonical_platform_key(issue_type)
    txt_filename = f"ia_{platform_key}_{issue_key}.txt"
    doc_id = f"ia_{platform_key}_{issue_key}"

    existing_aliases = registry.get("platform_aliases", {}).get(platform_key, [])
    normalized_aliases = set()
    for alias in existing_aliases:
        if isinstance(alias, str) and alias.strip():
            normalized_aliases.add(alias.strip().lower())

    # Always include canonical platform aliases
    normalized_aliases.add(platform_key)
    normalized_aliases.add(platform_key.replace("_", " "))
    for alias in aliases:
        if alias.strip():
            normalized_aliases.add(alias.strip().lower())
            normalized_aliases.add(canonical_platform_key(alias).replace("_", " "))

    registry.setdefault("platform_aliases", {})[platform_key] = sorted(normalized_aliases)
    registry.setdefault("platform_display_names", {})[platform_key] = platform_display
    registry.setdefault("platform_normalization", {})[platform_key] = platform_key
    registry.setdefault("platform_priority", {}).setdefault(platform_key, 2)
    registry.setdefault("txt_to_pdf_map", {})[txt_filename] = doc_id

    save_registry(registry)
    print(f"  ✅ Dynamic registry updated for platform '{platform_key}'")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    pdf_path   = Path(args.pdf_path).resolve()
    platform   = canonical_platform_key(args.platform)
    issue_type = canonical_platform_key(args.issue_type)
    aliases    = [a.strip().lower() for a in args.aliases.split(",") if a.strip()]

    # Validate
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)

    platform_display = PLATFORM_DISPLAY.get(platform, platform.title())
    issue_display    = ISSUE_DISPLAY.get(issue_type, issue_type.replace("_", " ").title())

    print(f"\n{'='*60}")
    print(f"  Lance — Add Instruction")
    print(f"  Platform:   {platform_display}")
    print(f"  Issue Type: {issue_display}")
    print(f"  PDF:        {pdf_path.name}")
    print(f"  Output:     ia_{platform}_{issue_type}.txt")
    print(f"{'='*60}\n")

    # Step 2: Extract
    print("[1/5] Extracting text from PDF...")
    raw_text = extract_pdf_text(pdf_path)
    print(f"  Extracted {len(raw_text)} characters across the document.")

    # Step 3: Clean
    print("\n[2/5] Cleaning text...")
    clean = clean_text(raw_text)

    # Step 4: Write txt
    print("\n[3/5] Writing instruction file...")
    txt_path = write_txt_file(clean, platform, issue_type, platform_display, issue_display)

    # Step 5: Firebase upload
    print("\n[4/5] Uploading to Firebase...")
    pdf_url = upload_to_firebase(pdf_path, platform, issue_type, platform_display, issue_display)

    # Step 6: Rebuild index
    rebuild = input("\nRebuild FAISS index now? (y/n): ").strip().lower()
    if rebuild == "y":
        rebuild_index()

    # Step 7: update runtime registry (platform detection + pdf mapping)
    print("\n[5/5] Updating runtime platform/pdf registry...")
    update_dynamic_registry(platform, issue_type, platform_display, aliases)

    # Final checklist
    print_checklist(txt_path, pdf_url, platform, issue_type)


if __name__ == "__main__":
    main()
