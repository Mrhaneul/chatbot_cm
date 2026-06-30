from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.policy_cache import upsert_policy_dates
from mbs_insite_probe import BASE, NAV_HEADERS, _request_with_retry, make_session

IA_URL = f"{BASE}/ia"
CUSTOMER_SERVICE_URL = f"{BASE}/customerservice"
IA_OVERVIEW_PATH = ROOT / "data" / "faqs" / "ia_overview.txt"
TEXTBOOK_REFUND_PATH = ROOT / "data" / "faqs" / "textbook_refund_policy.txt"

LONG_DATE_RE = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r")\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\b",
    re.IGNORECASE,
)
SHORT_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
LONG_DATE_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}"
)
SHORT_DATE_PATTERN = r"\d{1,2}/\d{1,2}/\d{2,4}"


def fetch_policy_pages() -> tuple[str, str]:
    client, _token = make_session()
    ia = _request_with_retry(client, "GET", IA_URL, headers={**NAV_HEADERS, "Referer": BASE})
    ia.raise_for_status()
    customerservice = _request_with_retry(
        client,
        "GET",
        CUSTOMER_SERVICE_URL,
        headers={**NAV_HEADERS, "Referer": IA_URL, "Sec-Fetch-Site": "same-origin"},
    )
    customerservice.raise_for_status()
    return ia.text or "", customerservice.text or ""


