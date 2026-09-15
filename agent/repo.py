"""Storage repository with two interchangeable backends.

- ``sqlite``  (default): local development and the offline test-suite.
- ``dynamodb``: the serverless backend used when Galen runs on AWS Lambda,
  where the filesystem is read-only and state must live outside the process.

Select with the ``STORAGE_BACKEND`` env var. The public functions are the only
storage surface used by the app / twin / seed script, so the backend can be
swapped without touching business logic.
"""
import os
import json
import uuid
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from agent.config import STORAGE_BACKEND, DYNAMO_TABLE


def _backend() -> str:
    chosen = (os.getenv("STORAGE_BACKEND") or STORAGE_BACKEND or "sqlite").lower()
    return "dynamodb" if chosen == "dynamodb" else "sqlite"


def backend_name() -> str:
    return _backend()


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


def _clean(obj: Any) -> Any:
    """Recursively convert DynamoDB Decimals to native JSON numbers."""
    if isinstance(obj, Decimal):
        f = float(obj)
        return int(f) if f.is_integer() else f
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _jsonish(value: Any, default: str = "[]") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value)


# ── backend selection ────────────────────────────────────────────────────────
def init() -> None:
    if _backend() == "dynamodb":
        return  # the table is provisioned out-of-band
    import agent.storage as storage
    storage.init_db()


def _sqlite_conn():
    import agent.storage as storage
    return storage._get_conn()


def _table():
    import boto3
    return boto3.resource("dynamodb").Table(DYNAMO_TABLE)


# ── equipment ────────────────────────────────────────────────────────────────
DEFAULT_METRICS = (("temperature", 55.0, "°C"), ("oee", 82.0, "%"))


def seed_equipment(items: List[Dict[str, str]]) -> None:
    if _backend() == "dynamodb":
        from botocore.exceptions import ClientError
        table = _table()
        now = _now()
        for it in items:
            try:
                table.put_item(
                    Item={
                        "pk": f"EQ#{it['id']}", "sk": "META",
                        "id": it["id"], "name": it.get("name") or it["id"],
                        "area": it.get("area", ""), "product": it.get("product", ""),
                        "created_at": now,
                    },
                    ConditionExpression="attribute_not_exists(pk)",
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
            for key, value, unit in DEFAULT_METRICS:
                try:
                    table.put_item(
                        Item={
                            "pk": f"EQ#{it['id']}", "sk": f"METRIC#{key}",
                            "equipment_id": it["id"], "metric_key": key,
                            "value": Decimal(str(value)), "unit": unit,
                            "source": "seeded", "last_updated": now,
                        },
                        ConditionExpression="attribute_not_exists(pk)",
                    )
                except ClientError as exc:
                    if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                        raise
        return

    conn = _sqlite_conn()
    now = _now()
    for it in items:
        conn.execute(
            "INSERT OR IGNORE INTO equipment (id, name, area, product, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (it["id"], it.get("name") or it["id"], it.get("area", ""),
             it.get("product", ""), now),
        )
        for key, value, unit in DEFAULT_METRICS:
            conn.execute(
                "INSERT OR IGNORE INTO metrics "
                "(equipment_id, metric_key, value, unit, source, last_updated) "
                "VALUES (?, ?, ?, ?, 'seeded', ?)",
                (it["id"], key, value, unit, now),
            )
    conn.commit()
    conn.close()


# ── sessions + transcript ────────────────────────────────────────────────────
def create_session(sess: Dict[str, Any]) -> str:
    sid = sess.get("id") or str(uuid.uuid4())
    if _backend() == "dynamodb":
        _table().put_item(Item={
            "pk": f"SESSION#{sid}", "sk": "META",
            "id": sid, "site": sess.get("site", ""), "area": sess.get("area", ""),
            "equipment": sess.get("equipment", ""), "product": sess.get("product", ""),
            "batch": sess.get("batch", ""),
            "participants": _jsonish(sess.get("participants")),
            "audio_url": sess.get("audio_url", ""),
            "started_at": sess.get("started_at") or _now(),
            "ended_at": sess.get("ended_at") or _now(),
        })
        return sid

    conn = _sqlite_conn()
    conn.execute(
        "INSERT INTO sessions "
        "(id, site, area, equipment, product, batch, participants, audio_url, started_at, ended_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, sess.get("site", ""), sess.get("area", ""), sess.get("equipment", ""),
         sess.get("product", ""), sess.get("batch", ""),
         _jsonish(sess.get("participants")), sess.get("audio_url", ""),
         sess.get("started_at") or _now(), sess.get("ended_at") or _now()),
    )
    conn.commit()
    conn.close()
    return sid


