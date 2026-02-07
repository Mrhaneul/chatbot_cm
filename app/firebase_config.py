"""
Firebase Configuration
Initializes Firebase Admin SDK for Firestore and Storage
"""

import firebase_admin
from firebase_admin import credentials, firestore, storage
import os

# Global variables
db = None
bucket = None

def initialize_firebase():
    """Initialize Firebase Admin SDK with service account"""
    global db, bucket
    
    # Path to service account key (same directory as this file)
    cred_path = os.path.join(os.path.dirname(__file__), 'firebase-service-account.json')
    
    if not os.path.exists(cred_path):
        raise FileNotFoundError(
            f"❌ Firebase service account key not found!\n"
            f"Expected location: {cred_path}\n"
            f"Download from: Firebase Console → Project Settings → Service Accounts → Generate new private key"
        )
    
    try:
        cred = credentials.Certificate(cred_path)
        
        # Initialize Firebase with storage bucket
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'lance-cbu.firebasestorage.app'
        })
        
        # Get Firestore and Storage clients
        db = firestore.client()
        bucket = storage.bucket()
        
        print("✅ Firebase initialized successfully")
        print(f"   📦 Project: lance-cbu")
        print(f"   💾 Storage bucket: lance-cbu.firebasestorage.app")
        
    except Exception as e:
        print(f"❌ Firebase initialization failed: {e}")
        raise

def get_firestore_client():
    """Get Firestore database client"""
    if db is None:
        initialize_firebase()
    return db

def get_storage_bucket():
    """Get Firebase Storage bucket"""
    if bucket is None:
        initialize_firebase()
    return bucket

# Initialize on module import
try:
    initialize_firebase()
except Exception as e:
    print(f"⚠️  Warning: Firebase not initialized on import: {e}")
    print("    Call initialize_firebase() manually when needed")
