"""
SQLite-backed lead store. Handles deduplication, CRM lifecycle fields,
and persistence across Streamlit sessions.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .pipeline import OUTPUT_FIELDS

DB_PATH = Path(__file__).resolve().parent.parent / "leads.db"

EXTRA_COLS = ["pipeline_status", "last_scraped_at", "edited_email_draft", "notes"]
ALL_COLS = list(OUTPUT_FIELDS) + EXTRA_COLS

PIPELINE_STATUSES = [
    "New", "Reviewing", "Approved", "Rejected",
    "Contacted", "Replied", "Won", "Lost", "Suppressed",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table(conn: sqlite3.Connection):
    col_defs = ", ".join(f'"{col}" TEXT' for col in ALL_COLS)
    conn.execute(f'CREATE TABLE IF NOT EXISTS leads ({col_defs}, UNIQUE("Website"))')
    cur = conn.execute("PRAGMA table_info(leads)")
    existing = {row[1] for row in cur.fetchall()}
    for col in ALL_COLS:
        if col not in existing:
            default = "'New'" if col == "pipeline_status" else "''"
            conn.execute(f'ALTER TABLE leads ADD COLUMN "{col}" TEXT DEFAULT {default}')
    conn.commit()


def init():
    conn = _connect()
    _ensure_table(conn)
    conn.close()


def lookup(website: str) -> Optional[dict]:
    conn = _connect()
    _ensure_table(conn)
    cols = ", ".join(f'"{c}"' for c in ALL_COLS)
    cur = conn.execute(f'SELECT {cols} FROM leads WHERE "Website" = ?', (website,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {col: (val or "") for col, val in zip(ALL_COLS, row)}


def upsert_pipeline_result(row: dict):
    """Insert or update from pipeline output.  Sets last_scraped_at;
    preserves CRM-only fields (pipeline_status, edited_email_draft, notes)
    on UPDATE so a re-scrape doesn't wipe manual edits."""
    conn = _connect()
    _ensure_table(conn)
    now = datetime.utcnow().isoformat()

    values = [str(row.get(c, "")) for c in OUTPUT_FIELDS]
    values += ["Reviewing", now, "", ""]

    cols = ", ".join(f'"{c}"' for c in ALL_COLS)
    placeholders = ", ".join("?" for _ in ALL_COLS)
    update_parts = [f'"{c}" = excluded."{c}"' for c in OUTPUT_FIELDS if c != "Website"]
    update_parts.append('"last_scraped_at" = excluded."last_scraped_at"')
    conflict = ", ".join(update_parts)

    conn.execute(
        f'INSERT INTO leads ({cols}) VALUES ({placeholders}) '
        f'ON CONFLICT("Website") DO UPDATE SET {conflict}',
        tuple(values),
    )
    conn.commit()
    conn.close()


def insert_manual_lead(company: str, website: str, niche: str = "", notes: str = ""):
    """Insert a manually-added lead with Pipeline Status 'New'.
    If the website already exists, only company/niche/notes are updated."""
    conn = _connect()
    _ensure_table(conn)
    row_data = {c: "" for c in ALL_COLS}
    row_data["Company Name"] = company
    row_data["Website"] = website
    row_data["Niche Profile"] = niche
    row_data["pipeline_status"] = "New"
    row_data["notes"] = notes

    cols = ", ".join(f'"{c}"' for c in ALL_COLS)
    placeholders = ", ".join("?" for _ in ALL_COLS)
    conn.execute(
        f'INSERT INTO leads ({cols}) VALUES ({placeholders}) '
        f'ON CONFLICT("Website") DO UPDATE SET '
        f'"Company Name" = excluded."Company Name", '
        f'"Niche Profile" = excluded."Niche Profile", '
        f'"notes" = excluded."notes"',
        tuple(str(row_data[c]) for c in ALL_COLS),
    )
    conn.commit()
    conn.close()


def update_fields(website: str, **fields):
    if not fields:
        return
    conn = _connect()
    _ensure_table(conn)
    set_clause = ", ".join(f'"{k}" = ?' for k in fields)
    values = list(fields.values()) + [website]
    conn.execute(f'UPDATE leads SET {set_clause} WHERE "Website" = ?', tuple(values))
    conn.commit()
    conn.close()


def upsert_many(rows: list[dict]):
    conn = _connect()
    _ensure_table(conn)
    cols = ", ".join(f'"{c}"' for c in ALL_COLS)
    placeholders = ", ".join("?" for _ in ALL_COLS)
    conflict = ", ".join(f'"{c}" = excluded."{c}"' for c in ALL_COLS if c != "Website")
    sql = (
        f'INSERT INTO leads ({cols}) VALUES ({placeholders}) '
        f'ON CONFLICT("Website") DO UPDATE SET {conflict}'
    )
    conn.executemany(sql, [
        tuple(str(r.get(c, "")) for c in ALL_COLS) for r in rows
    ])
    conn.commit()
    conn.close()


def load_all() -> list[dict]:
    conn = _connect()
    _ensure_table(conn)
    cols = ", ".join(f'"{c}"' for c in ALL_COLS)
    cur = conn.execute(f"SELECT {cols} FROM leads")
    rows = cur.fetchall()
    conn.close()
    return [{col: (val or "") for col, val in zip(ALL_COLS, row)} for row in rows]


def load_stale(days: int) -> list[dict]:
    conn = _connect()
    _ensure_table(conn)
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cols = ", ".join(f'"{c}"' for c in ALL_COLS)
    cur = conn.execute(
        f'SELECT {cols} FROM leads '
        f'WHERE "last_scraped_at" = "" OR "last_scraped_at" IS NULL OR "last_scraped_at" < ?',
        (cutoff,),
    )
    rows = cur.fetchall()
    conn.close()
    return [{col: (val or "") for col, val in zip(ALL_COLS, row)} for row in rows]


def diff_import(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    existing_websites = {r["Website"] for r in load_all()}
    new = [r for r in rows if r.get("Website", "") not in existing_websites]
    updates = [r for r in rows if r.get("Website", "") in existing_websites]
    return new, updates


def count() -> int:
    conn = _connect()
    _ensure_table(conn)
    cur = conn.execute("SELECT COUNT(*) FROM leads")
    n = cur.fetchone()[0]
    conn.close()
    return n


def clear():
    conn = _connect()
    _ensure_table(conn)
    conn.execute("DELETE FROM leads")
    conn.commit()
    conn.close()
