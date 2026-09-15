from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import datetime


KNOWN_THRESHOLDS = {
    "reactor_r2": {"temperature": {"max": 60.0, "unit": "°C"}},
    "line_4":     {"oee":        {"min": 70.0, "unit": "%"}},
}


def get_equipment_state(equipment: str) -> Dict[str, Any]:
    from agent.storage import _get_conn
    conn = _get_conn()
    rows = conn.execute(
        "SELECT metric_key, value, unit, last_updated "
        "FROM metrics WHERE equipment_id = ?", (equipment,)
    ).fetchall()
    conn.close()
    return {r["metric_key"]: {"value": r["value"], "unit": r["unit"],
                               "updated": r["last_updated"]} for r in rows}


def update_equipment_state(equipment: str, updates: Dict[str, Any]):
    from agent.storage import _get_conn
    conn = _get_conn()
    now = datetime.datetime.utcnow().isoformat()
    for key, val in updates.items():
        if isinstance(val, dict):
            value, unit = val.get("value"), val.get("unit", "")
        else:
            value, unit = float(val), ""
        conn.execute(
            "INSERT OR REPLACE INTO metrics "
            "(equipment_id, metric_key, value, unit, source, last_updated) "
            "VALUES (?, ?, ?, ?, 'spoken', ?)",
            (equipment, key, value, unit, now)
        )
    conn.commit()
    conn.close()


def check_twin_alerts(equipment: str, updates: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts = []
    thresholds = KNOWN_THRESHOLDS.get(equipment, {})
    for key, val in updates.items():
        if isinstance(val, dict):
            value = val.get("value")
        else:
            value = float(val)
        if key in thresholds:
            t = thresholds[key]
            if "max" in t and value > t["max"]:
                alerts.append({
                    "equipment": equipment,
                    "metric": key,
                    "value": value,
                    "threshold": t["max"],
                    "unit": t.get("unit", ""),
                    "severity": "high" if value > t["max"] * 1.1 else "medium",
                    "message": (
                        f"{equipment} {key} exceeded limit "
                        f"{value}{t.get('unit','')} > {t['max']}{t.get('unit','')}"
                    ),
                })
            if "min" in t and value < t["min"]:
                alerts.append({
                    "equipment": equipment,
                    "metric": key,
                    "value": value,
                    "threshold": t["min"],
                    "unit": t.get("unit", ""),
                    "severity": "medium",
                    "message": (
                        f"{equipment} {key} below target "
                        f"{value}{t.get('unit','')} < {t['min']}{t.get('unit','')}"
                    ),
                })
    return alerts
