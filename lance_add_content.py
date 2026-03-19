#!/usr/bin/env python3
"""
lance_add_content.py
--------------------
Lance Content Addition Script
CBU Campus Store

Usage:
    python lance_add_content.py --type faq --txt path/to/file.txt

    python lance_add_content.py --type faq --txt path/to/file.txt \\
        --pdf docs/Safari_Clear_Cache.pdf --pdf-label "Safari Clear Cache Guide" \\
        --pdf docs/Chrome_Clear_Cache.pdf --pdf-label "Chrome Clear Cache Guide" \\
        --pdf docs/iPad_Chrome.pdf        --pdf-label "iPad Chrome Clear Cache Guide"

What this script does:
    1. Validates the .txt file format (QUESTION: / ANSWER: headers)
    2. Copies the .txt file to the correct data/ subfolder
    3. Runs FAISS ingestion to rebuild the search index
    4. (Optional) Uploads each PDF to Firebase Storage and saves metadata to Firestore
       Each --pdf must have a matching --pdf-label in the same order.

Requirements:
    - Run from the project root directory (same folder as app/)
    - Conda environment must be active: conda activate campus-store-bot
    - For PDF upload: firebase-admin must be installed and app/firebase-service-account.json
      must exist, unless FIREBASE_SERVICE_ACCOUNT_PATH overrides it
"""

import argparse
import shutil
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
FAQ_DIR          = Path("data/faqs")
INSTRUCTIONS_DIR = Path("data/instructions")
_service_account_value = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "app/firebase-service-account.json")
SERVICE_ACCOUNT  = Path(_service_account_value)
if not SERVICE_ACCOUNT.is_absolute():
    SERVICE_ACCOUNT = Path(".") / SERVICE_ACCOUNT

# ── Terminal colors ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def log_step(msg):  print(f"{CYAN}{BOLD}▶ {msg}{RESET}")
def log_ok(msg):    print(f"{GREEN}  ✓ {msg}{RESET}")
def log_warn(msg):  print(f"{YELLOW}  ⚠ {msg}{RESET}")
def log_error(msg): print(f"{RED}  ✗ {msg}{RESET}")
def log_info(msg):  print(f"    {msg}")


# ── Step 1: Validate project root ──────────────────────────────────────────────
def check_project_root():
    log_step("Checking project root...")
    if not Path("app/main.py").exists():
        log_error("app/main.py not found.")
        log_info("Please run this script from the project root directory.")
        log_info("Example:  cd /path/to/lance && python lance_add_content.py ...")
        sys.exit(1)
    if not FAQ_DIR.exists() or not INSTRUCTIONS_DIR.exists():
        log_error("data/faqs/ or data/instructions/ directory not found.")
        sys.exit(1)
    log_ok("Project root confirmed.")


# ── Step 2: Validate .txt format ──────────────────────────────────────────────
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
        log_error("Missing QUESTION: header.")
        log_info("Every file must have both QUESTION: and ANSWER: sections.")
        sys.exit(1)
    if "ANSWER:" not in content:
        log_error("Missing ANSWER: header.")
        log_info("Every file must have both QUESTION: and ANSWER: sections.")
        sys.exit(1)

    log_ok("File format valid (QUESTION: and ANSWER: found).")


# ── Step 3: Copy .txt to correct data/ subfolder ──────────────────────────────
def copy_txt(txt_path: Path, content_type: str) -> Path:
    log_step(f"Copying file to data/{content_type}s/...")
    dest_dir  = FAQ_DIR if content_type == "faq" else INSTRUCTIONS_DIR
    dest_path = dest_dir / txt_path.name

    if dest_path.exists():
        log_warn(f"{txt_path.name} already exists in {dest_dir}/")
        answer = input("    Overwrite? (y/n): ").strip().lower()
        if answer != "y":
            log_info("Skipped. No changes made.")
            sys.exit(0)

    shutil.copy2(txt_path, dest_path)
    log_ok(f"Copied to {dest_path}")
    return dest_path


