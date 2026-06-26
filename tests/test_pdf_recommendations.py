from unittest.mock import MagicMock, patch


def test_get_pdf_from_firestore_prefers_url_over_legacy_public_url() -> None:
    """
    Static PDF migration stores the canonical URL in the Firestore 'url' field.
    Legacy 'public_url' values may still point at Firebase Storage and must not
    override the newer URL.
    """
    from app.pdf_recommendations import get_pdf_from_firestore

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "title": "Accessing Cengage MindTap",
        "filename": "Accessing Cengage MindTap-CNowV2 Courseware_Canvas.pdf",
        "url": "https://example.ngrok-free.dev/static/pdfs/cengage.pdf",
        "public_url": "https://storage.googleapis.com/lance-cbu.firebasestorage.app/pdfs/cengage/cengage_access.pdf",
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_doc
    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_ref

    with patch("app.pdf_recommendations.db") as mock_db:
        mock_db.collection.return_value = mock_collection
        pdf = get_pdf_from_firestore("cengage_access")

    assert pdf is not None
    assert pdf["public_url"] == "https://example.ngrok-free.dev/static/pdfs/cengage.pdf"


def test_related_pdf_lookup_prefers_url_over_legacy_public_url() -> None:
    from app.pdf_recommendations import get_related_pdfs_by_platform

    mock_doc = MagicMock()
    mock_doc.id = "cengage_access"
    mock_doc.to_dict.return_value = {
        "title": "Accessing Cengage MindTap",
        "filename": "Accessing Cengage MindTap-CNowV2 Courseware_Canvas.pdf",
        "url": "https://example.ngrok-free.dev/static/pdfs/cengage.pdf",
        "public_url": "https://storage.googleapis.com/lance-cbu.firebasestorage.app/pdfs/cengage/cengage_access.pdf",
        "platform": "cengage",
    }

    mock_query = MagicMock()
    mock_query.where.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.get.return_value = [mock_doc]

    with patch("app.pdf_recommendations.db") as mock_db:
        mock_db.collection.return_value = mock_query
        pdfs = get_related_pdfs_by_platform("cengage")

    assert len(pdfs) == 1
    assert pdfs[0]["public_url"] == "https://example.ngrok-free.dev/static/pdfs/cengage.pdf"


def test_opt_out_canvas_source_recommends_opt_out_pdf() -> None:
    from app.pdf_recommendations import get_recommendations_for_chat

    retrieval_result = {
        "context": "ANSWER:\nTo opt out of Immediate Access in Canvas...",
        "score": 1.0,
        "metadata": {"source_file": "immediate_access/ia_opt_out_canvas.txt"},
    }

    mock_map_doc = MagicMock()
    mock_map_doc.exists = False
    mock_map_ref = MagicMock()
    mock_map_ref.get.return_value = mock_map_doc
    mock_map_collection = MagicMock()
    mock_map_collection.document.return_value = mock_map_ref

    def collection(name):
        if name == "txt_to_pdf_map":
            return mock_map_collection
        raise AssertionError(f"unexpected collection: {name}")

    with (
        patch("app.pdf_recommendations.db") as mock_db,
        patch("app.pdf_recommendations.get_pdf_from_firestore") as mock_get_pdf,
    ):
        mock_db.collection.side_effect = collection
        mock_get_pdf.return_value = {
            "doc_id": "immediate_access_opt_out",
            "title": "How to Opt Out of Immediate Access (Canvas)",
            "description": "Instructions for opting out of Immediate Access through Canvas.",
            "filename": "How to Opt Out of Immediate Access_Canvas.pdf",
            "public_url": "https://example.ngrok-free.dev/static/pdfs/How%20to%20Opt%20Out%20of%20Immediate%20Access_Canvas.pdf",
            "pages": 0,
            "platform": "GENERAL",
            "tags": ["opt out", "immediate access", "canvas"],
        }

        pdfs = get_recommendations_for_chat(
            retrieval_result=retrieval_result,
            platform=None,
            query="How do I opt out?",
        )

    mock_get_pdf.assert_called_once_with("immediate_access_opt_out")
    assert len(pdfs) == 1
    assert pdfs[0]["doc_id"] == "immediate_access_opt_out"
    assert pdfs[0]["url"].endswith("Immediate%20Access_Canvas.pdf")
