"""
PDF Recommendation Module
Maps FAISS retrieval results to PDF documents stored in Firestore
"""

from app.firebase_config import db
from app.platform_registry import load_registry, canonical_platform_key
from typing import List, Dict, Optional
from datetime import datetime
import re

# Mapping of txt file sources to PDF document IDs in Firestore
TXT_TO_PDF_MAP = {
    # Bedford (both legacy key and actual source_file name in chunks)
    "ia_bedford_access.txt": "bedford_bookshelf_access",
    "ia_bedford_bookshelf_access.txt": "bedford_bookshelf_access",

    # Cengage (actual source_file in chunks is ia_cengage_mindtap_access.txt)
    "ia_cengage_access.txt": "cengage_access",
    "ia_cengage_mindtap_access.txt": "cengage_access",

    # CliftonStrengths (actual source_file is ia_cliftonstrengths_assessment_access.txt)
    "ia_clifton_access.txt": "clifton_access",
    "ia_cliftonstrengths_assessment_access.txt": "clifton_access",

    # DC Codes
    "ia_dccodes_access.txt": "dccodes_access",
    "dc_codes_instore_redemption.txt": "dccodes_access",

    # Macmillan (actual source_file is ia_macmillan_achieve_access.txt)
    "ia_macmillan_access.txt": "macmillan_access",
    "ia_macmillan_achieve_access.txt": "macmillan_access",

    # McGraw Hill (chunks currently resolve to macmillan source file)
    "ia_mcgraw_access.txt": "mcgraw_connect_access",
    "ia_mcgraw_navigation.txt": "mcgraw_tools_navigation",
    "ia_mcgraw_hill_connect_access.txt": "mcgraw_connect_access",
    "ia_mcgraw_hill_connect_learning_activities_access.txt": "mcgraw_connect_access",
    "ia_mcgraw_hill_connect_tools_access.txt": "mcgraw_tools_navigation",
    "ia_mcgraw_hill_tools_access.txt": "mcgraw_tools_navigation",

    # Pearson (actual source_file is ia_pearson_mylab_mastering_access.txt)
    "ia_pearson_access.txt": "pearson_mylab_access",
    "ia_pearson_mylab_mastering_access.txt": "pearson_mylab_access",

    # Sage (actual source_file is ia_sage_vantage_access.txt)
    "ia_sage_access.txt": "sage_access",
    "ia_sage_vantage_access.txt": "sage_access",

    # SimuCase
    "ia_simucase_access.txt": "simucase_access",

    # InQuizitive
    "ia_inquizitive_access.txt": "inquizitive_access",

    # Stukent
    "ia_stukent_access.txt": "stukent_access",

    # VitalSource (actual source_files)
    "ia_vitalsource_account.txt": "vitalsource_create_account",
    "ia_vitalsource_bookshelf_account_creation.txt": "vitalsource_create_account",
    "ia_vitalsource_launch_courseware_access.txt": "vitalsource_create_account",

    # Wiley (actual source_file is ia_wileyplus_access.txt)
    "ia_wiley_access.txt": "wiley_access",
    "ia_wileyplus_access.txt": "wiley_access",

    # ZyBooks
    "ia_zybooks_access.txt": "zybooks_access",

    # General - Cookies (actual source_file names)
    "ia_cookies_chrome.txt": "cookies_chrome",
    "ia_browser_chrome_cookies_popups.txt": "cookies_chrome",
    "ia_cookies_ipad.txt": "cookies_ipad",
    "ia_browser_ipad_safari_cookies_popups.txt": "cookies_ipad",
    "ia_cookies_safari.txt": "cookies_safari",
    "ia_browser_safari_cookies_popups.txt": "cookies_safari",

    # General - Overview / eTextbook
    "ia_overview.txt": "immediate_access_overview",
    "ia_etextbook_general_access.txt": "immediate_access_overview",
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
    "inquizitive": 2,
    "clifton": 2,
    "zybooks": 2,
    "stukent": 2,
    "vitalsource": 2,
    "dccodes": 2,
    "general": 3  # Cookies, troubleshooting
}

PLATFORM_NORMALIZATION = {
    "mcgraw_hill": "mcgraw",
    "mcgrawhill": "mcgraw",
    "inquizitive": "inquizitive",
    "inquisitive": "inquizitive",
}

