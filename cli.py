#!/usr/bin/env python3
"""
Interactive CLI that calls the FastAPI chatbot with session support.
Run: python cli.py

Now generates a unique session ID so multiple CLI instances
can run simultaneously without interfering with each other.
"""

import requests
from colorama import Fore, Style, init
import uuid

init(autoreset=True)

API_URL = "http://127.0.0.1:8000/chat"

def format_response(data: dict) -> str:
    """Format the API response for terminal display."""
    output = []
    output.append(f"{Fore.GREEN}Assistant:{Style.RESET_ALL} {data['reply']}")
    output.append(f"\n{Fore.CYAN}[Confidence: {data['confidence']:.2f}]{Style.RESET_ALL}")
    output.append(f"{Fore.CYAN}[Source: {data['source']}]{Style.RESET_ALL}")
    if data.get("article_link"):
        output.append(f"{Fore.BLUE}[Link: {data['article_link']}]{Style.RESET_ALL}")
    return "\n".join(output)

def main():
    # Generate unique session ID for this CLI instance
    session_id = str(uuid.uuid4())
    short_session_id = session_id[:8]
    
    print(f"{Fore.YELLOW}Campus Store Chatbot (Session Mode){Style.RESET_ALL}")
    print(f"{Fore.YELLOW}{'=' * 50}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}Session ID: {short_session_id}...{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Type 'exit' or 'quit' to stop{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Type 'new' to start a new session{Style.RESET_ALL}\n")

    while True:
        user_input = input(f"{Fore.BLUE}You: {Style.RESET_ALL}").strip()

        if user_input.lower() in {"exit", "quit", "q"}:
            print(f"{Fore.YELLOW}Goodbye!{Style.RESET_ALL}")
            break

        if user_input.lower() == "new":
            session_id = str(uuid.uuid4())
            short_session_id = session_id[:8]
            print(f"{Fore.MAGENTA}🔄 Started new session: {short_session_id}...{Style.RESET_ALL}\n")
            continue

        if not user_input:
            continue

        try:
            response = requests.post(
                API_URL,
                json={
                    "message": user_input,
                    "session_id": session_id
                },
                timeout=180
            )
            response.raise_for_status()
            data = response.json()
            print(format_response(data))
            print()

        except requests.exceptions.Timeout:
            print(f"{Fore.RED}Request timed out. Try again or check if Ollama is running.{Style.RESET_ALL}\n")
        except requests.exceptions.HTTPError as e:
            response = e.response
            detail = None
            if response is not None:
                try:
                    payload = response.json()
                    detail = payload.get("detail", payload)
                except ValueError:
                    detail = response.text
            detail_text = f" Details: {detail}" if detail else ""
            print(f"{Fore.RED}Server error: {e}{detail_text}{Style.RESET_ALL}\n")
        except requests.exceptions.ConnectionError:
            print(f"{Fore.RED}Could not connect to server. Is it running on {API_URL}?{Style.RESET_ALL}\n")
        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}Error: {e}{Style.RESET_ALL}\n")

if __name__ == "__main__":
    main()