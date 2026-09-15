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

from agent import repo
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
    repo.init()

    repo.seed_equipment([
        {"id": "reactor_r2", "name": "Reactor R2", "area": "API Manufacturing", "product": "Atorvastatin 20mg"},
        {"id": "line_4", "name": "Line 4", "area": "Packaging", "product": "Atorvastatin 20mg"},
    ])

    for huddle in HUDDLES:
        session_id = str(uuid.uuid4())
        turns = huddle["turns"]
        participants = sorted({t["speaker"] for t in turns})

        repo.create_session({
            "id": session_id, "site": "site_1", "area": "floor_1",
            "equipment": huddle["equipment"], "product": huddle["product"],
            "batch": huddle["batch"], "participants": participants,
            "started_at": huddle["when"], "ended_at": huddle["when"],
        })
        repo.add_turns(session_id, [
            {**t, "start_ms": i * 6000, "end_ms": (i + 1) * 6000}
            for i, t in enumerate(turns)
        ])

        extraction = extract_entries(turns)
        for entry in extraction.get("entries", []):
            repo.add_entry({
                "session_id": session_id,
                "entry_type": entry.get("entry_type", ""),
                "speaker": entry.get("speaker", ""),
                "title": entry.get("title", ""),
                "body": entry.get("body", ""),
                "equipment": huddle["equipment"], "product": huddle["product"],
                "batch": huddle["batch"],
                "citations": entry.get("citations", []),
                "confidence": 0.85,
                "parsed_by": extraction.get("parsed_by", "rules"),
                "status": "flag" if entry.get("severity") == "high" else "auto",
                "tags": entry.get("tags", []) or [],
                "severity": entry.get("severity", "low"),
                "created_at": huddle["when"],
            })

    # twin-lite metric history
    for equipment, readings in METRIC_HISTORY.items():
        updates = {}
        for key, value, unit in readings:
            updates[key] = {"value": value, "unit": unit}
        update_equipment_state(equipment, updates)
        check_twin_alerts(equipment, updates)

    summary = repo.counts()
    print(
        f"Seeded {summary['sessions']} sessions, {summary['entries']} entries "
        f"({summary['flags']} flagged for review) into '{repo.backend_name()}'."
    )


if __name__ == "__main__":
    seed()
