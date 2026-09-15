import uuid, datetime, json, os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, WebSocket, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from agent.config import ASSEMBLYAI_API_KEY, HOST, PORT
from agent.storage import init_db, _get_conn
from agent.twin import get_equipment_state, update_equipment_state, check_twin_alerts
from agent.extract import extract_entries
from agent.query import ask_knowledge


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Galen", lifespan=lifespan)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "app": "galen", "storage": os.getenv("STORAGE_BACKEND", "sqlite")}


# ── Streaming token endpoint ────────────────────────────────────────────────
@app.get("/api/streaming-token")
def get_streaming_token(expires_in: int = 300, max_session: int = 3600):
    if not ASSEMBLYAI_API_KEY:
        return JSONResponse({"error": "No API key configured"}, status_code=500)
    import httpx
    resp = httpx.get(
        "https://streaming.assemblyai.com/v3/token",
        params={"expires_in_seconds": expires_in, "max_session_duration_seconds": max_session},
        headers={"Authorization": ASSEMBLYAI_API_KEY},
        timeout=15.0,
    )
    if resp.status_code != 200:
        return JSONResponse({"error": resp.text}, status_code=resp.status_code)
    return JSONResponse(resp.json())


# ── Seed equipment ───────────────────────────────────────────────────────────
@app.post("/api/seed")
def seed_plant():
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
        conn.execute(
            "INSERT OR IGNORE INTO metrics "
            "(equipment_id, metric_key, value, unit, source, last_updated) "
            "VALUES (?, 'temperature', 55.0, '°C', 'seeded', ?)",
            (eq, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO metrics "
            "(equipment_id, metric_key, value, unit, source, last_updated) "
            "VALUES (?, 'oee', 82.0, '%', 'seeded', ?)",
            (eq, now),
        )
    conn.commit()
    conn.close()
    return JSONResponse({"seeded": ["reactor_r2", "line_4"]})


# ── Huddle session ───────────────────────────────────────────────────────────
@app.post("/api/huddle")
def record_huddle(request: dict):
    """Receive a completed huddle: turns[], equipment, product, batch."""
    session_id = str(uuid.uuid4())
    equipment = request.get("equipment", "reactor_r2")
    product   = request.get("product", "")
    batch     = request.get("batch", "")
    turns     = request.get("turns", [])

    conn = _get_conn()
    now = datetime.datetime.utcnow().isoformat()
    participants = list({t.get("speaker", "?") for t in turns})
    conn.execute(
        "INSERT INTO sessions "
        "(id, site, area, equipment, product, batch, participants, started_at, ended_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, "site_1", "floor_1", equipment, product, batch,
         json.dumps(participants), now, now),
    )
    for i, t in enumerate(turns):
        conn.execute(
            "INSERT INTO transcript (session_id, turn, speaker, text, start_ms, end_ms, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, i, t.get("speaker", ""), t.get("text", ""),
             t.get("start_ms", 0), t.get("end_ms", 0), t.get("language", "en")),
        )
    conn.commit()
    conn.close()

    # twin state from spoken updates
    updates = {}
    for t in turns:
        import re
        m = re.search(
            r"\b(temperature|temp)\s+(?:is|reads|at)?\s*(?:now\s+)?(?:at\s+)?(\d+(?:\.\d+)?)\s*°?\s?[cC]?",
            t.get("text", ""), re.I,
        )
        if not m:
            m = re.search(r"\b(setpoint|feed)\s+(?:to|at\s+)?(\d+(?:\.\d+)?)", t.get("text", ""), re.I)
        if m:
            key = m.group(1).lower()
            val = float(m.group(2))
            unit = "°C" if "temp" in key else "%"
            updates[key] = {"value": val, "unit": unit}
    if updates:
        update_equipment_state(equipment, updates)

    alerts = check_twin_alerts(equipment, updates)

    # extract knowledge entries
    extraction = extract_entries(turns)
    conn = _get_conn()
    stored_entries = []
    for entry in extraction.get("entries", []):
        eid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO entries "
            "(id, session_id, entry_type, speaker, title, body, equipment, product, batch, "
            " citations, confidence, parsed_by, status, tags, severity, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, session_id, entry.get("entry_type", ""),
             entry.get("speaker", ""), entry.get("title", ""), entry.get("body", ""),
             equipment, product, batch,
             json.dumps(entry.get("citations", [])), 0.8,
             extraction.get("parsed_by", "rules"),
             "flag" if entry.get("severity") == "high" else "auto",
             json.dumps(entry.get("tags", [])), entry.get("severity", "low"), now),
        )
        entry["id"] = eid
        stored_entries.append(entry)

    conn.commit()
    conn.close()

    return JSONResponse({
        "session_id": session_id,
        "entries": stored_entries,
        "entry_count": extraction.get("entry_count", 0),
        "alerts": alerts,
        "parsed_by": extraction.get("parsed_by", "rules"),
    })