def add_turns(session_id: str, turns: List[Dict[str, Any]]) -> None:
    if _backend() == "dynamodb":
        table = _table()
        with table.batch_writer() as batch:
            for i, t in enumerate(turns):
                batch.put_item(Item={
                    "pk": f"SESSION#{session_id}", "sk": f"TURN#{i:05d}",
                    "session_id": session_id, "turn": i,
                    "speaker": t.get("speaker", ""), "text": t.get("text", ""),
                    "start_ms": int(t.get("start_ms", 0) or 0),
                    "end_ms": int(t.get("end_ms", 0) or 0),
                    "language": t.get("language", "en"),
                })
        return

    conn = _sqlite_conn()
    for i, t in enumerate(turns):
        conn.execute(
            "INSERT INTO transcript (session_id, turn, speaker, text, start_ms, end_ms, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, i, t.get("speaker", ""), t.get("text", ""),
             t.get("start_ms", 0), t.get("end_ms", 0), t.get("language", "en")),
        )
    conn.commit()
    conn.close()


def get_turns(session_id: str) -> List[Dict[str, Any]]:
    if _backend() == "dynamodb":
        from boto3.dynamodb.conditions import Key
        resp = _table().query(
            KeyConditionExpression=Key("pk").eq(f"SESSION#{session_id}")
            & Key("sk").begins_with("TURN#")
        )
        rows = [_clean(r) for r in resp.get("Items", [])]
        for r in rows:
            r.pop("pk", None)
            r.pop("sk", None)
        rows.sort(key=lambda r: r.get("turn", 0))
        return rows

    conn = _sqlite_conn()
    rows = conn.execute(
        "SELECT * FROM transcript WHERE session_id = ? ORDER BY turn", (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    if _backend() == "dynamodb":
        from boto3.dynamodb.conditions import Attr
        resp = _table().scan(
            FilterExpression=Attr("pk").begins_with("SESSION#") & Attr("sk").eq("META")
        )
        rows = [_clean(r) for r in resp.get("Items", [])]
        for r in rows:
            r.pop("pk", None)
            r.pop("sk", None)
        rows.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        return rows[:limit]

    conn = _sqlite_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── knowledge entries ────────────────────────────────────────────────────────
_ENTRY_FIELDS = (
    "session_id", "entry_type", "speaker", "title", "body",
    "equipment", "product", "batch", "confidence", "parsed_by",
    "status", "severity", "created_at",
)


def add_entry(entry: Dict[str, Any]) -> str:
    eid = entry.get("id") or str(uuid.uuid4())
    rec = {k: entry.get(k) for k in _ENTRY_FIELDS}
    rec["citations"] = _jsonish(entry.get("citations"))
    rec["tags"] = _jsonish(entry.get("tags"))
    rec["confidence"] = float(entry.get("confidence", 0.8))
    rec["created_at"] = entry.get("created_at") or _now()

    if _backend() == "dynamodb":
        item = {"pk": f"ENTRY#{eid}", "sk": "META", "id": eid}
        item.update({k: v for k, v in rec.items() if v is not None})
        item["confidence"] = Decimal(str(rec["confidence"]))
        _table().put_item(Item=item)
        return eid

    conn = _sqlite_conn()
    conn.execute(
        "INSERT INTO entries "
        "(id, session_id, entry_type, speaker, title, body, equipment, product, batch, "
        " citations, confidence, parsed_by, status, tags, severity, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (eid, rec["session_id"], rec["entry_type"], rec["speaker"], rec["title"],
         rec["body"], rec["equipment"], rec["product"], rec["batch"],
         rec["citations"], rec["confidence"], rec["parsed_by"], rec["status"],
         rec["tags"], rec["severity"], rec["created_at"]),
    )
    conn.commit()
    conn.close()
    return eid


def list_entries(status: str = "", equipment: str = "", batch: str = "",
                 limit: int = 50) -> List[Dict[str, Any]]:
    if _backend() == "dynamodb":
        from boto3.dynamodb.conditions import Attr
        expr = Attr("pk").begins_with("ENTRY#") & Attr("sk").eq("META")
        if status:
            expr = expr & Attr("status").eq(status)
        if equipment:
            expr = expr & Attr("equipment").eq(equipment)
        if batch:
            expr = expr & Attr("batch").eq(batch)
        rows = [_clean(r) for r in _table().scan(FilterExpression=expr).get("Items", [])]
        for r in rows:
            r.pop("pk", None)
            r.pop("sk", None)
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return rows[:limit]

    conn = _sqlite_conn()
    sql = "SELECT * FROM entries WHERE 1=1"
    params: List[Any] = []
    if status:
        sql += " AND status = ?"; params.append(status)
    if equipment:
        sql += " AND equipment = ?"; params.append(equipment)
    if batch:
        sql += " AND batch = ?"; params.append(batch)
    rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_entry(entry_id: str) -> Optional[Dict[str, Any]]:
    if _backend() == "dynamodb":
        resp = _table().get_item(Key={"pk": f"ENTRY#{entry_id}", "sk": "META"})
        item = resp.get("Item")
        if not item:
            return None
        item = _clean(item)
        item.pop("pk", None)
        item.pop("sk", None)
        return item

    conn = _sqlite_conn()
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_entry_status(entry_id: str, status: str) -> None:
    if _backend() == "dynamodb":
        _table().update_item(
            Key={"pk": f"ENTRY#{entry_id}", "sk": "META"},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status},
        )
        return

    conn = _sqlite_conn()
    conn.execute("UPDATE entries SET status = ? WHERE id = ?", (status, entry_id))
    conn.commit()
    conn.close()


