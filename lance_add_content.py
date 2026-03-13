#!/usr/bin/env python3
"""
lance_add_content.py
--------------------
Lance Content Addition Script
CBU Campus Store — Lance Chatbot

Usage:
    python lance_add_content.py --type faq --txt path/to/file.txt
    python lance_add_content.py --type instruction --txt path/to/file.txt
    python lance_add_content.py --type faq --txt path/to/file.txt --pdf path/to/guide.pdf --pdf-label "Safari Clear Cache Guide"

What this script does:
    1. Validates the .txt file format (QUESTION: / ANSWER: headers)
    2. Copies the .txt file to the correct data/ subfolder
    3. Runs FAISS ingestion to rebuild the index
    4. (Optional) Uploads a PDF to Firebase Storage and saves its metadata to Firestore

Requirements:
    - Run from the project root directory (same folder as app/)
    - Conda environment must be active: conda activate campus-store-bot
    - For PDF upload: firebase-admin must be installed and serviceAccountKey.json must exist

"""

import argparse
import shutil
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

# ── Paths (relative to project root) ──────────────────────────────────────────
FAQ_DIR = Path("data/faqs")
INSTRUCTIONS_DIR = Path("data/instructions")
SERVICE_ACCOUNT_PATH = Path("serviceAccountKey.json")

# ── Colors for terminal output ─────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def log_step(msg):    print(f"{CYAN}{BOLD}▶ {msg}{RESET}")
def log_ok(msg):      print(f"{GREEN}  ✓ {msg}{RESET}")
def log_warn(msg):    print(f"{YELLOW}  ⚠ {msg}{RESET}")
def log_error(msg):   print(f"{RED}  ✗ {msg}{RESET}")
def log_info(msg):    print(f"    {msg}")


# ── Step 1: Validate project root ─────────────────────────────────────────────
def check_project_root():
    log_step("Checking project root...")
    if not Path("app/main.py").exists():
        log_error("app/main.py not found.")
        log_info("Please run this script from the project root directory.")
        log_info("Example:  cd /path/to/lance && python lance_add_content.py ...")
        sys.exit(1)
    if not FAQ_DIR.exists() or not INSTRUCTIONS_DIR.exists():
        log_error("data/faqs/ or data/instructions/ directory not found.")
        log_info("Make sure your data/ directory structure is intact.")
        sys.exit(1)
    log_ok("Project root confirmed.")


# ── Step 2: Validate .txt file format ─────────────────────────────────────────
def validate_txt(txt_path: Path):
    log_step(f"Validating {txt_path.name}...")
    if not txt_path.exists():
        log_error(f"File not found: {txt_path}")
        sys.exit(1)
    if txt_path.suffix.lower() != ".txt":
        log_error(f"Expected a .txt file, got: {txt_path.suffix}")
        sys.exit(1)

    content = txt_path.read_text(encoding="utf-8")

    if "QUESTION:" not in content:
        log_error("Missing QUESTION: header in .txt file.")
        log_info("Every instruction/FAQ file must start with:")
        log_info("  QUESTION:")
        log_info("  <your question here>")
        log_info("")
        log_info("  ANSWER:")
        log_info("  <your answer here>")
        sys.exit(1)

    if "ANSWER:" not in content:
        log_error("Missing ANSWER: header in .txt file.")
        log_info("Every instruction/FAQ file must include an ANSWER: section.")
        sys.exit(1)

    log_ok("File format is valid (QUESTION: and ANSWER: headers found).")
    return content


# ── Step 3: Copy .txt to correct data/ subfolder ──────────────────────────────
def copy_txt(txt_path: Path, content_type: str):
    log_step(f"Copying file to data/{content_type}s/...")

    dest_dir = FAQ_DIR if content_type == "faq" else INSTRUCTIONS_DIR
    dest_path = dest_dir / txt_path.name

    if dest_path.exists():
        log_warn(f"{txt_path.name} already exists in {dest_dir}/")
        answer = input(f"    Overwrite? (y/n): ").strip().lower()
        if answer != "y":
            log_info("Skipped. No changes made.")
            sys.exit(0)

    shutil.copy2(txt_path, dest_path)
    log_ok(f"Copied to {dest_path}")
    return dest_path


