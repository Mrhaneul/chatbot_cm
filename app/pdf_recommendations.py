"""
PDF Recommendation Module
Maps FAISS retrieval results to PDF documents stored in Firestore
"""

from app.firebase_config import db
from typing import List, Dict, Optional
import re

# Mapping of txt file sources to PDF document IDs in Firestore
TXT_TO_PDF_MAP = {
    # Bedford
    "ia_bedford_access.txt": "bedford_bookshelf_access",
    
    # Cengage
    "ia_cengage_access.txt": "cengage_access",
    
    # CliftonStrengths
    "ia_clifton_access.txt": "clifton_access",
    
    # DC Codes
    "ia_dccodes_access.txt": "dccodes_access",
    
    # Macmillan
    "ia_macmillan_access.txt": "macmillan_access",
    
    # McGraw Hill
    "ia_mcgraw_access.txt": "mcgraw_connect_access",
    "ia_mcgraw_navigation.txt": "mcgraw_tools_navigation",
    
    # Pearson
    "ia_pearson_access.txt": "pearson_mylab_access",
    
    # Sage
    "ia_sage_access.txt": "sage_access",
    
    # SimuCase
    "ia_simucase_access.txt": "simucase_access",
    
    # Stukent
    "ia_stukent_access.txt": "stukent_access",
    
    # VitalSource
    "ia_vitalsource_account.txt": "vitalsource_create_account",
    
    # Wiley
    "ia_wiley_access.txt": "wiley_access",
    
    # ZyBooks
    "ia_zybooks_access.txt": "zybooks_access",
    
    # General - Cookies
    "ia_cookies_chrome.txt": "cookies_chrome",
    "ia_cookies_ipad.txt": "cookies_ipad",
    "ia_cookies_safari.txt": "cookies_safari",
    
    # General - Overview
    "ia_overview.txt": "immediate_access_overview",
}

# Platform-specific relevance ranking
PLATFORM_PRIORITY = {
    "cengage": 1,
    "mcgraw": 1,
    "pearson": 1,
    "wiley": 1,
    "macmillan": 1,
    "bedford": 2,
    "sage": 2,
    "simucase": 2,
    "clifton": 2,
    "zybooks": 2,
    "stukent": 2,
    "vitalsource": 2,
    "dccodes": 2,
    "general": 3  # Cookies, troubleshooting
}


def extract_source_filename(retrieval_context: str) -> Optional[str]:
    """
    Extract the source filename from FAISS retrieval context.
    Example: "[SOURCE_0] [FILE:ia_mcgraw_access.txt]" -> "ia_mcgraw_access.txt"
    """
    match = re.search(r'\[FILE:([^\]]+)\]', retrieval_context)
    if match:
        return match.group(1)
    return None