# ── Transcribe uploaded audio (for browser mic + demo) ─────────────────────
@app.post("/api/transcribe-file")
async def transcribe_file(file: UploadFile = File(...)):
    import tempfile, os as _os
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        import assemblyai as aai
        aai.settings.api_key = ASSEMBLYAI_API_KEY
        transcriber = aai.Transcriber()
        config = aai.TranscriptionConfig(
            language_code="auto",
            speaker_labels=True,
            language_detection=True,
        )
        transcript = transcriber.transcribe(tmp_path, config)
        turns = []
        for u in (transcript.utterances or []):
            turns.append({
                "speaker": u.speaker or "voice",
                "text": u.text,
                "language": getattr(u, "language", "en") or "en",
            })
        if not turns:
            turns = [{"speaker": "voice", "text": transcript.text or "", "language": "en"}]
        return {"turns": turns}
    except Exception as e:
        return {"error": str(e), "turns": []}
    finally:
        _os.unlink(tmp_path)


DEMO_HUDDLE = {
    "equipment": "reactor_r2",
    "product": "Atorvastatin 20mg",
    "batch": "B-101",
    "turns": [
        {"speaker": "shift_lead",  "text": "Reactor R2 is running hot again this morning.", "language": "en"},
        {"speaker": "operator",    "text": "Temperature is at 62 degrees, we pulled the feed back to 30 percent.", "language": "en"},
        {"speaker": "shift_lead",  "text": "When R2 runs hot, first check the cooling water valve, it is usually stuck.", "language": "en"},
        {"speaker": "operator",    "text": "We cleared it last time and it was fine.", "language": "en"},
        {"speaker": "intern",      "text": "Mze, tunafaa kuandika hii kwenye system? (Should we log this in the system?)", "language": "sw"},
        {"speaker": "shift_lead",  "text": "Yes, log it, and log the CAPA candidate for the valve inspection.", "language": "en"},
    ],
}


@app.get("/api/demo-huddle")
def get_demo_huddle():
    return DEMO_HUDDLE


# ── Ask ──────────────────────────────────────────────────────────────────────
@app.post("/api/ask")
def ask(request: dict):
    question  = request.get("question", "")
    equipment = request.get("equipment", "")
    batch     = request.get("batch", "")

    conn = _get_conn()
    sql = "SELECT * FROM entries WHERE 1=1"
    params = []
    if equipment:
        sql += " AND equipment = ?"; params.append(equipment)
    if batch:
        sql += " AND batch = ?"; params.append(batch)
    rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT 20", params).fetchall()
    conn.close()

    entries = [dict(r) for r in rows]
    twin = {}
    if equipment:
        twin[equipment] = get_equipment_state(equipment)

    result = ask_knowledge(question, entries, twin)
    result["entries_used"] = len(entries)
    result["twin_state"] = twin
    if entries:
        result["top_entry_id"] = entries[0]["id"]
    return JSONResponse(result)


