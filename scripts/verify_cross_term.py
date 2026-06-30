from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/bookstore_cache.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def material_label(row: sqlite3.Row) -> str:
    isbn = (row["isbn"] or "").strip() or "NO_ISBN"
    title = (row["title"] or "").strip() or "Untitled"
    requirement = (row["requirement"] or "").strip()
    formats_raw = row["formats"] or ""
    try:
        formats = json.loads(formats_raw) if formats_raw else []
    except json.JSONDecodeError:
        formats = []
    format_text = ", ".join(formats) if formats else (row["format"] or "").strip()
    suffix = []
    if requirement:
        suffix.append(requirement)
    if format_text:
        suffix.append(format_text)
    suffix_text = f" ({'; '.join(suffix)})" if suffix else ""
    return f"{isbn} | {title}{suffix_text}"


def get_multi_term_sections(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT department, course_number, section, COUNT(DISTINCT term) tc,
               GROUP_CONCAT(DISTINCT term) terms
        FROM courses
        GROUP BY department, course_number, section
        HAVING tc > 1
        ORDER BY tc DESC, department, course_number, section
        """
    ).fetchall()


def get_course_terms(conn: sqlite3.Connection, course: sqlite3.Row) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, term, instructor, course_code
        FROM courses
        WHERE department = ?
          AND course_number = ?
          AND section = ?
        ORDER BY term
        """,
        (course["department"], course["course_number"], course["section"]),
    ).fetchall()


def get_materials(conn: sqlite3.Connection, course_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT isbn, title, requirement, format, formats
        FROM books
        WHERE course_id = ?
        ORDER BY title, isbn, id
        """,
        (course_id,),
    ).fetchall()


def material_signature(materials: list[sqlite3.Row]) -> tuple[str, ...]:
    return tuple(material_label(row) for row in materials)


def print_first_ten(multi_term: list[sqlite3.Row]) -> None:
    print(f"Multi-term course-sections found: {len(multi_term)}")
    print("First 10 multi-term course-sections:")
    for row in multi_term[:10]:
        print(
            f"- {row['department']} {row['course_number']} section {row['section']} "
            f"({row['tc']} terms): {row['terms']}"
        )
    if not multi_term:
        print("- none")


def inspect_first_five(conn: sqlite3.Connection, multi_term: list[sqlite3.Row]) -> list[str]:
    reasons: list[str] = []
    print()
    print("Per-term material comparison for first 5 multi-term course-sections:")
    for row in multi_term[:5]:
        label = f"{row['department']} {row['course_number']} section {row['section']}"
        print()
        print(f"=== {label} ===")
        term_rows = get_course_terms(conn, row)
        counts: list[int] = []
        signatures = []
        for term_row in term_rows:
            materials = get_materials(conn, term_row["id"])
            counts.append(len(materials))
            sig = material_signature(materials)
            signatures.append(sig)
            instructor = (term_row["instructor"] or "").strip() or "Instructor not listed"
            print(f"[{term_row['term']}] course_id={term_row['id']} instructor={instructor}")
            if not materials:
                print("  - no materials")
            else:
                for item in sig:
                    print(f"  - {item}")

        unique_signatures = len(set(signatures))
        if unique_signatures == 1:
            print("Comparison: identical material sets across terms (may be legitimate).")
        else:
            print("Comparison: different material sets across terms.")

        max_count = max(counts) if counts else 0
        min_positive = min((count for count in counts if count > 0), default=0)
        if min_positive and max_count >= min_positive * 2 and max_count - min_positive >= 2:
            msg = f"POSSIBLE BLEED: {label} material counts vary sharply: {counts}"
            print(msg)
            reasons.append(msg)
        else:
            print("Sanity flag: looks clean")
    return reasons


def check_duplicate_material_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT course_id, isbn, COUNT(*) count
        FROM books
        GROUP BY course_id, isbn
        HAVING COUNT(*) > 1
        ORDER BY count DESC, course_id, isbn
        """
    ).fetchall()


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Review needed: cache database missing")
        return 1

    review_reasons: list[str] = []
    with connect() as conn:
        multi_term = get_multi_term_sections(conn)
        print_first_ten(multi_term)
        review_reasons.extend(inspect_first_five(conn, multi_term))

        print()
        print("Duplicate material row check:")
        duplicates = check_duplicate_material_rows(conn)
        if duplicates:
            for row in duplicates:
                isbn = (row["isbn"] or "").strip() or "NO_ISBN"
                print(f"- course_id={row['course_id']} isbn={isbn} count={row['count']}")
            review_reasons.append(f"{len(duplicates)} duplicate material row group(s)")
        else:
            print("no duplicate material rows")

    print()
    if review_reasons:
        print(f"Review needed: {'; '.join(review_reasons)}")
        return 1
    print("Cross-term data clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
