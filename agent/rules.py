import re
from typing import Dict, Any, List, Tuple

URGENT_PHRASES = [
    re.compile(r"\bhot\b", re.I),
    re.compile(r"\bjam(ming|s|ed)\b", re.I),
    re.compile(r"\bleak(ing|s|ed)\b", re.I),
    re.compile(r"\boverflow(ing|s|ed)\b", re.I),
    re.compile(r"\bfail(ed|ure|ing|s)\b", re.I),
    re.compile(r"\bbreak(down|s|ing)\b", re.I),
]

WATCH_OUT_PATTERNS = [
    re.compile(r"when\s+(.{2,40}?)\s+(runs?\s+hot|jams?|fails?|goes?\s+hot|overflows?)", re.I),
    re.compile(r"if\s+(.{2,60}?)\s+(first|always|usually|check|clean|pull)", re.I),
    re.compile(r"before\s+(.{2,40}?)\s+(check|verify|clean|inspect)", re.I),
    re.compile(r"always\s+(.{2,40}?)\s+(check|verify|clean|inspect|replace|calibrat)", re.I),
]

TIP_PATTERNS = [
    re.compile(r"best\s+(way|practice)\s+(to|is)\s+(.{10,80})", re.I),
    re.compile(r"(we|they|you)\s+(usually|typically|always)\s+(.{10,80})", re.I),
]

PHARMA_TERMS = [
    "R2", "reactor", "API", "batch", "setpoint", "temperature", "CQA",
    "LOD", "OEE", "CAPA", "deviation", "line 4", "blister", "fill",
    "moisture", "pressure", "gauge", "COA", "BMR", "IPC",
]


def analyze_transcript(turns: List[Dict[str, str]]) -> Dict[str, Any]:
    issues = []
    watchouts = []
    tips = []
    urgent = False

    for turn in turns:
        text = turn.get("text", "")
        is_structured = False
        for pat in WATCH_OUT_PATTERNS:
            if pat.search(text):
                is_structured = True
                watchouts.append({"text": text, "speaker": turn.get("speaker", "")})
        for pat in TIP_PATTERNS:
            if pat.search(text):
                is_structured = True
                tips.append({"text": text, "speaker": turn.get("speaker", "")})
        if not is_structured:
            for pat in URGENT_PHRASES:
                if pat.search(text):
                    urgent = True
                    issues.append({"type": "urgent", "text": text, "speaker": turn.get("speaker", "")})

    return {
        "urgent": urgent,
        "issues": issues,
        "watchouts": watchouts,
        "tips": tips,
        "total_turns": len(turns),
    }
