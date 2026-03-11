import asyncio
import os
import uuid

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.main import process_chat_request
from app.schemas.chat import ChatRequest


async def run():
    sid = f"case012-{uuid.uuid4()}"

    # Sierra Cannon's exact scenario
    r1 = await process_chat_request(ChatRequest(
        message=(
            "I am unable to access my class textbooks via VitalSource. "
            "After following step by step directions in Blackboard, the link for "
            "immediate access only provides me with the option 'launch courseware' "
            "not 'read now.' There is also no access code to enter. "
            "I also don't see my textbook for another course listed at all in VitalSource."
        ),
        session_id=sid,
    ))
    print(f"T1 source: {r1.source}")
    print(f"T1 reply: {r1.reply[:350]}")
    print()


asyncio.run(run())
