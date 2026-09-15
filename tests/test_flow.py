"""End-to-end flow tests using FastAPI's TestClient.

These run entirely offline: the LLM/STT calls fall back to deterministic
rules because no network key is required for the assertions we make.
"""
import json
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Use a throwaway SQLite DB per test to keep runs isolated.
    import agent.storage as storage
    import agent.extract as extract
    import agent.query as query
    monkeypatch.setattr(storage, "_DB_PATH", tmp_path / "test.db")
    # Force the deterministic rule path so tests are offline and fast.
    monkeypatch.setattr(extract, "ASSEMBLYAI_API_KEY", "")
    monkeypatch.setattr(query, "ASSEMBLYAI_API_KEY", "")
    extract._EXTRACT_CACHE.clear()
    with TestClient(app) as c:
        yield c


def _huddle(client):
    demo = client.get("/api/demo-huddle").json()
    return client.post("/api/huddle", json=demo).json()


def test_seed_and_pages(client):
    assert client.post("/api/seed").json()["seeded"] == ["reactor_r2", "line_4"]
    for path in ["/", "/capture", "/ask"]:
        r = client.get(path)
        assert r.status_code == 200
        assert "Galen" in r.text


def test_twin_endpoint_after_seed(client):
    client.post("/api/seed")
    twin = client.get("/api/twin/reactor_r2").json()
    assert "temperature" in twin
    assert twin["temperature"]["value"] == 55.0


def test_huddle_extracts_entries_and_alert(client):
    client.post("/api/seed")
    result = _huddle(client)
    assert result["entry_count"] >= 1
    types = {e["entry_type"] for e in result["entries"]}
    assert types & {"watch_out", "deviation_observation", "capa_candidate"}
    # spoken temperature 62 > 60 threshold must raise a twin alert
    assert any(a["metric"] == "temperature" for a in result["alerts"])


def test_ask_is_grounded_and_cited(client):
    client.post("/api/seed")
    _huddle(client)
    r = client.post("/api/ask", json={"question": "What do I do when R2 runs hot?",
                                      "equipment": "reactor_r2"})
    body = r.json()
    assert body["answer"]
    assert body["entries_used"] >= 1
    assert body["cited"] is True


def test_approve_and_dismiss_gate(client):
    client.post("/api/seed")
    _huddle(client)
    entries = client.get("/api/entries").json()
    assert entries, "expected at least one entry"

    target = entries[0]["id"]
    assert client.post(f"/api/entry/{target}/approve").json()["status"] == "approved"
    approved = client.get("/api/entries?status=approved").json()
    assert any(e["id"] == target for e in approved)

    second = entries[1]["id"] if len(entries) > 1 else target
    client.post(f"/api/entry/{second}/dismiss")
    dismissed = client.get("/api/entries?status=dismissed").json()
    assert any(e["id"] == second for e in dismissed)


def test_transcript_endpoint(client):
    client.post("/api/seed")
    result = _huddle(client)
    rows = client.get(f"/api/transcript/{result['session_id']}").json()
    assert len(rows) >= 1
    assert rows[0]["speaker"]


def test_feedback_loop_validates_and_books_gap(client):
    client.post("/api/seed")
    _huddle(client)
    entries = client.get("/api/entries").json()
    entry_id = entries[0]["id"]

    ok = client.post("/api/feedback", json={
        "entry_id": entry_id, "question": "What do I do when R2 runs hot?",
        "worked": True, "note": "",
    }).json()
    assert ok["worked"] is True
    assert ok["validated_entry_id"] == entry_id
    assert ok["new_entry_id"] is None

    gap = client.post("/api/feedback", json={
        "entry_id": entry_id, "question": "How do I reset the line 4 alarms?",
        "worked": False, "note": "No documented procedure found.",
    }).json()
    assert gap["worked"] is False
    assert gap["new_entry_id"]
    gaps = client.get("/api/entries?status=flag").json()
    assert any(e["id"] == gap["new_entry_id"] for e in gaps)
    assert any("knowledge-gap" in (e["tags"] or "") for e in gaps)
