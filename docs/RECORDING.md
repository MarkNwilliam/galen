# Galen — Demo Recording Runbook

Purpose: a single ~4-minute screen recording for the AssemblyAI Voice Agent
Hackathon (lablab.ai). You (not the assistant) record the screen — this runbook
is your click-by-click script with timings and talking points.

Live demo URL: **https://galen-kb.vercel.app**
Repo: **https://github.com/MarkNwilliam/galen**

## Before you hit record

1. Open a fresh Incognito window so there are no stored microphones/consent.
2. Load `https://galen-kb.vercel.app` and confirm the dashboard loads (twin cards,
   flagged entries, sessions). Reload once if any API call is lazy.
3. Allow microphone permission when the browser asks (capture page only).
4. Mute Slack/Teams notifications. Close unrelated tabs.
5. Window size ≥ 1920ₓ1080, or 16:9 crop in OBS on export.

## Shot list (total ≈ 3:45)

### 0:00–0:25 — Cold open (title card)
- Show the cover image (`docs/cover.png`) full screen, or narrate over a static
  screenshot of the dashboard.
- Voice: "Galen is a voice-native knowledge bank for pharmaceutical operators.
  Shift handovers talk about what *they* saw; Galen turns that talk into an
  auditable knowledge base that answers the next shift's questions. Built on
  AssemblyAI universal voice streaming transcription."

### 0:25–1:00 — Ask first, prove the answers (Ask page)
- Go to `/ask`.
- Type: "What do I do when Reactor R2 runs hot?"
- Point at the response: it cites the entries it used, the twin state, and the
  answer is read aloud via browser TTS.
- Voice: "Galen answers from its knowledge base, cites the source entries, and
  speaks the answer — hands-free on the plant floor."

### 1:00–1:45 — Capture a live handover (Capture page, the core demo)
- Go to `/capture`, press **Record**.
- Speak the script below (≈30–40 s), naturally:
  1. *"Afternoon handover. Reactor R2 is running hot, sixty-three degrees, feed
     pulled back to twenty-five percent."*
  2. *"Operator note: check the cooling water valve — it sticks, it caused the
     overpressure alarm last month."*
- Watch the live transcript appear word-by-word (AssemblyAI streaming v3).
- Press **Stop** (or it auto-stops on silence).
- Point at the twin panel updating (Reactor R2 temperature/feed).
- Voice: "That's real-time streaming transcription over a WebSocket — a full
  shift handover, no keyboards required."

### 1:45–2:30 — Rules + LLM extraction
- Click **Run Huddle Analysis** (or it runs automatically).
- Point at the extracted entries: structured incident + operator corrective
  action, tagged `parsed by llm + rules`, plus the twin state snapshot.
- Voice: "Galen splits the transcript into audit-ready entries — what happened,
  and what to do next — then correlates them with the equipment digital twin."

### 2:30–3:00 — Ask again, now it's smarter
- Go back to `/ask`.
- Ask: "R2 runs hot — what do I do, and what caused it last time?"
- Show the answer cites the just-captured cooling-water-valve entry plus the
  twin history.
- Voice: "New knowledge flows straight in. The next shift gets the full context,
  including the root cause from the huddle we just captured."

### 3:00–3:30 — Review + approval (Dashboard)
- Go to `/`, open the flagged/incident entry that was created.
- Click **Approve**.
- Voice: "Nothing auto-publishes. A responsible operator reviews flagged entries
  and approves them into the knowledge base — that's how pharma stays audit-ready."

### 3:30–3:45 — Close
- Back to `/` or cover. Voice: "Galen: capture knowledge by talking, answer by
  asking. AssemblyAI streaming transcription on the front, a tamper-evident
  knowledge telos on the back. Thank you."

## Recording tips
- If live transcription is laggy in your network, pre-record the transcript
  text and use `/api/demo-huddle` so the extraction demo never stalls — but try
  live first; it's the strongest part.
- Edit out dead air; keep cuts only between sections so the flow stays honest.
- Export H.264 MP4, 1080p, 16:9, ≤ 100 MB for the submission upload.

## Assets
- Cover (16:9): `docs/cover.png`
- Slides source/PDF: `docs/slides/` (see README)
- Live backend health check: `https://3strtwnmd0.execute-api.us-east-1.amazonaws.com/prod/health`