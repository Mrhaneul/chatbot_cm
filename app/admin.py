"""
app/admin.py
------------
Lance Admin API — Content Addition Endpoint
CBU Campus Store

Provides a single POST /admin/add-content endpoint that:
  1. Receives a .txt file and optional multiple PDFs via multipart form
  2. Validates the .txt format (QUESTION: / ANSWER: headers)
  3. Copies the .txt to the correct data/ subfolder
  4. Runs FAISS ingestion (python -m app.rag.ingest)
  5. (Optional) Uploads each PDF to Firebase Storage + Firestore with its own label

Mount this router in app/main.py AFTER app = FastAPI(...):

    from app.admin import admin_router
    from fastapi.responses import FileResponse

    app.include_router(admin_router)

    @app.get("/admin")
    def admin_ui():
        return FileResponse("lance_admin_ui.html")

Security note:
    Protected by HTTP Basic Auth via app/admin_auth.py.
    Credentials are set in .env as LANCE_ADMIN_USER and LANCE_ADMIN_PASSWORD.
"""

import io
import re
import shutil
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.admin_auth import verify_admin_credentials
from app.rag.metadata import parse_front_matter_text

# ── Config ─────────────────────────────────────────────────────────────────────
FAQ_DIR          = Path(os.environ.get("FAQ_DIR", "data/faqs"))
INSTRUCTIONS_DIR = Path(os.environ.get("INSTRUCTIONS_DIR", "data/instructions"))
ARCHIVE_DIR      = Path(os.environ.get("CONTENT_ARCHIVE_DIR", "data/_archive"))

REQUIRED_FRONT_MATTER_FIELDS = (
    "source_id",
    "source_type",
    "category",
    "platform",
    "issue_type",
    "priority",
)


class ContentValidationRequest(BaseModel):
    content_type: str
    content: str


class ContentSaveRequest(BaseModel):
    content_type: str
    filename: str
    content: str

# All routes on this router require valid admin credentials
admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_credentials)]
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_txt_content(content: str) -> Optional[str]:
    """Return an error message string if the content is invalid, else None."""
    if "QUESTION:" not in content:
        return "Missing QUESTION: header. Every file must include a QUESTION: section."
    if "ANSWER:" not in content:
        return "Missing ANSWER: header. Every file must include an ANSWER: section."
    return None


def _validate_content_type(content_type: str) -> Optional[str]:
    if content_type not in ("faq", "instruction"):
        return "content_type must be 'faq' or 'instruction'."
    return None


def _validate_front_matter_for_admin(content: str, content_type: str) -> tuple[dict, str]:
    """
    Validate staff-edited content before saving.

    Admin-managed files must include complete front matter so published content
    has stable source identity and filtering metadata.
    """
    type_error = _validate_content_type(content_type)
    if type_error:
        raise ValueError(type_error)

    if not content.strip():
        raise ValueError("Content must not be empty.")
    if not content.lstrip().startswith("---"):
        raise ValueError(
            "Missing YAML front matter. Start the file with --- and include "
            "source_id, source_type, category, platform, issue_type, and priority."
        )

    try:
        metadata, body = parse_front_matter_text(content)
    except ValueError as exc:
        raise ValueError(f"Malformed YAML front matter: {exc}") from exc

    missing = [field for field in REQUIRED_FRONT_MATTER_FIELDS if field not in metadata]
    if missing:
        raise ValueError(f"Missing required front-matter field(s): {', '.join(missing)}.")

    for field in REQUIRED_FRONT_MATTER_FIELDS:
        value = metadata.get(field)
        if field == "platform" and value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Front-matter field '{field}' must be a non-empty value.")

    expected_source_type = "faq" if content_type == "faq" else "instruction"
    if metadata.get("source_type") != expected_source_type:
        raise ValueError(
            f"source_type must be '{expected_source_type}' for {content_type} content."
        )

    if not body.strip():
        raise ValueError("File body must not be empty after front matter.")

    if content_type == "faq":
        body_upper = body.upper()
        if "QUESTION:" not in body_upper:
            raise ValueError("FAQ body must include a QUESTION: section.")
        if "ANSWER:" not in body_upper:
            raise ValueError("FAQ body must include an ANSWER: section.")

    return metadata, body.strip()


def _content_root(content_type: str) -> Path:
    return FAQ_DIR if content_type == "faq" else INSTRUCTIONS_DIR