# Merge dynamic registry entries (added by add_instruction.py)
_registry = load_registry()
for _filename, _doc_id in _registry.get("txt_to_pdf_map", {}).items():
    if isinstance(_filename, str) and isinstance(_doc_id, str) and _filename and _doc_id:
        TXT_TO_PDF_MAP[_filename] = _doc_id

for _src, _dst in _registry.get("platform_normalization", {}).items():
    if isinstance(_src, str) and isinstance(_dst, str) and _src and _dst:
        PLATFORM_NORMALIZATION[canonical_platform_key(_src)] = canonical_platform_key(_dst)

for _platform, _priority in _registry.get("platform_priority", {}).items():
    try:
        PLATFORM_PRIORITY[canonical_platform_key(_platform)] = int(_priority)
    except Exception:
        pass


def extract_source_filename(retrieval_context: str) -> Optional[str]:
    """
    Extract the source filename from FAISS retrieval context.

    Supports two formats:
    - New:    [META:{"source_file": "ia_zybooks_access.txt", ...}]
    - Legacy: [SOURCE_0] [FILE:ia_mcgraw_access.txt]
    """
    import json as _json

    # New format: [META:{...}] with a "source_file" key
    meta_match = re.match(r'^\s*\[META:(\{.*?\})\]', retrieval_context)
    if meta_match:
        try:
            meta = _json.loads(meta_match.group(1))
            source_file = meta.get("source_file")
            if source_file:
                return source_file
        except Exception:
            pass

    # Legacy format: [FILE:filename.txt]
    legacy_match = re.search(r'\[FILE:([^\]]+)\]', retrieval_context)
    if legacy_match:
        return legacy_match.group(1)

    return None


def get_retrieval_source_filename(retrieval_result: Optional[Dict]) -> Optional[str]:
    """
    Return the source .txt path for a retrieval result.

    Prefer structured metadata because parent-source expansion can replace the
    raw chunk context and remove the [META:{...}] header. Fall back to legacy
    context parsing for older retrieval results and flat-file deployments.
    """
    if not retrieval_result:
        return None

    metadata = retrieval_result.get("metadata")
    if isinstance(metadata, dict):
        source_file = metadata.get("source_file")
        if isinstance(source_file, str) and source_file.strip():
            return source_file.strip()

    context = retrieval_result.get("context")
    if isinstance(context, str) and context:
        return extract_source_filename(context)

    return None


