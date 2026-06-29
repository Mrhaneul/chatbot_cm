from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mbs_insite_probe import (  # noqa: E402
    _parse_dropdown_items,
    add_course,
    delete_course,
    fetch_materials_html,
    get_courses,
    get_departments,
    get_terms,
    make_session,
    parse_materials,
)


DB_PATH = ROOT / "data" / "bookstore_cache.db"
OUT_DIR = ROOT / "scripts"


TARGETS = [
    {
        "dept": "NUR",
        "course": "502",
        "section": "A",
        "missing": [
            {
                "name": "Ogden PAPERBACK",
                "isbn": "9780323826228",
                "keywords": ["OGDEN", "CALCULATION OF DRUG"],
                "format_words": ["PAPERBACK"],
            }
        ],
    },
    {
        "dept": "RAD",
        "course": "425",
        "section": "A",
        "missing": [
            {
                "name": "digital option",
                "isbn": "9781260474947",
                "keywords": ["LANGE", "MAMMOGRAPHY"],
                "format_words": ["DIGITAL", "VITAL SOURCE"],
            }
        ],
    },
    {
        "dept": "SWK",
        "course": "720",
        "section": "A",
        "missing": [
            {
                "name": "Little Seagull PRINT",
                "isbn": "9781324060000",
                "keywords": ["LITTLE SEAGULL"],
                "format_words": ["PAPERBACK", "PRINT"],
            },
            {
                "name": "They Say/I Say PRINT",
                "isbn": "9781324070030",
                "keywords": ["THEY SAY", "I SAY"],
                "format_words": ["PAPERBACK", "PRINT"],
            },
        ],
    },
]


def norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def course_key(target: dict[str, Any]) -> str:
    return f"{target['dept']}{target['course']}{target['section']}"


