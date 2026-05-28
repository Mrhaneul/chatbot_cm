from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.rag.metadata import load_document_with_metadata


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SPACES_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"[\s.?!]+$")


@dataclass(frozen=True)
class QuickHelpRoute:
    prompt: str
    source_paths: tuple[str, ...]
    answer_kind: str
    title: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class QuickHelpMatch:
    route: QuickHelpRoute
    reply: str
    context: str
    source: str
    source_paths: tuple[str, ...]


def normalize_quick_help_prompt(prompt: str) -> str:
    """Conservative normalization for exact Quick Help prompt matching."""
    normalized = _SPACES_RE.sub(" ", (prompt or "").strip().lower())
    return _TRAILING_PUNCT_RE.sub("", normalized)


QUICK_HELP_ROUTES: dict[str, QuickHelpRoute] = {
    normalize_quick_help_prompt(route.prompt): route
    for route in (
        QuickHelpRoute(
            prompt="I can't access my McGraw Hill Connect textbook",
            source_paths=(
                "data/instructions/ia_mcgraw_hill_connect_access.txt",
                "data/instructions/ia_mcgraw_hill_tools_access.txt",
            ),
            answer_kind="mcgraw_combined",
            source="QUICK_HELP:ia_mcgraw_hill_connect_access.txt+ia_mcgraw_hill_tools_access.txt",
        ),
        QuickHelpRoute(
            prompt="I can't access my Vitalsource",
            source_paths=("data/instructions/ia_vitalsource_bookshelf_account_creation.txt",),
            answer_kind="instruction",
            title="VitalSource",
            source="QUICK_HELP:ia_vitalsource_bookshelf_account_creation.txt",
        ),
        QuickHelpRoute(
            prompt="My book is not showing up in Immediate Access",
            source_paths=("data/faqs/ia_bundle_missing_textbook.txt",),
            answer_kind="faq",
            source="QUICK_HELP:ia_bundle_missing_textbook.txt",
        ),
        QuickHelpRoute(
            prompt="How do I opt out of Immediate Access?",
            source_paths=("data/faqs/ia_overview.txt",),
            answer_kind="opt_out",
            source="QUICK_HELP:ia_overview.txt",
        ),
        QuickHelpRoute(
            prompt="What happens if I opt out of Immediate Access?",
            source_paths=("data/faqs/ia_overview.txt",),
            answer_kind="opt_out",
            source="QUICK_HELP:ia_overview.txt",
        ),
        QuickHelpRoute(
            prompt="Where do I opt out from Immediate Access?",
            source_paths=("data/faqs/ia_overview.txt",),
            answer_kind="opt_out",
            source="QUICK_HELP:ia_overview.txt",
        ),
        QuickHelpRoute(
            prompt="How do I return a textbook?",
            source_paths=("data/faqs/textbook_refund_policy.txt",),
            answer_kind="textbook_return",
            source="QUICK_HELP:textbook_refund_policy.txt",
        ),
        QuickHelpRoute(
            prompt="How can I return my textbook to the Campus Store?",
            source_paths=("data/faqs/textbook_refund_policy.txt",),
            answer_kind="textbook_return",
            source="QUICK_HELP:textbook_refund_policy.txt",
        ),
        QuickHelpRoute(
            prompt="What is the refund policy for Immediate Access?",
            source_paths=(
                "data/faqs/ia_overview.txt",
                "data/faqs/textbook_refund_policy.txt",
            ),
            answer_kind="ia_refund",
            source="QUICK_HELP:ia_overview.txt+textbook_refund_policy.txt",
        ),
    )
}


def find_quick_help_route(prompt: str) -> QuickHelpRoute | None:
    return QUICK_HELP_ROUTES.get(normalize_quick_help_prompt(prompt))


def resolve_source_path(source_path: str) -> Path:
    path = PROJECT_ROOT / source_path
    if not path.is_file():
        raise FileNotFoundError(f"Quick Help source file not found: {source_path}")
    return path


def read_quick_help_source(source_path: str) -> str:
    _, body = load_document_with_metadata(resolve_source_path(source_path))
    return body


