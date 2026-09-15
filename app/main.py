import uuid, datetime, json, os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, WebSocket, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from agent.config import ASSEMBLYAI_API_KEY, HOST, PORT
from agent import repo
from agent.twin import get_equipment_state, update_equipment_state, check_twin_alerts
from agent.extract import extract_entries
from agent.query import ask_knowledge


@asynccontextmanager
async def lifespan(app: FastAPI):
    repo.init()
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
    return {"status": "ok", "app": "galen", "storage": repo.backend_name()}


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
    repo.seed_equipment([
        {"id": "reactor_r2", "name": "Reactor R2", "area": "API Manufacturing", "product": "Atorvastatin 20mg"},
        {"id": "line_4", "name": "Line 4", "area": "Packaging", "product": "Atorvastatin 20mg"},
    ])
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

    now = datetime.datetime.utcnow().isoformat()
    participants = list({t.get("speaker", "?") for t in turns})
    repo.create_session({
        "id": session_id, "site": "site_1", "area": "floor_1",
        "equipment": equipment, "product": product, "batch": batch,
        "participants": participants, "started_at": now, "ended_at": now,
    })
    repo.add_turns(session_id, turns)

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
    stored_entries = []
    for entry in extraction.get("entries", []):
        eid = repo.add_entry({
            "session_id": session_id,
            "entry_type": entry.get("entry_type", ""),
            "speaker": entry.get("speaker", ""),
            "title": entry.get("title", ""),
            "body": entry.get("body", ""),
            "equipment": equipment, "product": product, "batch": batch,
            "citations": entry.get("citations", []),
            "confidence": 0.8,
            "parsed_by": extraction.get("parsed_by", "rules"),
            "status": "flag" if entry.get("severity") == "high" else "auto",
            "tags": entry.get("tags", []),
            "severity": entry.get("severity", "low"),
            "created_at": now,
        })
        entry["id"] = eid
        stored_entries.append(entry)

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

    entries = repo.list_entries(equipment=equipment, batch=batch, limit=20)
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

    repo.add_feedback({
        "entry_id": entry_id, "question": question,
        "worked": worked, "note": note, "created_at": now,
    })

    new_entry_id = None
    if worked and entry_id:
        repo.bump_confidence(entry_id, 0.05)
    elif not worked and question:
        new_entry_id = repo.add_entry({
            "session_id": None, "entry_type": "tip", "speaker": "feedback",
            "title": f"Unresolved: {question[:60]}",
            "body": note or f"Operator asked: {question}. The answer did not resolve the issue.",
            "equipment": None, "product": None, "batch": None,
            "citations": [], "confidence": 0.5, "parsed_by": "feedback",
            "status": "flag", "tags": ["feedback", "knowledge-gap"],
            "severity": "medium", "created_at": now,
        })

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
    repo.set_entry_status(entry_id, "approved")
    return JSONResponse({"success": True, "entry_id": entry_id, "status": "approved"})


@app.post("/api/entry/{entry_id}/dismiss")
def dismiss_entry(entry_id: str):
    repo.set_entry_status(entry_id, "dismissed")
    return JSONResponse({"success": True, "entry_id": entry_id, "status": "dismissed"})


# ── Dashboard APIs ────────────────────────────────────────────────────────────
@app.get("/api/entries")
def list_entries(status: str = "", equipment: str = "", limit: int = 50):
    return JSONResponse(repo.list_entries(status=status, equipment=equipment, limit=limit))


@app.get("/api/twin/{equipment_id}")
def get_twin(equipment_id: str):
    return JSONResponse(get_equipment_state(equipment_id))


@app.get("/api/sessions")
def list_sessions(limit: int = 20):
    return JSONResponse(repo.list_sessions(limit=limit))


@app.get("/api/transcript/{session_id}")
def get_transcript(session_id: str):
    return JSONResponse(repo.get_turns(session_id))


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