def get_pdf_from_firestore(doc_id: str) -> Optional[Dict]:
    """Fetch a single PDF document from Firestore by doc_id"""
    try:
        doc_ref = db.collection('pdf_documents').document(doc_id)
        doc = doc_ref.get(timeout=5.0)
        
        if doc.exists:
            data = doc.to_dict()
            return {
                "doc_id": doc_id,
                "title": data.get("title") or data.get("display_name", ""),
                "description": data.get("description", ""),
                "filename": data.get("filename", ""),
                "public_url": data.get("public_url") or data.get("pdf_url", ""),
                "pages": data.get("pages", 0),
                "platform": data.get("platform", ""),
                "issue_type": data.get("issue_type", ""),
                "tags": data.get("tags", []),
                "priority": data.get("priority", "medium"),
                "file_size_kb": data.get("file_size_kb", 0),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
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
        normalized_platform = platform.lower()
        docs = db.collection('pdf_documents')\
            .where('platform', '==', normalized_platform)\
            .limit(limit)\
            .get(timeout=5.0)

        # Fallback for deployments storing instruction metadata in a different collection.
        if not docs:
            docs = db.collection('instructions')\
                .where('platform', '==', normalized_platform)\
                .limit(limit)\
                .get(timeout=5.0)
        
        pdfs = []
        for doc in docs:
            data = doc.to_dict()
            pdfs.append({
                "doc_id": doc.id,
                "title": data.get("title") or data.get("display_name", ""),
                "description": data.get("description", ""),
                "filename": data.get("filename", ""),
                "public_url": data.get("public_url") or data.get("pdf_url", ""),
                "pages": data.get("pages", 0),
                "platform": data.get("platform", ""),
                "issue_type": data.get("issue_type", ""),
                "tags": data.get("tags", []),
                "priority": data.get("priority", "medium"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
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
        retrieval_result: The result from retriever.retrieve()
        platform: Detected platform (e.g., "MCGRAW_HILL", "CENGAGE")
        max_recommendations: Maximum number of PDFs to recommend
    
    Returns:
        List of PDF recommendation dictionaries with metadata
    """
    recommendations = []
    seen_doc_ids = set()

    # ===== PRIMARY RECOMMENDATIONS (from retrieval) =====
    if retrieval_result and retrieval_result.get("context"):
        source_filename = get_retrieval_source_filename(retrieval_result)

        if source_filename:
            retrieval_score = retrieval_result.get("score", 0.0)
            found_in_firestore = False

            # 1. Dynamic Firestore mapping (set by admin UI uploads).
            #    Supports multiple PDFs per .txt file.
            try:
                map_doc = db.collection("txt_to_pdf_map").document(source_filename).get(timeout=5.0)
                if map_doc.exists:
                    found_in_firestore = True
                    pdf_doc_ids = map_doc.to_dict().get("pdf_doc_ids", [])
                    for i, doc_id in enumerate(pdf_doc_ids):
                        if not doc_id or doc_id in seen_doc_ids:
                            continue
                        if len(recommendations) >= max_recommendations:
                            break
                        pdf_data = get_pdf_from_firestore(doc_id)
                        if pdf_data:
                            pdf_data["relevance"] = "Best Match" if i == 0 else "Related"
                            pdf_data["score"] = retrieval_score if i == 0 else 0.0
                            recommendations.append(pdf_data)
                            seen_doc_ids.add(doc_id)
                            print(f"✅ Primary recommendation (Firestore map): {pdf_data['title']}")
            except Exception as e:
                print(f"[WARN] txt_to_pdf_map Firestore lookup failed: {e}")

            # 2. Fall back to hardcoded TXT_TO_PDF_MAP for legacy entries that
            #    predate the admin UI (only used when Firestore has no mapping).
            if not found_in_firestore and source_filename in TXT_TO_PDF_MAP:
                doc_id = TXT_TO_PDF_MAP[source_filename]
                if doc_id not in seen_doc_ids:
                    pdf_data = get_pdf_from_firestore(doc_id)
                    if pdf_data:
                        pdf_data["relevance"] = "Best Match"
                        pdf_data["score"] = retrieval_score
                        recommendations.append(pdf_data)
                        seen_doc_ids.add(doc_id)
                        print(f"✅ Primary recommendation (hardcoded map): {pdf_data['title']}")
    
    # ===== SECONDARY RECOMMENDATIONS (platform-specific) =====
    if platform and len(recommendations) < max_recommendations:
        # Normalize platform name
        platform_normalized = platform.lower().strip()
        platform_normalized = PLATFORM_NORMALIZATION.get(
            platform_normalized,
            platform_normalized.replace("_", "")
        )
        platform_normalized = PLATFORM_NORMALIZATION.get(platform_normalized, platform_normalized)
        
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

            # Browser cache clearing ("0 Courses, 0 Materials" / no content available).
            # Chrome guide is already the TXT_TO_PDF_MAP primary; add Safari and iPad Chrome.
            if any(keyword in context_lower for keyword in ["cache", "clear browser", "clear history", "0 courses", "no content"]):
                cache_pdfs = ["safari_clear_cache_guide", "ipad_chrome_clear_cache_guide", "chrome_clear_cache_guide"]
                for doc_id in cache_pdfs:
                    if doc_id not in seen_doc_ids and len(recommendations) < max_recommendations:
                        pdf_data = get_pdf_from_firestore(doc_id)
                        if pdf_data:
                            pdf_data["relevance"] = "Relevant"
                            pdf_data["score"] = 0.0
                            recommendations.append(pdf_data)
                            seen_doc_ids.add(doc_id)

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
    def normalize_timestamp(value):
        if value is None:
            return None
        if hasattr(value, "to_datetime"):
            value = value.to_datetime()
        if isinstance(value, datetime):
            return value.isoformat()
        try:
            return value.isoformat()
        except Exception:
            return None

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
        "tags": pdf.get("tags", []),
        "created_at": normalize_timestamp(pdf.get("created_at")),
        "updated_at": normalize_timestamp(pdf.get("updated_at")),
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
        retrieval_result: FAISS retrieval result from retriever
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