def get_cached_course_id(target: dict[str, Any]) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT id
            FROM courses
            WHERE lower(trim(department)) = lower(trim(?))
              AND lower(trim(course_number)) = lower(trim(?))
              AND lower(trim(section)) = lower(trim(?))
            ORDER BY last_refreshed DESC
            LIMIT 1
            """,
            (target["dept"], target["course"], target["section"]),
        ).fetchone()
    return row[0] if row else None


def label_matches_course(label: str, target: dict[str, Any]) -> bool:
    label_norm = re.sub(r"\s+", " ", norm(label))
    dept = re.escape(target["dept"])
    course = re.escape(target["course"])
    section = re.escape(target["section"])
    patterns = [
        rf"\b{dept}\s*{course}\s*{section}\b",
        rf"\b{dept}\s*{course}\b.*\b{section}\b",
        rf"\b{course}\s*{section}\b",
        rf"\b{course}\b.*\b{section}\b",
    ]
    return any(re.search(pattern, label_norm) for pattern in patterns)


def find_live_cs_id(client, token: str, target: dict[str, Any]) -> str | None:
    terms = _parse_dropdown_items(get_terms(client, token, verbose=False), "ter")
    summer_terms = [term for term in terms if "SUMMER" in norm(term["label"])]
    candidate_labels: list[str] = []

    for term in summer_terms:
        departments = _parse_dropdown_items(get_departments(client, token, term["id"], verbose=False), "dpt")
        dept_matches = [
            dept for dept in departments
            if norm(dept["label"]).startswith(target["dept"])
            or norm(dept["label"]) == target["dept"]
            or f"({target['dept']})" in norm(dept["label"])
        ]
        for dept in dept_matches:
            courses = _parse_dropdown_items(
                get_courses(client, token, term["id"], dept["id"], verbose=False),
                "cou",
            )
            for course in courses:
                if target["course"] in norm(course["label"]):
                    candidate_labels.append(f"{term['label']} | {dept['label']} | {course['label']} | {course['raw_id']}")
                if label_matches_course(course["label"], target):
                    print(
                        "resolved live csId:",
                        f"{target['dept']} {target['course']} {target['section']}",
                        "->",
                        course["id"],
                        f"({term['label']} / {course['label']})",
                    )
                    return course["id"]

    print(f"could not resolve live csId for {target['dept']} {target['course']} {target['section']}")
    if candidate_labels:
        print("  candidates:")
        for label in candidate_labels[:20]:
            print("   ", label)
    return None


def flatten_parsed_materials(parsed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    books: list[dict[str, Any]] = []
    for course in parsed:
        books.extend(course.get("books") or [])
    return books


def visible_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def find_near(text: str, keywords: list[str], format_words: list[str], window: int = 900) -> tuple[bool, str]:
    upper = norm(text)
    positions = [upper.find(keyword) for keyword in keywords if upper.find(keyword) >= 0]
    if not positions:
        return False, ""
    start = max(min(positions) - window // 2, 0)
    end = min(min(positions) + window // 2, len(text))
    snippet = text[start:end]
    snippet_upper = norm(snippet)
    has_format = any(word in snippet_upper for word in format_words)
    return has_format, snippet


def find_material_in_html(html: str, material: dict[str, Any]) -> tuple[bool, str, int]:
    if material.get("isbn") and material["isbn"] in html:
        return True, material["isbn"], 0

    soup = BeautifulSoup(html, "html.parser")
    best_snippet = ""
    for block in soup.select(".courseBookDetail"):
        block_text = block.get_text("\n", strip=True)
        block_upper = norm(block_text)
        if not any(keyword in block_upper for keyword in material["keywords"]):
            continue
        best_snippet = block_text
        has_format = any(word in block_upper for word in material["format_words"])
        if has_format:
            return True, block_text, count_price_options(str(block))
    return False, best_snippet, count_price_options(best_snippet)


def parsed_contains(parsed_books: list[dict[str, Any]], material: dict[str, Any]) -> bool:
    if material.get("isbn"):
        for book in parsed_books:
            if str(book.get("isbn") or "").strip() == material["isbn"]:
                return True
    for book in parsed_books:
        haystack = " ".join(
            norm(book.get(field))
            for field in ("title", "author", "format", "notes", "requirement")
        )
        if any(keyword in haystack for keyword in material["keywords"]) and any(
            word in haystack for word in material["format_words"]
        ):
            return True
    return False


def count_price_options(snippet: str) -> int:
    dollar_prices = re.findall(r"\$\s*\d+(?:\.\d{2})?", snippet)
    json_prices = re.findall(r'"amount"\s*:', snippet)
    return max(len(dollar_prices), len(json_prices))


def print_context_lines(html: str, material: dict[str, Any], line_count: int = 30) -> None:
    lines = html.splitlines()
    upper_lines = [norm(line) for line in lines]
    hit_index = None
    for i, line in enumerate(upper_lines):
        if any(keyword in line for keyword in material["keywords"]):
            hit_index = i
            break
    if hit_index is None:
        return
    half = line_count // 2
    start = max(hit_index - half, 0)
    end = min(hit_index + half, len(lines))
    print(f"\nRAW HTML CONTEXT for {material['name']} ({end - start} lines):")
    for line in lines[start:end]:
        print(line)


def verify_target(target: dict[str, Any]) -> list[dict[str, str]]:
    label = f"{target['dept']} {target['course']} {target['section']}"
    cached_id = get_cached_course_id(target)
    print("\n" + "=" * 80)
    print(label)
    print("cached courses.id:", cached_id or "<missing>")
    if cached_id and not cached_id.isdigit():
        print("cached id is not numeric csId; resolving live csId from MBS dropdowns")

    client, token = make_session()
    cs_id = cached_id if cached_id and cached_id.isdigit() else find_live_cs_id(client, token, target)
    if not cs_id:
        return [
            {
                "course": label,
                "material": material["name"],
                "verdict": "SKIPPED_NO_CSID",
            }
            for material in target["missing"]
        ]

    add_course(client, cs_id, token=token, verbose=True)
    try:
        html = fetch_materials_html(client, cs_id=cs_id)
        raw_path = OUT_DIR / f"raw_{course_key(target)}.html"
        raw_path.write_text(html, encoding="utf-8")
        print("saved raw html:", raw_path)

        parsed = parse_materials(html)
        parsed_books = flatten_parsed_materials(parsed)
        print("parsed materials:")
        print(json.dumps(parsed, indent=2))

        text = visible_text(html)
        rows: list[dict[str, str]] = []
        for material in target["missing"]:
            in_html, snippet, price_options = find_material_in_html(html, material)
            in_parsed = parsed_contains(parsed_books, material)
            verdict = "IN_HTML_NOT_PARSED" if in_html and not in_parsed else "NOT_IN_HTML"
            if in_html and in_parsed:
                verdict = "IN_HTML_AND_PARSED"
            parsed_title_matches = [
                book for book in parsed_books
                if any(keyword in " ".join(norm(book.get(field)) for field in ("title", "author", "notes")) for keyword in material["keywords"])
            ]
            print(f"missing material check: {material['name']}")
            print("  html contains title+format near each other:", in_html)
            print("  parsed contains title+format:", in_parsed)
            print("  raw snippet price-option heuristic:", price_options)
            print("  parsed title matches:", len(parsed_title_matches))
            if in_html and not in_parsed:
                print_context_lines(html, material)
            rows.append({"course": label, "material": material["name"], "verdict": verdict})
        return rows
    finally:
        delete_course(client, cs_id, token=token, verbose=True)


def main() -> None:
    summary: list[dict[str, str]] = []
    for target in TARGETS:
        summary.extend(verify_target(target))

    print("\n=== SUMMARY ===")
    print("course | material | verdict")
    for row in summary:
        print(f"{row['course']} | {row['material']} | {row['verdict']}")


if __name__ == "__main__":
    main()