def soup_without_email_protection(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.select('a[href*="email-protection"]'):
        tag.decompose()
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_date_fragments(text: str) -> str:
    month_pattern = (
        r"January|February|March|April|May|June|July|August|September|October|November|December"
    )
    return re.sub(
        rf"\b({month_pattern})\s+(\d{{1,2}})\s*\n\s*(st|nd|rd|th)\s*\n\s*,\s*(\d{{4}})\b",
        r"\1 \2\3, \4",
        text or "",
        flags=re.IGNORECASE,
    )


def parse_date_to_iso(date_text: str) -> str:
    cleaned = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", date_text.strip(), flags=re.I)
    for fmt in ("%B %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date: {date_text!r}")


def extract_first_date(text: str) -> tuple[str, str] | tuple[None, None]:
    match = LONG_DATE_RE.search(text) or SHORT_DATE_RE.search(text)
    if not match:
        return None, None
    date_text = match.group(0)
    return date_text, parse_date_to_iso(date_text)


def clean_term_label(raw: str) -> str:
    value = normalize_space(raw)
    value = re.sub(r"^[\-\u2022\*\s:]+", "", value)
    value = re.sub(r"[:\-\u2013\u2014\s]+$", "", value)
    return value.strip()


def classify_ia_row_context(text: str) -> str | None:
    lower = text.lower()
    if "welcome" in lower and "email" in lower:
        return "welcome_email"
    if "opt" in lower and "deadline" in lower:
        return "opt_out"
    return None


def parse_ia_table_rows(soup: BeautifulSoup) -> list[dict]:
    rows: list[dict] = []
    seen = set()
    for tr in soup.select("tr"):
        cells = [normalize_space(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue
        joined = " ".join(cells)
        category = classify_ia_row_context(joined)
        date_text, date_iso = extract_first_date(joined)
        if not category or not date_text or not date_iso:
            continue

        term_candidates = []
        for cell in cells:
            if cell == date_text or date_text in cell:
                continue
            if classify_ia_row_context(cell):
                continue
            term_candidates.append(cell)
        term_label = clean_term_label(term_candidates[0] if term_candidates else joined[: joined.find(date_text)])
        key = (category, term_label.lower(), date_iso)
        if term_label and key not in seen:
            rows.append(
                {
                    "category": category,
                    "subtype": category,
                    "term_label": term_label,
                    "scope": "",
                    "date_text": date_text,
                    "date_iso": date_iso,
                }
            )
            seen.add(key)
    return rows


def parse_labeled_date_list(text: str, heading: str, category: str) -> list[dict]:
    lower = text.lower()
    preferred = {
        "welcome_email": "the ia welcome emails",
        "opt_out": "the opt-out deadlines",
    }.get(category, heading.lower())
    start = lower.find(preferred)
    if start == -1:
        start = lower.find(heading.lower())
    if start == -1:
        return []

    next_headings = [
        lower.find(candidate, start + len(heading))
        for candidate in ("the ia welcome emails", "the opt-out deadlines", "helpful links", "immediate access helpful links")
        if lower.find(candidate, start + len(heading)) != -1
    ]
    end = min(next_headings) if next_headings else len(text)
    block = normalize_date_fragments(text[start:end])
    rows = []
    pending_term = ""
    for line in block.splitlines():
        line = normalize_space(line)
        if not line or heading.lower() in line.lower():
            continue
        date_text, date_iso = extract_first_date(line)
        if not date_text:
            if line.endswith(":"):
                pending_term = clean_term_label(line[:-1])
            continue
        term_label = clean_term_label(line[: line.find(date_text)])
        if not term_label:
            term_label = pending_term
        pending_term = ""
        if not term_label:
            continue
        rows.append(
            {
                "category": category,
                "subtype": category,
                "term_label": term_label,
                "scope": "",
                "date_text": date_text,
                "date_iso": date_iso,
            }
        )
    return rows


def dedupe_rows(rows: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for row in rows:
        key = (
            row.get("category", "").lower(),
            row.get("subtype", "").lower(),
            row.get("term_label", "").lower(),
            row.get("scope", "").lower(),
            row.get("date_iso", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def parse_ia_dates(html: str) -> list[dict]:
    soup = soup_without_email_protection(html)
    rows = parse_ia_table_rows(soup)
    text = normalize_date_fragments(soup.get_text("\n", strip=True))
    rows.extend(parse_labeled_date_list(text, "IA Welcome Email", "welcome_email"))
    rows.extend(parse_labeled_date_list(text, "Opt-Out Deadline", "opt_out"))
    rows.extend(parse_labeled_date_list(text, "Opt Out Deadline", "opt_out"))
    return dedupe_rows(rows)


def find_refund_policy_text(html: str) -> str:
    soup = soup_without_email_protection(html)
    text = soup.get_text("\n", strip=True)
    matches = list(re.finditer(r"Campus Store Refund Policy", text, flags=re.I))
    if not matches:
        return text
    match = next(
        (
            candidate
            for candidate in matches
            if re.search(r"Textbooks.*All sales are FINAL", text[candidate.start() : candidate.start() + 2500], re.I | re.S)
        ),
        matches[-1],
    )
    tail = text[match.start() :]
    next_match = re.search(
        r"\n(?:Shipping|Privacy|Contact|Frequently Asked|Store Hours|Price Match)\b",
        tail,
        flags=re.I,
    )
    return tail[: next_match.start()] if next_match else tail


def parse_return_windows(html: str) -> list[dict]:
    text = find_refund_policy_text(html)
    compact = normalize_space(text)
    rows: list[dict] = []

    no_penalty = re.search(r"without penalties until\s+(" + SHORT_DATE_PATTERN + r")", compact, re.I)
    if no_penalty:
        date_text = no_penalty.group(1)
        rows.append(
            {
                "category": "return_window",
                "subtype": "no_penalty_until",
                "term_label": "",
                "scope": "Campus Store Refund Policy",
                "term_or_scope": "Campus Store Refund Policy",
                "date_text": date_text,
                "date_iso": parse_date_to_iso(date_text),
            }
        )

    restocking = re.search(
        r"25%\s+restocking fee from\s+(" + SHORT_DATE_RE.pattern[2:-2] + r")\s*[-\u2013\u2014]\s*("
        + SHORT_DATE_PATTERN
        + r")",
        compact,
        re.I,
    )
    if restocking:
        for subtype, date_text in (("restocking_start", restocking.group(1)), ("restocking_end", restocking.group(2))):
            rows.append(
                {
                    "category": "return_window",
                    "subtype": subtype,
                    "term_label": "",
                    "scope": "Campus Store Refund Policy",
                    "term_or_scope": "Campus Store Refund Policy",
                    "date_text": date_text,
                    "date_iso": parse_date_to_iso(date_text),
                }
            )

    final_after = re.search(r"All sales are FINAL after\s+(" + SHORT_DATE_PATTERN + r")", compact, re.I)
    if final_after:
        date_text = final_after.group(1)
        rows.append(
            {
                "category": "return_window",
                "subtype": "final_after",
                "term_label": "",
                "scope": "Campus Store Refund Policy",
                "term_or_scope": "Campus Store Refund Policy",
                "date_text": date_text,
                "date_iso": parse_date_to_iso(date_text),
            }
        )

    rental_patterns = [
        r"rental(?: textbook)?(?:s)?(?: return)?(?: deadline| due date)?[^.:\n]*?(?:by|until|deadline:?|due:?|on or before)\s+("
        + LONG_DATE_PATTERN
        + r")",
        r"("
        + LONG_DATE_PATTERN
        + r")[^.:\n]{0,80}rental",
    ]
    for pattern in rental_patterns:
        rental = re.search(pattern, compact, re.I)
        if rental:
            date_text = rental.group(1)
            rows.append(
                {
                    "category": "return_window",
                    "subtype": "rental_return",
                    "term_label": "",
                    "scope": "Rental Textbooks",
                    "term_or_scope": "Rental Textbooks",
                    "date_text": date_text,
                    "date_iso": parse_date_to_iso(date_text),
                }
            )
            break

    return dedupe_rows(rows)


def academic_year_start(today: date | None = None) -> date:
    today = today or date.today()
    year = today.year if today.month >= 7 else today.year - 1
    return date(year, 7, 1)


def validate_rows(rows: list[dict]) -> tuple[bool, list[str]]:
    errors = []
    opt_out = [row for row in rows if row.get("category") == "opt_out"]
    welcome = [row for row in rows if row.get("category") == "welcome_email"]
    return_windows = [row for row in rows if row.get("category") == "return_window"]
    if len(opt_out) < 4:
        errors.append(f"opt_out rows < 4 ({len(opt_out)})")
    if len(welcome) < 4:
        errors.append(f"welcome_email rows < 4 ({len(welcome)})")
    for row in rows:
        try:
            datetime.strptime(row.get("date_iso", ""), "%Y-%m-%d")
        except ValueError:
            errors.append(f"invalid ISO date for row: {row}")
    cutoff = academic_year_start()
    if not any(datetime.strptime(row["date_iso"], "%Y-%m-%d").date() >= cutoff for row in rows if row.get("date_iso")):
        errors.append(f"no parsed date is in the current/future academic year starting {cutoff.isoformat()}")
    if not any(row.get("category") == "return_window" and row.get("subtype") == "final_after" for row in rows):
        errors.append("return-window rows missing final_after")
    return not errors, errors


def strip_volatile_date_lines(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = normalize_space(raw_line)
        if not line:
            continue
        if SHORT_DATE_RE.search(line) or LONG_DATE_RE.search(line):
            continue
        if "email-protection" in line:
            continue
        lines.append(line)
    return lines


def extract_ia_prose(html: str) -> list[str]:
    soup = soup_without_email_protection(html)
    text = soup.get_text("\n", strip=True)
    start = text.lower().find("immediate access program:")
    end = text.lower().find("important dates", start if start != -1 else 0)
    if start != -1 and end != -1:
        text = text[start:end]
    lines = strip_volatile_date_lines(text)
    keep = []
    for line in lines:
        lower = line.lower()
        if lower in {"immediate access", "immediate access program:", "main objectives"}:
            continue
        if len(line) > 40 or lower.startswith(("reduce cost", "provide immediate access")):
            keep.append(line)
    return keep[:12]


def extract_return_prose(html: str) -> list[str]:
    text = find_refund_policy_text(html)
    start = text.lower().find("textbooks")
    end = text.lower().find("general merchandise", start if start != -1 else 0)
    if start != -1 and end != -1:
        text = text[start:end]
    lines = strip_volatile_date_lines(text)
    keep = []
    for line in lines:
        lower = line.lower()
        if lower in {"textbooks", "textbook faq", "page for more information.", "the following items are final sale:"}:
            continue
        if "academic school year" in lower or lower.startswith("purchases made for"):
            continue
        if len(line) > 25 or lower in {
            "arc / art / des / ill kits",
            "opened shrink-wrapped textbooks",
            "access codes / digital content",
            "lab coats",
            "pre-paid items",
            'items marked "final sale"',
        }:
            keep.append(line)
    return keep[:20]


def render_ia_overview(ia_html: str) -> str:
    prose = extract_ia_prose(ia_html)
    if not prose:
        prose = [
            "Immediate Access provides eligible digital course materials through Canvas.",
            "Students may opt out during the posted semester opt-out window.",
        ]
    bullets = "\n".join(f"- {line}" for line in prose)
    return f"""---
source_id: ia_overview
source_type: faq
category: immediate_access
platform: null
issue_type: overview
priority: canonical
---

QUESTION:
What is Immediate Access?

ANSWER:
Immediate Access is California Baptist University's program for providing eligible digital course materials through Canvas and billing them through the student account.

Current program notes from the Campus Store:
{bullets}

Opt-out and welcome-email dates are refreshed into the structured policy cache and should be checked there for semester-specific answers.

Article link: "https://bookstore.calbaptist.edu/ia"
"""


def render_textbook_refund_policy(customerservice_html: str) -> str:
    prose = extract_return_prose(customerservice_html)
    if not prose:
        prose = [
            "Textbook returns are subject to Campus Store refund conditions and semester-specific deadlines.",
            "Access codes and digital content are final sale items.",
        ]
    bullets = "\n".join(f"- {line}" for line in prose)
    return f"""---
source_id: textbook_refund_policy
source_type: faq
category: textbook_return
platform: null
issue_type: return_refund
priority: canonical
---

Textbook Refund Policy - FAQ

[FAQ_1]
1. What is the Campus Store textbook return policy?
Textbook returns and exchanges are governed by the Campus Store Refund Policy. Semester-specific return-window dates are refreshed into the structured policy cache and should be checked there for current deadlines.
Article link: "https://bookstore.calbaptist.edu/customerservice"

[FAQ_2]
2. What return conditions apply to textbooks and course materials?
{bullets}
Article link: "https://bookstore.calbaptist.edu/customerservice"

[FAQ_3]
3. Are access codes or digital content refundable?
No. Access codes and digital content are final sale items and are not eligible for return or refund.
Article link: "https://bookstore.calbaptist.edu/customerservice"

[FAQ_11]
11. If I opt out of Immediate Access, are the physical textbooks for my courses available in the Campus Store?
No. The Campus Store does not carry print alternatives for textbooks delivered through Immediate Access. This prevents students from purchasing the same material in-store after it has already been charged through Immediate Access. Students who want print copies may purchase them independently from their preferred textbook retailer.
Article link: "https://bookstore.calbaptist.edu/customerservice"
"""


def write_with_backup(path: Path, content: str) -> Path:
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8")
    return backup


def restore_backup(path: Path, backup: Path) -> None:
    if backup.exists():
        shutil.copy2(backup, path)


def run_ingest() -> None:
    candidates = [
        [sys.executable, "-m", "app.rag.ingest"],
        [sys.executable, "app/rag/ingest.py"],
    ]
    last_error: Exception | None = None
    for command in candidates:
        try:
            subprocess.run(command, cwd=ROOT, check=True)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"ingest failed: {last_error}")


def write_outputs(rows: list[dict], ia_html: str, customerservice_html: str) -> None:
    backups: list[tuple[Path, Path]] = []
    try:
        backups.append((IA_OVERVIEW_PATH, write_with_backup(IA_OVERVIEW_PATH, render_ia_overview(ia_html))))
        backups.append(
            (
                TEXTBOOK_REFUND_PATH,
                write_with_backup(TEXTBOOK_REFUND_PATH, render_textbook_refund_policy(customerservice_html)),
            )
        )
        run_ingest()
        upsert_policy_dates(rows)
    except Exception:
        for path, backup in backups:
            restore_backup(path, backup)
        raise


def scrape() -> tuple[list[dict], list[dict], str, str]:
    ia_html, customerservice_html = fetch_policy_pages()
    ia_rows = parse_ia_dates(ia_html)
    return_rows = parse_return_windows(customerservice_html)
    return ia_rows, return_rows, ia_html, customerservice_html


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh IA and Campus Store policy dates.")
    parser.add_argument("--dry-run", action="store_true", help="Scrape, validate, and print only.")
    args = parser.parse_args()

    ia_rows, return_rows, ia_html, customerservice_html = scrape()
    rows = ia_rows + return_rows
    valid, errors = validate_rows(rows)

    print("Parsed IA rows:")
    print(json.dumps(ia_rows, indent=2))
    print("\nParsed return-window rows:")
    print(json.dumps(return_rows, indent=2))
    print("\nValidation:")
    print(json.dumps({"valid": valid, "errors": errors}, indent=2))

    if not valid:
        print("Validation failed; no DB, RAG, or index files were modified.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    write_outputs(rows, ia_html, customerservice_html)
    print(f"Refreshed {len(rows)} policy rows and rebuilt the FAISS index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
