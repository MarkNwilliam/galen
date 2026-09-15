import json, os, time, httpx
from typing import Dict, Any, List, Optional
from agent.config import ASSEMBLYAI_API_KEY, LLM_MODEL

_EXTRACT_CACHE: Dict[str, Any] = {}


def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entry_type": {"type": "string", "enum": ["watch_out", "tip", "deviation_observation", "capa_candidate"]},
                    "title":       {"type": "string"},
                    "body":        {"type": "string"},
                    "equipment":   {"type": "string"},
                    "speaker":     {"type": "string"},
                    "severity":    {"type": "string", "enum": ["low", "medium", "high"]},
                    "condition":   {"type": "string"},
                    "citations":   {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["entry_type", "title", "body", "speaker", "citations"],
            },
        },
        "equipment_updates": {
            "type": "object",
            "description": "spoken metric changes, e.g. {'temperature': 62.0}",
        },
        "entry_count": {"type": "integer"},
    },
    "required": ["entries", "entry_count"],
}

EXTRACTION_PROMPT = (
    "You are a pharmaceutical knowledge extraction assistant for a GMP plant. "
    "Read the huddle transcript turns (with speaker labels) and extract structured "
    "knowledge entries. Return ONLY valid JSON, no prose, matching exactly this shape:\n"
    '{"entries":[{"entry_type":"watch_out|tip|deviation_observation|capa_candidate",'
    '"title":string,"body":string,"equipment":string,"speaker":string,'
    '"severity":"low|medium|high","condition":string,"citations":[integer]}],'
    '"entry_count":integer,"equipment_updates":object}\n'
    "Rules:\n"
    "- watch_out: an if-then operational warning (what to check when something happens).\n"
    "- tip: a helpful practice or trick.\n"
    "- deviation_observation: something that went wrong or is out of spec.\n"
    "- capa_candidate: a suggestion that needs a corrective/preventive action.\n"
    "- citations: 0-based indices of the transcript turns the entry came from.\n"
    "- equipment_updates: any spoken metric changes, e.g. {\"temperature\": 62.0}.\n"
    "- Do not fabricate. If nothing actionable is said, return entry_count 0.\n"
    "- Transcribe meaning across English, Luganda, and Swahili.\n\n"
    "TRANSCRIPT:\n"
)


def extract_entries(turns: List[Dict[str, str]], use_llm: bool = True) -> Dict[str, Any]:
    """Extract knowledge entries.

    Uses the AssemblyAI LLM Gateway for semantic extraction, then merges the
    deterministic regex/rule extraction so known phrasings are never missed.
    Falls back to rules-only if the LLM is unavailable.
    """
    fallback = _fallback_extract(turns)
    if not ASSEMBLYAI_API_KEY or not use_llm:
        return fallback

    transcript_text = "\n".join(
        f"[turn {i}] {t.get('speaker','?')}: {t.get('text','')}"
        for i, t in enumerate(turns)
    )
    cache_key = _hash(transcript_text)
    if cache_key in _EXTRACT_CACHE:
        cached = dict(_EXTRACT_CACHE[cache_key])
        cached["cache_hit"] = True
        return cached

    llm_entries: List[Dict[str, Any]] = []
    updates: Dict[str, Any] = {}
    llm_error = None
    for attempt in range(3):
        try:
            resp = httpx.post(
                "https://llm-gateway.assemblyai.com/v1/chat/completions",
                headers={
                    "Authorization": ASSEMBLYAI_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "user", "content": EXTRACTION_PROMPT + transcript_text},
                    ],
                    "temperature": 0,
                    "max_tokens": 1500,
                    "post_processing_steps": [{"type": "json-repair"}],
                },
                timeout=60.0,
            )
            if resp.status_code == 429:
                llm_error = "rate_limited"
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            llm_entries = parsed.get("entries", []) or []
            updates = parsed.get("equipment_updates", {}) or {}
            if llm_entries:
                break
            time.sleep(1)
        except Exception as e:
            llm_error = str(e)
            time.sleep(2 ** attempt)

    _backfill_citations(llm_entries, turns)
    merged = _merge_entries(llm_entries, fallback["entries"])
    _backfill_citations(merged, turns)
    result: Dict[str, Any] = {
        "entries": merged,
        "entry_count": len(merged),
        "equipment_updates": updates,
        "parsed_by": "llm+rules" if llm_entries else "rules",
    }
    if llm_error:
        result["llm_error"] = llm_error
    _EXTRACT_CACHE[cache_key] = dict(result)
    return result