# ── Step 4: Run FAISS ingestion ────────────────────────────────────────────────
def run_ingestion():
    log_step("Running FAISS ingestion (python -m app.rag.ingest)...")
    log_info("This rebuilds the search index. It may take 10–30 seconds.")

    result = subprocess.run(
        [sys.executable, "-m", "app.rag.ingest"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log_error("Ingestion failed. Output:")
        log_info(result.stdout)
        log_info(result.stderr)
        log_warn("Your .txt file was copied but the index was NOT rebuilt.")
        log_warn("Lance will NOT use this new content until ingestion succeeds.")
        log_warn("Try running manually:  python -m app.rag.ingest")
        sys.exit(1)

    log_ok("Ingestion complete. FAISS index rebuilt successfully.")
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines()[-5:]:  # show last 5 lines
            log_info(line)


# ── Step 5: Upload PDF to Firebase Storage + Firestore ────────────────────────
def upload_pdf(pdf_path: Path, label: str, content_type: str):
    log_step(f"Uploading PDF to Firebase: {pdf_path.name}...")

    # Check firebase-admin is installed
    try:
        import firebase_admin
        from firebase_admin import credentials, storage, firestore
    except ImportError:
        log_error("firebase-admin is not installed.")
        log_info("Install it with:  pip install firebase-admin")
        log_warn("PDF was NOT uploaded. All other steps completed successfully.")
        return

    # Check service account key exists
    if not SERVICE_ACCOUNT_PATH.exists():
        log_error(f"serviceAccountKey.json not found at: {SERVICE_ACCOUNT_PATH}")
        log_info("Place your Firebase service account key in the project root.")
        log_warn("PDF was NOT uploaded. All other steps completed successfully.")
        return

    if not pdf_path.exists():
        log_error(f"PDF file not found: {pdf_path}")
        log_warn("PDF was NOT uploaded. All other steps completed successfully.")
        return

    if pdf_path.suffix.lower() != ".pdf":
        log_error(f"Expected a .pdf file, got: {pdf_path.suffix}")
        log_warn("PDF was NOT uploaded. All other steps completed successfully.")
        return

    # Initialize Firebase (only once)
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred, {
            "storageBucket": _get_storage_bucket()
        })

    # Upload to Firebase Storage
    bucket = storage.bucket()
    blob_path = f"pdfs/{content_type}s/{pdf_path.name}"
    blob = bucket.blob(blob_path)

    blob.upload_from_filename(str(pdf_path), content_type="application/pdf")
    blob.make_public()
    download_url = blob.public_url

    log_ok(f"PDF uploaded to Firebase Storage: {blob_path}")
    log_info(f"Public URL: {download_url}")

    # Save metadata to Firestore
    db = firestore.client()
    doc_ref = db.collection("pdf_guides").document()
    doc_ref.set({
        "label": label,
        "filename": pdf_path.name,
        "type": content_type,
        "storage_path": blob_path,
        "download_url": download_url,
        "uploaded_at": datetime.utcnow().isoformat(),
    })

    log_ok(f"Firestore metadata saved (collection: pdf_guides, label: '{label}')")


def _get_storage_bucket():
    """Read storage bucket from config or prompt user."""
    # Try to read from environment variable first
    bucket = os.environ.get("FIREBASE_STORAGE_BUCKET", "")
    if bucket:
        return bucket

    # Try to read from a local config file
    config_path = Path("firebase_config.txt")
    if config_path.exists():
        return config_path.read_text().strip()

    # Fall back to prompting
    log_warn("FIREBASE_STORAGE_BUCKET environment variable not set.")
    bucket = input("    Enter your Firebase Storage bucket name (e.g. your-app.appspot.com): ").strip()
    if not bucket:
        log_error("No bucket name provided. Cannot upload PDF.")
        sys.exit(1)
    return bucket


# ── Summary printer ────────────────────────────────────────────────────────────
def print_summary(txt_dest: Path, pdf_path: Path = None, label: str = None):
    print()
    print(f"{BOLD}{'─'*55}{RESET}")
    print(f"{BOLD}  Lance Content Addition — Complete{RESET}")
    print(f"{'─'*55}")
    print(f"  .txt file  →  {txt_dest}")
    print(f"  Index      →  Rebuilt ✓")
    if pdf_path:
        print(f"  PDF        →  {pdf_path.name} uploaded ✓")
        print(f"  Label      →  {label}")
    print(f"{'─'*55}")
    print(f"  {GREEN}Lance will now use this content in responses.{RESET}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Lance Content Addition Script — CBU Campus Store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Add a FAQ (no PDF):
    python lance_add_content.py --type faq --txt data/faqs/ia_browser_cache_clear.txt

  Add a platform instruction (no PDF):
    python lance_add_content.py --type instruction --txt data/instructions/ia_mcgraw_hill_connect_no_read_now.txt

  Add a FAQ with a PDF guide attached:
    python lance_add_content.py --type faq --txt data/faqs/ia_browser_cache_clear.txt \\
        --pdf docs/Safari_Clear_Cache.pdf --pdf-label "Safari Clear Cache Guide"
        """
    )

    parser.add_argument(
        "--type", required=True, choices=["faq", "instruction"],
        help="Whether this is a general FAQ or a platform-specific instruction."
    )
    parser.add_argument(
        "--txt", required=True, type=Path,
        help="Path to the .txt file to add."
    )
    parser.add_argument(
        "--pdf", type=Path, default=None,
        help="(Optional) Path to a PDF guide to upload to Firebase Storage."
    )
    parser.add_argument(
        "--pdf-label", type=str, default=None,
        help="(Optional) Human-readable label for the PDF (e.g. 'Safari Clear Cache Guide')."
    )

    args = parser.parse_args()

    # Validate PDF args together
    if args.pdf and not args.pdf_label:
        parser.error("--pdf-label is required when --pdf is provided.")
    if args.pdf_label and not args.pdf:
        parser.error("--pdf is required when --pdf-label is provided.")

    print()
    print(f"{BOLD}  Lance Content Addition Script{RESET}")
    print(f"  CBU Campus Store\n")

    check_project_root()
    validate_txt(args.txt)
    txt_dest = copy_txt(args.txt, args.type)
    run_ingestion()

    if args.pdf:
        upload_pdf(args.pdf, args.pdf_label, args.type)

    print_summary(txt_dest, args.pdf, args.pdf_label)


if __name__ == "__main__":
    main()
