from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAQ_CONFIG_PATH = PROJECT_ROOT / "ui" / "src" / "faqConfig.ts"
REPORT_PATH = PROJECT_ROOT / "faq_quick_help_audit_results.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.quick_help_routes import find_quick_help_route  # noqa: E402


@dataclass(frozen=True)
class QuickHelpExpectation:
    expected_source_files: tuple[str, ...]
    forbidden_source_files: tuple[str, ...] = ()
    should_not_clarify: bool = True
    should_use_llm: bool = True


KNOWN_EXPECTATIONS: dict[str, QuickHelpExpectation] = {
    "I can't access my McGraw Hill Connect textbook": QuickHelpExpectation(
        expected_source_files=(
            "data/instructions/ia_mcgraw_hill_connect_access.txt",
            "data/instructions/ia_mcgraw_hill_tools_access.txt",
        ),
    ),
    "I can't access my Vitalsource": QuickHelpExpectation(
        expected_source_files=("data/instructions/ia_vitalsource_bookshelf_account_creation.txt",),
        forbidden_source_files=("data/instructions/ia_bedford_bookshelf_email_error_access.txt",),
    ),
    "My book is not showing up in Immediate Access": QuickHelpExpectation(
        expected_source_files=("data/faqs/ia_bundle_missing_textbook.txt",),
    ),
    "How do I opt out of Immediate Access?": QuickHelpExpectation(
        expected_source_files=("data/faqs/immediate_access/ia_opt_out_canvas.txt",),
        forbidden_source_files=("data/faqs/ia_access_issue.txt",),
    ),
    "How do I return a textbook?": QuickHelpExpectation(
        expected_source_files=("data/faqs/textbook_refund_policy.txt",),
    ),
    "What is the refund policy for Immediate Access?": QuickHelpExpectation(
        expected_source_files=(
            "data/faqs/ia_overview.txt",
            "data/faqs/textbook_refund_policy.txt",
        ),
        forbidden_source_files=("data/faqs/campus_store_refund_merchandise.txt",),
    ),
}


