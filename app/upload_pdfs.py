"""
Upload PDFs to Firebase Storage and Metadata to Firestore
Uploads all Lance CBU Immediate Access platform PDFs
"""

from firebase_config import bucket, db
from firebase_admin import firestore
import os
from datetime import datetime
from pathlib import Path

# Base path to PDFs directory
PDF_BASE_PATH = Path(__file__).parent.parent / "pdfs"

# Comprehensive PDF metadata for all platforms
PDF_METADATA = [
    # Bedford
    {
        "doc_id": "bedford_bookshelf_access",
        "platform": "bedford",
        "issue_type": "access",
        "title": "Bedford Bookshelf Access",
        "description": "Complete guide to accessing Bedford digital books through Blackboard",
        "filename": "bedford_bookshelf_access.pdf",
        "local_path": "bedford/bedford_bookshelf_access.pdf",
        "storage_path": "pdfs/bedford/bedford_bookshelf_access.pdf",
        "pages": 3,
        "txt_source": "ia_bedford_access.txt",
        "tags": ["bedford", "bookshelf", "access", "blackboard"],
        "priority": "high"
    },
    
    # Cengage
    {
        "doc_id": "cengage_access",
        "platform": "cengage",
        "issue_type": "access",
        "title": "Cengage Access Guide",
        "description": "Step-by-step instructions for accessing Cengage courseware and eTextbooks",
        "filename": "cengage_access.pdf",
        "local_path": "cengage/cengage_access.pdf",
        "storage_path": "pdfs/cengage/cengage_access.pdf",
        "pages": 3,
        "txt_source": "ia_cengage_access.txt",
        "tags": ["cengage", "access", "blackboard", "etextbook"],
        "priority": "high"
    },
    
    # CliftonStrengths
    {
        "doc_id": "clifton_access",
        "platform": "clifton",
        "issue_type": "access",
        "title": "CliftonStrengths Access",
        "description": "Guide to accessing CliftonStrengths assessment through Blackboard",
        "filename": "clifton_access.pdf",
        "local_path": "clifton/clifton_access.pdf",
        "storage_path": "pdfs/clifton/clifton_access.pdf",
        "pages": 2,
        "txt_source": "ia_clifton_access.txt",
        "tags": ["clifton", "strengths", "assessment", "access"],
        "priority": "medium"
    },
    
    # DC Codes
    {
        "doc_id": "dccodes_access",
        "platform": "dccodes",
        "issue_type": "access",
        "title": "DC Codes Access",
        "description": "Instructions for accessing DC Codes platform materials",
        "filename": "dc_codes_access.pdf",
        "local_path": "dccodes/dc_codes_access.pdf",
        "storage_path": "pdfs/dccodes/dc_codes_access.pdf",
        "pages": 3,
        "txt_source": "ia_dccodes_access.txt",
        "tags": ["dccodes", "access", "blackboard"],
        "priority": "medium"
    },
    
    # Macmillan
    {
        "doc_id": "macmillan_access",
        "platform": "macmillan",
        "issue_type": "access",
        "title": "Macmillan Learning Access",
        "description": "Guide to accessing Macmillan Learning courseware and content",
        "filename": "macmillan_access.pdf",
        "local_path": "macmillan/macmillan_access.pdf",
        "storage_path": "pdfs/macmillan/macmillan_access.pdf",
        "pages": 2,
        "txt_source": "ia_macmillan_access.txt",
        "tags": ["macmillan", "access", "learning", "blackboard"],
        "priority": "high"
    },
    
    # McGraw Hill
    {
        "doc_id": "mcgraw_connect_access",
        "platform": "mcgraw",
        "issue_type": "access",
        "title": "McGraw Hill Connect Access",
        "description": "Complete guide to accessing McGraw Hill Connect through Blackboard",
        "filename": "mcgraw_hill_connect_access.pdf",
        "local_path": "mcgraw/mcgraw_hill_connect_access.pdf",
        "storage_path": "pdfs/mcgraw/mcgraw_hill_connect_access.pdf",
        "pages": 4,
        "txt_source": "ia_mcgraw_access.txt",
        "tags": ["mcgraw", "connect", "access", "blackboard", "lti"],
        "priority": "high"
    },
    {
        "doc_id": "mcgraw_tools_navigation",
        "platform": "mcgraw",
        "issue_type": "navigation",
        "title": "McGraw Hill Tools Navigation",
        "description": "How to access materials through the Blackboard Tools menu",
        "filename": "mcgraw_hill_connect_access_tools.pdf",
        "local_path": "mcgraw/mcgraw_hill_connect_access_tools.pdf",
        "storage_path": "pdfs/mcgraw/mcgraw_hill_connect_access_tools.pdf",
        "pages": 3,
        "txt_source": "ia_mcgraw_navigation.txt",
        "tags": ["mcgraw", "tools", "navigation", "blackboard"],
        "priority": "medium"
    },
    
    # Pearson
    {
        "doc_id": "pearson_mylab_access",
        "platform": "pearson",
        "issue_type": "access",
        "title": "Pearson MyLab Access",
        "description": "Step-by-step guide for accessing Pearson MyLab and Mastering platforms",
        "filename": "pearson_mylab_access.pdf",
        "local_path": "pearson/pearson_mylab_access.pdf",
        "storage_path": "pdfs/pearson/pearson_mylab_access.pdf",
        "pages": 4,
        "txt_source": "ia_pearson_access.txt",
        "tags": ["pearson", "mylab", "mastering", "access", "blackboard"],
        "priority": "high"
    },
    
    # Sage
    {
        "doc_id": "sage_access",
        "platform": "sage",
        "issue_type": "access",
        "title": "Sage Vantage Access",
        "description": "Instructions for accessing Sage Vantage courseware",
        "filename": "sage_access.pdf",
        "local_path": "sage/sage_access.pdf",
        "storage_path": "pdfs/sage/sage_access.pdf",
        "pages": 2,
        "txt_source": "ia_sage_access.txt",
        "tags": ["sage", "vantage", "access", "blackboard"],
        "priority": "medium"
    },
    
    # SimuCase
    {
        "doc_id": "simucase_access",
        "platform": "simucase",
        "issue_type": "access",
        "title": "SimuCase Access",
        "description": "Guide to accessing SimuCase simulation platform",
        "filename": "simucase_access.pdf",
        "local_path": "simucase/simucase_access.pdf",
        "storage_path": "pdfs/simucase/simucase_access.pdf",
        "pages": 3,
        "txt_source": "ia_simucase_access.txt",
        "tags": ["simucase", "simulation", "access", "blackboard"],
        "priority": "medium"
    },
    
    # Stukent
    {
        "doc_id": "stukent_access",
        "platform": "stukent",
        "issue_type": "access",
        "title": "Stukent Access",
        "description": "Instructions for accessing Stukent courseware and simulations",
        "filename": "stukent_access.pdf",
        "local_path": "stukent/stukent_access.pdf",
        "storage_path": "pdfs/stukent/stukent_access.pdf",
        "pages": 3,
        "txt_source": "ia_stukent_access.txt",
        "tags": ["stukent", "access", "simulations", "blackboard"],
        "priority": "medium"
    },
    
    # VitalSource
    {
        "doc_id": "vitalsource_create_account",
        "platform": "vitalsource",
        "issue_type": "account",
        "title": "VitalSource Bookshelf Account Creation",
        "description": "Guide to creating a VitalSource Bookshelf account",
        "filename": "vitalsource_bookshelf_create_account.pdf",
        "local_path": "vitalsource/vitalsource_bookshelf_create_account.pdf",
        "storage_path": "pdfs/vitalsource/vitalsource_bookshelf_create_account.pdf",
        "pages": 3,
        "txt_source": "ia_vitalsource_account.txt",
        "tags": ["vitalsource", "bookshelf", "account", "ebook"],
        "priority": "medium"
    },
    
    # Wiley
    {
        "doc_id": "wiley_access",
        "platform": "wiley",
        "issue_type": "access",
        "title": "WileyPLUS Access",
        "description": "Complete guide to accessing WileyPLUS through Blackboard",
        "filename": "wiley_access.pdf",
        "local_path": "wiley/wiley_access.pdf",
        "storage_path": "pdfs/wiley/wiley_access.pdf",
        "pages": 3,
        "txt_source": "ia_wiley_access.txt",
        "tags": ["wiley", "wileyplus", "access", "blackboard"],
        "priority": "high"
    },
    
    # ZyBooks
    {
        "doc_id": "zybooks_access",
        "platform": "zybooks",
        "issue_type": "access",
        "title": "ZyBooks Access",
        "description": "Instructions for accessing ZyBooks interactive textbooks",
        "filename": "zybooks_access.pdf",
        "local_path": "zybooks/zybooks_access.pdf",
        "storage_path": "pdfs/zybooks/zybooks_access.pdf",
        "pages": 2,
        "txt_source": "ia_zybooks_access.txt",
        "tags": ["zybooks", "access", "interactive", "blackboard"],
        "priority": "medium"
    },
    
    # General - Cookie Troubleshooting
    {
        "doc_id": "cookies_chrome",
        "platform": "general",
        "issue_type": "troubleshooting",
        "title": "Enable Cookies - Chrome",
        "description": "How to enable cookies in Google Chrome browser",
        "filename": "cookies_enable_chrome.pdf",
        "local_path": "general/cookies_enable_chrome.pdf",
        "storage_path": "pdfs/general/cookies_enable_chrome.pdf",
        "pages": 3,
        "txt_source": "ia_cookies_chrome.txt",
        "tags": ["cookies", "chrome", "browser", "troubleshooting"],
        "priority": "high"
    },
    {
        "doc_id": "cookies_ipad",
        "platform": "general",
        "issue_type": "troubleshooting",
        "title": "Enable Cookies - iPad",
        "description": "How to enable cookies on iPad Safari browser",
        "filename": "cookies_enable_ipad.pdf",
        "local_path": "general/cookies_enable_ipad.pdf",
        "storage_path": "pdfs/general/cookies_enable_ipad.pdf",
        "pages": 2,
        "txt_source": "ia_cookies_ipad.txt",
        "tags": ["cookies", "ipad", "safari", "troubleshooting"],
        "priority": "medium"
    },
    {
        "doc_id": "cookies_safari",
        "platform": "general",
        "issue_type": "troubleshooting",
        "title": "Enable Cookies - Safari",
        "description": "How to enable cookies in Safari browser",
        "filename": "cookies_enable_safari.pdf",
        "local_path": "general/cookies_enable_safari.pdf",
        "storage_path": "pdfs/general/cookies_enable_safari.pdf",
        "pages": 2,
        "txt_source": "ia_cookies_safari.txt",
        "tags": ["cookies", "safari", "browser", "troubleshooting"],
        "priority": "medium"
    },
    
    # General - Immediate Access Overview
    {
        "doc_id": "immediate_access_overview",
        "platform": "general",
        "issue_type": "info",
        "title": "Immediate Access Program Overview",
        "description": "What is Immediate Access and how does it work at CBU",
        "filename": "immediate_access.pdf",
        "local_path": "general/immediate_access.pdf",
        "storage_path": "pdfs/general/immediate_access.pdf",
        "pages": 2,
        "txt_source": "ia_overview.txt",
        "tags": ["immediate-access", "overview", "program", "info"],
        "priority": "high"
    }
]

