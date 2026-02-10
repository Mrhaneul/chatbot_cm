"""
INTEGRATION GUIDE: Adding PDF Recommendations to main.py

This file contains the changes needed to integrate PDF recommendations into your existing chatbot.
"""

# ==============================================================================
# STEP 1: Update your app/schemas/chat.py
# ==============================================================================

"""
Add this new field to your ChatResponse class:

from typing import List, Dict

class ChatResponse(BaseModel):
    reply: str
    source: str
    article_link: Optional[str] = None
    confidence: float
    retrieval_time_ms: float
    llm_time_ms: float
    total_time_ms: float
    recommended_pdfs: List[Dict] = []  # ← ADD THIS LINE
"""

# ==============================================================================
# STEP 2: Add import at the top of main.py
# ==============================================================================

"""
Add this import after your existing imports:

from app.pdf_recommendations import get_recommendations_for_chat
"""

# ==============================================================================
# STEP 3: Modify the /chat endpoint - Add PDF recommendations
# ==============================================================================

"""
Find this section in your /chat endpoint (around line 450):

    confidence = retrieval["score"] if retrieval else 0.0
    source = retrieval["source_id"] if retrieval else "LLM_ONLY"
    article_link = (
        retrieval.get("article_link")
        if retrieval and confidence >= CONFIDENCE_THRESHOLD
        else None
    )

Add this IMMEDIATELY AFTER the above code:

    # ===== PDF RECOMMENDATIONS (NEW) =====
    recommended_pdfs = []
    try:
        # Only recommend PDFs for IA_ACCESS_ISSUE intent with actual retrieval
        if intent == "IA_ACCESS_ISSUE" and retrieval and not is_greeting:
            recommended_pdfs = get_recommendations_for_chat(
                retrieval_result=retrieval,
                platform=platform,
                query=message
            )
            print(f"📄 Recommending {len(recommended_pdfs)} PDFs")
    except Exception as e:
        print(f"⚠️  PDF recommendation failed (non-critical): {e}")
        recommended_pdfs = []

Then UPDATE the return statement to include recommended_pdfs:

    return ChatResponse(
        reply=reply,
        source=source,
        article_link=article_link,
        confidence=confidence,
        retrieval_time_ms=round(retrieval_time_ms, 2),
        llm_time_ms=round(llm_time_ms, 2),
        total_time_ms=round(total_time_ms, 2),
        recommended_pdfs=recommended_pdfs  # ← ADD THIS LINE
    )
"""

# ==============================================================================
# COMPLETE CODE SNIPPET (Replace lines 445-470 in your main.py)
# ==============================================================================

COMPLETE_REPLACEMENT = """
        confidence = retrieval["score"] if retrieval else 0.0
        source = retrieval["source_id"] if retrieval else "LLM_ONLY"
        article_link = (
            retrieval.get("article_link")
            if retrieval and confidence >= CONFIDENCE_THRESHOLD
            else None
        )

        # ===== PDF RECOMMENDATIONS =====
        recommended_pdfs = []
        try:
            # Only recommend PDFs for troubleshooting queries with retrieval
            if intent == "IA_ACCESS_ISSUE" and retrieval and not is_greeting:
                recommended_pdfs = get_recommendations_for_chat(
                    retrieval_result=retrieval,
                    platform=platform,
                    query=message
                )
                print(f"📄 Recommending {len(recommended_pdfs)} PDFs")
        except Exception as e:
            print(f"⚠️  PDF recommendation failed (non-critical): {e}")
            recommended_pdfs = []

        return ChatResponse(
            reply=reply,
            source=source,
            article_link=article_link,
            confidence=confidence,
            retrieval_time_ms=round(retrieval_time_ms, 2),
            llm_time_ms=round(llm_time_ms, 2),
            total_time_ms=round(total_time_ms, 2),
            recommended_pdfs=recommended_pdfs  # ← NEW
        )
"""

# ==============================================================================
# TESTING THE INTEGRATION
# ==============================================================================

TEST_QUERIES = """
Once integrated, test with these queries:

1. "I need help with McGraw Hill Connect"
   → Should recommend mcgraw_connect_access.pdf as "Best Match"

2. "How do I access Cengage MindTap?"
   → Should recommend cengage_access.pdf as "Best Match"

3. "I can't access my Pearson MyLab"
   → Should recommend pearson_mylab_access.pdf as "Best Match"

4. "Help with cookies on Chrome"
   → Should recommend cookies_chrome.pdf as "Best Match"

Expected response structure:
{
  "reply": "Here's how to access...",
  "source": "INSTR_MCGRAW_SOURCE_0",
  "confidence": 0.95,
  "recommended_pdfs": [
    {
      "doc_id": "mcgraw_connect_access",
      "title": "McGraw Hill Connect Access",
      "description": "Complete guide to accessing...",
      "url": "https://storage.googleapis.com/...",
      "pages": 4,
      "relevance": "Best Match",
      "platform": "mcgraw"
    }
  ]
}
"""

print(__doc__)
print("\n" + "="*80)
print("COMPLETE CODE REPLACEMENT:")
print("="*80)
print(COMPLETE_REPLACEMENT)
print("\n" + "="*80)
print("TESTING GUIDE:")
print("="*80)
print(TEST_QUERIES)