def _strip_article_link_lines(text: str) -> str:
    cleaned = re.sub(r'(?im)^\s*Article link:\s*"?[^"\n]+"?\s*$', "", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _extract_faq_answer(text: str) -> str:
    if "ANSWER:" in text:
        answer = text.split("ANSWER:", 1)[1]
        return _strip_article_link_lines(answer)
    return _strip_article_link_lines(text)


def _numbered_faq_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for raw in re.split(r"(?=\[FAQ_\d+\])", text):
        block = raw.strip()
        if not block.startswith("[FAQ_"):
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        question_idx = next(
            (idx for idx, line in enumerate(lines) if re.match(r"^\d+\.\s+.+\?$", line)),
            None,
        )
        if question_idx is None or question_idx + 1 >= len(lines):
            continue
        question = lines[question_idx]
        answer_lines = []
        for line in lines[question_idx + 1:]:
            if line.startswith("Article link:"):
                continue
            answer_lines.append(line)
        blocks.append((question, "\n".join(answer_lines).strip()))
    return blocks


def _instruction_answer(title: str, text: str) -> str:
    return f"Here's how to access {title}:\n\n{_strip_article_link_lines(text)}"


def _mcgraw_combined_answer(texts: list[str]) -> str:
    learning_activities_text, tools_text = texts
    return (
        "Here's how to access McGraw Hill Connect.\n\n"
        "The exact Blackboard location may depend on how your instructor set up the course. "
        "Check both of these official access paths:\n\n"
        "OPTION 1 - Learning Activities tab:\n"
        f"{_strip_article_link_lines(learning_activities_text)}\n\n"
        "OPTION 2 - Tools tab:\n"
        f"{_strip_article_link_lines(tools_text)}"
    )


def _opt_out_answer(text: str) -> str:
    answer = _extract_faq_answer(text)
    return (
        "Immediate Access has a 14-day opt-out period from the start of the semester. "
        "You can opt out through the Immediate Access page in Blackboard. "
        "After opting out, you must purchase materials separately.\n\n"
        f"Additional Immediate Access context from the Campus Store FAQ:\n\n{answer}"
    )


def _textbook_return_answer(text: str) -> str:
    blocks = _numbered_faq_blocks(text)
    if not blocks:
        return _strip_article_link_lines(text)
    lines = ["Here is the textbook return and refund policy from the Campus Store FAQ:"]
    for question, answer in blocks:
        lines.append(f"\n{question}\n{answer}")
    return "\n".join(lines).strip()


def _ia_refund_answer(overview_text: str, textbook_policy_text: str) -> str:
    overview = _extract_faq_answer(overview_text)
    policy_blocks = _numbered_faq_blocks(textbook_policy_text)
    relevant_policy = []
    for question, answer in policy_blocks:
        haystack = f"{question} {answer}".lower()
        if any(term in haystack for term in ("access code", "digital content", "immediate access", "opt out")):
            relevant_policy.append(f"{question}\n{answer}")
    policy = "\n\n".join(relevant_policy).strip()
    return (
        "For Immediate Access, the Campus Store FAQ says there is a 14-day opt-out period "
        "from the start of the semester. You opt out through the Immediate Access page in "
        "Blackboard. After opting out, you must purchase materials separately.\n\n"
        "Relevant textbook/digital-content refund policy:\n\n"
        f"{policy or _strip_article_link_lines(textbook_policy_text)}\n\n"
        "Immediate Access overview context:\n\n"
        f"{overview}"
    ).strip()


def build_quick_help_match(prompt: str) -> QuickHelpMatch | None:
    route = find_quick_help_route(prompt)
    if route is None:
        return None

    texts = [read_quick_help_source(source_path) for source_path in route.source_paths]
    if route.answer_kind == "mcgraw_combined":
        reply = _mcgraw_combined_answer(texts)
    elif route.answer_kind == "instruction":
        reply = _instruction_answer(route.title or "your materials", texts[0])
    elif route.answer_kind == "faq":
        reply = _extract_faq_answer(texts[0])
    elif route.answer_kind == "opt_out":
        reply = _opt_out_answer(texts[0])
    elif route.answer_kind == "textbook_return":
        reply = _textbook_return_answer(texts[0])
    elif route.answer_kind == "ia_refund":
        reply = _ia_refund_answer(texts[0], texts[1])
    else:
        reply = "\n\n---\n\n".join(_strip_article_link_lines(text) for text in texts)

    return QuickHelpMatch(
        route=route,
        reply=reply,
        context="\n\n---\n\n".join(texts),
        source=route.source or "QUICK_HELP",
        source_paths=route.source_paths,
    )