# ── Step 4: Run FAISS ingestion ────────────────────────────────────────────────
def run_ingestion():
    log_step("Running FAISS ingestion (python -m app.rag.ingest)...")
    log_info("This may take 10–30 seconds.")

    result = subprocess.run(
        [sys.executable, "-m", "app.rag.ingest"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        log_error("Ingestion failed. Output:")
        log_info(result.stdout)
        log_info(result.stderr)
        log_warn("Your .txt file was copied but the FAISS index was NOT rebuilt.")
        log_warn("Run manually to fix:  python -m app.rag.ingest")
        sys.exit(1)

    log_ok("Ingestion complete. FAISS index rebuilt.")
    for line in (result.stdout or "").strip().splitlines()[-5:]:
        if line.strip():
            log_info(line)


# ── Step 5: Upload PDFs ────────────────────────────────────────────────────────
def upload_pdfs(pdf_paths: list, pdf_labels: list, content_type: str):
    """Upload each PDF individually. A failure on one does not stop the rest."""
    for pdf_path, label in zip(pdf_paths, pdf_labels):
        _upload_single_pdf(pdf_path, label, content_type)


def _upload_single_pdf(pdf_path: Path, label: str, content_type: str):
    log_step(f"Uploading PDF: {pdf_path.name}  [{label}]")

    try:
        import firebase_admin
        from firebase_admin import credentials, storage, firestore
    except ImportError:
        log_warn("firebase-admin not installed — skipping PDF upload.")
        log_info("Install with:  pip install firebase-admin")
        return

    if not SERVICE_ACCOUNT.exists():
        log_warn(f"Firebase service account not found at {SERVICE_ACCOUNT} — skipping {pdf_path.name}")
        return

    if not pdf_path.exists():
        log_error(f"PDF file not found: {pdf_path}")
        return

    if pdf_path.suffix.lower() != ".pdf":
        log_error(f"Expected a .pdf file, got: {pdf_path.suffix}")
        return

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET", "")
    if not bucket_name:
        config_file = Path("firebase_config.txt")
        if config_file.exists():
            bucket_name = config_file.read_text().strip()
    if not bucket_name:
        log_warn("FIREBASE_STORAGE_BUCKET not set.")
        bucket_name = input("    Enter Firebase Storage bucket name: ").strip()
        if not bucket_name:
            log_error("No bucket name — skipping PDF upload.")
            return

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT))
        firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})

    bucket    = storage.bucket()
    blob_path = f"pdfs/{content_type}s/{pdf_path.name}"
    blob      = bucket.blob(blob_path)
    blob.upload_from_filename(str(pdf_path), content_type="application/pdf")
    blob.make_public()
    url = blob.public_url
    log_ok(f"Uploaded: {blob_path}")
    log_info(f"URL: {url}")

    db = firestore.client()
    db.collection("pdf_guides").document().set({
        "label":        label,
        "filename":     pdf_path.name,
        "type":         content_type,
        "storage_path": blob_path,
        "download_url": url,
        "uploaded_at":  datetime.utcnow().isoformat(),
    })
    log_ok(f"Firestore metadata saved  (label: '{label}')")


# ── Summary ────────────────────────────────────────────────────────────────────
def print_summary(txt_dest: Path, pdf_paths: list, pdf_labels: list):
    print()
    print(f"{BOLD}{'─'*55}{RESET}")
    print(f"{BOLD}  Lance Content Addition — Complete{RESET}")
    print(f"{'─'*55}")
    print(f"  .txt file  →  {txt_dest}")
    print(f"  Index      →  Rebuilt ✓")
    for path, label in zip(pdf_paths, pdf_labels):
        print(f"  PDF        →  {path.name}  [{label}]  ✓")
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
    python lance_add_content.py --type instruction \\
        --txt data/instructions/ia_mcgraw_hill_connect_no_read_now.txt

  Add a FAQ with multiple PDF guides:
    python lance_add_content.py --type faq \\
        --txt data/faqs/ia_browser_cache_clear.txt \\
        --pdf docs/Safari_Clear_Cache.pdf   --pdf-label "Safari Clear Cache Guide" \\
        --pdf docs/Chrome_Clear_Cache.pdf   --pdf-label "Chrome Clear Cache Guide" \\
        --pdf docs/iPad_Chrome.pdf          --pdf-label "iPad Chrome Clear Cache Guide"

Note: --pdf and --pdf-label must be paired in the same order.
      Each --pdf must have its own --pdf-label immediately after it.
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
        "--pdf", type=Path, action="append", default=[],
        help="(Repeatable) Path to a PDF guide to upload. Pair each with --pdf-label."
    )
    parser.add_argument(
        "--pdf-label", type=str, action="append", default=[], dest="pdf_label",
        help="(Repeatable) Label for the corresponding --pdf, in the same order."
    )

    args = parser.parse_args()

    # Validate PDF / label pairing
    if len(args.pdf) != len(args.pdf_label):
        parser.error(
            f"{len(args.pdf)} --pdf flag(s) but {len(args.pdf_label)} --pdf-label flag(s). "
            "Every --pdf must have a matching --pdf-label in the same order."
        )

    print()
    print(f"{BOLD}  Lance Content Addition Script{RESET}")
    print(f"  CBU Campus Store\n")

    check_project_root()
    validate_txt(args.txt)
    txt_dest = copy_txt(args.txt, args.type)
    run_ingestion()

    if args.pdf:
        upload_pdfs(args.pdf, args.pdf_label, args.type)

    print_summary(txt_dest, args.pdf, args.pdf_label)


if __name__ == "__main__":
    main()