def get_pdf_from_firestore(doc_id: str) -> Optional[Dict]:
    """Fetch a single PDF document from Firestore by doc_id"""
    try:
        doc_ref = db.collection('pdf_documents').document(doc_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            return {
                "doc_id": doc_id,
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "filename": data.get("filename", ""),
                "public_url": data.get("public_url", ""),
                "pages": data.get("pages", 0),
                "platform": data.get("platform", ""),
                "issue_type": data.get("issue_type", ""),
                "tags": data.get("tags", []),
                "priority": data.get("priority", "medium"),
                "file_size_kb": data.get("file_size_kb", 0)
            }
    except Exception as e:
        print(f"❌ Error fetching PDF {doc_id} from Firestore: {e}")
    
    return None


def get_related_pdfs_by_platform(platform: str, limit: int = 3) -> List[Dict]:
    """
    Get related PDFs for a given platform from Firestore.
    Used as fallback or for additional recommendations.
    """
    try:
        docs = db.collection('pdf_documents')\
            .where('platform', '==', platform.lower())\
            .limit(limit)\
            .get()
        
        pdfs = []
        for doc in docs:
            data = doc.to_dict()
            pdfs.append({
                "doc_id": doc.id,
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "filename": data.get("filename", ""),
                "public_url": data.get("public_url", ""),
                "pages": data.get("pages", 0),
                "platform": data.get("platform", ""),
                "issue_type": data.get("issue_type", ""),
                "tags": data.get("tags", []),
                "priority": data.get("priority", "medium")
            })
        
        return pdfs
    except Exception as e:
        print(f"❌ Error fetching related PDFs for {platform}: {e}")
        return []


def determine_relevance_label(pdf_data: Dict, is_primary: bool = False) -> str:
    """
    Determine the relevance label for a PDF recommendation.
    Returns: "Best Match", "Related", or "Relevant"
    """
    if is_primary:
        return "Best Match"
    
    priority = pdf_data.get("priority", "medium")
    if priority == "high":
        return "Related"
    else:
        return "Relevant"


def get_pdf_recommendations(
    retrieval_result: Optional[Dict],
    platform: Optional[str] = None,
    max_recommendations: int = 5
) -> List[Dict]:
    """
    Generate PDF recommendations based on FAISS retrieval results.
    
    Args:
        retrieval_result: The result from FAQRetriever.retrieve()
        platform: Detected platform (e.g., "MCGRAW_HILL", "CENGAGE")
        max_recommendations: Maximum number of PDFs to recommend
    
    Returns:
        List of PDF recommendation dictionaries with metadata
    """
    recommendations = []
    seen_doc_ids = set()
    
    # ===== PRIMARY RECOMMENDATION (from retrieval) =====
    if retrieval_result and retrieval_result.get("context"):
        source_filename = extract_source_filename(retrieval_result["context"])
        
        if source_filename and source_filename in TXT_TO_PDF_MAP:
            doc_id = TXT_TO_PDF_MAP[source_filename]
            pdf_data = get_pdf_from_firestore(doc_id)
            
            if pdf_data:
                pdf_data["relevance"] = "Best Match"
                pdf_data["score"] = retrieval_result.get("score", 0.0)
                recommendations.append(pdf_data)
                seen_doc_ids.add(doc_id)
                
                print(f"✅ Primary recommendation: {pdf_data['title']}")
    
    # ===== SECONDARY RECOMMENDATIONS (platform-specific) =====
    if platform and len(recommendations) < max_recommendations:
        # Normalize platform name
        platform_normalized = platform.lower().replace("_", "")
        if platform_normalized == "mcgrawhill":
            platform_normalized = "mcgraw"
        
        related_pdfs = get_related_pdfs_by_platform(
            platform_normalized,
            limit=max_recommendations - len(recommendations)
        )
        
        for pdf in related_pdfs:
            if pdf["doc_id"] not in seen_doc_ids:
                pdf["relevance"] = determine_relevance_label(pdf, is_primary=False)
                pdf["score"] = 0.0  # No direct score for platform-based recommendations
                recommendations.append(pdf)
                seen_doc_ids.add(pdf["doc_id"])
    
    # ===== GENERAL TROUBLESHOOTING (if cookie/browser issues detected) =====
    if len(recommendations) < max_recommendations:
        # Check if query mentions cookies or browser issues
        if retrieval_result and retrieval_result.get("context"):
            context_lower = retrieval_result["context"].lower()
            
            if any(keyword in context_lower for keyword in ["cookie", "browser", "chrome", "safari"]):
                # Add cookie troubleshooting PDFs
                cookie_pdfs = ["cookies_chrome", "cookies_safari", "cookies_ipad"]
                
                for doc_id in cookie_pdfs:
                    if doc_id not in seen_doc_ids and len(recommendations) < max_recommendations:
                        pdf_data = get_pdf_from_firestore(doc_id)
                        if pdf_data:
                            pdf_data["relevance"] = "Relevant"
                            pdf_data["score"] = 0.0
                            recommendations.append(pdf_data)
                            seen_doc_ids.add(doc_id)
    
    # ===== SORT BY RELEVANCE =====
    relevance_order = {"Best Match": 0, "Related": 1, "Relevant": 2}
    recommendations.sort(key=lambda x: (
        relevance_order.get(x["relevance"], 3),
        -x.get("score", 0.0)
    ))
    
    print(f"📄 Generated {len(recommendations)} PDF recommendations")
    return recommendations[:max_recommendations]


def format_pdf_for_frontend(pdf: Dict) -> Dict:
    """
    Format PDF metadata for frontend consumption.
    Ensures consistent structure for React components.
    """
    return {
        "doc_id": pdf.get("doc_id", ""),
        "title": pdf.get("title", "Untitled Document"),
        "description": pdf.get("description", ""),
        "filename": pdf.get("filename", ""),
        "url": pdf.get("public_url", ""),  # React expects "url" not "public_url"
        "pages": pdf.get("pages", 0),
        "relevance": pdf.get("relevance", "Relevant"),
        "platform": pdf.get("platform", "general"),
        "file_size_kb": pdf.get("file_size_kb", 0),
        "tags": pdf.get("tags", [])
    }


# ===== CONVENIENCE FUNCTION FOR MAIN.PY =====
def get_recommendations_for_chat(
    retrieval_result: Optional[Dict],
    platform: Optional[str],
    query: str
) -> List[Dict]:
    """
    High-level function to get PDF recommendations for a chat interaction.
    This is the main function you'll call from main.py.
    
    Args:
        retrieval_result: FAISS retrieval result from FAQRetriever
        platform: Detected platform (CENGAGE, MCGRAW_HILL, etc.)
        query: Original user query (for additional context)
    
    Returns:
        List of formatted PDF recommendations ready for frontend
    """
    raw_recommendations = get_pdf_recommendations(
        retrieval_result=retrieval_result,
        platform=platform,
        max_recommendations=5
    )
    
    # Format for frontend
    formatted = [format_pdf_for_frontend(pdf) for pdf in raw_recommendations]
    
    return formatted
