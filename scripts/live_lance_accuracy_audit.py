"""
live_lance_accuracy_audit.py — End-to-end accuracy audit using the real local LLM.

Tests Lance across three groups:
  Group A  22 Quick Help prompts from ui/src/faqConfig.ts
  Group B  12 paraphrased high-risk RAG questions
  Group C   6 unsupported / ambiguous questions

Outputs:
  live_lance_accuracy_audit_results.json
  live_lance_accuracy_audit_summary.md

Usage:
  python scripts/live_lance_accuracy_audit.py
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAQ_CONFIG_PATH = PROJECT_ROOT / "ui" / "src" / "faqConfig.ts"
JSON_REPORT = PROJECT_ROOT / "live_lance_accuracy_audit_results.json"
MD_REPORT = PROJECT_ROOT / "live_lance_accuracy_audit_summary.md"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Test groups ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TestCase:
    prompt: str
    group: str          # "A", "B", or "C"
    description: str = ""

    # Source routing constraints
    required_source_keywords: tuple[str, ...] = ()
    forbidden_source_keywords: tuple[str, ...] = ()

    # Reply content constraints
    reply_must_contain: tuple[str, ...] = ()
    reply_must_not_contain: tuple[str, ...] = ()

    # Behavioural flags
    expect_quick_help: bool = False     # source should start with QUICK_HELP
    expect_clarification: bool = False  # source should be CLARIFICATION_NEEDED
    expect_safe_fallback: bool = False  # reply admits no info / no hallucinated facts


# Group A fixture expectations (the 6 prompts with known Quick Help routes)
_GROUP_A_FIXTURES: dict[str, TestCase] = {
    "I can't access my McGraw Hill Connect textbook": TestCase(
        prompt="I can't access my McGraw Hill Connect textbook",
        group="A",
        description="Quick Help fixture — McGraw Hill combined",
        required_source_keywords=("QUICK_HELP",),
        expect_quick_help=True,
    ),
    "I can't access my Vitalsource": TestCase(
        prompt="I can't access my Vitalsource",
        group="A",
        description="Quick Help fixture — VitalSource",
        required_source_keywords=("QUICK_HELP",),
        forbidden_source_keywords=("bedford",),
        expect_quick_help=True,
    ),
    "My book is not showing up in Immediate Access": TestCase(
        prompt="My book is not showing up in Immediate Access",
        group="A",
        description="Quick Help fixture — IA bundle missing",
        required_source_keywords=("QUICK_HELP",),
        expect_quick_help=True,
    ),
    "How do I opt out of Immediate Access?": TestCase(
        prompt="How do I opt out of Immediate Access?",
        group="A",
        description="Quick Help fixture — opt-out",
        required_source_keywords=("QUICK_HELP",),
        forbidden_source_keywords=("ia_access_issue",),
        expect_quick_help=True,
    ),
    "How do I return a textbook?": TestCase(
        prompt="How do I return a textbook?",
        group="A",
        description="Quick Help fixture — textbook return",
        required_source_keywords=("QUICK_HELP",),
        expect_quick_help=True,
    ),
    "What is the refund policy for Immediate Access?": TestCase(
        prompt="What is the refund policy for Immediate Access?",
        group="A",
        description="Quick Help fixture — IA refund policy",
        required_source_keywords=("QUICK_HELP",),
        forbidden_source_keywords=("campus_store_refund_merchandise",),
        expect_quick_help=True,
    ),
}

GROUP_B_CASES: list[TestCase] = [
    TestCase(
        prompt="Can I get a refund for Immediate Access?",
        group="B",
        description="IA refund — must not bleed into merchandise return policy",
        forbidden_source_keywords=("campus_store_refund_merchandise",),
        # "final sale" is a legitimate term in textbook_refund_policy.txt for digital content;
        # only "restocking fee" is a signal of merchandise-policy bleed
        reply_must_not_contain=("restocking fee",),
    ),
    TestCase(
        prompt="What happens if I opt out of Immediate Access?",
        group="B",
        description="IA opt-out consequences",
        required_source_keywords=("ia_overview",),
    ),
    TestCase(
        prompt="Where do I opt out from Immediate Access?",
        group="B",
        description="Opt-out location — should mention Blackboard",
        reply_must_contain=("blackboard",),
        forbidden_source_keywords=("campus_store_refund_merchandise",),
    ),
    TestCase(
        prompt="My IA textbook is missing from Blackboard. What should I do?",
        group="B",
        description="Missing IA textbook in Blackboard",
        required_source_keywords=("ia_bundle_missing", "ia_access_issue", "ia_overview"),
    ),
    TestCase(
        prompt="How can I return my textbook to the Campus Store?",
        group="B",
        description="Textbook return policy",
        required_source_keywords=("textbook_refund",),
    ),
    TestCase(
        prompt="Can I return merchandise from the Campus Store?",
        group="B",
        description="Merchandise return — must use merchandise policy, not textbook policy",
        # Accept campus_store_refund_merchandise OR campus_store_refund_process (both are correct)
        required_source_keywords=("campus_store_refund",),
    ),
    TestCase(
        prompt="I cannot open my VitalSource book.",
        group="B",
        description="VitalSource access issue — must not route to Bedford email error",
        required_source_keywords=("vitalsource",),
        forbidden_source_keywords=("bedford_bookshelf_email_error",),
    ),
    TestCase(
        prompt="I need to create a VitalSource Bookshelf account.",
        group="B",
        description="VitalSource account creation",
        required_source_keywords=("vitalsource_bookshelf_account_creation",),
        forbidden_source_keywords=("bedford_bookshelf_email_error",),
    ),
    TestCase(
        prompt="Bedford Bookshelf says my email is wrong.",
        group="B",
        description="Bedford email error — must not route to VitalSource account creation",
        required_source_keywords=("bedford",),
        forbidden_source_keywords=("vitalsource_bookshelf_account_creation",),
    ),
    TestCase(
        prompt="McGraw Hill Connect is not opening from Blackboard.",
        group="B",
        description="McGraw Hill Connect access issue",
        required_source_keywords=("mcgraw",),
    ),
    TestCase(
        prompt="Cengage MindTap is not showing my textbook.",
        group="B",
        description="Cengage MindTap access issue",
        required_source_keywords=("cengage",),
    ),
    TestCase(
        prompt="Pearson MyLab access is not working.",
        group="B",
        description="Pearson MyLab access issue",
        required_source_keywords=("pearson",),
    ),
]

GROUP_C_CASES: list[TestCase] = [
    TestCase(
        prompt="Can I get a refund after 60 days?",
        group="C",
        description="Unsupported refund timeline — must not invent a policy",
        expect_safe_fallback=True,
    ),
    TestCase(
        prompt="What is the Campus Store manager's personal phone number?",
        group="C",
        description="Personal contact info — must not invent",
        expect_safe_fallback=True,
    ),
    TestCase(
        prompt="Can you send me a private discount code?",
        group="C",
        description="Discount code — must not invent",
        expect_safe_fallback=True,
    ),
    TestCase(
        prompt="Can I access my textbook through Canvas?",
        group="C",
        description="Canvas (not Blackboard) — must not hallucinate Canvas steps",
        expect_safe_fallback=True,
    ),
    TestCase(
        prompt="What if my professor changed the textbook today?",
        group="C",
        description="Volatile operational fact — must not invent professor/admin details",
        expect_safe_fallback=True,
    ),
    TestCase(
        prompt="Can you guarantee I will get a refund?",
        group="C",
        description="Guarantee demand — must not promise outcomes",
        expect_safe_fallback=True,
        reply_must_not_contain=("guarantee", "yes, you will", "i can confirm"),
    ),
]


# ── Regex patterns used in evaluation ────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?:\(\d{3}\)\s*\d{3}[\s.\-]\d{4}|\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b|\b\d{10}\b)"
)
_URL_RE = re.compile(r"https?://[^\s\)\"'<>]+|(?<!\S)www\.[A-Za-z0-9\-]+\.[^\s\)\"'<>]+")
_DOLLAR_RE = re.compile(r"\$\s*\d+(?:\.\d{1,2})?")


def _detect_hallucination_patterns(reply: str) -> list[dict]:
    """Extract emails, phones, URLs, dollar amounts directly from reply text."""
    found = []
    for m in _EMAIL_RE.finditer(reply):
        found.append({"type": "email", "value": m.group()})
    for m in _PHONE_RE.finditer(reply):
        found.append({"type": "phone_number", "value": m.group()})
    for m in _URL_RE.finditer(reply):
        found.append({"type": "url", "value": m.group()})
    for m in _DOLLAR_RE.finditer(reply):
        found.append({"type": "dollar_amount", "value": m.group()})
    return found


def _safe_fallback_admitted(reply: str) -> bool:
    """Return True if the reply admits insufficient documentation or asks for clarification."""
    markers = [
        "do not have enough information",
        "don't have enough information",
        "not have enough information",
        "i cannot provide",
        "unable to confirm",
        "please contact",
        "contact the campus store",
        "contact immediateaccess",
        "contact immediate access",
        "no information in",
        "outside of what i have",
        # Clarification responses are also acceptable safe behavior for unsupported questions
        "could you please specify",
        "could you clarify",
        "could you please clarify",
        "which platform",
        "which publisher",
    ]
    lower = reply.lower()
    return any(m in lower for m in markers)


def _source_haystack(source: str, source_paths: list[str], reply: str) -> str:
    return " ".join([source.lower(), reply.lower()] + [sp.lower() for sp in source_paths])


# ── Result capture for grounding verifier ────────────────────────────────────

_PER_CASE_GV_RESULTS: list = []


def _install_gv_capture(app_main_module: Any) -> None:
    """Patch verify_answer_grounding in app.main to capture results per call."""
    from app.rag.grounding_verifier import verify_answer_grounding as _orig

    def _capturing(answer: str, context: str, **kwargs):
        result = _orig(answer, context, **kwargs)
        _PER_CASE_GV_RESULTS.append(result)
        return result

    app_main_module.verify_answer_grounding = _capturing


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate_result(
    tc: TestCase,
    *,
    reply: str,
    source: str,
    source_paths: list[str],
    gv_triggered: bool,
    unsupported_claims: list[dict],
    error: str | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    failure_categories: list[str] = []

    haystack = _source_haystack(source, source_paths, reply)

    if error:
        reasons.append(f"error: {error}")
        failure_categories.append("error")

    # Source routing checks
    if tc.required_source_keywords:
        if not any(kw.lower() in haystack for kw in tc.required_source_keywords):
            reasons.append(f"expected source keyword missing: {tc.required_source_keywords}")
            failure_categories.append("wrong_retrieval_source")

    if tc.forbidden_source_keywords:
        found_forbidden = [kw for kw in tc.forbidden_source_keywords if kw.lower() in haystack]
        if found_forbidden:
            reasons.append(f"forbidden source keyword present: {found_forbidden}")
            failure_categories.append("wrong_retrieval_source")

    # Quick Help source check
    if tc.expect_quick_help and not source.startswith("QUICK_HELP"):
        reasons.append(f"expected QUICK_HELP source, got: {source}")
        failure_categories.append("wrong_retrieval_source")

    # Reply content checks
    reply_lower = reply.lower()
    for must in tc.reply_must_contain:
        if must.lower() not in reply_lower:
            reasons.append(f"reply missing required keyword: '{must}'")
            failure_categories.append("incomplete_answer")
    for must_not in tc.reply_must_not_contain:
        if must_not.lower() in reply_lower:
            reasons.append(f"reply contains forbidden text: '{must_not}'")
            failure_categories.append("generation_hallucination")

    # Grounding verifier triggered
    if gv_triggered:
        reasons.append("grounding verifier blocked LLM answer; safe fallback returned")
        failure_categories.append("grounding_verifier_fallback")

    # Direct hallucination pattern check (always run for Group C; as supplement for others)
    raw_patterns = _detect_hallucination_patterns(reply)
    if tc.group == "C":
        # For unsupported questions any invented contact / amount is a hallucination
        for pat in raw_patterns:
            # ImmediateAccess@calbaptist.edu is the real documented contact — allow it
            if pat["type"] == "email" and "calbaptist.edu" in pat["value"].lower():
                continue
            # 951-343-4259 is the real Campus Store number — allow it
            if pat["type"] == "phone_number" and "951" in pat["value"] and "4259" in pat["value"]:
                continue
            reasons.append(f"hallucinated {pat['type']}: {pat['value']!r}")
            if "generation_hallucination" not in failure_categories:
                failure_categories.append("generation_hallucination")

    # Grounding verifier unsupported claims
    if unsupported_claims:
        reasons.append(
            f"verifier found {len(unsupported_claims)} unsupported claim(s): "
            + ", ".join(f"{c['type']}={c['value']!r}" for c in unsupported_claims)
        )
        if "generation_hallucination" not in failure_categories:
            failure_categories.append("generation_hallucination")

    # Group C: check safe fallback admission
    if tc.expect_safe_fallback:
        admitted = _safe_fallback_admitted(reply)
        if not admitted and not reasons:
            # Didn't admit insufficiency but also didn't hallucinate — warn
            reasons.append("expected safe fallback acknowledgement but got a confident answer")
            failure_categories.append("missing_data_admission")

    # Determine status
    if error or any(cat in failure_categories for cat in (
        "wrong_retrieval_source", "generation_hallucination", "error"
    )):
        status = "FAIL"
    elif reasons:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "status": status,
        "reasons": reasons,
        "failure_categories": list(set(failure_categories)),
    }


# ── Prompt loading ────────────────────────────────────────────────────────────

def load_quick_help_prompts(config_path: Path = FAQ_CONFIG_PATH) -> list[str]:
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


def build_test_cases() -> list[TestCase]:
    """Build all test cases in order: Group A, B, C."""
    cases: list[TestCase] = []

    # Group A — all Quick Help prompts from faqConfig.ts
    prompts = load_quick_help_prompts()
    for p in prompts:
        if p in _GROUP_A_FIXTURES:
            cases.append(_GROUP_A_FIXTURES[p])
        else:
            cases.append(TestCase(prompt=p, group="A", description="Quick Help (non-fixture)"))

    # Group B — paraphrased RAG questions
    cases.extend(GROUP_B_CASES)

    # Group C — unsupported/ambiguous questions
    cases.extend(GROUP_C_CASES)

    return cases


# ── Source path resolution (reuse existing logic) ─────────────────────────────

def _extract_source_file_from_context(context: str) -> str | None:
    match = re.match(r"^\s*\[META:(\{.*?\})\]", context or "")
    if not match:
        return None
    try:
        metadata = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    sf = metadata.get("source_file")
    return sf if isinstance(sf, str) and sf else None


def _source_paths_from_retriever(app_main: Any, source_id: str) -> list[str]:
    if not source_id:
        return []
    from app.quick_help_routes import find_quick_help_route
    route = find_quick_help_route(source_id)
    if route:
        return list(route.source_paths)
    if source_id.startswith("FAQ_SOURCE_"):
        try:
            idx = int(source_id.rsplit("_", 1)[1])
            chunk = app_main.retriever.faq_chunks[idx]
            sf = _extract_source_file_from_context(chunk)
            return [f"data/faqs/{sf}"] if sf else []
        except Exception:
            return []
    m = re.match(r"^INSTR_(.+)_SOURCE_(\d+)$", source_id)
    if not m:
        return []
    source_key, raw_idx = m.groups()
    try:
        idx = int(raw_idx)
        if source_key == "GENERAL":
            chunk = app_main.retriever.instruction_chunks[idx]
        else:
            chunk = app_main.retriever._platform_indexes[source_key]["chunks"][idx]
        sf = _extract_source_file_from_context(chunk)
        return [f"data/instructions/{sf}"] if sf else []
    except Exception:
        return []


def source_paths_for_result(app_main: Any, tc: TestCase, source: str) -> list[str]:
    from app.quick_help_routes import find_quick_help_route
    route = find_quick_help_route(tc.prompt)
    if route and route.source == source:
        return list(route.source_paths)
    return _source_paths_from_retriever(app_main, source)


# ── Single test runner ────────────────────────────────────────────────────────

async def run_single(
    tc: TestCase,
    app_main: Any,
    ChatRequest: Any,
    case_idx: int,
    total: int,
) -> dict[str, Any]:
    label = f"[{case_idx}/{total}] [{tc.group}] {tc.prompt[:70]}"
    print(f"  {label} ...", end="", flush=True)

    _PER_CASE_GV_RESULTS.clear()
    error = None
    response = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            response = await app_main.process_chat_request(
                ChatRequest(
                    message=tc.prompt,
                    session_id=f"live-audit-{uuid.uuid4()}",
                )
            )
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"

    # Extract response fields
    if response is None:
        reply = ""
        source = ""
        source_paths: list[str] = []
        confidence = 0.0
        retrieval_time_ms = None
        llm_time_ms = None
        total_time_ms = None
    else:
        reply = response.reply
        source = response.source
        source_paths = source_paths_for_result(app_main, tc, source)
        confidence = response.confidence
        retrieval_time_ms = response.retrieval_time_ms
        llm_time_ms = response.llm_time_ms
        total_time_ms = response.total_time_ms

    # Grounding verifier info
    from app.rag.grounding_verifier import GROUNDING_SAFE_FALLBACK
    gv_triggered = reply == GROUNDING_SAFE_FALLBACK
    gv_unsupported: list[dict] = []
    for gv_result in _PER_CASE_GV_RESULTS:
        if not gv_result.passed:
            gv_triggered = True
            for claim in gv_result.unsupported_claims:
                gv_unsupported.append({"type": claim.claim_type, "value": claim.claim_text})

    # Evaluate
    evaluation = evaluate_result(
        tc,
        reply=reply,
        source=source,
        source_paths=source_paths,
        gv_triggered=gv_triggered,
        unsupported_claims=gv_unsupported,
        error=error,
    )

    status = evaluation["status"]
    status_icon = {"PASS": "[OK]", "WARN": "[WN]", "FAIL": "[!!]"}.get(status, "[?]")
    print(f" {status_icon} {status}")
    if evaluation["reasons"]:
        for r in evaluation["reasons"]:
            print(f"      >> {r}")

    return {
        "group": tc.group,
        "description": tc.description,
        "prompt": tc.prompt,
        "reply": reply,
        "source": source,
        "source_paths": source_paths,
        "confidence": confidence,
        "retrieval_time_ms": retrieval_time_ms,
        "llm_time_ms": llm_time_ms,
        "total_time_ms": total_time_ms,
        "grounding_verifier_triggered": gv_triggered,
        "unsupported_claims": gv_unsupported,
        "recommended_pdfs": getattr(response, "recommended_pdfs", []) if response else [],
        "status": status,
        "failure_categories": evaluation["failure_categories"],
        "reasons": evaluation["reasons"],
        "error": error,
    }


# ── Main audit runner ─────────────────────────────────────────────────────────

async def run_audit() -> list[dict[str, Any]]:
    print("Loading Lance backend (app.main)...")
    with contextlib.redirect_stdout(io.StringIO()):
        from app import main as app_main
        from app.schemas.chat import ChatRequest

    # Patch grounding verifier to capture per-case results
    _install_gv_capture(app_main)

    cases = build_test_cases()
    total = len(cases)

    from app.llm.llama_client import PRIMARY_LLM_MODEL, FALLBACK_LLM_MODEL
    print(f"\nRunning {total} test cases against real LLM ({PRIMARY_LLM_MODEL} / fallback {FALLBACK_LLM_MODEL})")
    print(f"Grounding verifier: {'ENABLED' if app_main.cfg.ENABLE_GROUNDING_VERIFIER else 'DISABLED'}\n")

    results: list[dict[str, Any]] = []
    for i, tc in enumerate(cases, start=1):
        result = await run_single(tc, app_main, ChatRequest, i, total)
        results.append(result)

    return results


# ── Markdown summary writer ───────────────────────────────────────────────────

def build_markdown(results: list[dict[str, Any]], run_ts: str) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")

    hallucinations = sum(
        1 for r in results if "generation_hallucination" in r["failure_categories"]
    )
    unsupported_claim_count = sum(
        1 for r in results if r.get("unsupported_claims")
    )
    wrong_source = sum(
        1 for r in results if "wrong_retrieval_source" in r["failure_categories"]
    )
    incomplete = sum(
        1 for r in results if "incomplete_answer" in r["failure_categories"]
    )
    gv_fallback = sum(
        1 for r in results if r.get("grounding_verifier_triggered")
    )
    missing_data = sum(
        1 for r in results if "missing_data_admission" in r["failure_categories"]
    )

    by_group: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    for r in results:
        by_group[r["group"]].append(r)

    def group_summary(group: str) -> str:
        items = by_group[group]
        gp = sum(1 for r in items if r["status"] == "PASS")
        gf = sum(1 for r in items if r["status"] == "FAIL")
        gw = sum(1 for r in items if r["status"] == "WARN")
        return f"{len(items)} tested | {gp} passed | {gf} failed | {gw} warned"

    lines = [
        f"# Lance Live Accuracy Audit",
        f"",
        f"**Run timestamp:** {run_ts}",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total tested | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Warnings | {warned} |",
        f"| Hallucinations detected | {hallucinations} |",
        f"| Grounding verifier triggered | {gv_fallback} |",
        f"| Unsupported-claim count | {unsupported_claim_count} |",
        f"| Wrong-source count | {wrong_source} |",
        f"| Incomplete-answer count | {incomplete} |",
        f"| Missing safe-fallback admission | {missing_data} |",
        f"",
        f"## Group Results",
        f"",
        f"### Group A — Quick Help Prompts ({len(by_group['A'])})",
        f"{group_summary('A')}",
        f"",
    ]

    for r in by_group["A"]:
        icon = {"PASS": "OK", "WARN": "WN", "FAIL": "!!"}.get(r["status"], "?")
        reason = "; ".join(r["reasons"]) if r["reasons"] else ""
        lines.append(f"- {icon} `{r['prompt']}` — source: `{r['source']}`" + (f" — {reason}" if reason else ""))

    lines += [
        f"",
        f"### Group B — Paraphrased RAG Questions ({len(by_group['B'])})",
        f"{group_summary('B')}",
        f"",
    ]
    for r in by_group["B"]:
        icon = {"PASS": "OK", "WARN": "WN", "FAIL": "!!"}.get(r["status"], "?")
        reason = "; ".join(r["reasons"]) if r["reasons"] else ""
        lines.append(
            f"- {icon} `{r['prompt']}` — source: `{r['source']}`"
            + (f" — {reason}" if reason else "")
        )

    lines += [
        f"",
        f"### Group C — Unsupported/Ambiguous Questions ({len(by_group['C'])})",
        f"{group_summary('C')}",
        f"",
    ]
    for r in by_group["C"]:
        icon = {"PASS": "OK", "WARN": "WN", "FAIL": "!!"}.get(r["status"], "?")
        reason = "; ".join(r["reasons"]) if r["reasons"] else ""
        lines.append(
            f"- {icon} `{r['prompt']}` — source: `{r['source']}`"
            + (f" — {reason}" if reason else "")
        )

    # Top failures
    failures = [r for r in results if r["status"] == "FAIL"]
    if failures:
        lines += [f"", f"## Top Failures", f""]
        for r in failures[:10]:
            lines += [
                f"### [{r['group']}] {r['prompt']}",
                f"**Source:** `{r['source']}`",
                f"**Categories:** {', '.join(r['failure_categories'])}",
                f"**Reasons:**",
            ]
            for reason in r["reasons"]:
                lines.append(f"- {reason}")
            if r["reply"]:
                preview = r["reply"][:300].replace("\n", " ")
                lines.append(f"**Reply preview:** {preview}...")
            lines.append("")
    else:
        lines += [f"", f"## Failures", f"", f"No failures detected.", f""]

    # Warnings (abbreviated)
    warnings_list = [r for r in results if r["status"] == "WARN"]
    if warnings_list:
        lines += [f"## Warnings", f""]
        for r in warnings_list:
            reason = "; ".join(r["reasons"])
            lines.append(f"- [{r['group']}] `{r['prompt']}` — {reason}")
        lines.append("")

    # Recommended fixes
    lines += [f"## Recommended Next Fixes", f""]
    fix_items: list[str] = []
    if wrong_source:
        fix_items.append(
            f"**Wrong retrieval source ({wrong_source} case(s)):** Review metadata filtering "
            f"and hybrid scoring weights. Check if the affected queries need new/updated "
            f"source files or keyword boosting."
        )
    if hallucinations:
        fix_items.append(
            f"**Hallucinations ({hallucinations} case(s)):** Lower RAG_TEMPERATURE further "
            f"or tighten the grounding verifier policy phrase list. Verify retrieved context "
            f"actually contains the answer before the LLM generates."
        )
    if gv_fallback and not hallucinations:
        fix_items.append(
            f"**Grounding verifier triggered ({gv_fallback} case(s)) with no detected hallucinations:** "
            f"The verifier may be producing false positives. Check the blocked claims and consider "
            f"expanding the supported-claim context (e.g. ensure the documented contact email is "
            f"in the retrieved chunk, not just the parent source)."
        )
    if incomplete:
        fix_items.append(
            f"**Incomplete answers ({incomplete} case(s)):** Expand the retrieved context "
            f"(MAX_EXPANDED_CONTEXT_CHARS or MAX_PARENT_SOURCES) or add missing data files."
        )
    if missing_data:
        fix_items.append(
            f"**Missing safe-fallback admission ({missing_data} case(s)):** "
            f"These Group C answers were confident when they should have admitted insufficient "
            f"data. Strengthen the grounded prompt's insufficient-info rule or add a "
            f"deterministic guard for these query types."
        )
    if not fix_items:
        fix_items.append("No critical fixes required. Monitor false-positive rate of grounding verifier during live traffic.")

    for item in fix_items:
        lines.append(f"- {item}")
        lines.append("")

    lines += [
        f"---",
        f"*Generated by `scripts/live_lance_accuracy_audit.py`*",
    ]

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"Lance Live Accuracy Audit — {run_ts}")
    print(f"{'='*60}\n")

    results = asyncio.run(run_audit())

    # Save JSON
    JSON_REPORT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nJSON report -> {JSON_REPORT}")

    # Save Markdown
    md = build_markdown(results, run_ts)
    MD_REPORT.write_text(md, encoding="utf-8")
    print(f"Markdown summary -> {MD_REPORT}")

    # Terminal summary
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    gv_triggered = sum(1 for r in results if r.get("grounding_verifier_triggered"))
    hallucinations = sum(
        1 for r in results if "generation_hallucination" in r["failure_categories"]
    )

    print(f"\n{'='*60}")
    print(f"RESULTS: {total} tested | {passed} passed | {failed} failed | {warned} warned")
    print(f"Grounding verifier triggered: {gv_triggered}")
    print(f"Hallucinations detected:      {hallucinations}")
    print(f"{'='*60}")

    if failed:
        print("\nFailed cases:")
        for r in results:
            if r["status"] == "FAIL":
                cats = ", ".join(r["failure_categories"])
                print(f"  [{r['group']}] {r['prompt'][:70]} [{cats}]")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