# ── Feedback loop ("Fix it") ─────────────────────────────────────────────────
@app.post("/api/feedback")
def submit_feedback(request: dict):
    """Close the loop on an answer.

    worked=True  -> the cited entry is validated (confidence nudged up).
    worked=False -> the gap is booked as a new flagged entry for human review.
    """
    entry_id = request.get("entry_id") or ""
    question = (request.get("question") or "").strip()
    worked = bool(request.get("worked"))
    note = (request.get("note") or "").strip()
    now = datetime.datetime.utcnow().isoformat()

    conn = _get_conn()
    conn.execute(
        "INSERT INTO feedback (id, entry_id, question, worked, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), entry_id, question, 1 if worked else 0, note, now),
    )

    new_entry_id = None
    if worked and entry_id:
        conn.execute(
            "UPDATE entries SET confidence = MIN(1.0, COALESCE(confidence, 0.8) + 0.05) "
            "WHERE id = ?",
            (entry_id,),
        )
    elif not worked and question:
        new_entry_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO entries "
            "(id, session_id, entry_type, speaker, title, body, equipment, product, batch, "
            " citations, confidence, parsed_by, status, tags, severity, created_at) "
            "VALUES (?, NULL, 'tip', 'feedback', ?, ?, NULL, NULL, NULL, '[]', 0.5, "
            "'feedback', 'flag', ?, 'medium', ?)",
            (new_entry_id, f"Unresolved: {question[:60]}",
             note or f"Operator asked: {question}. The answer did not resolve the issue.",
             json.dumps(["feedback", "knowledge-gap"]), now),
        )
    conn.commit()
    conn.close()

    return JSONResponse({
        "success": True,
        "worked": worked,
        "validated_entry_id": entry_id if worked else None,
        "new_entry_id": new_entry_id,
        "message": (
            "Thanks — the source entry is now marked as validated."
            if worked else
            "Logged as an open knowledge gap for review. Nothing gets lost."
        ),
    })


# ── Approve / Dismiss ────────────────────────────────────────────────────────
@app.post("/api/entry/{entry_id}/approve")
def approve_entry(entry_id: str):
    conn = _get_conn()
    conn.execute("UPDATE entries SET status = 'approved' WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return JSONResponse({"success": True, "entry_id": entry_id, "status": "approved"})


@app.post("/api/entry/{entry_id}/dismiss")
def dismiss_entry(entry_id: str):
    conn = _get_conn()
    conn.execute("UPDATE entries SET status = 'dismissed' WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return JSONResponse({"success": True, "entry_id": entry_id, "status": "dismissed"})


# ── Dashboard APIs ────────────────────────────────────────────────────────────
@app.get("/api/entries")
def list_entries(status: str = "", equipment: str = "", limit: int = 50):
    conn = _get_conn()
    sql = "SELECT * FROM entries WHERE 1=1"
    params = []
    if status:
        sql += " AND status = ?"; params.append(status)
    if equipment:
        sql += " AND equipment = ?"; params.append(equipment)
    rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", params + [limit]).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/twin/{equipment_id}")
def get_twin(equipment_id: str):
    return JSONResponse(get_equipment_state(equipment_id))


@app.get("/api/sessions")
def list_sessions(limit: int = 20):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/transcript/{session_id}")
def get_transcript(session_id: str):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM transcript WHERE session_id = ? ORDER BY turn", (session_id,)
    ).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


# ── HTML pages (static; also deployable to Vercel) ──────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return FileResponse(str(UI_DIR / "index.html"))

@app.get("/capture", response_class=HTMLResponse)
def capture_page():
    return FileResponse(str(UI_DIR / "capture.html"))

@app.get("/ask", response_class=HTMLResponse)
def ask_page():
    return FileResponse(str(UI_DIR / "ask.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