def bump_confidence(entry_id: str, delta: float = 0.05) -> None:
    if _backend() == "dynamodb":
        table = _table()
        resp = table.get_item(Key={"pk": f"ENTRY#{entry_id}", "sk": "META"})
        item = resp.get("Item")
        if not item:
            return
        current = float(item.get("confidence", Decimal("0.8")))
        table.update_item(
            Key={"pk": f"ENTRY#{entry_id}", "sk": "META"},
            UpdateExpression="SET confidence = :c",
            ExpressionAttributeValues={":c": Decimal(str(min(1.0, current + delta)))},
        )
        return

    conn = _sqlite_conn()
    conn.execute(
        "UPDATE entries SET confidence = MIN(1.0, COALESCE(confidence, 0.8) + ?) WHERE id = ?",
        (delta, entry_id),
    )
    conn.commit()
    conn.close()


# ── feedback ("Fix it" loop) ─────────────────────────────────────────────────
def add_feedback(fb: Dict[str, Any]) -> str:
    fid = fb.get("id") or str(uuid.uuid4())
    now = fb.get("created_at") or _now()
    if _backend() == "dynamodb":
        _table().put_item(Item={
            "pk": f"FEEDBACK#{fid}", "sk": "META", "id": fid,
            "entry_id": fb.get("entry_id", ""), "question": fb.get("question", ""),
            "worked": bool(fb.get("worked")),
            "note": fb.get("note", ""), "created_at": now,
        })
        return fid

    conn = _sqlite_conn()
    conn.execute(
        "INSERT INTO feedback (id, entry_id, question, worked, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (fid, fb.get("entry_id", ""), fb.get("question", ""),
         1 if fb.get("worked") else 0, fb.get("note", ""), now),
    )
    conn.commit()
    conn.close()
    return fid


# ── twin-lite metrics ────────────────────────────────────────────────────────
def get_metrics(equipment: str) -> Dict[str, Dict[str, Any]]:
    if _backend() == "dynamodb":
        from boto3.dynamodb.conditions import Key
        resp = _table().query(
            KeyConditionExpression=Key("pk").eq(f"EQ#{equipment}")
            & Key("sk").begins_with("METRIC#")
        )
        state: Dict[str, Dict[str, Any]] = {}
        for item in resp.get("Items", []):
            item = _clean(item)
            state[item["metric_key"]] = {
                "value": item.get("value"), "unit": item.get("unit", ""),
                "updated": item.get("last_updated", ""),
            }
        return state

    conn = _sqlite_conn()
    rows = conn.execute(
        "SELECT metric_key, value, unit, last_updated "
        "FROM metrics WHERE equipment_id = ?", (equipment,)
    ).fetchall()
    conn.close()
    return {r["metric_key"]: {"value": r["value"], "unit": r["unit"],
                              "updated": r["last_updated"]} for r in rows}


def set_metrics(equipment: str, updates: Dict[str, Any]) -> None:
    now = _now()
    if _backend() == "dynamodb":
        table = _table()
        for key, val in updates.items():
            if isinstance(val, dict):
                value, unit = val.get("value"), val.get("unit", "")
            else:
                value, unit = float(val), ""
            table.put_item(Item={
                "pk": f"EQ#{equipment}", "sk": f"METRIC#{key}",
                "equipment_id": equipment, "metric_key": key,
                "value": Decimal(str(value)), "unit": unit,
                "source": "spoken", "last_updated": now,
            })
        return

    conn = _sqlite_conn()
    for key, val in updates.items():
        if isinstance(val, dict):
            value, unit = val.get("value"), val.get("unit", "")
        else:
            value, unit = float(val), ""
        conn.execute(
            "INSERT OR REPLACE INTO metrics "
            "(equipment_id, metric_key, value, unit, source, last_updated) "
            "VALUES (?, ?, ?, ?, 'spoken', ?)",
            (equipment, key, value, unit, now),
        )
    conn.commit()
    conn.close()


# ── reporting ────────────────────────────────────────────────────────────────
def counts() -> Dict[str, int]:
    if _backend() == "dynamodb":
        from boto3.dynamodb.conditions import Attr
        sessions = _table().scan(
            FilterExpression=Attr("pk").begins_with("SESSION#") & Attr("sk").eq("META")
        ).get("Items", [])
        entries = _table().scan(
            FilterExpression=Attr("pk").begins_with("ENTRY#") & Attr("sk").eq("META")
        ).get("Items", [])
        flags = [e for e in entries if e.get("status") == "flag"]
        return {"sessions": len(sessions), "entries": len(entries), "flags": len(flags)}

    conn = _sqlite_conn()
    entries = conn.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
    sessions = conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
    flags = conn.execute("SELECT COUNT(*) c FROM entries WHERE status='flag'").fetchone()["c"]
    conn.close()
    return {"sessions": sessions, "entries": entries, "flags": flags}
