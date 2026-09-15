const els = {
  recordBtn: document.getElementById('recordBtn'),
  status: document.getElementById('status'),
  transcript: document.getElementById('transcript'),
  twin: document.getElementById('twin'),
  entries: document.getElementById('entries'),
};

const SAMPLE_RATE = 16000;
const PHARMA_KEYTERMS = [
  "reactor R2", "Reactor R2", "OEE", "capa", "CAPA", "deviation",
  "batch", "setpoint", "Atorvastatin", "shift handover", "cooling water valve",
  "overpressure", "out of specification", "line 4", "changeover",
];

let ws = null;
let audioContext = null;
let mediaStream = null;
let workletNode = null;
let turns = [];
let recording = false;

async function toggleRecord() {
  if (recording) { await stopRecord(); return; }
  await startRecord();
}

async function startRecord() {
  turns = [];
  els.transcript.innerHTML = '';
  els.entries.innerHTML = '';
  els.status.textContent = 'Requesting microphone...';

  let token;
  try {
    const tr = await fetch(galenApi('/api/streaming-token?expires_in=300'));
    const td = await tr.json();
    token = td.token;
    if (!token) throw new Error(td.error || 'no token');
  } catch (e) {
    els.status.textContent = 'Could not get streaming token: ' + e.message;
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
  } catch (e) {
    els.status.textContent = 'Microphone permission denied.';
    return;
  }

  audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
  await audioContext.audioWorklet.addModule('/static/pcm-processor.js');
  const source = audioContext.createMediaStreamSource(mediaStream);
  workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');
  source.connect(workletNode);

  const params = new URLSearchParams({
    sample_rate: String(SAMPLE_RATE),
    encoding: 'pcm_s16le',
    speech_model: 'universal-3-5-pro',
    speaker_labels: 'true',
    language_detection: 'true',
    format_turns: 'true',
    keyterms_prompt: JSON.stringify(PHARMA_KEYTERMS),
    token,
  });

  ws = new WebSocket(`wss://streaming.assemblyai.com/v3/ws?${params.toString()}`);

  ws.onopen = () => {
    recording = true;
    els.recordBtn.textContent = '⏹ End Huddle';
    els.status.textContent = '🔴 Listening... speak naturally (English / Luganda / Swahili).';
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    if (msg.type === 'Turn') handleTurn(msg);
    else if (msg.type === 'Begin') {
      els.status.textContent = '🔴 Session ' + msg.id + ' — listening...';
    } else if (msg.type === 'Error') {
      els.status.textContent = 'AssemblyAI error: ' + JSON.stringify(msg);
    }
  };

  ws.onerror = () => { els.status.textContent = 'WebSocket error.'; };
  ws.onclose = (e) => {
    els.status.textContent = `Session closed (${e.code}).`;
  };

  workletNode.port.onmessage = (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(e.data);
    }
  };
  workletNode.connect(audioContext.destination);
}

function handleTurn(msg) {
  const text = msg.transcript || '';
  if (!text) return;
  const speaker = msg.speaker_label || msg.speaker || 'speaker';
  const lang = msg.language_code || 'en';

  if (msg.end_of_turn) {
    turns.push({ speaker, text, language: lang });
  }
  renderLive(speaker, text, lang, msg.end_of_turn);
}

function renderLive(speaker, text, lang, isFinal) {
  let host = document.getElementById('live-' + speaker);
  if (!host) {
    host = document.createElement('div');
    host.id = 'live-' + speaker;
    host.className = 'turn';
    host.innerHTML = `<span class="who">${speaker}</span><span class="liveText"></span>`;
    els.transcript.appendChild(host);
  }
  host.querySelector('.liveText').textContent = text + (isFinal ? '' : ' …');
  host.classList.toggle('partial', !isFinal);
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

async function stopRecord() {
  recording = false;
  els.recordBtn.textContent = '🎙 Start Huddle';
  els.status.textContent = 'Finalising transcript...';

  if (workletNode) { workletNode.port.onmessage = null; }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'Terminate' }));
  }
  await new Promise(r => setTimeout(r, 800));
  try { ws && ws.close(); } catch {}
  try { mediaStream && mediaStream.getTracks().forEach(t => t.stop()); } catch {}
  try { audioContext && await audioContext.close(); } catch {}

  if (!turns.length && lastTranscript) {
    turns = [{ speaker: 'speaker', text: lastTranscript, language: 'en' }];
  }
  if (!turns.length) {
    els.status.textContent = 'No speech detected. Use "Replay demo huddle" to see the flow.';
    return;
  }
  await submitHuddle(turns);
}

let lastTranscript = '';

async function submitHuddle(turnList) {
  els.status.textContent = `Extracting knowledge from ${turnList.length} turns...`;
  const meta = Object.fromEntries(new FormData(document.getElementById('meta')));
  const res = await fetch(galenApi('/api/huddle'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...meta, turns: turnList }),
  });
  const data = await res.json();
  renderEntries(data);
  refreshTwin(meta.equipment);
}

function renderEntries(data) {
  els.entries.innerHTML = '';
  (data.entries || []).forEach(e => {
    els.entries.innerHTML += `
      <div class="entry ${e.severity === 'high' ? 'flagged' : ''}">
        <strong>${e.title}</strong> <span class="tag">${e.entry_type}</span>
        <p>${e.body}</p>
        <small>${e.speaker || ''} · parsed by ${data.parsed_by}</small>
      </div>`;
  });
  if ((data.alerts || []).length) {
    els.status.textContent = '⚠ ' + data.alerts.map(a => a.message).join('; ');
  } else {
    els.status.textContent = `Captured ${data.entry_count} entries. No actionable deviation.`;
  }
}

async function refreshTwin(equipment) {
  const twin = await (await fetch(galenApi(`/api/twin/${equipment}`))).json();
  els.twin.innerHTML = Object.entries(twin).map(([k, v]) =>
    `<div class="card"><strong>${k}</strong> ${v.value}${v.unit || ''}</div>`).join('');
}

async function replayFixture() {
  els.status.textContent = 'Replaying demo huddle (simulated shift handover)...';
  turns = [];
  els.transcript.innerHTML = '';
  els.entries.innerHTML = '';

  const fixture = await (await fetch(galenApi('/api/demo-huddle'))).json();
  const stage = [
    ['shift_lead', 'Reactor R2 is running hot again this morning.'],
    ['operator', 'Temperature is at 62 degrees, we pulled the feed back to 30 percent.'],
    ['shift_lead', 'When R2 runs hot, first check the cooling water valve, it is usually stuck.'],
    ['operator', 'We cleared it last time and it was fine.'],
    ['intern', 'Mze, tunafaa kuandika hii kwenye system?'],
    ['shift_lead', 'Yes, log it, and log the CAPA candidate for the valve inspection.'],
  ];
  for (const [speaker, text] of stage) {
    turns.push({ speaker, text, language: speaker === 'intern' ? 'sw' : 'en' });
    renderLive(speaker, text, speaker === 'intern' ? 'sw' : 'en', true);
    await new Promise(r => setTimeout(r, 450));
  }
  await submitHuddle(turns);
}