def _safe_relative_path(value: str | None, *, allow_empty: bool = False) -> Path:
    """
    Normalize a staff-provided relative path and reject absolute/traversal paths.
    """
    raw = (value or "").strip()
    for _ in range(3):
        decoded = unquote(raw)
        if decoded == raw:
            break
        raw = decoded
    raw = raw.replace("\\", "/")
    if not raw:
        if allow_empty:
            return Path()
        raise ValueError("Path must not be empty.")

    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"..", ""} for part in candidate.parts):
        raise ValueError("Use a relative path inside the content directory.")
    return candidate


def _resolve_content_path(root: Path, relative_path: str) -> Path:
    rel_path = _safe_relative_path(relative_path)
    resolved_root = root.resolve()
    resolved_target = (root / rel_path).resolve()
    if resolved_root != resolved_target and resolved_root not in resolved_target.parents:
        raise ValueError("Path escapes the content directory.")
    return resolved_target


def _content_relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _list_txt_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.txt")
        if path.is_file()
    )


def _archive_path_for(source_path: Path, source_root: Path, action: str) -> Path:
    relative = _content_relative_path(source_path, source_root)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    unique_suffix = uuid4().hex[:8]
    archive_path = ARCHIVE_DIR / action / source_root.name / relative
    return archive_path.with_name(
        f"{archive_path.stem}.{timestamp}.{unique_suffix}{archive_path.suffix}"
    )


def _archive_content_file(source_path: Path, source_root: Path, action: str, *, move: bool) -> Path:
    archive_path = _archive_path_for(source_path, source_root, action)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(os.fspath(source_path), os.fspath(archive_path))
    else:
        shutil.copy2(source_path, archive_path)
    return archive_path


def _read_content_file(content_type: str, filename: str) -> tuple[Path, str, dict]:
    type_error = _validate_content_type(content_type)
    if type_error:
        raise ValueError(type_error)
    root = _content_root(content_type)
    target = _resolve_content_path(root, filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"'{filename}' not found in the {content_type} directory.")
    content = target.read_text(encoding="utf-8")
    try:
        metadata, _body = parse_front_matter_text(content)
    except ValueError as exc:
        metadata = {"front_matter_error": str(exc)}
    return target, content, metadata


def _save_content_file(content_type: str, filename: str, content: str) -> tuple[Path, Path, dict]:
    metadata, _body = _validate_front_matter_for_admin(content, content_type)
    root = _content_root(content_type)
    target = _resolve_content_path(root, filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"'{filename}' not found in the {content_type} directory.")
    backup_path = _archive_content_file(target, root, "backups", move=False)
    temp_path = target.with_name(f".{target.name}.tmp")
    try:
        temp_path.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target, backup_path, metadata


def _copy_txt(
    content: bytes,
    filename: str,
    content_type: str,
    target_folder: str | None = None,
) -> Path:
    """Save uploaded .txt bytes to the correct data/ subfolder."""
    dest_root = _content_root(content_type)
    safe_filename = _safe_relative_path(filename).name
    safe_folder = _safe_relative_path(target_folder, allow_empty=True)
    dest_dir = _resolve_content_path(dest_root, safe_folder.as_posix()) if safe_folder.parts else dest_root
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_filename
    dest_path.write_bytes(content)
    return dest_path


def _run_ingestion() -> str:
    """Run FAISS ingestion. Returns a detail string. Raises on failure."""
    result = subprocess.run(
        [sys.executable, "-m", "app.rag.ingest"],
        capture_output=True,
        text=True,
        timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Ingestion failed (exit {result.returncode}):\n"
            f"{result.stderr or result.stdout}"
        )
    lines = [l.strip() for l in (result.stdout or "").splitlines() if l.strip()]
    return lines[-1] if lines else "Index rebuilt successfully."


def _upload_single_pdf(
    pdf_bytes: bytes,
    filename: str,
    label: str,
    content_type: str
) -> tuple:
    """
    Upload one PDF to Firebase Storage and save its metadata to Firestore
    collection pdf_documents.

    Returns (url, doc_id) on success, or (None, None) if Firebase is not
    configured or the upload fails.
    """
    try:
        from app.firebase_config import get_storage_bucket, get_firestore_client
    except ImportError:
        return None, None

    bucket = get_storage_bucket()
    if bucket is None:
        return None, None

    blob_path = f"pdfs/{content_type}s/{filename}"
    blob = bucket.blob(blob_path)
    blob.upload_from_file(io.BytesIO(pdf_bytes), content_type="application/pdf")
    blob.make_public()
    url = blob.public_url

    # Derive a stable, addressable document ID from the label.
    # e.g. "Safari Clear Cache Guide" → "safari_clear_cache_guide"
    doc_id = re.sub(r"[^a-z0-9_]", "", label.lower().replace(" ", "_"))

    now = datetime.utcnow().isoformat()

    db = get_firestore_client()
    db.collection("pdf_documents").document(doc_id).set({
        # Core identity
        "doc_id":       doc_id,
        "title":        label,
        "filename":     filename,
        "public_url":   url,
        "storage_path": blob_path,

        # Metadata read by get_pdf_from_firestore()
        "description":  f"Guide: {label}",
        "platform":     "general",
        "type":         content_type,
        "issue_type":   "",
        "tags":         [],
        "priority":     "medium",
        "pages":        0,
        "file_size_kb": 0,

        # Timestamps
        "created_at":   now,
        "updated_at":   now,
        "uploaded_via": "admin_ui",
    })

    return url, doc_id


