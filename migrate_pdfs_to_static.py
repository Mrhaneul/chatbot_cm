from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = PROJECT_ROOT / "app" / "firebase-service-account.json"

BASE_URL = os.getenv("LANCE_BASE_URL", "http://localhost:8000").rstrip("/")

REQUIRED_UPDATES = {
    "bedford_bookshelf_access": "Accessing Bedford BookShelf_Canvas.pdf",
    "cengage_access": "Accessing Cengage MindTap-CNowV2 Courseware_Canvas.pdf",
    "clifton_access": "Accessing CliftonStrengths_Canvas.pdf",
    "clear_cache_chrome_firefox": "Chrome_Clear Browser Cookies, Cache, and History.pdf",
    "clear_cache_ipad": "iPad_Clear Browser Cookies Cache and History.pdf",
    "clear_cache_safari": "Safari_Clear Browser Cookies, Cache, and History.pdf",
    "cookies_chrome": "Chrome_Clear Browser Cookies, Cache, and History.pdf",
    "cookies_ipad": "iPad_Clear Browser Cookies Cache and History.pdf",
    "cookies_safari": "Safari_Clear Browser Cookies, Cache, and History.pdf",
    "dccodes_access": "DC Codes Access_Canvas.pdf",
    "immediate_access_overview": "Accessing Immediate Access eTextbooks_Canvas.pdf",
    "macmillan_access": "Accessing MacMillan Achieve_Canvas.pdf",
    "mcgraw_connect_access": "Accessing McGrawHill-Connect_Canvas.pdf",
    "simucase_access": "Accessing SimuCase Courseware_Canvas.pdf",
    "stukent_access": "Accessing Stukent Courseware_Canvas.pdf",
    "vitalsource_create_account": "How To Create a VitalSource Bookshelf Account.pdf",
}

OPTIONAL_UPDATES = {
    "pearson_mylab_access": "Accessing Pearson MyLab_Canvas.pdf",
    "wiley_access": "Accessing WileyPLUS Courseware_Canvas.pdf",
    "zybooks_access": "Accessing ZyBooks_Canvas.pdf",
    "sage_access": "Accessing Sage Vantage_Canvas.pdf",
}

NEW_DOCS = {
    "inquizitive_access": {
        "title": "Accessing Little Seagull InQuizitive (Canvas)",
        "description": (
            "Step-by-step guide for accessing InQuizitive (Norton) courseware "
            "through Canvas Immediate Access."
        ),
        "filename": "Accessing Little Seagull InQuizitive_Canvas.pdf",
        "platform": "INQUIZITIVE",
        "tags": ["inquizitive", "norton", "little seagull", "canvas"],
        "relevance": "primary",
    },
    "strengths_leadership_access": {
        "title": "Accessing StrengthsBased Leadership (Canvas)",
        "description": (
            "Guide for accessing StrengthsBased Leadership through Canvas "
            "Immediate Access."
        ),
        "filename": "Accessing StrengthsBased-Leadership_Canvas.pdf",
        "platform": "CLIFTON",
        "tags": ["clifton", "cliftonstrengths", "strengths", "leadership", "canvas"],
        "relevance": "secondary",
    },
    "jones_bartlett_access": {
        "title": "Accessing Jones & Bartlett Navigate (Canvas)",
        "description": (
            "Step-by-step guide for accessing Jones & Bartlett Navigate "
            "courseware through Canvas Immediate Access."
        ),
        "filename": "Accessing Jones & Bartlett Navigate_Canvas.pdf",
        "platform": "JONES_BARTLETT",
        "tags": ["jones bartlett", "navigate", "jones and bartlett", "canvas"],
        "relevance": "primary",
    },
    "elsevier_evolve_access": {
        "title": "Accessing Elsevier Evolve (Canvas)",
        "description": (
            "Step-by-step guide for accessing Elsevier Evolve courseware "
            "through Canvas Immediate Access."
        ),
        "filename": "Accessing Elsevier Evolve_Canvas.pdf",
        "platform": "ELSEVIER",
        "tags": ["elsevier", "evolve", "canvas"],
        "relevance": "primary",
    },
    "immediate_access_opt_out": {
        "title": "How to Opt Out of Immediate Access (Canvas)",
        "description": (
            "Instructions for opting out of the Immediate Access program "
            "through Canvas."
        ),
        "filename": "How to Opt Out of Immediate Access_Canvas.pdf",
        "platform": "GENERAL",
        "tags": ["opt out", "immediate access", "refund", "canvas"],
        "relevance": "primary",
    },
}


def static_url(filename: str) -> str:
    return f"{BASE_URL}/static/pdfs/{filename}"


def credentials_path() -> Path:
    configured = (
        os.getenv("FIREBASE_CREDENTIALS_PATH")
        or os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        or ""
    ).strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DEFAULT_CREDENTIALS


def firestore_client():
    cred_path = credentials_path()
    if not cred_path.exists():
        raise FileNotFoundError(f"Firebase credentials not found: {cred_path}")
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(cred_path))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def update_doc(db, doc_id: str, filename: str, *, optional: bool = False) -> None:
    ref = db.collection("pdf_documents").document(doc_id)
    snap = ref.get()
    if not snap.exists:
        level = "optional" if optional else "required"
        print(f"SKIP missing {level} doc: {doc_id}")
        return
    ref.update({
        "filename": filename,
        "url": static_url(filename),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"UPDATED {doc_id} -> {filename}")


def delete_doc(db, doc_id: str) -> None:
    ref = db.collection("pdf_documents").document(doc_id)
    if not ref.get().exists:
        print(f"SKIP missing delete doc: {doc_id}")
        return
    ref.delete()
    print(f"DELETED {doc_id}")


def create_doc_if_missing(db, doc_id: str, data: dict, now: str) -> None:
    ref = db.collection("pdf_documents").document(doc_id)
    if ref.get().exists:
        print(f"SKIP existing doc: {doc_id}")
        return
    payload = {
        **data,
        "doc_id": doc_id,
        "pages": 0,
        "file_size_kb": 0,
        "created_at": now,
        "updated_at": now,
        "url": static_url(data["filename"]),
    }
    ref.set(payload)
    print(f"CREATED {doc_id}")


def main() -> None:
    db = firestore_client()
    now = datetime.now(timezone.utc).isoformat()
    print(f"Using BASE_URL={BASE_URL}")

    for doc_id, filename in REQUIRED_UPDATES.items():
        update_doc(db, doc_id, filename)

    for doc_id, filename in OPTIONAL_UPDATES.items():
        update_doc(db, doc_id, filename, optional=True)

    delete_doc(db, "mcgraw_tools_navigation")

    for doc_id, data in NEW_DOCS.items():
        create_doc_if_missing(db, doc_id, data, now)


if __name__ == "__main__":
    main()
