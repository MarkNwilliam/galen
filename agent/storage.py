import os, json, sqlite3, uuid, datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge.db"


def _get_conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS equipment (
            id TEXT PRIMARY KEY,
            name TEXT,
            area TEXT,
            product TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS metrics (
            equipment_id TEXT,
            metric_key TEXT,
            value REAL,
            unit TEXT,
            source TEXT DEFAULT 'spoken',
            last_updated TEXT,
            PRIMARY KEY (equipment_id, metric_key)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            site TEXT, area TEXT,
            equipment TEXT, product TEXT, batch TEXT,
            participants TEXT,
            audio_url TEXT,
            started_at TEXT, ended_at TEXT
        );
        CREATE TABLE IF NOT EXISTS transcript (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, turn INTEGER,
            speaker TEXT, text TEXT,
            start_ms INTEGER, end_ms INTEGER,
            language TEXT
        );
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            entry_type TEXT,
            speaker TEXT,
            title TEXT, body TEXT,
            equipment TEXT, product TEXT, batch TEXT,
            citations TEXT,
            confidence REAL,
            parsed_by TEXT DEFAULT 'llm',
            status TEXT DEFAULT 'flag',
            tags TEXT, severity TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            entry_id TEXT,
            question TEXT,
            worked INTEGER,
            note TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()