def _write_txt_to_pdf_map(txt_filename: str, doc_ids: List[str]) -> None:
    """
    Upsert the txt→pdf mapping in Firestore collection txt_to_pdf_map.

    Merges new doc_ids with any that already exist for this .txt file so that
    PDFs added across multiple admin submissions are all retained.
    """
    if not doc_ids:
        return
    try:
        from app.firebase_config import get_firestore_client
    except ImportError:
        return

    db = get_firestore_client()
    if db is None:
        return

    ref = db.collection("txt_to_pdf_map").document(txt_filename)
    existing = ref.get()
    existing_ids: List[str] = existing.to_dict().get("pdf_doc_ids", []) if existing.exists else []

    # Merge, preserving order and deduplicating.
    merged = list(dict.fromkeys(existing_ids + [d for d in doc_ids if d]))

    ref.set({
        "txt_filename": txt_filename,
        "pdf_doc_ids":  merged,
        "updated_at":   datetime.utcnow().isoformat(),
    })


def _upload_all_pdfs(
    pdf_files: List[UploadFile],
    pdf_labels: List[str],
    pdf_bytes_list: List[bytes],
    content_type: str
) -> List[dict]:
    """
    Upload all PDFs. Returns a list of result dicts, one per PDF.
    Each dict includes a 'doc_id' field with the Firestore document ID so the
    caller can write the txt_to_pdf_map after all uploads complete.
    Never raises — individual failures are captured per-PDF.
    """
    results = []
    for pdf_file, label, pdf_bytes in zip(pdf_files, pdf_labels, pdf_bytes_list):
        try:
            url, doc_id = _upload_single_pdf(pdf_bytes, pdf_file.filename, label, content_type)
            results.append({
                "filename": pdf_file.filename,
                "label":    label,
                "uploaded": url is not None,
                "url":      url,
                "doc_id":   doc_id,
                "error":    None,
            })
        except Exception as e:
            results.append({
                "filename": pdf_file.filename,
                "label":    label,
                "uploaded": False,
                "url":      None,
                "doc_id":   None,
                "error":    str(e),
            })
    return results


# ── Endpoint ───────────────────────────────────────────────────────────────────

