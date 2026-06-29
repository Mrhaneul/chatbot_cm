"""
SQLite cache for bookstore course-material records.

The probe writes parsed MBS InSite records here so the chatbot can later answer
course-material lookup questions without scraping the bookstore in request time.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path("data/bookstore_cache.db")


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY,
            term TEXT,
            department TEXT,
            course_number TEXT,
            section TEXT,
            instructor TEXT,
            course_code TEXT,
            last_refreshed TEXT
        );

        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            isbn TEXT,
            title TEXT,
            author TEXT,
            edition TEXT,
            publisher TEXT,
            requirement TEXT,
            immediate_access INTEGER,
            format TEXT,
            price TEXT,
            hide_pricing INTEGER,
            publisher_direct_link TEXT,
            notes TEXT,
            image_url TEXT,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_courses_lookup
            ON courses(department, course_number, section, term);
        CREATE INDEX IF NOT EXISTS idx_courses_instructor
            ON courses(instructor, term);
        CREATE INDEX IF NOT EXISTS idx_books_course_id
            ON books(course_id);
        """
    )


def _norm(value: Optional[str]) -> str:
    return (value or "").strip()


def _row_to_course(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    course = dict(row)
    books = conn.execute(
        """
        SELECT isbn, title, author, edition, publisher, requirement,
               immediate_access, format, price, hide_pricing,
               publisher_direct_link, notes, image_url
        FROM books
        WHERE course_id = ?
        ORDER BY id
        """,
        (course["id"],),
    ).fetchall()
    course["books"] = []
    for book_row in books:
        book = dict(book_row)
        book["immediate_access"] = bool(book["immediate_access"])
        book["hide_pricing"] = bool(book["hide_pricing"])
        course["books"].append(book)
    return course


def _book_price(book: dict) -> str:
    prices = book.get("prices")
    if isinstance(prices, list):
        return json.dumps(prices, ensure_ascii=False)
    return _norm(book.get("price"))


def upsert_courses(records: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        for record in records:
            course_id = _norm(record.get("course_id"))
            if not course_id:
                continue
            conn.execute(
                """
                INSERT INTO courses (
                    id, term, department, course_number, section, instructor,
                    course_code, last_refreshed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    term = excluded.term,
                    department = excluded.department,
                    course_number = excluded.course_number,
                    section = excluded.section,
                    instructor = excluded.instructor,
                    course_code = excluded.course_code,
                    last_refreshed = excluded.last_refreshed
                """,
                (
                    course_id,
                    _norm(record.get("term")),
                    _norm(record.get("department")),
                    _norm(record.get("course_number")),
                    _norm(record.get("section")),
                    _norm(record.get("instructor")),
                    _norm(record.get("course_code")),
                    now,
                ),
            )
            conn.execute("DELETE FROM books WHERE course_id = ?", (course_id,))
            for book in record.get("books", []):
                conn.execute(
                    """
                    INSERT INTO books (
                        course_id, isbn, title, author, edition, publisher,
                        requirement, immediate_access, format, price,
                        hide_pricing, publisher_direct_link, notes, image_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        course_id,
                        _norm(book.get("isbn")),
                        _norm(book.get("title")),
                        _norm(book.get("author")),
                        _norm(book.get("edition")),
                        _norm(book.get("publisher")),
                        _norm(book.get("requirement")),
                        1 if book.get("immediate_access") else 0,
                        _norm(book.get("format")),
                        _book_price(book),
                        1 if book.get("hide_pricing") else 0,
                        _norm(book.get("publisher_direct_link")),
                        _norm(book.get("notes")),
                        _norm(book.get("image")),
                    ),
                )


def lookup_course(dept, course_number, section, term=None) -> Optional[dict]:
    dept = _norm(dept)
    course_number = _norm(course_number)
    section = _norm(section)
    term = _norm(term)

    query = """
        SELECT *
        FROM courses
        WHERE lower(trim(department)) = lower(trim(?))
          AND lower(trim(course_number)) = lower(trim(?))
          AND lower(trim(section)) = lower(trim(?))
    """
    params: list[str] = [dept, course_number, section]
    if term:
        query += " AND lower(trim(term)) = lower(trim(?))"
        params.append(term)
    query += " ORDER BY last_refreshed DESC LIMIT 1"

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
        return _row_to_course(conn, row) if row else None


def lookup_by_instructor(instructor_name, term=None) -> list[dict]:
    instructor_name = _norm(instructor_name)
    term = _norm(term)

    query = """
        SELECT *
        FROM courses
        WHERE lower(trim(instructor)) LIKE lower(trim(?))
    """
    params: list[str] = [f"%{instructor_name}%"]
    if term:
        query += " AND lower(trim(term)) = lower(trim(?))"
        params.append(term)
    query += " ORDER BY last_refreshed DESC, term, department, course_number, section"

    with _connect() as conn:
        return [_row_to_course(conn, row) for row in conn.execute(query, params).fetchall()]
