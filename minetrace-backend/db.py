"""SQLite storage. One file, no server, works fully offline."""

import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mineral TEXT NOT NULL,
    hs_code TEXT NOT NULL,
    year INTEGER NOT NULL,
    reporter_iso TEXT NOT NULL,      -- country that reported the record
    partner_iso TEXT NOT NULL,       -- its trading partner
    flow TEXT NOT NULL CHECK (flow IN ('X', 'M')),   -- X = export, M = import
    value_usd REAL,
    net_weight_kg REAL,
    is_reported INTEGER,             -- 1 = reported by the country, 0 = estimated by UN
    source TEXT NOT NULL DEFAULT 'UN Comtrade',
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (hs_code, year, reporter_iso, partner_iso, flow)
);

CREATE INDEX IF NOT EXISTS idx_flows_mineral_year ON trade_flows (mineral, year);

CREATE TABLE IF NOT EXISTS sanctions_exposure (
    iso3 TEXT PRIMARY KEY,
    sanctioned_entities INTEGER NOT NULL DEFAULT 0,
    mining_linked_entities INTEGER NOT NULL DEFAULT 0,
    sample_entities TEXT,            -- JSON list of {id, name}
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS narrative_cache (
    cache_key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    generator TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingestion_state (
    job TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    rows_saved INTEGER DEFAULT 0,
    message TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path=None):
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path=None):
    with session(path) as conn:
        conn.executescript(SCHEMA)


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def upsert_flow(conn, *, mineral, hs_code, year, reporter_iso, partner_iso, flow,
                value_usd, net_weight_kg, is_reported, source="UN Comtrade"):
    conn.execute(
        """
        INSERT INTO trade_flows
            (mineral, hs_code, year, reporter_iso, partner_iso, flow,
             value_usd, net_weight_kg, is_reported, source, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (hs_code, year, reporter_iso, partner_iso, flow) DO UPDATE SET
            value_usd = excluded.value_usd,
            net_weight_kg = excluded.net_weight_kg,
            is_reported = excluded.is_reported,
            fetched_at = CURRENT_TIMESTAMP
        """,
        (mineral, hs_code, year, reporter_iso, partner_iso, flow,
         value_usd, net_weight_kg, is_reported, source),
    )


def db_signature(path=None):
    """Changes whenever the database file changes; used to invalidate caches."""
    p = path or DB_PATH
    try:
        stat = p.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        return (0, 0)