@admin_router.post("/add-content")
async def add_content(
    content_type: str             = Form(...),
    txt_file:     UploadFile      = File(...),
    target_folder: str | None      = Form(default=None),
    pdf_files:    List[UploadFile] = File(default=[]),
    pdf_labels:   List[str]        = Form(default=[]),
):
    """
    Add a new FAQ or instruction .txt file to Lance, rebuild the FAISS index,
    and optionally upload one or more PDF guides to Firebase Storage.

    Form fields:
        content_type  — "faq" or "instruction"
        txt_file      — the .txt file (required)
        pdf_files     — one or more PDF guides (optional, repeatable)
        pdf_labels    — one label per PDF, in the same order (required if pdf_files provided)

    Each PDF must have a corresponding label at the same index position.
    Example: pdf_files[0] ↔ pdf_labels[0], pdf_files[1] ↔ pdf_labels[1], etc.
    """

    # ── Validate content_type ──────────────────────────────────────────────────
    if content_type not in ("faq", "instruction"):
        raise HTTPException(
            status_code=400,
            detail="content_type must be 'faq' or 'instruction'."
        )

    # ── Validate .txt extension ────────────────────────────────────────────────
    if not txt_file.filename.lower().endswith(".txt"):
        return JSONResponse(status_code=400, content={
            "success":     False,
            "failed_step": "upload_txt",
            "message":     f"Expected a .txt file, received: {txt_file.filename}"
        })

    # ── Read + decode .txt ─────────────────────────────────────────────────────
    txt_bytes = await txt_file.read()
    try:
        txt_content = txt_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={
            "success":     False,
            "failed_step": "upload_txt",
            "message":     "Could not read the .txt file. Make sure it is saved as UTF-8."
        })

    # ── Validate content format ────────────────────────────────────────────────
    format_error = _validate_txt_content(txt_content)
    if format_error:
        return JSONResponse(status_code=400, content={
            "success":     False,
            "failed_step": "validate",
            "message":     format_error
        })

    # ── Validate PDF / label pairing ───────────────────────────────────────────
    # Filter out any empty file slots the browser may send
    active_pdfs = [f for f in pdf_files if f and f.filename]

    if active_pdfs:
        if len(pdf_labels) != len(active_pdfs):
            return JSONResponse(status_code=400, content={
                "success":     False,
                "failed_step": "upload_pdf",
                "message":     (
                    f"Mismatch: {len(active_pdfs)} PDF(s) uploaded "
                    f"but {len(pdf_labels)} label(s) provided. "
                    "Every PDF must have its own label."
                )
            })
        for f in active_pdfs:
            if not f.filename.lower().endswith(".pdf"):
                return JSONResponse(status_code=400, content={
                    "success":     False,
                    "failed_step": "upload_pdf",
                    "message":     f"Expected .pdf files only. Got: {f.filename}"
                })
        missing_labels = [i for i, lbl in enumerate(pdf_labels) if not lbl.strip()]
        if missing_labels:
            return JSONResponse(status_code=400, content={
                "success":     False,
                "failed_step": "upload_pdf",
                "message":     f"PDF label(s) at position(s) {missing_labels} are empty."
            })

    # ── Copy .txt to data/ subfolder ───────────────────────────────────────────
    try:
        txt_dest = _copy_txt(txt_bytes, txt_file.filename, content_type, target_folder)
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success":     False,
            "failed_step": "upload_txt",
            "message":     f"Failed to save file: {str(e)}"
        })
    txt_relative_path = _content_relative_path(txt_dest, _content_root(content_type))

    # ── Run FAISS ingestion ────────────────────────────────────────────────────
    try:
        ingest_detail = _run_ingestion()
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success":     False,
            "failed_step": "ingest",
            "message":     f"Ingestion failed: {str(e)}"
        })

    # ── Upload PDFs (optional) ─────────────────────────────────────────────────
    pdf_results = []
    if active_pdfs:
        pdf_bytes_list = [await f.read() for f in active_pdfs]
        pdf_results = _upload_all_pdfs(
            active_pdfs, pdf_labels, pdf_bytes_list, content_type
        )

    pdfs_uploaded  = sum(1 for r in pdf_results if r["uploaded"])
    pdfs_failed    = sum(1 for r in pdf_results if not r["uploaded"] and r["error"])
    pdfs_skipped   = sum(1 for r in pdf_results if not r["uploaded"] and not r["error"])

    # ── Write txt→pdf mapping in Firestore (if any PDFs were uploaded) ─────────
    if pdfs_uploaded > 0:
        successful_doc_ids = [r["doc_id"] for r in pdf_results if r.get("doc_id")]
        try:
            _write_txt_to_pdf_map(txt_relative_path, successful_doc_ids)
        except Exception as e:
            print(f"[WARN] txt_to_pdf_map write failed: {e}")

    # ── Success ────────────────────────────────────────────────────────────────
    message = "Content added successfully."
    if pdfs_failed:
        message += f" Warning: {pdfs_failed} PDF(s) failed to upload — see pdf_results for details."
    if pdfs_skipped:
        message += f" Note: {pdfs_skipped} PDF(s) skipped (Firebase not configured)."

    return JSONResponse(content={
        "success":        True,
        "txt_dest":       str(txt_dest),
        "txt_relative_path": txt_relative_path,
        "ingest_detail":  ingest_detail,
        "pdf_results":    pdf_results,
        "pdfs_uploaded":  pdfs_uploaded,
        "message":        message,
    })


# ── List content ────────────────────────────────────────────────────────────────

@admin_router.get("/list-content")
async def list_content():
    """Return sorted lists of all .txt files in data/faqs/ and data/instructions/."""
    faqs         = _list_txt_files(FAQ_DIR)
    instructions = _list_txt_files(INSTRUCTIONS_DIR)
    return JSONResponse(content={"faqs": faqs, "instructions": instructions})


@admin_router.get("/content")
async def get_content(
    filename: str = None,
    content_type: str = None,
):
    """Return a source .txt file for admin editing."""
    if not filename or not content_type:
        return JSONResponse(status_code=400, content={
            "success": False,
            "message": "Both 'filename' and 'content_type' query parameters are required."
        })
    try:
        target, content, metadata = _read_content_file(content_type, filename)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "message": str(exc)})
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"success": False, "message": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False,
            "message": f"Failed to read file: {exc}",
        })

    return JSONResponse(content={
        "success": True,
        "filename": filename,
        "content_type": content_type,
        "path": str(target),
        "content": content,
        "metadata": metadata,
    })


