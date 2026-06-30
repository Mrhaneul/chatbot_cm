"""Smoke-test chatbot routing before demos.

Requires the FastAPI server to be running at http://localhost:8000.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib import error, request


BASE_URL = "http://localhost:8000/chat"


@dataclass
class SmokeResult:
    message: str
    source: str
    route_type: str
    reply_preview: str
    expected: bool
    note: str = ""


def post_chat(message: str, session_id: str) -> dict:
    body = json.dumps({"message": message, "session_id": session_id}).encode("utf-8")
    req = request.Request(
        BASE_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def response_text(data: dict) -> str:
    value = data.get("reply") or data.get("response") or data.get("message") or ""
    return str(value).replace("\r\n", "\n")


def source_text(data: dict) -> str:
    source = data.get("source") or ""
    route_type = data.get("route_type") or ""
    return f"{source} {route_type}".strip()


def preview(text: str, limit: int = 200) -> str:
    compact = " ".join(text.split())
    return compact[:limit]


def expect_book_lookup(data: dict) -> tuple[bool, str]:
    source = source_text(data)
    ok = "BOOK_LOOKUP" in source
    return ok, "" if ok else f"expected BOOK_LOOKUP, got {source or 'no source'}"


def expect_book_lookup_not_found(data: dict) -> tuple[bool, str]:
    source = source_text(data)
    reply = response_text(data).lower()
    ok = (
        "BOOK_LOOKUP" in source
        and (
            "NOT_FOUND" in source
            or "wasn't able to find" in reply
            or "bookstore.calbaptist.edu/textbooks" in reply
        )
    )
    return ok, "" if ok else f"expected BOOK_LOOKUP not-found, got {source or 'no source'}"


def expect_policy_deadline(data: dict) -> tuple[bool, str]:
    source = source_text(data)
    ok = "POLICY:DEADLINE" in source
    return ok, "" if ok else f"expected POLICY:DEADLINE, got {source or 'no source'}"


def expect_procedure(data: dict) -> tuple[bool, str]:
    source = source_text(data)
    reply = response_text(data).lower()
    ok = "POLICY:DEADLINE" not in source and "opt out" in reply and "canvas" in reply
    return ok, "" if ok else f"expected Canvas opt-out procedure, got {source or 'no source'}"


def expect_rag_overview(data: dict) -> tuple[bool, str]:
    source = source_text(data)
    ok = "BOOK_LOOKUP" not in source and "POLICY:DEADLINE" not in source
    return ok, "" if ok else f"expected non-book/non-deadline RAG, got {source}"


def run_message(message: str, session_id: str, checker: Callable[[dict], tuple[bool, str]]) -> SmokeResult:
    data = post_chat(message, session_id)
    ok, note = checker(data)
    return SmokeResult(
        message=message,
        source=str(data.get("source") or ""),
        route_type=str(data.get("route_type") or ""),
        reply_preview=preview(response_text(data)),
        expected=ok,
        note=note,
    )


def print_result(result: SmokeResult) -> None:
    status = "PASS" if result.expected else "CHECK"
    route = result.source or result.route_type or "(none)"
    if result.source and result.route_type:
        route = f"{result.source} / {result.route_type}"
    print(f"[{status}] {result.message}")
    print(f"  route: {route}")
    print(f"  reply: {result.reply_preview}")
    if result.note:
        print(f"  note: {result.note}")


def run_group(
    name: str,
    messages: list[str],
    checker: Callable[[dict], tuple[bool, str]],
    reuse_session: bool = False,
) -> list[SmokeResult]:
    print()
    print("=" * 72)
    print(name)
    print("=" * 72)
    results: list[SmokeResult] = []
    shared_session = f"demo-{uuid.uuid4().hex[:10]}"
    for message in messages:
        session_id = shared_session if reuse_session else f"demo-{uuid.uuid4().hex[:10]}"
        result = run_message(message, session_id, checker)
        results.append(result)
        print_result(result)
        time.sleep(0.2)

    misses = [result.message for result in results if not result.expected]
    if misses:
        print(f"GROUP SUMMARY: CHECK ({len(misses)} need review)")
        for message in misses:
            print(f"  - {message}")
    else:
        print("GROUP SUMMARY: PASS")
    return results


def run_cache_miss_group() -> list[SmokeResult]:
    print()
    print("=" * 72)
    print("GROUP F - Cache miss / not found")
    print("=" * 72)
    results: list[SmokeResult] = []

    immediate = run_message(
        "what book do I need for HIST 101 section A full term",
        f"demo-{uuid.uuid4().hex[:10]}",
        expect_book_lookup_not_found,
    )
    results.append(immediate)
    print_result(immediate)

    flow_session = f"demo-{uuid.uuid4().hex[:10]}"
    flow_steps = [
        ("what do I need for ENGR3100", expect_book_lookup),
        ("section A", expect_book_lookup),
        ("full term", expect_book_lookup_not_found),
    ]
    for message, checker in flow_steps:
        result = run_message(message, flow_session, checker)
        results.append(result)
        print_result(result)
        time.sleep(0.2)

    misses = [result.message for result in results if not result.expected]
    if misses:
        print(f"GROUP SUMMARY: CHECK ({len(misses)} need review)")
        for message in misses:
            print(f"  - {message}")
    else:
        print("GROUP SUMMARY: PASS")
    return results


def main() -> int:
    groups = [
        (
            "GROUP A - Course materials, natural phrasings",
            [
                "what book do I need for ATR 511?",
                "what materials do I need for ATR511",
                "what's my textbook for ACC 250",
                "what do I need to buy for BIO 101",
                "books for NUR 502",
                "what software do I need for ACC 410",
            ],
            expect_book_lookup,
            False,
        ),
        (
            "GROUP B - Course materials full clarification flow",
            [
                "what materials do I need for ATR 511?",
                "section A",
                "full term",
            ],
            expect_book_lookup,
            True,
        ),
        (
            "GROUP C - Opt-out / return deadlines, natural phrasings",
            [
                "when is the opt out date?",
                "when's the opt out deadline",
                "how long do I have to opt out",
                "what's the cutoff to opt out",
                "when can I return my textbook",
                "last day to return books",
                "when is the return deadline",
            ],
            expect_policy_deadline,
            False,
        ),
        (
            "GROUP D - Procedure vs date guardrail",
            [
                "how do I opt out of immediate access?",
                "how do I opt out",
                "steps to opt out",
            ],
            expect_procedure,
            False,
        ),
        (
            "GROUP E - General IA / RAG",
            [
                "what is immediate access?",
                "how does immediate access work",
            ],
            expect_rag_overview,
            False,
        ),
    ]

    all_results: list[SmokeResult] = []
    try:
        for name, messages, checker, reuse_session in groups:
            all_results.extend(run_group(name, messages, checker, reuse_session))
        all_results.extend(run_cache_miss_group())
    except error.URLError as exc:
        print(f"Could not connect to {BASE_URL}. Start the chatbot server and rerun this script.")
        print(f"Connection error: {exc}")
        return 2
    except TimeoutError as exc:
        print(f"Timed out waiting for {BASE_URL}. Check that the chatbot server is running.")
        print(f"Timeout error: {exc}")
        return 2

    expected_count = sum(1 for result in all_results if result.expected)
    misses = [result for result in all_results if not result.expected]
    print()
    print("=" * 72)
    print("OVERALL SUMMARY")
    print("=" * 72)
    print(f"Total messages: {len(all_results)}")
    print(f"Routed as expected: {expected_count}")
    if misses:
        print("Need review:")
        for result in misses:
            print(f"- {result.message}: {result.note}")
        return 1
    print("Need review: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
