# Architecture

## Overview

Galen is a three-stage pipeline — **Capture → Extract → Ask** —
with a deterministic fallback at every model-backed step.

```
Browser (Web Audio / AudioWorklet)
   │  16 kHz PCM s16le, 100 ms frames
   ▼
AssemblyAI Streaming v3  ──(Turn events, speaker_label, language_code)──┐
   │                                                                     │
   ▼                                                                     ▼
FastAPI  /api/huddle  ──▶  agent.extract.extract_entries  ──▶  SQLite / DynamoDB
   │                          │  LLM Gateway (semantic)                 │
   │                          └  rules.py (deterministic)               │
   ▼                                                                     │
agent.twin  (thresholds, "quiet when fine")                              │
                                                                        ▼
FastAPI  /api/ask  ──▶  agent.query.ask_knowledge  ──▶  grounded cited answer
```

## Modules

| Module | Responsibility |
| --- | --- |
| `agent/config.py` | Loads `.env`; single source of truth for keys, model, backend. |
| `agent/storage.py` | SQLite schema + `_get_conn()` (WAL, busy timeout). DynamoDB swap point. |
| `agent/twin.py` | Twin-lite metric state, known thresholds, alert evaluation. |
| `agent/rules.py` | Urgent phrases, watch-out/tip patterns, pharma terms, transcript analysis. |
| `agent/extract.py` | LLM Gateway extraction, rule merge, citation backfill, caching, backoff. |
| `agent/query.py` | Context formatting, grounded answer generation, retrieval fallback. |
| `app/main.py` | HTTP routes, templates, streaming token minting, transcription. |
| `ui/static/capture.js` | Realtime mic → PCM → v3 WebSocket; live diarized transcript. |
| `ui/static/pcm-processor.js` | AudioWorklet that converts Float32 to 16-bit PCM. |

## Data model

- **equipment** — id, name, area, product.
- **metrics** — (equipment_id, metric_key) → value, unit, source, last_updated.
- **sessions** — a huddle: site/area/equipment/product/batch, participants, timestamps.
- **transcript** — ordered turns with speaker, text, timing, language.
- **entries** — typed knowledge (`watch_out`, `tip`, `deviation_observation`,
  `capa_candidate`) with citations, confidence, `parsed_by`, and a review
  `status` (`auto` / `flag` / `approved` / `dismissed`).

## Robustness

- **LLM + rules union.** The deterministic extractor always runs. Its entries are
  merged with the LLM's, de-duplicated by entry type + citation/token overlap.
  If the LLM returns nothing, the system still captures known signals.
- **Citation backfill.** If the model omits citations, they are inferred from
  token overlap against transcript turns.
- **Caching & back-off.** Identical transcripts are cached; `429` responses use
  exponential back-off. Free-tier LLM Gateway rate limits are handled gracefully.
- **Quiet when fine.** Alerts only fire when a spoken metric breaches a known
  threshold.

## AssemblyAI API notes

- **Streaming:** `wss://streaming.assemblyai.com/v3/ws`; authenticate in the
  browser with a server-minted temporary token (`GET /v3/token`), never the
  permanent key. Model `universal-3-5-pro`, `speaker_labels=true`,
  `language_detection=true`, `keyterms_prompt=[...]`.
- **LLM Gateway:** `https://llm-gateway.assemblyai.com/v1/chat/completions`,
  OpenAI-compatible. Model availability is account-dependent; `extract.py`
  requests a specific model and falls back to rules on any error.
- **Batch STT:** the official Python SDK with `speaker_labels` for pre-recorded
  audio (used by Ask-by-voice).
