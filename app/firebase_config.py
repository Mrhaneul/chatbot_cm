"""
Firebase Configuration
Initializes Firebase Admin SDK for Firestore and Storage.

Environment overrides:
    FIREBASE_SERVICE_ACCOUNT_PATH
    FIREBASE_STORAGE_BUCKET
"""

import os
from pathlib import Path

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore, storage

load_dotenv()

# Global variables
db = None
bucket = None

DEFAULT_SERVICE_ACCOUNT_PATH = Path(__file__).resolve().parent / "firebase-service-account.json"


def _get_service_account_path() -> Path:
    configured = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = Path(__file__).resolve().parent.parent / candidate
        return candidate
    return DEFAULT_SERVICE_ACCOUNT_PATH


def _get_storage_bucket_name() -> str:
    return os.environ.get("FIREBASE_STORAGE_BUCKET", "lance-cbu.firebasestorage.app")


def initialize_firebase():
    """Initialize Firebase Admin SDK using app/firebase-service-account.json by default."""
    global db, bucket

    cred_path = _get_service_account_path()
    storage_bucket = _get_storage_bucket_name()

    if not cred_path.exists():
        raise FileNotFoundError(
            " Firebase service account key not found!\n"
            f"Expected location: {cred_path}\n"
            "Set FIREBASE_SERVICE_ACCOUNT_PATH to override the default path.\n"
            "Download from: Firebase Console -> Project Settings -> Service Accounts -> Generate new private key"
        )

    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(str(cred_path))
            firebase_admin.initialize_app(cred, {
                "storageBucket": storage_bucket
            })

        db = firestore.client()
        bucket = storage.bucket()

        print("Firebase initialized successfully")
        print("   Project: lance-cbu")
        print(f"   Storage bucket: {storage_bucket}")

    except Exception as e:
        print(f"Firebase initialization failed: {e}")
        raise


def get_firestore_client():
    """Get Firestore database client."""
    if db is None:
        initialize_firebase()
    return db


def get_storage_bucket():
    """Get Firebase Storage bucket."""
    if bucket is None:
        initialize_firebase()
    return bucket


try:
    initialize_firebase()
except Exception as e:
    print(f"  Warning: Firebase not initialized on import: {e}")
    print("    Call initialize_firebase() manually when needed")