@admin_router.post("/validate-content")
async def validate_content(payload: ContentValidationRequest = Body(...)):
    """Validate edited text without saving it."""
    try:
        metadata, _body = _validate_front_matter_for_admin(
            payload.content,
            payload.content_type,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "success": False,
            "message": str(exc),
        })
    return JSONResponse(content={
        "success": True,
        "message": "Front matter and body look valid.",
        "metadata": metadata,
    })


@admin_router.post("/save-content")
async def save_content(payload: ContentSaveRequest = Body(...)):
    """
    Save an edited .txt file, archiving the previous version first, then rebuild
    the FAISS index so the published answer is queryable.
    """
    try:
        target, backup_path, metadata = _save_content_file(
            payload.content_type,
            payload.filename,
            payload.content,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "success": False,
            "failed_step": "validate",
            "message": str(exc),
        })
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={
            "success": False,
            "failed_step": "save",
            "message": str(exc),
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False,
            "failed_step": "save",
            "message": f"Failed to save file: {exc}",
        })

    try:
        ingest_detail = _run_ingestion()
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False,
            "failed_step": "ingest",
            "message": f"File saved and backup created, but ingestion failed: {exc}",
            "backup_path": str(backup_path),
        })

    return JSONResponse(content={
        "success": True,
        "filename": payload.filename,
        "content_type": payload.content_type,
        "path": str(target),
        "backup_path": str(backup_path),
        "metadata": metadata,
        "ingest_detail": ingest_detail,
        "message": "Content saved. Previous version was archived.",
    })


# ── Remove content ──────────────────────────────────────────────────────────────

@admin_router.delete("/remove-content")
async def remove_content(
    filename:     str = None,
    content_type: str = None,
):
    """
    Remove a .txt file from Lance, rebuild the FAISS index, and clean up
    its Firestore txt_to_pdf_map entry.

    Pass filename and content_type as query parameters:
        DELETE /admin/remove-content?filename=ia_example.txt&content_type=faq
    """
    # ── Validate ───────────────────────────────────────────────────────────────
    if not filename or not content_type:
        return JSONResponse(status_code=400, content={
            "success": False,
            "message": "Both 'filename' and 'content_type' query parameters are required."
        })

    if content_type not in ("faq", "instruction"):
        return JSONResponse(status_code=400, content={
            "success": False,
            "message": "content_type must be 'faq' or 'instruction'."
        })

    target_dir  = _content_root(content_type)
    try:
        target_file = _resolve_content_path(target_dir, filename)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "success": False,
            "message": str(exc)
        })

    if not target_file.exists() or not target_file.is_file():
        return JSONResponse(status_code=404, content={
            "success": False,
            "message": f"'{filename}' not found in the {content_type} directory."
        })

    # ── Delete file from disk ──────────────────────────────────────────────────
    try:
        archive_path = _archive_content_file(target_file, target_dir, "removed", move=True)
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "message": f"Failed to archive file before removal: {str(e)}"
        })

    # ── Rebuild FAISS index ────────────────────────────────────────────────────
    try:
        ingest_detail = _run_ingestion()
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "message": f"File archived but ingestion failed: {str(e)}"
        })

    # ── Remove txt_to_pdf_map entry from Firestore (non-fatal) ────────────────
    firestore_map_deleted = False
    try:
        from app.firebase_config import get_firestore_client
        db = get_firestore_client()
        if db:
            ref = db.collection("txt_to_pdf_map").document(filename)
            if ref.get().exists:
                ref.delete()
                firestore_map_deleted = True
    except Exception as e:
        print(f"[WARN] Firestore txt_to_pdf_map delete failed: {e}")

    return JSONResponse(content={
        "success":               True,
        "filename":              filename,
        "content_type":          content_type,
        "archive_path":          str(archive_path),
        "firestore_map_deleted": firestore_map_deleted,
        "ingest_detail":         ingest_detail,
        "message":               f"'{filename}' archived successfully.",
    })


# ── Hot-reload index ─────────────────────────────────────────────────────────

@admin_router.post("/reload-index")
async def reload_index():
    """
    Hot-reload the FAISS index into the running process without restarting uvicorn.
    Call this after adding or removing content to make changes live immediately.
    """
    try:
        from app.rag.retriever import get_retriever
        get_retriever(force_reload=True)
        return JSONResponse(content={
            "success":     True,
            "message":     "FAISS index reloaded successfully. New content is now live.",
            "reloaded_at": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "message": f"Hot-reload failed: {str(e)}. Use the Restart Server button as a fallback.",
        })

