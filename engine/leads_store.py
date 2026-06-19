"""
SQLite-backed lead store for deduplication and persistence across sessions.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from .pipeline import OUTPUT_FIELDS

DB_PATH = Path(__file__).resolve().parent.parent / "leads.db"

_TEXT_COLS = [f for f in OUTPUT_FIELDS]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table(conn: sqlite3.Connection):
    col_defs = ", ".join(
        f'"{col}" TEXT' for col in _TEXT_COLS
    )
    conn.execute(f'CREATE TABLE IF NOT EXISTS leads ({col_defs}, UNIQUE("Website"))')
    conn.commit()


def init():
    conn = _connect()
    _ensure_table(conn)
    conn.close()


def lookup(website: str) -> Optional[dict]:
    conn = _connect()
    _ensure_table(conn)
    cols = ", ".join(f'"{c}"' for c in _TEXT_COLS)
    cur = conn.execute(f'SELECT {cols} FROM leads WHERE "Website" = ?', (website,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {col: (val or "") for col, val in zip(_TEXT_COLS, row)}


def upsert(row: dict):
    conn = _connect()
    _ensure_table(conn)
    cols = ", ".join(f'"{c}"' for c in _TEXT_COLS)
    placeholders = ", ".join("?" for _ in _TEXT_COLS)
    conflict = ", ".join(f'"{c}" = excluded."{c}"' for c in _TEXT_COLS if c != "Website")
    conn.execute(
        f'INSERT INTO leads ({cols}) VALUES ({placeholders}) '
        f'ON CONFLICT("Website") DO UPDATE SET {conflict}',
        tuple(str(row.get(c, "")) for c in _TEXT_COLS),
    )
    conn.commit()
    conn.close()


def upsert_many(rows: list[dict]):
    conn = _connect()
    _ensure_table(conn)
    cols = ", ".join(f'"{c}"' for c in _TEXT_COLS)
    placeholders = ", ".join("?" for _ in _TEXT_COLS)
    conflict = ", ".join(f'"{c}" = excluded."{c}"' for c in _TEXT_COLS if c != "Website")
    sql = (
        f'INSERT INTO leads ({cols}) VALUES ({placeholders}) '
        f'ON CONFLICT("Website") DO UPDATE SET {conflict}'
    )
    conn.executemany(sql, [
        tuple(str(r.get(c, "")) for c in _TEXT_COLS) for r in rows
    ])
    conn.commit()
    conn.close()


def load_all() -> list[dict]:
    conn = _connect()
    _ensure_table(conn)
    cols = ", ".join(f'"{c}"' for c in _TEXT_COLS)
    cur = conn.execute(f"SELECT {cols} FROM leads")
    rows = cur.fetchall()
    conn.close()
    return [{col: (val or "") for col, val in zip(_TEXT_COLS, row)} for row in rows]


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
