# Submission copy

## Live links

- **Demo URL:** https://galen-kb.vercel.app
- **Repository (public):** https://github.com/MarkNwilliam/galen
- **Backend health:** https://3strtwnmd0.execute-api.us-east-1.amazonaws.com/prod/health

## Title

**Galen — the voice knowledge bank for pharmaceutical manufacturing**

## Short description (≤ 250 chars)

Shift handovers carry the knowledge nobody writes down. Galen listens to the
plant floor with AssemblyAI streaming STT, turns huddles into cited, searchable
knowledge entries anchored to live equipment state, and answers operators by
voice.

## Long description

Every GMP plant loses know-how at every shift change. Under ICH Q10 §1.6.1,
manufacturers must acquire, analyse, store and disseminate process knowledge —
but in practice it lives in people's heads, in 6am huddles, and in stories
traded between operators. Deviations get re-discovered, new hires repeat old
mistakes, and QA reconstructs history by hand.

**Galen** turns those spoken moments into an institutional memory.

- **Capture.** A shift huddle is transcribed live with AssemblyAI's streaming
  speech-to-text (`universal-3-5-pro`), with speaker diarization and
  language detection so it handles the English / Luganda / Swahili
  code-switching that real African plant floors use. Pharma keyterms
  ("Reactor R2", "CAPA", "out of specification") are boosted at the audio layer.
- **Extract.** The AssemblyAI LLM Gateway converts the transcript into typed
  knowledge entries — `watch_out`, `tip`, `deviation_observation`,
  `capa_candidate` — each citing the exact transcript turns and speaker behind
  it. A deterministic regex/rule layer runs in parallel and is merged in, so a
  known phrase is never lost if the model is slow or rate-limited.
- **Anchor.** Entries are tied to equipment, product, batch and a lightweight
  live "twin" (reactor temperature, line OEE). Spoken metric changes update the
  twin and breach thresholds raise alerts. *Quiet when fine*: the system only
  escalates what needs a human.
- **Ask.** Operators ask a question by text or voice and get a grounded,
  cited answer, spoken back. If the answer doesn't resolve the issue, one tap
  books the gap as a new flagged entry — **nothing gets lost**.
- **Review.** High-severity deviations and CAPA candidates pass through an
  explicit Approve / Dismiss gate.

Galen is designed for the reality of a plant network: every model-backed step
degrades gracefully to a deterministic fallback, and every failure is surfaced
rather than hidden.

## Technology

AssemblyAI Streaming v3 STT · Streamlining diarization · Language detection ·
Keyterms prompting · AssemblyAI LLM Gateway · Batch transcription · FastAPI ·
Web Audio API / AudioWorklet · SQLite / DynamoDB · Vercel · AWS · Vanilla JS

## Tags

`voice-ai`, `assemblyai`, `speech-to-text`, `llm`, `pharmaceutical`,
`manufacturing`, `gmp`, `knowledge-management`, `fastapi`, `python`,
`realtime`, `diarization`, `multilingual`

## Elevator pitch (30s)

"Plant floors lose their memory every shift change. Galen listens to the huddle,
extracts what matters into cited knowledge entries, wires them to live equipment
state, and answers the next operator's question out loud — in English, Luganda
or Swahili. It never loses a known warning to a failed API call, and it never
stays silent when something's wrong."

## 4-minute demo video script

See **`docs/RECORDING.md`** for the live, click-by-click recording runbook
(with the exact URLs and spoken lines). High-level beats:

**0:00–0:30 — Problem.** A retiring operator, a 6am huddle, a near-miss nobody
recorded. "This is where process knowledge dies."

**0:30–1:00 — Capture.** Open `/capture`. Press *Start Huddle*. Speak a short
handover (or press *Replay demo huddle*). Point out the live transcript, speaker
labels, and the Swahili line detected as `sw`.

**1:00–1:45 — Extract + Alert.** Show the typed entries appearing with citations,
and the twin alert (`reactor_r2 temperature exceeded limit 62.0°C > 60.0°C`).
Highlight the CAPA candidate landing in the flagged queue.

**1:45–2:30 — Ask + speak.** Go to `/ask`. Ask "What do I do when reactor R2
runs hot?" The cited answer appears and is spoken. Tap **❌ No** to show the
gap being booked, then **✅ Yes** to show validation.

**2:30–3:15 — Dashboard + twin-lite.** Show the plant overview, flagged entries,
review Approve/Dismiss, and recent sessions.

**3:15–3:45 — Architecture.** Show `docs/ARCHITECTURE.md`: realtime STT + LLM
Gateway with a deterministic fallback; Vercel frontend + AWS backend; the
storage swap-point.

**3:45–4:00 — Close.** "Galen: the voice knowledge bank for pharma. Quiet when
fine, cited when it matters."

## Judging-criteria mapping

| Criterion | Where it shows |
| --- | --- |
| **Application of Technology** | Realtime v3 STT with diarization + keyterms, LLM Gateway structured extraction, deterministic fallback, twin state, Vercel/AWS split. |
| **Presentation** | Polished three-page UI, live mic + fixture replay, spoken answers, one-command demo seed. |
| **Business Value** | ICH Q10 §1.6.1 knowledge management, shift-handover retention, deviation reduction, audit trail with citations, multilingual African context. |
| **Originality** | Voice-native knowledge capture anchored to live plant state, with a "Fix it" loop that books knowledge gaps automatically. |
