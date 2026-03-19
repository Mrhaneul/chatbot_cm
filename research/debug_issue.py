
import asyncio
import json
from app.main import process_chat_request, ChatRequest

async def main():
    message = "Good morning, my name is Bradley Boster, I am currently enrolled in MPA 545 and I am not able to access a pulldown for immediate access on the left hand side of the online interface. I paid everything in full, curious why it is not populating on my screen."
    payload = ChatRequest(message=message, session_id="debug-session")
    
    print("\n--- PROCESSING START ---")
    response = await process_chat_request(payload)
    print("\n--- PROCESSING END ---")
    
    print("\n📝 Response:")
    print(response.reply)
    print(f"\n📊 Metadata: Source={response.source}, Confidence={response.confidence}")

if __name__ == "__main__":
    asyncio.run(main())
