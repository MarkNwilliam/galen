const answerEl = document.getElementById('answer');
const contextEl = document.getElementById('context');
const feedbackEl = document.getElementById('feedback');
let lastPayload = null;
let lastData = null;

function speak(text) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.0;
  u.pitch = 1.0;
  window.speechSynthesis.speak(u);
}

document.getElementById('askForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = { question: fd.get('question'), equipment: fd.get('equipment') || null };
  await ask(payload);
});

async function ask(payload) {
  lastPayload = payload;
  answerEl.textContent = 'Thinking...';
  feedbackEl.innerHTML = '';
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  lastData = data;
  answerEl.innerHTML = data.answer;
  contextEl.innerHTML = `
    <h2>Context</h2>
    <small>Entries used: ${data.entries_used || 0} · parsed by ${data.parsed_by} · cited: ${data.cited}</small>
    <pre>${JSON.stringify(data.twin_state || {}, null, 2)}</pre>`;
  if (data.answer) speak(data.answer.replace(/<[^>]+>/g, ''));
  renderFeedback();
}

function renderFeedback() {
  if (!lastData) return;
  feedbackEl.innerHTML = `
    <div class="feedback-bar">
      <span>Did this resolve it?</span>
      <button onclick="sendFeedback(true)">✅ Yes</button>
      <button onclick="sendFeedback(false)">❌ No, still stuck</button>
    </div>`;
}

async function sendFeedback(worked) {
  feedbackEl.innerHTML = '<span class="status">Recording…</span>';
  const res = await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      entry_id: lastData.top_entry_id || null,
      question: (lastPayload && lastPayload.question) || '',
      worked,
    }),
  });
  const data = await res.json();
  feedbackEl.innerHTML = `<div class="feedback-bar"><strong>${data.message}</strong></div>`;
}

async function voiceAsk() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mr = new MediaRecorder(stream);
  const chunks = [];
  mr.ondataavailable = e => chunks.push(e.data);
  mr.onstop = async () => {
    const res = await fetch('/api/transcribe-file', {
      method: 'POST',
      body: new Blob(chunks, { type: 'audio/webm' }),
    });
    const data = await res.json();
    const question = (data.turns || []).map(t => t.text).join(' ');
    document.querySelector('[name=question]').value = question;
    await ask({ question, equipment: null });
  };
  mr.start();
  setTimeout(() => mr.stop(), 6000);
}