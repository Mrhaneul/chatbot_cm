import asyncio
import os
import uuid

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.main import process_chat_request
from app.schemas.chat import ChatRequest


def test_missing_immediate_access_tab_escalates_after_platform_clarification():
    async def run_case():
        session_id = f"case-006-{uuid.uuid4()}"

        first = await process_chat_request(
            ChatRequest(
                message=(
                    "Good morning, my name is Bradley Boster, I am currently enrolled in MPA 545 "
                    "in the Masters in Public Administration program and I am not able to access "
                    "a pulldown for immediate access on the left hand side of the online interface. "
                    "I paid everything in full, curious why it is not populating on my screen."
                ),
                session_id=session_id,
            )
        )
        assert first.source == "CLARIFICATION_NEEDED"
        assert "which platform or publisher" in first.reply.lower()

        second = await process_chat_request(
            ChatRequest(
                message="I do not know which platform.",
                session_id=session_id,
            )
        )
        assert second.source == "CLARIFICATION_NEEDED"
        assert "platform name" in second.reply.lower()

        third = await process_chat_request(
            ChatRequest(
                message="There is no Immediate Access tab on the left side in Blackboard.",
                session_id=session_id,
            )
        )
        assert third.source == "LLM_ONLY"
        assert "immediateaccess@calbaptist.edu" in third.reply.lower()
        assert "lancermail" in third.reply.lower()

    asyncio.run(run_case())
