document.addEventListener('DOMContentLoaded', () => {
  const $ = id => document.getElementById(id);

  /* Sidebar toggle (mobile) */
  const menu = $('menuButton'), sidebar = $('sidebar');
  if (menu && sidebar) menu.addEventListener('click', () => sidebar.classList.toggle('open'));

  /* Game search: filters cards, updates count and empty message */
  const search = $('gameSearch'), cards = [...document.querySelectorAll('#gameGrid .game-card')];
  const count = $('gameCount'), none = $('noGamesMessage');
  if (search) search.addEventListener('input', () => {
    const t = search.value.trim().toLowerCase();
    let shown = 0;
    cards.forEach(c => {
      const ok = !t || c.dataset.name.includes(t);
      c.hidden = !ok;
      if (ok) shown++;
    });
    if (count) count.textContent = shown;
    if (none) none.hidden = shown > 0;
  });

  /* Upload file name */
  const file = $('learningFile'), fileMsg = $('fileMessage');
  if (file && fileMsg) file.addEventListener('change', () => {
    fileMsg.textContent = file.files.length ? 'Selected: ' + file.files[0].name : 'No file selected.';
  });

  /* Video form: validate and show progress */
  const form = $('videoForm'), btn = $('generateButton'), msg = $('formMessage');
  if (form) form.addEventListener('submit', e => {
    const topic = $('topic').value.trim();
    if (!topic && !(file && file.files.length)) {
      e.preventDefault();
      if (msg) msg.textContent = 'Enter a topic or upload a file first.';
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = 'Generating… please wait'; }
    if (msg) msg.textContent = 'Creating your lesson. This can take a few minutes.';
  });

  /* Replay video */
  const vid = $('learningVideo'), replay = $('replayVideo');
  if (vid && replay) replay.addEventListener('click', () => { vid.currentTime = 0; vid.play(); });

  /* Ask EduAI: posts to /ask_question (change the URL to match your Flask route) */
  const qForm = $('questionForm'), qText = $('questionText'), qOut = $('questionResponse');
  if (qForm) qForm.addEventListener('submit', async e => {
    e.preventDefault();
    const question = qText.value.trim();
    if (!question) { qOut.textContent = 'Type a question first.'; return; }
    qOut.textContent = 'Thinking…';
    try {
      const r = await fetch('/ask_question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      qOut.textContent = d.answer || 'No answer returned.';
    } catch (err) {
      qOut.textContent = 'Could not reach EduAI right now. Please try again.';
    }
  });
});