def upload_pdf_to_storage(local_path, storage_path):
    """Upload a single PDF to Firebase Storage"""
    full_local_path = PDF_BASE_PATH / local_path
    
    if not full_local_path.exists():
        raise FileNotFoundError(f"PDF not found: {full_local_path}")
    
    # Upload to Firebase Storage
    blob = bucket.blob(storage_path)
    blob.upload_from_filename(str(full_local_path))
    
    # Make publicly accessible
    blob.make_public()
    
    return blob.public_url

def add_pdf_metadata_to_firestore(pdf_data):
    """Add PDF metadata to Firestore"""
    doc_ref = db.collection('pdf_documents').document(pdf_data['doc_id'])
    doc_ref.set(pdf_data)

def upload_all_pdfs(dry_run=False):
    """Upload all PDFs and their metadata"""
    print("="*70)
    print("📤 LANCE CBU - PDF UPLOAD TO FIREBASE")
    print("="*70)
    print(f"   Base path: {PDF_BASE_PATH}")
    print(f"   Total PDFs: {len(PDF_METADATA)}")
    print(f"   Dry run: {dry_run}")
    print("="*70)
    
    success_count = 0
    failed_count = 0
    skipped_count = 0
    
    for idx, pdf_info in enumerate(PDF_METADATA, 1):
        print(f"\n[{idx}/{len(PDF_METADATA)}] {pdf_info['title']}")
        print(f"    Platform: {pdf_info['platform']} | File: {pdf_info['filename']}")
        
        try:
            local_path = PDF_BASE_PATH / pdf_info['local_path']
            
            # Check if file exists
            if not local_path.exists():
                print(f"    ⚠️  SKIPPED - File not found: {local_path}")
                skipped_count += 1
                continue
            
            # Get file size
            file_size_kb = local_path.stat().st_size / 1024
            
            if dry_run:
                print(f"    [DRY RUN] Would upload: {file_size_kb:.1f} KB")
                continue
            
            # Upload to Storage
            print(f"    📤 Uploading to Storage... ({file_size_kb:.1f} KB)")
            public_url = upload_pdf_to_storage(pdf_info['local_path'], pdf_info['storage_path'])
            
            # Prepare Firestore metadata
            firestore_data = {
                **pdf_info,
                'public_url': public_url,
                'file_size_kb': round(file_size_kb, 2),
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
            
            # Remove local_path (not needed in Firestore)
            firestore_data.pop('local_path', None)
            
            # Add to Firestore
            print(f"    💾 Adding metadata to Firestore...")
            add_pdf_metadata_to_firestore(firestore_data)
            
            print(f"    ✅ SUCCESS")
            success_count += 1
            
        except Exception as e:
            print(f"    ❌ FAILED: {e}")
            failed_count += 1
    
    # Summary
    print("\n" + "="*70)
    print("📊 UPLOAD SUMMARY")
    print("="*70)
    print(f"   ✅ Successful: {success_count}")
    print(f"   ❌ Failed: {failed_count}")
    print(f"   ⚠️  Skipped: {skipped_count}")
    print(f"   📦 Total: {len(PDF_METADATA)}")
    print("="*70)
    
    if success_count > 0:
        print("\n🎉 PDFs uploaded successfully!")
        print("   View in Firebase Console: https://console.firebase.google.com/project/lance-cbu/storage")
        print("   Next: Integrate PDF recommendations in your chatbot backend")
    
    return success_count, failed_count, skipped_count

def main():
    """Main execution"""
    import sys
    
    # Check for dry run flag
    dry_run = '--dry-run' in sys.argv
    
    if dry_run:
        print("\n⚠️  DRY RUN MODE - No files will be uploaded\n")
    
    try:
        upload_all_pdfs(dry_run=dry_run)
    except KeyboardInterrupt:
        print("\n\n⚠️  Upload cancelled by user")
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
