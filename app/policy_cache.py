"""
SQLite cache for semester policy dates scraped from the Campus Store site.

The policy scraper writes structured opt-out, welcome-email, and textbook
return-window dates here so RAG prose does not need to carry volatile dates.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path("data/policy_cache.db")


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS policy_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            subtype TEXT,
            term_label TEXT,
            scope TEXT,
            date_text TEXT,
            date_iso TEXT,
            last_refreshed TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_policy_dates_category
            ON policy_dates(category, subtype);
        CREATE INDEX IF NOT EXISTS idx_policy_dates_term
            ON policy_dates(term_label);
        CREATE INDEX IF NOT EXISTS idx_policy_dates_scope
            ON policy_dates(scope);
        """
    )


def _norm(value: Optional[str]) -> str:
    return (value or "").strip()


def _fresh_cutoff(max_age_days: Optional[float]) -> str:
    if max_age_days is None:
        return ""
    seconds = max(float(max_age_days), 0.0) * 86400
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def upsert_policy_dates(rows: list[dict]) -> None:
    """Replace full snapshots for each category present in rows."""
    now = datetime.now(timezone.utc).isoformat()
    categories = sorted({_norm(row.get("category")) for row in rows if _norm(row.get("category"))})
    if not categories:
        return

    with _connect() as conn:
        with conn:
            for category in categories:
                conn.execute("DELETE FROM policy_dates WHERE category = ?", (category,))
            for row in rows:
                category = _norm(row.get("category"))
                if not category:
                    continue
                conn.execute(
                    """
                    INSERT INTO policy_dates (
                        category, subtype, term_label, scope, date_text,
                        date_iso, last_refreshed
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        category,
                        _norm(row.get("subtype")),
                        _norm(row.get("term_label")),
                        _norm(row.get("scope") or row.get("term_or_scope")),
                        _norm(row.get("date_text")),
                        _norm(row.get("date_iso")),
                        now,
                    ),
                )


def _query_policy_dates(
    category: str,
    *,
    term_label: Optional[str] = None,
    scope: Optional[str] = None,
    max_age_days: Optional[float] = 365,
) -> list[dict]:
    query = """
        SELECT *
        FROM policy_dates
        WHERE lower(trim(category)) = lower(trim(?))
    """
    params: list[str] = [_norm(category)]
    if term_label:
        query += " AND lower(trim(term_label)) = lower(trim(?))"
        params.append(_norm(term_label))
    if scope:
        query += " AND lower(trim(scope)) = lower(trim(?))"
        params.append(_norm(scope))
    cutoff = _fresh_cutoff(max_age_days)
    if cutoff:
        query += " AND last_refreshed >= ?"
        params.append(cutoff)
    query += " ORDER BY date_iso, subtype, term_label, scope"

    with _connect() as conn:
        return [_row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def get_opt_out_deadline(term_label=None, max_age_days=365):
    rows = _query_policy_dates(
        "opt_out",
        term_label=term_label,
        max_age_days=max_age_days,
    )
    if term_label:
        return rows[0] if rows else None
    return rows


def get_return_deadline(term_or_scope=None, max_age_days=365):
    return _query_policy_dates(
        "return_window",
        scope=term_or_scope,
        max_age_days=max_age_days,
    )
