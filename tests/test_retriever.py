import os
import asyncio
import pytest

# Ensure the config points to the correct platforms.yaml location
os.environ["PLATFORMS_CONFIG"] = os.path.join(os.path.dirname(__file__), "..", "app", "rag", "platforms.yaml")

from app.main import retrieve_async

@pytest.mark.asyncio
async def test_retriever_general():
    # General query should route to the general instruction index
    result = await retrieve_async("How do I access Immediate Access?")
    assert result["source_id"].startswith("INSTR_GENERAL"), f"Unexpected source_id {result['source_id']}"
    # Metadata should contain the instruction schema keys
    meta = result.get("metadata", {})
    assert "platform" in meta and isinstance(meta["platform"], list)
    assert "source_file" in meta and isinstance(meta["source_file"], str)
    assert "section_title" in meta and isinstance(meta["section_title"], str)

@pytest.mark.asyncio
async def test_retriever_platform_specific():
    # Platform‑specific query – provide platform argument
    result = await retrieve_async("How do I access Cengage MindTap?", platform="CENGAGE")
    assert result["source_id"].startswith("INSTR_CENGAGE"), f"Unexpected source_id {result['source_id']}"
    meta = result.get("metadata", {})
    # Platform metadata should be a list containing "cengage"
    assert meta.get("platform") == ["cengage"]
    assert "source_file" in meta
    assert "section_title" in meta