class AuditLLMStub:
    """LLM replacement used so this audit never requires a live Ollama server."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(self, *args: Any, **kwargs: Any) -> str:
        message = args[0] if args else kwargs.get("message", "")
        self.calls.append({"message": message})
        return (
            "[AUDIT LLM STUB] This prompt reached the LLM path. "
            "Run a live model audit separately if answer quality needs validation."
        )

    async def call(self, *args: Any, **kwargs: Any) -> tuple[str, float]:
        message = kwargs.get("message", args[0] if args else "")
        context = kwargs.get("context", "")
        self.calls.append({"message": message, "context": context})
        return (
            "[AUDIT LLM STUB] This prompt reached the final grounded LLM path. "
            "Run a live model audit separately if answer quality needs validation.",
            0.0,
        )


def load_quick_help_prompts(config_path: Path = FAQ_CONFIG_PATH) -> list[str]:
    """
    Parse ui/src/faqConfig.ts for Quick Help option strings.

    This intentionally extracts only strings inside `options: [...]` arrays.
    It is not a full TypeScript parser, but it matches the maintained config
    shape and avoids duplicating the frontend FAQ list in Python.
    """
    text = config_path.read_text(encoding="utf-8")
    prompts: list[str] = []
    seen: set[str] = set()
    for block in re.findall(r"options\s*:\s*\[(.*?)\]", text, flags=re.DOTALL):
        for prompt in re.findall(r'"((?:[^"\\]|\\.)*)"', block):
            prompt = bytes(prompt, "utf-8").decode("unicode_escape")
            if prompt not in seen:
                prompts.append(prompt)
                seen.add(prompt)
    return prompts


def _extract_source_file_from_context(context: str) -> str | None:
    match = re.match(r"^\s*\[META:(\{.*?\})\]", context or "")
    if not match:
        return None
    try:
        metadata = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    source_file = metadata.get("source_file")
    return source_file if isinstance(source_file, str) and source_file else None


def _source_paths_from_retriever(app_main: Any, source_id: str) -> list[str]:
    if not source_id:
        return []

    if source_id.startswith("FAQ_SOURCE_"):
        try:
            idx = int(source_id.rsplit("_", 1)[1])
            chunk = app_main.retriever.faq_chunks[idx]
            source_file = _extract_source_file_from_context(chunk)
            return [f"data/faqs/{source_file}"] if source_file else []
        except Exception:
            return []

    match = re.match(r"^INSTR_(.+)_SOURCE_(\d+)$", source_id)
    if not match:
        return []

    source_key, raw_idx = match.groups()
    try:
        idx = int(raw_idx)
        if source_key == "GENERAL":
            chunk = app_main.retriever.instruction_chunks[idx]
        else:
            chunk = app_main.retriever._platform_indexes[source_key]["chunks"][idx]
        source_file = _extract_source_file_from_context(chunk)
        return [f"data/instructions/{source_file}"] if source_file else []
    except Exception:
        return []


def source_paths_for_prompt(app_main: Any, prompt: str, source_id: str) -> list[str]:
    route = find_quick_help_route(prompt)
    if route:
        return list(route.source_paths)
    return _source_paths_from_retriever(app_main, source_id)


def _source_matches(expected: str, observed_paths: list[str], source_haystack: str) -> bool:
    expected_normalized = expected.replace("\\", "/")
    expected_without_prefix = re.sub(r"^data/(faqs|instructions)/", "", expected_normalized)
    for observed in observed_paths:
        observed_normalized = (observed or "").replace("\\", "/")
        if (
            observed_normalized == expected_normalized
            or observed_normalized == expected_without_prefix
            or expected_normalized.endswith(observed_normalized)
            or observed_normalized.endswith(expected_without_prefix)
        ):
            return True
    return expected_normalized in source_haystack or expected_without_prefix in source_haystack


def evaluate_audit_result(
    *,
    prompt: str,
    source: str,
    source_paths: list[str],
    reply: str,
    clarification_triggered: bool,
    llm_calls: int,
    retrieval_time_ms: float | None,
    expectation: QuickHelpExpectation | None,
    error: str | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    source_haystack = " ".join([source, reply, *source_paths])

    if expectation:
        expected_source_match = all(
            _source_matches(expected, source_paths, source_haystack)
            for expected in expectation.expected_source_files
        )
        forbidden_source_found = any(
            forbidden in source_paths or forbidden in source_haystack
            for forbidden in expectation.forbidden_source_files
        )
        if not expected_source_match:
            reasons.append("expected source file missing")
        if forbidden_source_found:
            reasons.append("forbidden source file found")
        if expectation.should_not_clarify and clarification_triggered:
            reasons.append("clarification triggered")
        if expectation.should_use_llm and llm_calls == 0:
            reasons.append("LLM was not called")
    else:
        expected_source_match = None
        forbidden_source_found = False
        if llm_calls > 0:
            reasons.append("LLM stub used; source routing only partially audited")
        if clarification_triggered:
            reasons.append("clarification triggered for non-fixture prompt")

    if error:
        reasons.append(error)

    if error or (expectation and reasons):
        status = "FAIL"
    elif reasons:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "expected_source_match": expected_source_match,
        "forbidden_source_found": forbidden_source_found,
        "status": status,
        "reasons": reasons,
    }


async def run_audit() -> list[dict[str, Any]]:
    prompts = load_quick_help_prompts()
    if not prompts:
        raise RuntimeError(f"No Quick Help prompts found in {FAQ_CONFIG_PATH}")

    # Importing app.main initializes the same backend objects used by /chat.
    # Redirect stdout to keep this audit's terminal output concise.
    with contextlib.redirect_stdout(io.StringIO()):
        from app import main as app_main
        from app.schemas.chat import ChatRequest

    llm_stub = AuditLLMStub()
    app_main.llm.chat = llm_stub.chat
    app_main.call_llm_with_semaphore = llm_stub.call

    results: list[dict[str, Any]] = []
    for prompt in prompts:
        before_llm_calls = len(llm_stub.calls)
        error = None
        response = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                response = await app_main.process_chat_request(
                    ChatRequest(
                        message=prompt,
                        session_id=f"quick-help-audit-{uuid.uuid4()}",
                    )
                )
        except Exception as exc:
            error = f"{exc.__class__.__name__}: {exc}"

        llm_calls = len(llm_stub.calls) - before_llm_calls
        if response is None:
            source = ""
            source_paths: list[str] = []
            reply = ""
            confidence = 0.0
            retrieval_time_ms = None
            llm_time_ms = None
            total_time_ms = None
            clarification_triggered = False
        else:
            source = response.source
            source_paths = source_paths_for_prompt(app_main, prompt, source)
            selected_source_file = getattr(response, "selected_source_file", None)
            retrieved_source_file = getattr(response, "retrieved_source_file", None)
            for source_file in (selected_source_file, retrieved_source_file):
                if source_file and source_file not in source_paths:
                    source_paths.append(source_file)
            reply = response.reply
            confidence = response.confidence
            retrieval_time_ms = response.retrieval_time_ms
            llm_time_ms = response.llm_time_ms
            total_time_ms = response.total_time_ms
            clarification_triggered = source == "CLARIFICATION_NEEDED"

        expectation = KNOWN_EXPECTATIONS.get(prompt)
        evaluation = evaluate_audit_result(
            prompt=prompt,
            source=source,
            source_paths=source_paths,
            reply=reply,
            clarification_triggered=clarification_triggered,
            llm_calls=llm_calls,
            retrieval_time_ms=retrieval_time_ms,
            expectation=expectation,
            error=error,
        )
        results.append(
            {
                "prompt": prompt,
                "reply": reply,
                "source": source,
                "source_paths": source_paths,
                "confidence": confidence,
                "retrieval_time_ms": retrieval_time_ms,
                "llm_time_ms": llm_time_ms,
                "total_time_ms": total_time_ms,
                "clarification_triggered": clarification_triggered,
                "expected_source_match": evaluation["expected_source_match"],
                "forbidden_source_found": evaluation["forbidden_source_found"],
                "status": evaluation["status"],
                "reasons": evaluation["reasons"],
                "llm_stub_calls": llm_calls,
            }
        )

    return results


def print_summary(results: list[dict[str, Any]]) -> None:
    total = len(results)
    passed = sum(1 for item in results if item["status"] == "PASS")
    failed = sum(1 for item in results if item["status"] == "FAIL")
    warned = sum(1 for item in results if item["status"] == "WARN")

    print("Quick Help FAQ audit")
    print(f"Total prompts tested: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Warnings: {warned}")
    print(f"Report: {REPORT_PATH}")

    failed_items = [item for item in results if item["status"] == "FAIL"]
    if failed_items:
        print("\nFailed prompts:")
        for item in failed_items:
            reason = "; ".join(item["reasons"]) or "unknown failure"
            print(f"- {item['prompt']} [{reason}]")

    warned_items = [item for item in results if item["status"] == "WARN"]
    if warned_items:
        print("\nWarnings:")
        for item in warned_items:
            reason = "; ".join(item["reasons"]) or "review recommended"
            print(f"- {item['prompt']} [{reason}]")


def main() -> int:
    results = asyncio.run(run_audit())
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print_summary(results)
    return 1 if any(item["status"] == "FAIL" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
