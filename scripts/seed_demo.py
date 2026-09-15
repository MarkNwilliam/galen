"""Seed the knowledge bank with a realistic demo dataset.

Run from the repo root:
    python -m scripts.seed_demo

This creates two huddle sessions (one historical, one live demo), the
resulting knowledge entries, twin-lite metric history, and one open
CAPA-candidate that needs human review.
"""
import json
import sys
import uuid
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.storage import init_db, _get_conn
from agent.extract import extract_entries
from agent.twin import update_equipment_state, check_twin_alerts


HUDDLES = [
    {
        "equipment": "reactor_r2",
        "product": "Atorvastatin 20mg",
        "batch": "B-101",
        "when": "2026-09-14T06:10:00",
        "turns": [
            {"speaker": "shift_lead", "text": "Morning handover. Reactor R2 ran hot overnight, peaked at 64 degrees.", "language": "en"},
            {"speaker": "operator",   "text": "We pulled the feed back to 30 percent and it settled at 58.", "language": "en"},
            {"speaker": "shift_lead", "text": "When R2 runs hot, first check the cooling water valve because it sticks.", "language": "en"},
            {"speaker": "operator",   "text": "Cleaning the valve actuator fixed it last month.", "language": "en"},
            {"speaker": "qa",         "text": "Log a CAPA candidate for a preventative valve inspection schedule.", "language": "en"},
        ],
    },
    {
        "equipment": "line_4",
        "product": "Atorvastatin 20mg",
        "batch": "B-102",
        "when": "2026-09-15T06:05:00",
        "turns": [
            {"speaker": "shift_lead", "text": "Line 4 changeover to 20mg took 55 minutes yesterday, OEE dropped to 66 percent.", "language": "en"},
            {"speaker": "operator",   "text": "The blister foil roll was misaligned, we had to stop twice.", "language": "en"},
            {"speaker": "shift_lead", "text": "Always verify foil alignment before starting the changeover.", "language": "en"},
            {"speaker": "intern",     "text": "Tunaweza kuweka checklist kwa hii? (Can we put a checklist for this?)", "language": "sw"},
            {"speaker": "shift_lead", "text": "Good idea, add it as a CAPA candidate for the changeover SOP.", "language": "en"},
        ],
    },
]

METRIC_HISTORY = {
    "reactor_r2": [("temperature", 64.0, "°C"), ("temperature", 58.0, "°C"), ("oee", 81.0, "%")],
    "line_4":     [("oee", 66.0, "%"), ("oee", 79.0, "%")],
}


def seed():
    init_db()
    conn = _get_conn()
    now = datetime.datetime.utcnow().isoformat()

    for eq, area, product in [
        ("reactor_r2", "API Manufacturing", "Atorvastatin 20mg"),
        ("line_4", "Packaging", "Atorvastatin 20mg"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO equipment (id, name, area, product, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (eq, eq.replace("_", " ").title(), area, product, now),
        )
    conn.commit()
    conn.close()

    for huddle in HUDDLES:
        session_id = str(uuid.uuid4())
        turns = huddle["turns"]
        participants = sorted({t["speaker"] for t in turns})

        conn = _get_conn()
        conn.execute(
            "INSERT INTO sessions (id, site, area, equipment, product, batch, participants, started_at, ended_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, "site_1", "floor_1", huddle["equipment"], huddle["product"],
             huddle["batch"], json.dumps(participants), huddle["when"], huddle["when"]),
        )
        for i, t in enumerate(turns):
            conn.execute(
                "INSERT INTO transcript (session_id, turn, speaker, text, start_ms, end_ms, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, i, t["speaker"], t["text"], i * 6000, (i + 1) * 6000, t.get("language", "en")),
            )
        conn.commit()
        conn.close()

        extraction = extract_entries(turns)
        conn = _get_conn()
        for entry in extraction.get("entries", []):
            status = "flag" if entry.get("severity") == "high" else "auto"
            conn.execute(
                "INSERT INTO entries "
                "(id, session_id, entry_type, speaker, title, body, equipment, product, batch, "
                " citations, confidence, parsed_by, status, tags, severity, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), session_id, entry.get("entry_type", ""),
                 entry.get("speaker", ""), entry.get("title", ""), entry.get("body", ""),
                 huddle["equipment"], huddle["product"], huddle["batch"],
                 json.dumps(entry.get("citations", [])), 0.85,
                 extraction.get("parsed_by", "rules"), status,
                 json.dumps(entry.get("tags", []) or []), entry.get("severity", "low"),
                 huddle["when"]),
            )
        conn.commit()
        conn.close()

    # twin-lite metric history
    for equipment, readings in METRIC_HISTORY.items():
        updates = {}
        for key, value, unit in readings:
            updates[key] = {"value": value, "unit": unit}
        update_equipment_state(equipment, updates)
        check_twin_alerts(equipment, updates)

    # summary
    conn = _get_conn()
    entries = conn.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
    sessions = conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
    flags = conn.execute("SELECT COUNT(*) c FROM entries WHERE status='flag'").fetchone()["c"]
    conn.close()
    print(f"Seeded {sessions} sessions, {entries} entries ({flags} flagged for review).")


if __name__ == "__main__":
    seed()