def _backfill_citations(entries: List[Dict[str, Any]], turns: List[Dict[str, str]]) -> None:
    """Assign citation turn indices to entries that arrived without any.

    Matches an entry's title/body tokens against each turn and cites the
    best-scoring turn(s). Mutates entries in place.
    """
    def tokens(s: str) -> set:
        stop = {"the", "a", "an", "is", "are", "was", "to", "of", "and", "it",
                "we", "at", "in", "on", "for", "with", "this", "that"}
        return {w.strip(".,!?°%") for w in (s or "").lower().split()
                if len(w) > 2 and w not in stop}

    turn_tokens = [tokens(t.get("text", "")) for t in turns]
    for entry in entries:
        if entry.get("citations"):
            continue
        target = tokens(entry.get("title", "")) | tokens(entry.get("body", ""))
        if not target:
            continue
        scored = []
        for i, tt in enumerate(turn_tokens):
            if target & tt:
                scored.append((len(target & tt), i))
        if scored:
            scored.sort(key=lambda x: -x[0])
            best = scored[0][0]
            entry["citations"] = [i for score, i in scored if score == best][:3]


def _merge_entries(llm_entries: List[Dict[str, Any]], rule_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Union LLM + rule entries, de-duplicating semantically equivalent ones.

    Two entries are considered duplicates when they share an entry_type and
    either their citation sets overlap or their body token sets are similar.
    LLM entries are kept over rule entries because their titles/bodies are cleaner.
    """
    def tokens(s: str) -> set:
        stop = {"the", "a", "an", "is", "are", "was", "to", "of", "and", "it",
                "we", "at", "in", "on", "for", "with", "this", "that", "when",
                "again", "first", "check", "watch-out:", "issue:"}
        return {w.strip(".,!?°%") for w in (s or "").lower().split() if w not in stop}

    def citations(entry: Dict[str, Any]) -> set:
        return set(entry.get("citations") or [])

    merged: List[Dict[str, Any]] = []
    for entry in llm_entries + rule_entries:
        body = (entry.get("body") or "").strip()
        if not body:
            continue
        entry_type = entry.get("entry_type", "")
        toks = tokens(body)
        cites = citations(entry)

        duplicate = False
        for existing in merged:
            if existing.get("entry_type") != entry_type:
                continue
            existing_toks = tokens(existing.get("body", ""))
            existing_cites = citations(existing)
            cite_overlap = bool(cites & existing_cites)
            if toks and existing_toks:
                union = toks | existing_toks
                jaccard = len(toks & existing_toks) / len(union) if union else 0.0
            else:
                jaccard = 0.0
            if cite_overlap or jaccard >= 0.3:
                duplicate = True
                break
        if not duplicate:
            merged.append(entry)
    return merged


def _fallback_extract(turns: List[Dict[str, str]]) -> Dict[str, Any]:
    """Deterministic fallback extraction using regex/phrase rules."""
    from agent.rules import analyze_transcript
    analysis = analyze_transcript(turns)
    entries = []

    for w in analysis["watchouts"]:
        entries.append({
            "entry_type": "watch_out",
            "title": f"Watch-out: {w['text'][:40]}...",
            "body": w["text"],
            "speaker": w["speaker"],
            "severity": "medium",
            "condition": None,
            "citations": [i for i, t in enumerate(turns) if t.get("text") == w["text"]],
        })

    for t_item in analysis["tips"]:
        entries.append({
            "entry_type": "tip",
            "title": f"Tip: {t_item['text'][:40]}...",
            "body": t_item["text"],
            "speaker": t_item["speaker"],
            "severity": "low",
            "citations": [i for i, t in enumerate(turns) if t.get("text") == t_item["text"]],
        })

    for issue in analysis["issues"]:
        entries.append({
            "entry_type": "deviation_observation",
            "title": f"Issue: {issue['text'][:40]}...",
            "body": issue["text"],
            "speaker": issue["speaker"],
            "severity": "high",
            "citations": [i for i, t in enumerate(turns) if t.get("text") == issue["text"]],
        })

    return {
        "entries": entries,
        "entry_count": len(entries),
        "equipment_updates": {},
        "parsed_by": "rules",
    }
