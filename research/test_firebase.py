"""
Test Firebase Connection
Run this to verify Firestore and Storage are properly configured
"""

from firebase_config import db, bucket
from firebase_admin import firestore
from datetime import datetime

def test_firestore_connection():
    """Test Firestore write and read operations"""
    print("\n🔵 Testing Firestore connection...")
    
    try:
        # Write test document
        test_ref = db.collection('_test').document('connection_test')
        test_data = {
            'message': 'Hello from Lance!',
            'timestamp': firestore.SERVER_TIMESTAMP,
            'test_date': datetime.utcnow().isoformat()
        }
        test_ref.set(test_data)
        print("   ✅ Firestore write successful")
        
        # Read it back
        doc = test_ref.get()
        if doc.exists:
            data = doc.to_dict()
            print(f"   ✅ Firestore read successful")
            print(f"      Message: {data.get('message')}")
        else:
            print("   ❌ Document not found after write")
            return False
        
        # Clean up test document
        test_ref.delete()
        print("   ✅ Test document deleted (cleanup successful)")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Firestore test failed: {e}")
        return False

def test_storage_connection():
    """Test Storage bucket access"""
    print("\n🟡 Testing Storage connection...")
    
    try:
        # Check bucket accessibility
        bucket_name = bucket.name
        print(f"   ✅ Storage bucket accessible: {bucket_name}")
        
        # List any existing files (just to test read access)
        blobs = list(bucket.list_blobs(max_results=5))
        if blobs:
            print(f"   📁 Found {len(blobs)} existing file(s) in storage")
        else:
            print("   📁 Storage bucket is empty (ready for uploads)")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Storage test failed: {e}")
        return False

def test_firestore_collections():
    """Test creating collections we'll use"""
    print("\n🟢 Testing Firestore collections...")
    
    try:
        # Test pdf_documents collection
        collections = ['pdf_documents', 'recommendations', 'analytics']
        
        for collection_name in collections:
            # Check if collection exists (try to get first doc)
            docs = db.collection(collection_name).limit(1).get()
            print(f"   ✅ Collection '{collection_name}' accessible")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Collections test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("="*60)
    print("🔥 FIREBASE CONNECTION TEST")
    print("="*60)
    
    results = {
        'Firestore': test_firestore_connection(),
        'Storage': test_storage_connection(),
        'Collections': test_firestore_collections()
    }
    
    print("\n" + "="*60)
    print("📊 TEST RESULTS")
    print("="*60)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"   {test_name:20s} {status}")
        if not passed:
            all_passed = False
    
    print("="*60)
    
    if all_passed:
        print("\n🎉 All tests passed! Firebase is ready to use.")
        print("   Next step: Run upload_pdfs.py to upload your PDF files")
    else:
        print("\n❌ Some tests failed. Please check:")
        print("   1. firebase-service-account.json is in the correct location")
        print("   2. Firebase Storage is enabled in console")
        print("   3. Firestore Database is created")
        print("   4. Internet connection is working")
    
    return all_passed

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        exit(1)
