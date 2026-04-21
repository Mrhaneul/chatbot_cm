#!/usr/bin/env python3
"""
Batch-test explicit FAQ questions under data/faqs against Lance in both
auto mode and session debug/LLM mode.

The script:
- extracts QUESTION/ANSWER pairs from real FAQ source files
- sends each question to /chat in fresh sessions for both modes
- records reply/source/confidence/timing
- estimates whether the reply matches the expected FAQ answer or a different FAQ
- writes JSON, CSV, and Markdown summaries under research/
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
FAQ_DIR = ROOT / "data" / "faqs"
API_BASE = "http://127.0.0.1:8000"
CHAT_URL = f"{API_BASE}/chat"
DEBUG_MODE_URL = f"{API_BASE}/session/debug-mode"
CLEAR_SESSION_URL = f"{API_BASE}/sessions"

JSON_OUT = ROOT / "research" / "data_question_mode_results.json"
CSV_OUT = ROOT / "research" / "data_question_mode_results.csv"
MD_OUT = ROOT / "research" / "data_question_mode_report.md"


QUESTION_RE = re.compile(
    r"QUESTION:\s*(.*?)\s*ANSWER:\s*(.*?)(?:\s*CONTACT:.*)?\s*$",
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class FAQCase:
    file_name: str
    question: str
    expected_answer: str


def normalize_text(text: str) -> str:
    text = re.sub(r"(?im)^\s*Article link:\s*.*$", "", text or "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def token_set(text: str) -> set[str]:
    return set(normalize_text(text).split())


def combined_similarity(a: str, b: str) -> float:
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    seq = SequenceMatcher(None, a_norm, b_norm).ratio()
    a_tokens = token_set(a)
    b_tokens = token_set(b)
    if not a_tokens or not b_tokens:
        jaccard = 0.0
    else:
        jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    return round((seq * 0.7) + (jaccard * 0.3), 4)


def load_cases() -> list[FAQCase]:
    cases: list[FAQCase] = []
    for path in sorted(FAQ_DIR.glob("*.txt")):
        if path.name == "faqs_chunks.txt":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = QUESTION_RE.search(text)
        if not match:
            continue
        question = match.group(1).strip()
        answer = match.group(2).strip()
        cases.append(
            FAQCase(
                file_name=path.name,
                question=question,
                expected_answer=answer,
            )
        )
    return cases


def set_session_debug_mode(session: requests.Session, session_id: str, enabled: bool) -> None:
    response = session.post(
        DEBUG_MODE_URL,
        params={"session_id": session_id, "enabled": str(enabled).lower()},
        timeout=20,
    )
    response.raise_for_status()


def clear_session(session: requests.Session, session_id: str) -> None:
    try:
        session.delete(f"{CLEAR_SESSION_URL}/{session_id}", timeout=20)
    except requests.RequestException:
        pass


def call_chat(session: requests.Session, question: str, session_id: str) -> dict[str, Any]:
    response = session.post(
        CHAT_URL,
        json={"message": question, "session_id": session_id},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def classify_result(
    case: FAQCase,
    mode: str,
    result: dict[str, Any],
    all_cases: list[FAQCase],
) -> dict[str, Any]:
    reply = result.get("reply", "") or ""
    scored_matches: list[tuple[float, str]] = []
    for other in all_cases:
        score = combined_similarity(reply, other.expected_answer)
        scored_matches.append((score, other.file_name))
    scored_matches.sort(reverse=True)
    best_score, best_match_file = scored_matches[0]
    expected_score = next(
        combined_similarity(reply, other.expected_answer)
        for other in all_cases
        if other.file_name == case.file_name
    )

    if best_match_file == case.file_name and expected_score >= 0.55:
        verdict = "good"
    elif best_match_file != case.file_name and best_score >= 0.45:
        verdict = "retrieving_else"
    else:
        verdict = "needs_review"

    return {
        "mode": mode,
        "file_name": case.file_name,
        "question": case.question,
        "expected_answer": case.expected_answer,
        "reply": reply,
        "source": result.get("source"),
        "article_link": result.get("article_link"),
        "confidence": result.get("confidence"),
        "debug_mode": result.get("debug_mode"),
        "retrieval_time_ms": result.get("retrieval_time_ms"),
        "llm_time_ms": result.get("llm_time_ms"),
        "total_time_ms": result.get("total_time_ms"),
        "best_match_file": best_match_file,
        "best_match_score": best_score,
        "expected_match_score": expected_score,
        "verdict": verdict,
    }


def write_outputs(results: list[dict[str, Any]]) -> None:
    JSON_OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")

    fieldnames = [
        "mode",
        "file_name",
        "verdict",
        "source",
        "confidence",
        "best_match_file",
        "best_match_score",
        "expected_match_score",
        "retrieval_time_ms",
        "llm_time_ms",
        "total_time_ms",
        "question",
        "reply",
    ]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({key: row.get(key) for key in fieldnames})

    by_mode: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_mode.setdefault(row["mode"], []).append(row)

    lines: list[str] = ["# Data Question Test Report", ""]
    for mode, rows in sorted(by_mode.items()):
        good = sum(1 for row in rows if row["verdict"] == "good")
        drift = sum(1 for row in rows if row["verdict"] == "retrieving_else")
        review = sum(1 for row in rows if row["verdict"] == "needs_review")
        lines.append(f"## {mode}")
        lines.append("")
        lines.append(f"- Total: {len(rows)}")
        lines.append(f"- Good: {good}")
        lines.append(f"- Retrieving else: {drift}")
        lines.append(f"- Needs review: {review}")
        lines.append("")
        bad_rows = [row for row in rows if row["verdict"] != "good"]
        if bad_rows:
            lines.append("| File | Verdict | Source | Best match | Conf |")
            lines.append("| --- | --- | --- | --- | --- |")
            for row in bad_rows:
                conf = row.get("confidence")
                conf_str = "" if conf is None else f"{conf:.3f}"
                lines.append(
                    f"| {row['file_name']} | {row['verdict']} | {row.get('source','')} | "
                    f"{row['best_match_file']} ({row['best_match_score']:.3f}) | {conf_str} |"
                )
            lines.append("")

    MD_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    cases = load_cases()
    if not cases:
        print("No FAQ QUESTION/ANSWER pairs found.", file=sys.stderr)
        return 1

    session = requests.Session()
    results: list[dict[str, Any]] = []
    modes = [("auto", False), ("llm", True)]

    print(f"Loaded {len(cases)} FAQ questions.")
    for mode, debug_enabled in modes:
        print(f"\n=== Testing mode: {mode} ===")
        for idx, case in enumerate(cases, start=1):
            session_id = f"data-test-{mode}-{uuid.uuid4()}"
            print(f"[{mode} {idx}/{len(cases)}] {case.file_name}")
            try:
                set_session_debug_mode(session, session_id, debug_enabled)
                result = call_chat(session, case.question, session_id)
                classified = classify_result(case, mode, result, cases)
                results.append(classified)
                print(
                    f"  -> {classified['verdict']} | source={classified['source']} | "
                    f"best_match={classified['best_match_file']} ({classified['best_match_score']:.3f})"
                )
            except Exception as exc:
                results.append(
                    {
                        "mode": mode,
                        "file_name": case.file_name,
                        "question": case.question,
                        "expected_answer": case.expected_answer,
                        "reply": "",
                        "source": "ERROR",
                        "article_link": None,
                        "confidence": None,
                        "debug_mode": debug_enabled,
                        "retrieval_time_ms": None,
                        "llm_time_ms": None,
                        "total_time_ms": None,
                        "best_match_file": "",
                        "best_match_score": 0.0,
                        "expected_match_score": 0.0,
                        "verdict": "error",
                        "error": str(exc),
                    }
                )
                print(f"  -> error: {exc}")
            finally:
                clear_session(session, session_id)
                time.sleep(0.2)

    write_outputs(results)
    print(f"\nWrote {JSON_OUT}")
    print(f"Wrote {CSV_OUT}")
    print(f"Wrote {MD_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
