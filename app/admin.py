"""
app/admin.py
------------
Lance Admin API — Content Addition Endpoint
CBU Campus Store

Provides a single POST /admin/add-content endpoint that:
  1. Receives a .txt file and optional PDF via multipart form
  2. Validates the .txt format (QUESTION: / ANSWER: headers)
  3. Copies the .txt to the correct data/ subfolder
  4. Runs FAISS ingestion (python -m app.rag.ingest)
  5. (Optional) Uploads the PDF to Firebase Storage + Firestore

Mount this router in app/main.py:

    from app.admin import admin_router
    app.include_router(admin_router)

Also serve the admin UI in main.py:

    from fastapi.responses import FileResponse
    @app.get("/admin")
    def admin_ui():
        return FileResponse("lance_admin_ui.html")

Security note:
    This endpoint is intended for internal/local use only.
    If the Lance backend is ever exposed publicly, add authentication
    before this endpoint (e.g. HTTP Basic Auth via fastapi.security).
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from app.admin_auth import verify_admin_credentials

# ── Config ─────────────────────────────────────────────────────────────────────
FAQ_DIR          = Path(os.environ.get("FAQ_DIR", "data/faqs"))
INSTRUCTIONS_DIR = Path(os.environ.get("INSTRUCTIONS_DIR", "data/instructions"))
SERVICE_ACCOUNT  = Path("serviceAccountKey.json")

# All routes on this router require valid admin credentials
admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_credentials)]
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_txt_content(content: str) -> str | None:
    """Return an error message string if the content is invalid, else None."""
    if "QUESTION:" not in content:
        return "Missing QUESTION: header. Every file must include a QUESTION: section."
    if "ANSWER:" not in content:
        return "Missing ANSWER: header. Every file must include an ANSWER: section."
    return None


def _copy_txt(content: bytes, filename: str, content_type: str) -> Path:
    """Save uploaded .txt bytes to the correct data/ subfolder."""
    dest_dir = FAQ_DIR if content_type == "faq" else INSTRUCTIONS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    dest_path.write_bytes(content)
    return dest_path


def _run_ingestion() -> str:
    """Run FAISS ingestion. Returns a detail string. Raises on failure."""
    result = subprocess.run(
        [sys.executable, "-m", "app.rag.ingest"],
        capture_output=True,
        text=True,
        timeout=120  # 2 minute timeout
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Ingestion failed (exit {result.returncode}):\n"
            f"{result.stderr or result.stdout}"
        )
    # Return last meaningful line of output as detail
    lines = [l.strip() for l in (result.stdout or "").splitlines() if l.strip()]
    return lines[-1] if lines else "Index rebuilt successfully."


def _upload_pdf_to_firebase(
    pdf_bytes: bytes,
    filename: str,
    label: str,
    content_type: str
) -> str | None:
    """
    Upload PDF to Firebase Storage and save metadata to Firestore.
    Returns the public download URL, or None if Firebase is not configured.
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, storage, firestore as fs
    except ImportError:
        return None  # firebase-admin not installed — silently skip

    if not SERVICE_ACCOUNT.exists():
        return None  # No credentials — silently skip

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET", "")
    if not bucket_name:
        return None  # No bucket configured — silently skip

    # Initialize Firebase app (only once per process)
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT))
        firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})

    # Upload to Storage
    bucket = storage.bucket()
    blob_path = f"pdfs/{content_type}s/{filename}"
    blob = bucket.blob(blob_path)

    import io
    blob.upload_from_file(io.BytesIO(pdf_bytes), content_type="application/pdf")
    blob.make_public()
    url = blob.public_url

    # Save metadata to Firestore
    db = fs.client()
    db.collection("pdf_guides").document().set({
        "label":         label,
        "filename":      filename,
        "type":          content_type,
        "storage_path":  blob_path,
        "download_url":  url,
        "uploaded_at":   datetime.utcnow().isoformat(),
    })

    return url


# ── Endpoint ───────────────────────────────────────────────────────────────────

@admin_router.post("/add-content")
async def add_content(
    content_type: str       = Form(...),
    txt_file:     UploadFile = File(...),
    pdf_file:     UploadFile = File(None),
    pdf_label:    str        = Form(None),
):
    """
    Add a new FAQ or instruction .txt file to Lance, rebuild the FAISS index,
    and optionally upload a PDF guide to Firebase Storage.

    Form fields:
        content_type  — "faq" or "instruction"
        txt_file      — the .txt file (required)
        pdf_file      — a PDF guide (optional)
        pdf_label     — human-readable label for the PDF (required if pdf_file provided)
    """

    # ── Validate content_type ──────────────────────────────────────────────────
    if content_type not in ("faq", "instruction"):
        raise HTTPException(status_code=400, detail="content_type must be 'faq' or 'instruction'.")

    # ── Validate .txt file extension ───────────────────────────────────────────
    if not txt_file.filename.lower().endswith(".txt"):
        return JSONResponse(status_code=400, content={
            "success": False,
            "failed_step": "upload_txt",
            "message": f"Expected a .txt file, received: {txt_file.filename}"
        })

    # ── Read .txt content ──────────────────────────────────────────────────────
    txt_bytes = await txt_file.read()
    try:
        txt_content = txt_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={
            "success": False,
            "failed_step": "upload_txt",
            "message": "Could not read the .txt file. Make sure it is saved as UTF-8."
        })

    # ── Validate content format ────────────────────────────────────────────────
    format_error = _validate_txt_content(txt_content)
    if format_error:
        return JSONResponse(status_code=400, content={
            "success": False,
            "failed_step": "validate",
            "message": format_error
        })

    # ── Copy .txt to data/ subfolder ───────────────────────────────────────────
    try:
        txt_dest = _copy_txt(txt_bytes, txt_file.filename, content_type)
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "failed_step": "upload_txt",
            "message": f"Failed to save file: {str(e)}"
        })

    # ── Run FAISS ingestion ────────────────────────────────────────────────────
    try:
        ingest_detail = _run_ingestion()
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "failed_step": "ingest",
            "message": f"Ingestion failed: {str(e)}"
        })

    # ── Upload PDF (optional) ──────────────────────────────────────────────────
    pdf_url      = None
    pdf_uploaded = False

    if pdf_file and pdf_file.filename:
        if not pdf_file.filename.lower().endswith(".pdf"):
            return JSONResponse(status_code=400, content={
                "success": False,
                "failed_step": "upload_pdf",
                "message": f"Expected a .pdf file, received: {pdf_file.filename}"
            })
        if not pdf_label:
            return JSONResponse(status_code=400, content={
                "success": False,
                "failed_step": "upload_pdf",
                "message": "pdf_label is required when uploading a PDF."
            })

        pdf_bytes = await pdf_file.read()

        try:
            pdf_url = _upload_pdf_to_firebase(
                pdf_bytes, pdf_file.filename, pdf_label, content_type
            )
            pdf_uploaded = pdf_url is not None
        except Exception as e:
            # PDF upload failure is non-fatal — .txt and ingestion already succeeded
            return JSONResponse(content={
                "success": True,
                "txt_dest":      str(txt_dest),
                "ingest_detail": ingest_detail,
                "pdf_uploaded":  False,
                "pdf_url":       None,
                "message":       f"Content added and index rebuilt, but PDF upload failed: {str(e)}"
            })

    # ── Success ────────────────────────────────────────────────────────────────
    return JSONResponse(content={
        "success":       True,
        "txt_dest":      str(txt_dest),
        "ingest_detail": ingest_detail,
        "pdf_uploaded":  pdf_uploaded,
        "pdf_url":       pdf_url,
        "message":       "Content added successfully."
    })
