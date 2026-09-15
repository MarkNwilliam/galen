import json, time, httpx
from typing import Dict, Any, List, Optional
from agent.config import ASSEMBLYAI_API_KEY, LLM_MODEL

ASK_PROMPT = (
    "You are a pharmaceutical manufacturing knowledge assistant. "
    "Answer the user's question using ONLY the provided context entries from the knowledge bank. "
    "Always cite the speaker and date for each fact. "
    "If you do not have enough information, say so clearly. "
    "Keep answers to 2-3 sentences.\n\n"
    "CONTEXT ENTRIES:\n{context}\n\n"
    "PLANT STATE:\n{twin_state}\n\n"
    "USER QUESTION: {question}\n"
    "CITED ANSWER:"
)


def format_context(entries: List[Dict[str, Any]]) -> str:
    parts = []
    for e in entries:
        citations = e.get("citations", [])
        cite_str = f" [cites turns {citations}]" if citations else ""
        parts.append(
            f"- [{e.get('entry_type','?')}] {e.get('title','')} "
            f"(by {e.get('speaker','?')}, {e.get('created_at','?')}){cite_str}: "
            f"{e.get('body','')}"
        )
    return "\n".join(parts) if parts else "(no relevant entries found)"


def format_twin_state(twin: Dict[str, Any]) -> str:
    parts = []
    for equip, metrics in twin.items():
        for k, v in metrics.items():
            if isinstance(v, dict):
                parts.append(f"{equip} {k}: {v.get('value')} {v.get('unit','')}")
    return "\n".join(parts) if parts else "(no live state available)"


def ask_knowledge(
    question: str,
    entries: List[Dict[str, Any]],
    twin_state: Dict[str, Any],
    fallback: bool = True,
) -> Dict[str, Any]:
    """Answer a question grounded in the KB + twin state."""
    if not ASSEMBLYAI_API_KEY:
        return _fallback_ask(question, entries)

    prompt = ASK_PROMPT.format(
        context=format_context(entries),
        twin_state=format_twin_state(twin_state),
        question=question,
    )

    try:
        resp = None
        for attempt in range(3):
            resp = httpx.post(
                "https://llm-gateway.assemblyai.com/v1/chat/completions",
                headers={
                    "Authorization": ASSEMBLYAI_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 256,
                },
                timeout=60.0,
            )
            if resp.status_code != 429:
                break
            time.sleep(2 ** attempt)
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
        cited = any(e.get("citations") for e in entries)
        return {"answer": answer, "cited": cited, "parsed_by": "llm"}
    except Exception as e:
        if fallback:
            result = _fallback_ask(question, entries)
            result["llm_error"] = str(e)
            return result
        raise


def _fallback_ask(question: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic fallback: keyword retrieval from entries."""
    if not entries:
        return {"answer": "No relevant knowledge entries found.", "cited": False, "parsed_by": "rules"}

    q_lower = question.lower()
    scored = []
    for e in entries:
        text = (e.get("title", "") + " " + e.get("body", "")).lower()
        hits = sum(1 for w in q_lower.split() if w in text)
        scored.append((hits, e))
    scored.sort(key=lambda x: -x[0])
    top = scored[0][1]

    answer_parts = [f"{top.get('title', '')}: {top.get('body', '')}"]
    if top.get("speaker"):
        answer_parts.append(f"(Source: {top['speaker']}, {top.get('created_at', '')})")
    return {"answer": " ".join(answer_parts), "cited": bool(top.get("citations")), "parsed_by": "rules"}
