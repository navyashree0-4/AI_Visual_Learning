/* EduVision Arcade - static/js/game.js (all games) */
(() => {
"use strict";
const B = document.body, $ = id => document.getElementById(id), cfg = window.EDUVISION_GAME || {};
const key = String(cfg.key || B.dataset.gameKey || ""), url = B.dataset.finishUrl || "", area = $("game-content");
if (!area || !key) { console.error("EduVision: missing #game-content or data-game-key"); return; }
const MAXL = Number(cfg.lives || 3), SPRINT = key === "sprint_game";
const TOTAL = SPRINT ? 999 : Math.max(1, Math.min(Number(cfg.count || 5), 20));
const R = a => a[Math.random() * a.length | 0], sh = a => [...a].sort(() => Math.random() - .5);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const render = h => { area.innerHTML = h; };
const bestKey = "ev_best_" + key;
let best = +localStorage.getItem(bestKey) || 0, muted = localStorage.getItem("ev_mute") === "1";
let S = null, clock = null;

/* ---------- sound + effects ---------- */
let ac;
function beep(f, d = .12, t = "sine") {
  if (muted) return;
  try {
    ac = ac || new (window.AudioContext || window.webkitAudioContext)();
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = t; o.frequency.value = f; g.gain.value = .08; o.connect(g); g.connect(ac.destination);
    o.start(); g.gain.exponentialRampToValueAtTime(.001, ac.currentTime + d); o.stop(ac.currentTime + d);
  } catch (e) {}
}
const sfx = { ok() { beep(660); setTimeout(() => beep(880), 90); }, bad() { beep(180, .25, "sawtooth"); },
  win() { [523, 659, 784, 1047].forEach((f, i) => setTimeout(() => beep(f, .18), i * 110)); } };
function floatText(t, c = "") { const e = document.createElement("div"); e.className = "float " + c; e.textContent = t; document.body.appendChild(e); setTimeout(() => e.remove(), 1000); }
function confetti() {
  for (let i = 0; i < 70; i++) {
    const c = document.createElement("i"); c.className = "conf";
    c.style.cssText = `left:${Math.random() * 100}vw;background:hsl(${Math.random() * 360} 90% 60%);animation-delay:${Math.random() * .5}s;--x:${Math.random() * 240 - 120}px`;
    document.body.appendChild(c); setTimeout(() => c.remove(), 3000);
  }
}
const msg = (t, c = "") => { const f = $("feedback"); f.textContent = t; f.className = "feedback " + c; };
const mb = $("muteBtn");
if (mb) { mb.textContent = muted ? "🔇" : "🔊"; mb.onclick = () => { muted = !muted; localStorage.setItem("ev_mute", muted ? "1" : "0"); mb.textContent = muted ? "🔇" : "🔊"; }; }

/* ---------- content ---------- */
const HOW = {
  snake_learner: "Steer the snake with arrows or the pad. Eat only the right category!",
  whack_concept: "Tap only the concepts that match the category. It changes every few seconds!",
  typing_racer: "Type the word exactly to drive your car to the finish.",
  simon_memory: "Watch the colours and sounds, then repeat the pattern.",
  tech_2048: "Swipe or use arrows. Merge Bit, Byte, KB, MB, GB until you reach TB!",
  flappy_brain: "Flap through the gate with the right term. Wrong gates cost a heart.",
  tetris_blocks: "Fill lines to clear them and learn a tech fact.",
  minesweeper_debug: "Dig safe cells and flag bugs using the number clues.",
  maze_runner: "Walk the maze, answer questions to win keys, then open the door.",
  tower_firewall: "Build firewalls, antivirus and routers to stop 5 waves of viruses.",
  pacman_data: "Eat every data packet and dodge the bug ghosts.",
  logic_gates: "Place logic gates so the bulb matches the target for every input.",
  robot_coder: "Program the robot with commands to reach the star.",
  platform_adventure: "Run and jump! Collect topic words and dodge bugs through 3 worlds.",
  escape_room_2: "Drag clues into place to unlock 3 rooms and escape.",
  candy_match: "Swap two neighbouring candies to line up 3 or more. You have 20 moves!",
  bubble_shooter: "Pick a column, shoot, and match 3+ colours. 15 shots to clear the board!",
  mind_match: "Flip two cards at a time and find all 6 pairs.",
  cosmic_quiz: "Answer tech questions. Wrong answers cost a heart.",
  daily_brain_boost: "A mix of quiz, word, mystery and number puzzles.",
  word_wizard: "Unscramble the tech word using the hint.",
  match_concept: "Pick a term, then pick its meaning.",
  sprint_game: "Answer as many as you can in 60 seconds!",
  concept_detective: "Read the clues and name the concept.",
  code_builder: "Tap the code lines in the right order.",
  tech_escape_room: "Solve each lock to escape.",
  listen_recall: "Play the word, then type what you heard.",
  knowledge_league: "Climb the league with correct answers.",
  sequence_master: "Find the number that comes next."
};
const Q = [
  ["Which component is the brain of a computer?", "CPU", ["Monitor", "Keyboard", "Mouse"], "The CPU processes instructions."],
  ["Which language structures a web page?", "HTML", ["SQL", "Python", "C"], "HTML defines page structure."],
  ["What does RAM provide?", "Temporary memory", ["Permanent storage", "Internet access", "Power"], "RAM holds data for running programs."],
  ["Which is a relational database system?", "MySQL", ["HTML", "CSS", "PNG"], "MySQL manages relational data."],
  ["What is an algorithm?", "Steps to solve a problem", ["A monitor", "An image format", "A keyboard key"], "It is a sequence of steps."],
  ["Which data structure follows FIFO?", "Queue", ["Stack", "Tree", "Graph"], "First In, First Out."],
  ["What does CSS control?", "Page appearance", ["Database records", "Hardware", "Cables"], "CSS handles style and layout."],
  ["Which language queries databases?", "SQL", ["CSS", "HTML", "PNG"], "SQL queries relational data."],
  ["What does HTTP stand for?", "HyperText Transfer Protocol", ["High Tech Transfer Page", "Home Tool Text Process", "Hyper Tab Tool Program"], "It is how browsers talk to servers."],
  ["Which data structure follows LIFO?", "Stack", ["Queue", "Array", "Table"], "Last In, First Out."]
];
const WORDS = [["PYTHON", "A programming language"], ["DATABASE", "An organised collection of data"], ["NETWORK", "Connected computers"], ["BROWSER", "Software to visit websites"], ["VARIABLE", "A named place for a value"], ["FUNCTION", "Reusable block of code"], ["ALGORITHM", "Steps to solve a problem"]];
const PAIRS = [["CPU", "Processes instructions"], ["RAM", "Temporary memory"], ["HTML", "Page structure"], ["CSS", "Page styling"], ["SQL", "Database queries"], ["ALGORITHM", "Steps to solve a problem"]];
const CODE = [["Arrange the lines to print a greeting.", ["name = 'Student'", "print(name)", 'print("Hello")']], ["Arrange the lines to calculate a sum.", ["a = 5", "total = a + 3", "print(total)"]], ["Arrange the lines to loop 3 times.", ["for i in range(3):", "    print(i)", "print('done')"]]];
const CASES = [[["I temporarily store data for active programs.", "My contents vanish when power is removed."], "RAM", ["RAM", "SSD", "Monitor", "Keyboard"]], [["I organise information in tables.", "SQL can query me."], "Database", ["Database", "Browser", "Mouse", "Compiler"]], [["I translate source code into machine code.", "I run before the program does."], "Compiler", ["Compiler", "Router", "Printer", "Cursor"]]];
const LOCKS = [["What is 2 + 3?", "5", "Add two and three."], ["Which language structures web pages?", "html", "It uses tags."], ["Which language uses SELECT to query data?", "sql", "Three letters."], ["What is 4 × 4?", "16", "Four groups of four."]];
const LISTEN = ["CPU", "RAM", "HTML", "SQL", "PYTHON", "NETWORK"];

/* ---------- state + HUD ---------- */
function ui() {
  if (!S) return;
  $("score").textContent = S.score;
  $("streak").textContent = S.streak >= 3 ? "🔥" + S.streak : S.streak;
  $("lives").textContent = "❤️".repeat(S.lives) + "🖤".repeat(Math.max(0, MAXL - S.lives));
  $("level").textContent = 1 + Math.floor(S.score / 100);
  $("bestScore").textContent = Math.max(best, S.score);
  $("xp").style.width = (S.score % 100) + "%";
  const left = SPRINT ? Math.max(0, 60 - S.secs) : S.secs;
  $("timer").textContent = String(left / 60 | 0).padStart(2, "0") + ":" + String(left % 60).padStart(2, "0");
  $("progressLabel").textContent = S.moves != null ? (S.mlabel || "Moves left") : "Round";
  $("progress").textContent = S.moves != null ? S.moves : SPRINT ? S.round + 1 : Math.min(S.round + 1, S.total) + " / " + S.total;
}
const lock = () => { if (S.wait || S.done || !S.on) return true; S.wait = true; return false; };
function award(base) {
  const lvl = 1 + Math.floor(S.score / 100);
  S.streak++; S.correct++;
  const mult = S.streak >= 5 ? 3 : S.streak >= 3 ? 2 : 1, pts = base * mult;
  S.score += pts; sfx.ok(); floatText("+" + pts + (mult > 1 ? " 🔥x" + mult : ""));
  if (1 + Math.floor(S.score / 100) > lvl) { floatText("LEVEL UP! ⭐"); sfx.win(); }
  ui();
}
function lose(m) {
  S.streak = 0; S.lives = Math.max(0, S.lives - 1); sfx.bad(); floatText("💔", "bad");
  $("game-content").classList.add("shake"); setTimeout(() => $("game-content").classList.remove("shake"), 400);
  msg(m, "bad"); ui();
  if (S.lives === 0) finish();
}
function after() {
  if (S.done) return;
  if (SPRINT) setTimeout(advance, 650);
  else { $("next").hidden = false; $("finish").hidden = S.round < S.total - 1; }
}
function advance() {
  if (!S.on || S.done) return;
  S.round++;
  if (S.round >= S.total) { finish(); return; }
  S.wait = false; $("next").hidden = true; msg(""); launch(); ui();
}

/* ---------- generic renderers ---------- */
function choice(r) {
  render(`<section class="card"><span class="tag">${esc(r.tag)}</span><h2>${esc(r.q)}</h2>${(r.clues || []).map((c, i) => `<p>🔎 Clue ${i + 1}: ${esc(c)}</p>`).join("")}${r.big ? `<div class="big">${esc(r.big)}</div>` : ""}<div class="opts">${sh(r.opts).map(o => `<button type="button" class="opt" data-o="${esc(o)}">${esc(o)}</button>`).join("")}</div></section>`);
  area.querySelectorAll(".opt").forEach(b => b.onclick = () => {
    if (lock()) return;
    area.querySelectorAll(".opt").forEach(x => { x.disabled = true; if (x.dataset.o === r.ans) x.classList.add("ok"); });
    if (b.dataset.o === r.ans) { award(r.pts || 10); msg("Correct! " + (r.exp || ""), "ok"); }
    else { b.classList.add("no"); lose("Not quite. " + (r.exp || "Answer: " + r.ans)); }
    after();
  });
}
function text(r) {
  render(`<section class="card"><span class="tag">${esc(r.tag)}</span><h2>${esc(r.q)}</h2>${r.big ? `<div class="big">${esc(r.big)}</div>` : ""}${r.speak ? `<button type="button" class="btn alt" id="say">🔊 Play word</button>` : ""}<input id="ans" class="input" placeholder="${esc(r.ph || "Type your answer")}" autocomplete="off"><button type="button" class="btn" id="chk">Check</button>${r.hint ? `<p class="hint">💡 ${esc(r.hint)}</p>` : ""}</section>`);
  const inp = $("ans");
  const go = () => {
    if (lock()) return;
    inp.disabled = true; $("chk").disabled = true;
    if (inp.value.trim().toLowerCase() === r.ans.toLowerCase()) { inp.classList.add("ok"); award(r.pts || 12); msg("Correct! " + r.ans, "ok"); }
    else { inp.classList.add("no"); lose("The answer was " + r.ans + "."); }
    after();
  };
  $("chk").onclick = go; inp.onkeydown = e => { if (e.key === "Enter") go(); }; inp.focus();
  if (r.speak) $("say").onclick = () => {
    if (!("speechSynthesis" in window)) { msg("Speech is not available in this browser."); return; }
    speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(r.ans); u.rate = .8; speechSynthesis.speak(u);
  };
}
const quiz = () => { const q = S.qs[S.round % S.qs.length]; choice({ tag: SPRINT ? "⚡ SPRINT" : "ROUND " + (S.round + 1), q: q[0], ans: q[1], opts: [q[1], ...q[2]], exp: q[3] }); };
const word = () => { const [w, h] = WORDS[S.round % WORDS.length]; let s = sh(w.split("")).join(""); if (s === w) s = w.slice(1) + w[0]; text({ tag: "WORD WIZARD", q: "Unscramble the word", big: s, hint: h, ans: w }); };
const detective = () => { const [c, a, o] = CASES[S.round % CASES.length]; choice({ tag: "CASE " + (S.round + 1), q: "Who am I?", clues: c, ans: a, opts: o, pts: 12 }); };
const escape = () => { const [q, a, h] = LOCKS[S.round % LOCKS.length]; text({ tag: "🔐 LOCK " + (S.round + 1), q, hint: h, ans: a, pts: 15 }); };
const listen = () => text({ tag: "LISTEN & RECALL", q: "Play the word and type it", speak: true, ans: LISTEN[S.round % LISTEN.length], ph: "What did you hear?" });
function sequence() {
  const a = 1 + Math.random() * 6 | 0, d = 2 + Math.random() * 5 | 0, geo = Math.random() < .3;
  const v = Array.from({ length: 4 }, (_, i) => geo ? a * 2 ** i : a + d * i), ans = geo ? a * 16 : a + d * 4;
  choice({ tag: "SEQUENCE MASTER", q: "What comes next?", big: v.join(" → ") + " → ?", ans: String(ans), opts: [...new Set([ans, ans + d, ans - 1, ans + 2].map(String))], pts: 10 });
}
function daily() { [quiz, word, detective, sequence][S.round % 4](); }

/* ---------- matching cards (flip) ---------- */
function memory() {
  const pool = sh(["🧠", "🚀", "📘", "💡", "🌟", "🎯", "💻", "🔐", "📡", "🤖"]), np = [3, 4, 6, 8, 8][S.round] || 8;
  const v = sh(pool.slice(0, np).flatMap(x => [x, x])); let pick = [], found = 0, moves = 0;
  render(`<section class="card"><span class="tag">🃏 LEVEL ${S.round + 1} · ${np} PAIRS · MOVES <span id="mv">0</span></span><h2>Remember and match the pairs</h2><div class="fgrid">${v.map((x, i) => `<button type="button" class="fc" data-i="${i}" aria-label="Card ${i + 1}"><span class="fi"><b class="ff">?</b><b class="fb">${x}</b></span></button>`).join("")}</div></section>`);
  const cards = [...area.querySelectorAll(".fc")];
  S.wait = true; cards.forEach(c => c.classList.add("flip")); msg("Memorise the cards...");
  setTimeout(() => { cards.forEach(c => c.classList.remove("flip")); S.wait = false; msg("Go!"); }, 1300 + np * 100);
  cards.forEach(c => c.onclick = () => {
    const i = +c.dataset.i; if (S.wait || S.done || pick.includes(i) || c.classList.contains("done")) return;
    c.classList.add("flip"); pick.push(i); beep(520, .06);
    if (pick.length < 2) return;
    const [x, y] = pick; moves++; $("mv").textContent = moves;
    if (v[x] === v[y]) {
      [x, y].forEach(k => cards[k].classList.add("done")); pick = []; award(10); msg("Pair found!", "ok");
      if (++found === np) { const bonus = Math.max(0, (np * 3 - moves) * 3); if (bonus) { S.score += bonus; floatText("Bonus +" + bonus); } confetti(); msg("Level cleared in " + moves + " moves!", "ok"); ui(); after(); }
    } else {
      S.wait = true; S.streak = 0; ui(); msg("Not a pair", "bad");
      setTimeout(() => { [x, y].forEach(k => cards[k].classList.remove("flip")); pick = []; S.wait = false; }, 750);
    }
  });
}

/* ---------- match the concept ---------- */
function concept() {
  const p = sh(PAIRS).slice(0, 4), t = sh(p.map(x => x[0])), d = sh(p.map(x => x[1])); let ct = null, n = 0;
  render(`<section class="card"><span class="tag">MATCH THE CONCEPT</span><h2>Match each term to its meaning</h2><div class="mt"><div>${t.map((x, i) => `<button type="button" data-t="${i}">${esc(x)}</button>`).join("")}</div><div>${d.map((x, i) => `<button type="button" data-d="${i}">${esc(x)}</button>`).join("")}</div></div></section>`);
  area.querySelectorAll("[data-t]").forEach(b => b.onclick = () => { if (S.done) return; ct = +b.dataset.t; area.querySelectorAll("[data-t]").forEach(x => x.classList.remove("sel")); b.classList.add("sel"); });
  area.querySelectorAll("[data-d]").forEach(b => b.onclick = () => {
    if (S.done || ct === null) return;
    const pair = p.find(x => x[0] === t[ct]);
    if (pair[1] === d[+b.dataset.d]) {
      const tb = area.querySelector(`[data-t="${ct}"]`); tb.disabled = b.disabled = true; tb.classList.remove("sel"); tb.classList.add("ok"); b.classList.add("ok");
      ct = null; award(5); msg("Great match!", "ok"); if (++n === 4) after();
    } else { S.streak = 0; sfx.bad(); msg("Not a match, try again", "bad"); ui(); }
  });
}

/* ---------- code builder ---------- */
function code() {
  const [title, ans] = CODE[S.round % CODE.length], ls = sh(ans); let sel = [];
  render(`<section class="card"><span class="tag">CODE BUILDER</span><h2>${esc(title)}</h2>${ls.map((l, i) => `<button type="button" class="code" data-i="${i}">${esc(l)}</button>`).join("")}<p id="cs">Tap the lines in order. Tap again to undo.</p><button type="button" class="btn" id="chk">Run code ▶</button></section>`);
  area.querySelectorAll(".code").forEach(b => b.onclick = () => {
    if (S.wait || S.done) return; const i = +b.dataset.i;
    sel = sel.includes(i) ? sel.filter(x => x !== i) : [...sel, i]; b.classList.toggle("sel"); beep(400, .05);
    $("cs").textContent = sel.length ? sel.map(k => ls[k].trim()).join("  →  ") : "Tap the lines in order.";
  });
  $("chk").onclick = () => {
    if (lock()) return;
    if (sel.map(k => ls[k]).join("\n") === ans.join("\n")) { award(15); msg("Code runs perfectly!", "ok"); } else lose("Wrong order. The code crashed!");
    $("chk").disabled = true; after();
  };
}

/* ---------- candy crush ---------- */
const N = 8, CD = [["🍓", "#ff4d6d"], ["🍋", "#ffd23f"], ["🍇", "#a66bff"], ["🍊", "#ff9f43"], ["🫐", "#3d8bff"], ["🍏", "#2ed573"]];
let cd = [], csel = null, boom = new Set(), drop = new Set(), swiped = false;
const rc = () => Math.random() * 6 | 0;
function cm() {
  const m = new Set();
  for (let i = 0; i < N * N; i++) {
    const r = i / N | 0, c = i % N;
    if (c < N - 2 && cd[i] === cd[i + 1] && cd[i] === cd[i + 2]) [i, i + 1, i + 2].forEach(x => m.add(x));
    if (r < N - 2 && cd[i] === cd[i + N] && cd[i] === cd[i + 2 * N]) [i, i + N, i + 2 * N].forEach(x => m.add(x));
  }
  return [...m];
}
function hasMove() {
  for (let i = 0; i < N * N; i++) for (const j of [i + 1, i + N]) {
    if (j >= N * N || (j === i + 1 && j % N === 0)) continue;
    [cd[i], cd[j]] = [cd[j], cd[i]]; const ok = cm().length > 0; [cd[i], cd[j]] = [cd[j], cd[i]]; if (ok) return true;
  }
  return false;
}
function candy() {
  do { cd = Array.from({ length: N * N }, rc); for (let k = 0; k < 40 && cm().length; k++) cm().forEach(i => cd[i] = rc()); } while (!hasMove());
  csel = null; S.moves = 20; S.goal = 250; S.mlabel = "Moves left"; drawCandy(); ui();
}
function drawCandy() {
  render(`<section class="card"><span class="tag">🍬 GOAL ${S.goal} PTS · YOU ${S.score}</span><h2>Swap or swipe candies to match 3+</h2><div class="board" id="cb">${cd.map((c, i) => `<button type="button" class="cell${boom.has(i) ? " boom" : ""}${drop.has(i) ? " drop" : ""}" data-i="${i}" aria-label="Candy ${i + 1}" style="--c:${CD[c][1]}">${CD[c][0]}</button>`).join("")}</div></section>`);
  let down = null;
  area.querySelectorAll(".cell").forEach(b => {
    b.onpointerdown = e => { down = { i: +b.dataset.i, x: e.clientX, y: e.clientY }; };
    b.onpointerup = e => {
      if (!down) return; const dx = e.clientX - down.x, dy = e.clientY - down.y, a = down.i; down = null;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 22) return;
      swiped = true; const t = Math.abs(dx) > Math.abs(dy) ? a + Math.sign(dx) : a + N * Math.sign(dy);
      if (t < 0 || t >= N * N || (Math.abs(dx) > Math.abs(dy) && (t / N | 0) !== (a / N | 0))) return;
      csel = null; trySwap(a, t);
    };
    b.onclick = () => {
      if (swiped) { swiped = false; return; } if (S.wait || S.done) return; const i = +b.dataset.i;
      if (csel === null) { csel = i; b.classList.add("sel"); beep(500, .05); return; }
      const a = csel; csel = null; trySwap(a, i);
    };
  });
}
function trySwap(a, i) {
  if (S.wait || S.done) return;
  const near = Math.abs(a - i) === N || ((a / N | 0) === (i / N | 0) && Math.abs(a - i) === 1);
  if (!near) { drawCandy(); msg("Pick a neighbouring candy"); return; }
  [cd[a], cd[i]] = [cd[i], cd[a]]; const m = cm();
  if (!m.length) { [cd[a], cd[i]] = [cd[i], cd[a]]; drawCandy(); msg("No match. Try another swap.", "bad"); sfx.bad(); return; }
  S.moves--; S.wait = true; cascade(m);
}
function cascade(m) {
  boom = new Set(m); drawCandy(); beep(600, .08);
  setTimeout(() => {
    const low = {}; m.forEach(i => { const c = i % N, r = i / N | 0; low[c] = Math.max(low[c] ?? -1, r); });
    m.forEach(i => cd[i] = null);
    const pts = m.length * 5 + Math.max(0, m.length - 3) * 5; award(pts); msg(m.length > 3 ? `Super combo! ${m.length} candies` : `Sweet! ${m.length} candies`, "ok");
    drop = new Set();
    for (let c = 0; c < N; c++) {
      const col = []; for (let r = N - 1; r >= 0; r--) if (cd[r * N + c] !== null) col.push(cd[r * N + c]);
      while (col.length < N) col.push(rc());
      for (let r = N - 1; r >= 0; r--) cd[r * N + c] = col[N - 1 - r];
      if (low[c] !== undefined) for (let r = 0; r <= low[c]; r++) drop.add(r * N + c);
    }
    boom = new Set(); drawCandy(); ui(); drop = new Set();
    const more = cm();
    if (more.length) { setTimeout(() => !S.done && cascade(more), 450); return; }
    if (S.score >= S.goal) { S.wait = false; award(30); msg("Goal reached! 🎉", "ok"); confetti(); finish(); return; }
    if (S.moves <= 0) { S.wait = false; finish(); return; }
    if (!hasMove()) { msg("No moves left, shuffling...", "bad"); do { cd = sh(cd); } while (cm().length || !hasMove()); drawCandy(); }
    S.wait = false;
  }, 330);
}

/* ---------- bubble shooter (canvas, aim with mouse/finger) ---------- */
const BR2 = 21, RH = BR2 * 1.732, MAXR = 12, CW = 420, CH = 560, SX = CW / 2, SY = CH - 38;
const BCOL = ["#ff4d6d", "#3d8bff", "#2ed573", "#ffd23f", "#a66bff", "#ff9f43"];
let bg = [], boff = 0, bcur = 0, bnext = 0, bang = Math.PI / 2, bshot = null, bparts = [], bmiss = 0, bcv = null;
const bpar = r => (r + boff) % 2, bcols = r => bpar(r) ? 9 : 10;
const bx = (r, c) => bpar(r) ? c * 2 * BR2 + 2 * BR2 : c * 2 * BR2 + BR2, by = r => BR2 + r * RH;
function bn(r, c) {
  const o = [[r, c - 1], [r, c + 1]];
  [r - 1, r + 1].forEach(y => bpar(r) ? o.push([y, c], [y, c + 1]) : o.push([y, c - 1], [y, c]));
  return o.filter(([y, x]) => y >= 0 && y < MAXR && x >= 0 && x < bcols(y));
}
const bcolors = () => { const s = [...new Set(bg.flat().filter(v => v >= 0))]; return s.length ? s : [rc()]; };
function bubble() {
  boff = 0; bmiss = 0; bshot = null; bparts = [];
  bg = Array.from({ length: MAXR }, (_, r) => Array.from({ length: bcols(r) }, () => r < 5 ? rc() : -1));
  bcur = R(bcolors()); bnext = R(bcolors()); S.moves = 6; S.mlabel = "Next row in";
  render(`<section class="card"><span class="tag">🫧 AIM · TAP TO SHOOT</span><h2>Match 3+ colours. Drop the hanging bubbles!</h2><canvas id="bcv" width="${CW}" height="${CH}" style="width:100%;max-width:${CW}px;touch-action:none;background:#17123b;border:4px solid #17123b;border-radius:18px"></canvas></section>`);
  bcv = $("bcv");
  const aimTo = e => { const r = bcv.getBoundingClientRect(), x = (e.clientX - r.left) * CW / r.width, y = (e.clientY - r.top) * CH / r.height; bang = Math.min(Math.PI - .17, Math.max(.17, Math.atan2(SY - y, x - SX))); };
  bcv.onpointermove = aimTo; bcv.onpointerdown = aimTo;
  bcv.onpointerup = e => { aimTo(e); if (bshot || S.wait || S.done) return; bshot = { x: SX, y: SY, vx: Math.cos(bang) * 15, vy: -Math.sin(bang) * 15, c: bcur }; beep(300, .05); };
  ui(); bframe();
}
function bsnap(x, y) {
  const row = Math.max(0, Math.min(MAXR - 1, Math.round((y - BR2) / RH))); let best = null, bd = 1e9;
  for (let r = Math.max(0, row - 2); r <= Math.min(MAXR - 1, row + 2); r++) for (let c = 0; c < bcols(r); c++) {
    if (bg[r][c] !== -1) continue;
    if (r > 0 && !bn(r, c).some(([a, b]) => bg[a][b] !== -1)) continue;
    const d = Math.hypot(bx(r, c) - x, by(r) - y); if (d < bd) { bd = d; best = [r, c]; }
  }
  return best;
}
function bland() {
  const s = bshot; bshot = null; const cell = bsnap(s.x, s.y) || [0, 0]; const [r, c] = cell;
  bg[r][c] = s.c; const col = s.c, g = new Set([r + "," + c]), st = [[r, c]];
  while (st.length) { const [y, x] = st.pop(); bn(y, x).forEach(([a, b]) => { if (bg[a][b] === col && !g.has(a + "," + b)) { g.add(a + "," + b); st.push([a, b]); } }); }
  if (g.size >= 3) {
    g.forEach(k => { const [a, b] = k.split(",").map(Number); bpop(a, b, bg[a][b]); bg[a][b] = -1; });
    const seen = new Set(), q = []; bg[0].forEach((v, x) => { if (v >= 0) { seen.add("0," + x); q.push([0, x]); } });
    while (q.length) { const [y, x] = q.pop(); bn(y, x).forEach(([a, b]) => { if (bg[a][b] >= 0 && !seen.has(a + "," + b)) { seen.add(a + "," + b); q.push([a, b]); } }); }
    let fall = 0; bg.forEach((row, a) => row.forEach((v, b) => { if (v >= 0 && !seen.has(a + "," + b)) { fall++; bparts.push({ x: bx(a, b), y: by(a), vx: Math.random() * 2 - 1, vy: 0, c: v, big: 1, l: 70 }); row[b] = -1; } }));
    award(g.size * 5 + fall * 10); msg(fall ? `POP! ${g.size} + ${fall} dropped!` : `POP! ${g.size} bubbles`, "ok");
  } else {
    sfx.bad(); S.streak = 0; bmiss++;
    if (bmiss >= 6) { bmiss = 0; boff ^= 1; bg.unshift(Array.from({ length: bcols(0) }, rc)); bg.pop(); msg("New row!", "bad"); }
  }
  S.moves = 6 - bmiss; ui();
  if (bg.flat().every(v => v < 0)) { award(60); confetti(); msg("Board cleared! 🎉", "ok"); finish(); return; }
  if (bg.slice(MAXR - 1).flat().some(v => v >= 0)) { msg("The bubbles reached the line!", "bad"); sfx.bad(); finish(); return; }
  bcur = bnext; bnext = R(bcolors());
}
function bpop(r, c, col) { for (let i = 0; i < 6; i++) bparts.push({ x: bx(r, c), y: by(r), vx: Math.random() * 6 - 3, vy: Math.random() * 6 - 3, c: col, l: 18 }); beep(700 + Math.random() * 200, .05); }
function bdot(x, y, rad, c) {
  const g = bcv.getContext("2d"); g.fillStyle = BCOL[c]; g.beginPath(); g.arc(x, y, rad, 0, 7); g.fill();
  g.strokeStyle = "#17123b"; g.lineWidth = 2; g.stroke(); g.fillStyle = "#ffffff99"; g.beginPath(); g.arc(x - rad * .3, y - rad * .3, rad * .28, 0, 7); g.fill();
}
function bframe() {
  if (!bcv || !bcv.isConnected || S.done) return;
  if (bshot) for (let k = 0; k < 3 && bshot; k++) {
    bshot.x += bshot.vx / 3; bshot.y += bshot.vy / 3;
    if (bshot.x < BR2) { bshot.x = BR2; bshot.vx *= -1; } if (bshot.x > CW - BR2) { bshot.x = CW - BR2; bshot.vx *= -1; }
    if (bshot.y <= BR2 || bg.some((row, r) => row.some((v, c) => v >= 0 && Math.hypot(bx(r, c) - bshot.x, by(r) - bshot.y) < BR2 * 1.8))) bland();
  }
  bparts.forEach(p => { p.x += p.vx; p.y += p.vy; if (p.big) p.vy += .6; p.l--; }); bparts = bparts.filter(p => p.l > 0 && p.y < CH + 30);
  const g = bcv.getContext("2d"); g.clearRect(0, 0, CW, CH);
  g.strokeStyle = "#ff4d5e"; g.setLineDash([8, 8]); g.lineWidth = 2; g.beginPath(); g.moveTo(0, by(MAXR - 1) - BR2); g.lineTo(CW, by(MAXR - 1) - BR2); g.stroke();
  g.strokeStyle = "#ffffff77"; g.setLineDash([4, 10]); g.beginPath(); g.moveTo(SX, SY); g.lineTo(SX + Math.cos(bang) * 150, SY - Math.sin(bang) * 150); g.stroke(); g.setLineDash([]);
  bg.forEach((row, r) => row.forEach((v, c) => { if (v >= 0) bdot(bx(r, c), by(r), BR2 - 1, v); }));
  bparts.forEach(p => bdot(p.x, p.y, p.big ? BR2 - 1 : 6, p.c));
  if (bshot) bdot(bshot.x, bshot.y, BR2 - 1, bshot.c); else bdot(SX, SY, BR2 - 1, bcur);
  bdot(46, SY + 6, 13, bnext); g.fillStyle = "#fff"; g.font = "bold 11px sans-serif"; g.fillText("NEXT", 28, SY + 34);
  requestAnimationFrame(bframe);
}

/* =====================================================
   15 MORE GAMES (shared helpers first)
   ===================================================== */
let kh = null;
document.addEventListener("keydown", e => {
  if (!kh || !S || !S.on || S.done) return;
  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(e.key)) e.preventDefault();
  kh(e);
});
const DIR = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", w: "up", s: "down", a: "left", d: "right" };
const pad = () => `<div class="dpad"><button type="button" data-k="up">▲</button><div><button type="button" data-k="left">◀</button><button type="button" data-k="down">▼</button><button type="button" data-k="right">▶</button></div></div>`;
function ctrl(fn) { kh = e => { const k = DIR[e.key]; if (k) fn(k); }; area.querySelectorAll(".dpad button").forEach(b => b.onclick = () => fn(b.dataset.k)); }
const alive = el => el && el.isConnected && S && !S.done && S.on;
const cvs = (w, h, x = "") => `<canvas id="cv" width="${w}" height="${h}" class="gcv" style="max-width:${w}px;${x}"></canvas>`;
const rr = (g, x, y, w, h, r) => { g.beginPath(); g.roundRect ? g.roundRect(x, y, w, h, r) : g.rect(x, y, w, h); };
const HW = ["CPU", "RAM", "GPU", "SSD", "USB", "Mouse"], SW = ["Linux", "Excel", "Java", "Chrome", "Zoom", "Word"], IN = ["Mic", "Mouse", "Keys", "Scanner"], OUT = ["Printer", "Speaker", "Screen", "Beamer"];
const pairPick = () => R([[["Hardware", HW], ["Software", SW]], [["Input device", IN], ["Output device", OUT]]]);
function dd(root, onPlace) {
  let sc = null;
  root.querySelectorAll(".chip").forEach(c => {
    c.draggable = true; c.ondragstart = e => e.dataTransfer.setData("text", c.dataset.v);
    c.onclick = () => { root.querySelectorAll(".chip").forEach(x => x.classList.remove("sel")); c.classList.add("sel"); sc = c; };
  });
  root.querySelectorAll(".slot").forEach(s => {
    s.ondragover = e => e.preventDefault();
    s.ondrop = e => { e.preventDefault(); onPlace(s, e.dataTransfer.getData("text")); };
    s.onclick = () => { if (sc) { onPlace(s, sc.dataset.v); sc.classList.remove("sel"); sc = null; } };
  });
}

/* 1. Snake Learner */
function snake() {
  const G = 10, C = 36, pk = pairPick(), [tn, tl] = pk[0], ol = pk[1][1];
  render(`<section class="card"><span class="tag">🐍 EAT ONLY: ${esc(tn.toUpperCase())}</span><h2>Eat ${esc(tn)} items. Avoid the rest!</h2>${cvs(G * C, G * C)}${pad()}</section>`);
  const cv = $("cv"), g = cv.getContext("2d"); S.moves = 10; S.mlabel = "Food left";
  let sn, d, nd, foods = [];
  const reset = () => { sn = [{ x: 4, y: 5 }, { x: 3, y: 5 }, { x: 2, y: 5 }]; d = nd = { x: 1, y: 0 }; };
  const free = () => { let p; do p = { x: Math.random() * G | 0, y: Math.random() * G | 0 }; while (sn.some(s => s.x === p.x && s.y === p.y) || foods.some(f => f.x === p.x && f.y === p.y)); return p; };
  const spawn = () => { foods = []; [...sh(tl).slice(0, 3).map(t => [t, 1]), ...sh(ol).slice(0, 2).map(t => [t, 0])].forEach(([t, ok]) => foods.push({ ...free(), t, ok })); };
  const draw = () => {
    g.fillStyle = "#fff7e0"; g.fillRect(0, 0, G * C, G * C); g.font = "bold 11px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.lineWidth = 2; g.strokeStyle = "#17123b";
    foods.forEach(f => { g.fillStyle = "#ffc93c"; rr(g, f.x * C + 2, f.y * C + 5, C - 4, C - 10, 8); g.fill(); g.stroke(); g.fillStyle = "#17123b"; g.fillText(f.t, f.x * C + C / 2, f.y * C + C / 2); });
    sn.forEach((s, i) => { g.fillStyle = i ? "#17c97a" : "#0a9e5c"; rr(g, s.x * C + 2, s.y * C + 2, C - 4, C - 4, 10); g.fill(); g.stroke(); });
  };
  reset(); spawn(); draw(); ui();
  ctrl(k => { const m = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] }[k]; if (!(m[0] === -d.x && m[1] === -d.y)) nd = { x: m[0], y: m[1] }; });
  const iv = setInterval(() => {
    if (!alive(cv)) { clearInterval(iv); return; }
    d = nd; const h = { x: sn[0].x + d.x, y: sn[0].y + d.y };
    if (h.x < 0 || h.y < 0 || h.x >= G || h.y >= G || sn.some(s => s.x === h.x && s.y === h.y)) { lose("Crash! Mind the walls."); if (!S.done) reset(); draw(); return; }
    sn.unshift(h); const i = foods.findIndex(f => f.x === h.x && f.y === h.y);
    if (i < 0) sn.pop();
    else { const f = foods[i]; if (f.ok) { award(10); S.moves--; ui(); if (S.moves <= 0) { confetti(); finish(); return; } msg("Yum! " + f.t, "ok"); spawn(); } else { sn.pop(); sn.length = Math.max(2, sn.length - 2); foods.splice(i, 1); lose(f.t + " is not " + tn + "! You shrank."); } }
    draw();
  }, 170);
}

/* 2. Whack-a-Concept */
function whack() {
  const [[an, al], [bn, bl]] = pairPick(), L = { [an]: al, [bn]: bl }; let cat = an, t = 0, cur = null; S.moves = 45; S.mlabel = "Seconds left";
  render(`<section class="card"><span class="tag">🔨 WHACK ONLY: <b id="wc">${esc(an.toUpperCase())}</b></span><h2>Tap the right concept before it hides!</h2><div class="holes">${Array.from({ length: 9 }, (_, i) => `<button type="button" class="hole" data-i="${i}"></button>`).join("")}</div></section>`);
  const hs = [...area.querySelectorAll(".hole")];
  hs.forEach(h => h.onclick = () => {
    if (S.done || !cur || cur.hit || +h.dataset.i !== cur.i) return; cur.hit = 1; h.classList.add("hit");
    if (cur.ok) { award(8); msg("Smash! " + cur.t, "ok"); } else lose(cur.t + " is not " + cat + "!");
  });
  const iv = setInterval(() => {
    if (!alive(hs[0])) { clearInterval(iv); return; } t++;
    if (t % 14 === 0) { cat = cat === an ? bn : an; $("wc").textContent = cat.toUpperCase(); floatText("Now: " + cat); }
    hs.forEach(h => { h.textContent = ""; h.classList.remove("up", "hit"); });
    const i = Math.random() * 9 | 0, ok = Math.random() < .5, w = R(ok ? L[cat] : L[cat === an ? bn : an]); cur = { i, t: w, ok };
    hs[i].textContent = w; hs[i].classList.add("up"); S.moves = Math.max(0, 45 - Math.round(t * .6)); ui();
    if (S.moves <= 0) { clearInterval(iv); confetti(); finish(); }
  }, 600);
}

/* 3. Typing Racer */
const TW = ["python", "server", "router", "kernel", "pixel", "binary", "cloud", "npm install", "print(x)", "git commit", "for i in range(3):", "SELECT * FROM users;", "<div></div>", "ssh user@host"];
function typing() {
  S.ws = S.ws || sh(TW); const w = S.ws[S.round % S.ws.length];
  render(`<section class="card"><span class="tag">🏎️ RACE ${S.round + 1} / ${S.total}</span><h2>Type it fast to drive!</h2><div class="track"><span class="car" id="car" style="left:${S.round / S.total * 82}%">🏎️</span><span class="flag">🏁</span></div><div class="big tw" id="tw">${[...w].map(c => `<span>${esc(c === " " ? "␣" : c)}</span>`).join("")}</div><input id="ty" class="input" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Start typing..."></section>`);
  const t0 = Date.now(), inp = $("ty"), sp = [...$("tw").children];
  const to = setTimeout(() => { if (!inp.isConnected || S.wait || S.done) return; S.wait = true; lose("Too slow!"); inp.disabled = true; after(); }, 18000);
  inp.oninput = () => {
    const v = inp.value; let bad = false;
    sp.forEach((s, i) => { s.className = i < v.length ? (v[i] === w[i] ? "c" : "x") : ""; if (i < v.length && v[i] !== w[i]) bad = true; });
    if (!bad && v === w && !S.wait && !S.done) {
      S.wait = true; clearTimeout(to); const secs = (Date.now() - t0) / 1000; award(10 + Math.max(0, Math.round(8 - secs)));
      inp.disabled = true; $("car").style.left = (S.round + 1) / S.total * 82 + "%"; msg(Math.round(w.length / 5 / (secs / 60)) + " WPM!", "ok"); after();
    }
  };
  inp.focus();
}

/* 4. Simon Memory */
function simon() {
  const cols = ["#ff4d6d", "#2ed573", "#3d8bff", "#ffd23f"], fr = [262, 330, 392, 494]; let seq = [], pos = 0, busy = true; S.mlabel = "Length"; S.moves = 0;
  render(`<section class="card"><span class="tag">🎵 SIMON MEMORY</span><h2 id="sm">Watch...</h2><div class="simon">${cols.map((c, i) => `<button type="button" class="sp" data-i="${i}" style="--c:${c}" aria-label="Pad ${i + 1}"></button>`).join("")}</div></section>`);
  const ps = [...area.querySelectorAll(".sp")];
  const flash = i => { ps[i].classList.add("lit"); beep(fr[i], .3, "triangle"); setTimeout(() => ps[i].classList.remove("lit"), 320); };
  const play = () => { busy = true; pos = 0; $("sm").textContent = "Watch..."; seq.forEach((v, k) => setTimeout(() => alive(ps[0]) && flash(v), 700 + k * 600)); setTimeout(() => { if (alive(ps[0])) { busy = false; $("sm").textContent = "Your turn!"; } }, 700 + seq.length * 600); };
  const grow = () => { seq.push(Math.random() * 4 | 0); S.moves = seq.length; ui(); play(); };
  ps.forEach(p => p.onclick = () => {
    if (busy || S.done) return; const i = +p.dataset.i; flash(i);
    if (i === seq[pos]) { pos++; if (pos === seq.length) { award(seq.length * 3); busy = true; if (seq.length >= 10) { confetti(); finish(); return; } msg("Great memory!", "ok"); setTimeout(() => alive(ps[0]) && grow(), 900); } }
    else { busy = true; lose("Wrong pad! Watch again."); if (!S.done) setTimeout(() => alive(ps[0]) && play(), 1000); }
  });
  setTimeout(() => alive(ps[0]) && grow(), 600);
}

/* 5. 2048 Tech Edition */
const LBL = ["", "Bit", "Byte", "KB", "MB", "GB", "TB"], FACTS = ["", "A bit is 0 or 1.", "8 bits make 1 byte.", "1 KB = 1,024 bytes.", "1 MB = 1,024 KB.", "1 GB = 1,024 MB.", "1 TB = 1,024 GB!"];
function g2048() {
  let b = Array.from({ length: 4 }, () => Array(4).fill(0)); S.mlabel = "Best tile (goal 6)"; S.moves = 1;
  render(`<section class="card"><span class="tag">💾 MERGE TO REACH TB</span><h2>Bit → Byte → KB → MB → GB → TB</h2><div class="b2048" id="bd"></div>${pad()}</section>`);
  const add = () => { const e = []; b.forEach((r, y) => r.forEach((v, x) => !v && e.push([y, x]))); if (e.length) { const [y, x] = R(e); b[y][x] = Math.random() < .85 ? 1 : 2; } };
  const slide = r => { const a = r.filter(Boolean), o = []; let g = 0; for (let i = 0; i < a.length; i++) { if (a[i] === a[i + 1]) { o.push(a[i] + 1); g += 1 << (a[i] + 1); i++; } else o.push(a[i]); } while (o.length < 4) o.push(0); return [o, g]; };
  const draw = () => { $("bd").innerHTML = b.flat().map(v => `<div class="t2" style="${v ? `background:hsl(${v * 48} 85% 62%)` : ""}">${LBL[v] || (v ? "2^" + v : "")}</div>`).join(""); };
  const can = () => b.some((r, y) => r.some((v, x) => !v || (x < 3 && v === r[x + 1]) || (y < 3 && v === b[y + 1][x])));
  const mv = k => {
    if (S.done) return; let gain = 0; const T = a => a[0].map((_, i) => a.map(r => r[i])), f = rows => rows.map(r => { const [o, g] = slide(r); gain += g; return o; });
    let m = b.map(r => [...r]);
    if (k === "left") m = f(m); else if (k === "right") m = f(m.map(r => r.reverse())).map(r => r.reverse());
    else if (k === "up") m = T(f(T(m))); else m = T(f(T(m).map(r => r.reverse())).map(r => r.reverse()));
    if (JSON.stringify(m) === JSON.stringify(b)) return; b = m; beep(400 + gain, .05); if (gain) award(gain); add(); draw();
    const mx = Math.max(...b.flat()); if (mx > S.moves) { S.moves = mx; floatText(LBL[mx] + "!"); msg("💡 " + FACTS[mx], "ok"); } ui();
    if (mx >= 6) { award(100); confetti(); finish(); return; } if (!can()) { msg("No moves left!", "bad"); finish(); }
  };
  add(); add(); draw(); ctrl(mv);
  let sx, sy; const bd = $("bd"); bd.onpointerdown = e => { sx = e.clientX; sy = e.clientY; };
  bd.onpointerup = e => { const dx = e.clientX - sx, dy = e.clientY - sy; if (Math.max(Math.abs(dx), Math.abs(dy)) < 25) return; mv(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up")); };
}

/* 6. Flappy Brain */
function flappy() {
  const W = 360, H = 480, pk = pairPick(), [tn, tl] = pk[0], bl = pk[1][1]; S.moves = 6; S.mlabel = "Gates left";
  render(`<section class="card"><span class="tag">🐦 FLY THROUGH: ${esc(tn.toUpperCase())}</span><h2>Tap or press Space to flap</h2>${cvs(W, H, "width:100%;touch-action:none;")}</section>`);
  const cv = $("cv"), g = cv.getContext("2d"); let y = 240, vy = 0, cols = [], f = 0, inv = 0;
  const flap = () => { vy = -6.4; beep(520, .04); }; cv.onpointerdown = flap; kh = e => { if (e.key === " " || e.key === "ArrowUp") flap(); };
  const loop = () => {
    if (!alive(cv)) return; f++; vy += .36; y += vy; if (inv) inv--;
    if (f % 110 === 1) cols.push({ x: W, top: Math.random() < .5, t: R(tl), w: R(bl), done: 0 });
    for (const c of cols) {
      c.x -= 2.4;
      if (!c.done && c.x + 28 <= 80) {
        c.done = 1;
        if (!inv) {
          const z = y > 40 && y < 170 ? 1 : y > 310 && y < 440 ? 2 : 0;
          if (z && z === (c.top ? 1 : 2)) { award(15); S.moves--; ui(); msg("Gate: " + c.t, "ok"); if (S.moves <= 0) { confetti(); finish(); return; } }
          else { lose(z ? c.w + " is not " + tn + "!" : "You hit the wall!"); if (S.done) return; y = 240; vy = 0; inv = 50; }
        }
      }
    }
    cols = cols.filter(c => c.x > -60);
    if (y > H - 10 || y < 10) { if (!inv) { lose("Crashed!"); if (S.done) return; } y = 240; vy = 0; inv = 50; }
    g.fillStyle = "#bfe8ff"; g.fillRect(0, 0, W, H); g.font = "bold 12px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    cols.forEach(c => {
      g.fillStyle = "#17123b"; [[0, 40], [170, 140], [440, 40]].forEach(([a, h]) => g.fillRect(c.x, a, 56, h));
      [[40, c.top ? c.t : c.w], [310, c.top ? c.w : c.t]].forEach(([a, t]) => { g.fillStyle = "#ffc93c"; g.fillRect(c.x, a, 56, 130); g.fillStyle = "#17123b"; g.fillText(t, c.x + 28, a + 65); });
    });
    g.font = "28px serif"; g.globalAlpha = inv && f % 6 < 3 ? .4 : 1; g.fillText("🐦", 80, y); g.globalAlpha = 1; requestAnimationFrame(loop);
  };
  loop();
}

/* 7. Tetris Blocks */
const TSH = [[[1, 1, 1, 1]], [[1, 1], [1, 1]], [[0, 1, 0], [1, 1, 1]], [[1, 0], [1, 0], [1, 1]], [[0, 1], [0, 1], [1, 1]], [[0, 1, 1], [1, 1, 0]], [[1, 1, 0], [0, 1, 1]]];
const TFACT = ["The first computer bug was a real moth (1947).", "Python is named after Monty Python.", "The first website went live in 1991.", "One byte stores one character like 'A'.", "Email's @ symbol was chosen in 1971.", "Wi-Fi doesn't officially stand for anything."];
function tetris() {
  const W = 10, H = 16, C = 24, PC = ["", "#ff4d6d", "#2ed573", "#3d8bff", "#ffd23f", "#a66bff", "#ff9f43", "#35c8ff"];
  render(`<section class="card"><span class="tag">🧱 CLEAR 6 LINES</span><h2>←→ move · ↑ rotate · ↓ drop</h2>${cvs(W * C, H * C)}${pad()}<p class="hint" id="fact">💡 Clear a line to learn a fact!</p></section>`);
  const cv = $("cv"), g = cv.getContext("2d"); let b = Array.from({ length: H }, () => Array(W).fill(0)), p = null, lines = 0; S.moves = 6; S.mlabel = "Lines left";
  const hit = (m, x, y) => m.some((r, i) => r.some((v, j) => v && (y + i >= H || x + j < 0 || x + j >= W || b[y + i][x + j])));
  const draw = () => {
    g.fillStyle = "#17123b"; g.fillRect(0, 0, W * C, H * C);
    const cell = (x, y, c) => { g.fillStyle = PC[c]; g.fillRect(x * C + 1, y * C + 1, C - 2, C - 2); };
    b.forEach((r, y) => r.forEach((v, x) => v && cell(x, y, v))); p && p.m.forEach((r, i) => r.forEach((v, j) => v && cell(p.x + j, p.y + i, p.c)));
  };
  const nw = () => { const k = Math.random() * 7 | 0; p = { m: TSH[k], c: k + 1, x: 3, y: 0 }; if (hit(p.m, p.x, p.y)) { msg("Stack is full!", "bad"); finish(); } };
  const lock = () => {
    p.m.forEach((r, i) => r.forEach((v, j) => v && (b[p.y + i][p.x + j] = p.c)));
    const keep = b.filter(r => r.some(v => !v)), n = H - keep.length;
    if (n) { b = [...Array.from({ length: n }, () => Array(W).fill(0)), ...keep]; lines += n; award(n * n * 10); S.moves = Math.max(0, 6 - lines); ui(); $("fact").textContent = "💡 " + TFACT[(lines - 1) % TFACT.length]; if (lines >= 6) { award(50); confetti(); finish(); return; } }
    nw();
  };
  const step = () => { if (hit(p.m, p.x, p.y + 1)) lock(); else p.y++; };
  ctrl(k => {
    if (!p || S.done) return;
    if (k === "left" && !hit(p.m, p.x - 1, p.y)) p.x--; else if (k === "right" && !hit(p.m, p.x + 1, p.y)) p.x++; else if (k === "down") step();
    else if (k === "up") { const m = p.m[0].map((_, i) => p.m.map(r => r[i]).reverse()); for (const dx of [0, -1, 1, -2, 2]) if (!hit(m, p.x + dx, p.y)) { p.m = m; p.x += dx; break; } }
    draw();
  });
  nw(); draw();
  const iv = setInterval(() => { if (!alive(cv)) { clearInterval(iv); return; } step(); draw(); }, 650);
}

/* 8. Minesweeper Debug */
function mines() {
  let bug = [], num = [], rev = Array(64).fill(0), fl = Array(64).fill(0), mode = 0, first = 1, left = 54; S.mlabel = "Safe left"; S.moves = left;
  render(`<section class="card"><span class="tag">🐞 FIND THE 10 BUGS</span><h2>Reveal safe cells. Numbers count nearby bugs.</h2><div class="mine">${Array.from({ length: 64 }, (_, i) => `<button type="button" class="mc" data-i="${i}"></button>`).join("")}</div><button type="button" class="btn alt" id="fm">⛏️ Dig mode</button></section>`);
  const cs = [...area.querySelectorAll(".mc")];
  const nb = i => { const x = i % 8, y = i / 8 | 0, o = []; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const a = x + dx, c = y + dy; if ((dx || dy) && a >= 0 && c >= 0 && a < 8 && c < 8) o.push(c * 8 + a); } return o; };
  const paint = () => cs.forEach((c, i) => { c.className = "mc" + (rev[i] ? " rv" : "") + (fl[i] && !rev[i] ? " fg" : ""); c.textContent = rev[i] ? (bug[i] ? "🐞" : num[i] || "") : fl[i] ? "🚩" : ""; c.dataset.n = rev[i] && !bug[i] ? num[i] : ""; });
  const open = i => { if (rev[i] || fl[i]) return; rev[i] = 1; if (bug[i]) { lose("Bug found! 🐞"); return; } left--; S.score += 2; if (!num[i]) nb(i).forEach(open); };
  $("fm").onclick = () => { mode ^= 1; $("fm").textContent = mode ? "🚩 Flag mode" : "⛏️ Dig mode"; };
  cs.forEach((c, i) => c.onclick = () => {
    if (S.done) return;
    if (mode) { if (!rev[i]) fl[i] ^= 1; paint(); return; }
    if (first) { first = 0; const ban = new Set([i, ...nb(i)]); bug = Array(64).fill(0); let n = 0; while (n < 10) { const k = Math.random() * 64 | 0; if (!ban.has(k) && !bug[k]) { bug[k] = 1; n++; } } num = bug.map((_, k) => nb(k).filter(q => bug[q]).length); }
    open(i); S.moves = left; ui(); paint();
    if (left <= 0 && !S.done) { award(60); confetti(); finish(); }
  });
}

/* 9. Maze Runner */
function maze() {
  const W = 11, H = 11, C = 30; const m = Array.from({ length: H }, () => Array(W).fill(1));
  (function carve(x, y) { m[y][x] = 0; sh([[1, 0], [-1, 0], [0, 1], [0, -1]]).forEach(([dx, dy]) => { const nx = x + dx * 2, ny = y + dy * 2; if (nx > 0 && ny > 0 && nx < W - 1 && ny < H - 1 && m[ny][nx]) { m[y + dy][x + dx] = 0; carve(nx, ny); } }); })(1, 1);
  const open = []; m.forEach((r, y) => r.forEach((v, x) => !v && x + y > 8 && !(x === 9 && y === 9) && open.push([x, y])));
  let keys = sh(open).slice(0, 2), have = 0, me = { x: 1, y: 1 }, pz = false; S.moves = 2; S.mlabel = "Keys left";
  render(`<section class="card"><span class="tag">🗝️ FIND 2 KEYS · REACH THE DOOR</span><h2>Each key is guarded by a question</h2>${cvs(W * C, H * C)}${pad()}<div id="pz"></div></section>`);
  const cv = $("cv"), g = cv.getContext("2d");
  const draw = () => {
    g.font = "22px serif"; g.textAlign = "center"; g.textBaseline = "middle";
    m.forEach((r, y) => r.forEach((v, x) => { g.fillStyle = v ? "#17123b" : "#fff7e0"; g.fillRect(x * C, y * C, C, C); }));
    keys.forEach(([x, y]) => g.fillText("🔑", x * C + C / 2, y * C + C / 2)); g.fillText(have >= 2 ? "🚪" : "🔒", 9 * C + C / 2, 9 * C + C / 2); g.fillText("🧑‍💻", me.x * C + C / 2, me.y * C + C / 2);
  };
  ctrl(k => {
    if (pz || S.done) return; const d = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] }[k], nx = me.x + d[0], ny = me.y + d[1];
    if (m[ny] && m[ny][nx] === 0) { me = { x: nx, y: ny }; beep(300, .03); }
    const ki = keys.findIndex(([x, y]) => x === me.x && y === me.y);
    if (ki >= 0) {
      pz = true; const q = R(S.qs);
      $("pz").innerHTML = `<h2>🔑 ${esc(q[0])}</h2><div class="opts">${sh([q[1], ...q[2]]).map(o => `<button type="button" class="opt" data-o="${esc(o)}">${esc(o)}</button>`).join("")}</div>`;
      $("pz").querySelectorAll(".opt").forEach(bt => bt.onclick = () => {
        if (bt.dataset.o === q[1]) { award(15); keys.splice(ki, 1); have++; S.moves = 2 - have; ui(); msg("Key collected!", "ok"); } else { lose("Wrong! The key stays here."); }
        $("pz").innerHTML = ""; pz = false; draw();
      });
    }
    if (me.x === 9 && me.y === 9) { if (have >= 2) { award(40); confetti(); finish(); return; } msg("🔒 Locked! Collect both keys first.", "bad"); }
    draw();
  });
  draw();
}

/* 10. Tower Defense (Firewall) */
function tower() {
  const W = 480, H = 240, C = 40, T = { fw: ["🧱", 20, 100, 1, 25], av: ["🛡️", 35, 120, 4, 60], rt: ["📡", 25, 90, 0, 0] };
  let cr = 70, sel = "fw", ts = [], es = [], f = 0, wave = 0, q = 0, gap = 0; S.moves = 5; S.mlabel = "Waves left";
  render(`<section class="card"><span class="tag">🛡️ STOP THE VIRUSES</span><h2>Pick a tool, then tap a square to build</h2>${cvs(W, H, "width:100%;")}<div class="tbar">${Object.entries(T).map(([k, v]) => `<button type="button" class="btn alt tb${k === "fw" ? " on" : ""}" data-t="${k}">${v[0]} ${v[1]}</button>`).join("")}<b id="cr">🪙 ${cr}</b></div><p class="hint">🧱 Firewall: fast · 🛡️ Antivirus: strong · 📡 Router: slows viruses</p></section>`);
  const cv = $("cv"), g = cv.getContext("2d");
  area.querySelectorAll(".tb").forEach(b => b.onclick = () => { sel = b.dataset.t; area.querySelectorAll(".tb").forEach(x => x.classList.toggle("on", x === b)); });
  cv.onpointerdown = e => {
    const r = cv.getBoundingClientRect(), cx = (e.clientX - r.left) * W / r.width / C | 0, cy = (e.clientY - r.top) * H / r.height / C | 0;
    if (cy === 2 || ts.some(t => t.cx === cx && t.cy === cy)) return; if (cr < T[sel][1]) { msg("Not enough credits", "bad"); return; }
    cr -= T[sel][1]; ts.push({ k: sel, cx, cy, x: cx * C + 20, y: cy * C + 20, cd: 0 }); $("cr").textContent = "🪙 " + cr; beep(450, .06);
  };
  const loop = () => {
    if (!alive(cv)) return; f++;
    if (!q && !es.length) { if (wave >= 5) { award(80); confetti(); finish(); return; } wave++; q = 3 + wave * 2; gap = 100; S.moves = 5 - wave; ui(); msg("Wave " + wave + " incoming!", "ok"); }
    if (gap > 0) gap--; else if (q && f % 55 === 0) { es.push({ x: -10, hp: 2 + wave * 2, sp: .6 + wave * .08 }); q--; }
    es.forEach(e => { let s = e.sp; ts.forEach(t => { if (t.k === "rt" && Math.hypot(t.x - e.x, 100 - t.y) < T.rt[2]) s *= .5; }); e.x += s; });
    ts.forEach(t => {
      if (t.k === "rt") return; t.cd--; t.sf = (t.sf || 0) - 1; if (t.cd > 0) return;
      const e = es.filter(e => Math.hypot(t.x - e.x, t.y - 100) < T[t.k][2]).sort((a, b) => b.x - a.x)[0];
      if (e) { e.hp -= T[t.k][3]; t.cd = T[t.k][4]; t.sf = 5; t.tx = e.x; }
    });
    es = es.filter(e => { if (e.hp <= 0) { cr += 8; award(5); $("cr").textContent = "🪙 " + cr; return false; } if (e.x > W) { lose("A virus got through!"); return false; } return true; });
    if (S.done) return;
    g.fillStyle = "#e8f7ee"; g.fillRect(0, 0, W, H); g.fillStyle = "#c9d3e8"; g.fillRect(0, 2 * C, W, C); g.font = "24px serif"; g.textAlign = "center"; g.textBaseline = "middle";
    ts.forEach(t => { g.fillText(T[t.k][0], t.x, t.y); if (t.sf > 0) { g.strokeStyle = "#ff4d5e"; g.lineWidth = 3; g.beginPath(); g.moveTo(t.x, t.y); g.lineTo(t.tx, 100); g.stroke(); } });
    es.forEach(e => { g.fillText("🦠", e.x, 100); g.fillStyle = "#ff4d5e"; g.fillRect(e.x - 12, 80, 24 * Math.max(0, e.hp) / (2 + wave * 2), 4); });
    requestAnimationFrame(loop);
  };
  loop();
}

/* 11. Pac-Man Data Hunt */
const PM = ["#############", "#...........#", "#.##.###.##.#", "#...........#", "#.##.#.#.##.#", "#....#.#....#", "#.##.#.#.##.#", "#...........#", "#.##.###.##.#", "#...........#", "#############"];
function pacman() {
  const C = 28, W = 13, H = 11; const dots = PM.map(r => [...r].map(c => c === "."));
  let left = dots.flat().filter(Boolean).length, me, d = { x: 0, y: 0 }, nd = d, gs; S.moves = left; S.mlabel = "Packets left";
  render(`<section class="card"><span class="tag">👾 EAT ALL DATA PACKETS</span><h2>Dodge the bug ghosts!</h2>${cvs(W * C, H * C)}${pad()}</section>`);
  const cv = $("cv"), g = cv.getContext("2d"), wall = (x, y) => PM[y] === undefined || PM[y][x] === "#" || PM[y][x] === undefined;
  const reset = () => { me = { x: 6, y: 9 }; d = nd = { x: 0, y: 0 }; gs = [{ x: 1, y: 1 }, { x: 11, y: 1 }]; };
  const draw = () => {
    g.fillStyle = "#17123b"; g.fillRect(0, 0, W * C, H * C); g.font = "20px serif"; g.textAlign = "center"; g.textBaseline = "middle";
    PM.forEach((r, y) => [...r].forEach((c, x) => { if (c === "#") { g.fillStyle = "#3d4aa8"; g.fillRect(x * C + 2, y * C + 2, C - 4, C - 4); } else if (dots[y][x]) { g.fillStyle = "#ffc93c"; g.fillRect(x * C + 11, y * C + 11, 6, 6); } }));
    g.fillText("😮", me.x * C + C / 2, me.y * C + C / 2); gs.forEach(o => g.fillText("🐞", o.x * C + C / 2, o.y * C + C / 2));
  };
  const hitG = () => gs.some(o => o.x === me.x && o.y === me.y);
  reset(); draw(); ctrl(k => { nd = { up: { x: 0, y: -1 }, down: { x: 0, y: 1 }, left: { x: -1, y: 0 }, right: { x: 1, y: 0 } }[k]; });
  const tick = () => {
    if (!wall(me.x + nd.x, me.y + nd.y)) d = nd;
    if (!wall(me.x + d.x, me.y + d.y)) { me.x += d.x; me.y += d.y; }
    if (dots[me.y][me.x]) { dots[me.y][me.x] = false; left--; S.score++; S.moves = left; ui(); if (left <= 0) { award(60); confetti(); finish(); return false; } }
    if (hitG()) { lose("A bug caught you!"); if (!S.done) reset(); return !S.done; } return true;
  };
  let n = 0;
  const iv = setInterval(() => {
    if (!alive(cv)) { clearInterval(iv); return; } n++;
    if (!tick()) return;
    if (n % 2 === 0) {
      gs.forEach(o => {
        const opts = [[1, 0], [-1, 0], [0, 1], [0, -1]].filter(([a, b]) => !wall(o.x + a, o.y + b));
        const dir = Math.random() < .55 ? opts.sort((p, q) => Math.hypot(o.x + p[0] - me.x, o.y + p[1] - me.y) - Math.hypot(o.x + q[0] - me.x, o.y + q[1] - me.y))[0] : R(opts); o.x += dir[0]; o.y += dir[1];
      });
      if (hitG()) { lose("A bug caught you!"); if (!S.done) reset(); }
    }
    draw();
  }, 190);
}

/* 12. Logic Gates Lab */
const GF = { AND: (a, b) => a & b, OR: (a, b) => a | b, XOR: (a, b) => a ^ b, NAND: (a, b) => 1 - (a & b), NOR: (a, b) => 1 - (a | b), NOT: a => 1 - a };
const LG = [{ t: "A AND B", n: 2, sl: 1, f: (a, b) => a & b, tray: ["AND", "OR", "NOT"] }, { t: "A OR B", n: 2, sl: 1, f: (a, b) => a | b, tray: ["AND", "OR", "XOR"] }, { t: "NOT A", n: 1, sl: 1, f: a => 1 - a, tray: ["AND", "NOT", "OR"] }, { t: "A XOR B", n: 2, sl: 1, f: (a, b) => a ^ b, tray: ["XOR", "NAND", "NOR"] }, { t: "(A AND B) OR C", n: 3, sl: 2, f: (a, b, c) => (a & b) | c, tray: ["AND", "OR", "XOR", "NOR"] }];
function gates() {
  const L = LG[S.round % LG.length], names = "ABC".slice(0, L.n), sl = Array(L.sl).fill(null), inp = Array(L.n).fill(0);
  render(`<section class="card"><span class="tag">⚡ LEVEL ${S.round + 1} · TARGET: ${L.t}</span><h2>Drag a gate into each slot (or tap, then tap the slot)</h2><div class="lab"><div class="tg">${names.split("").map((n, i) => `<button type="button" class="tog" data-i="${i}">${n}: 0</button>`).join("")}</div>${sl.map((_, i) => `<div class="slot" data-s="${i}">?</div>`).join("")}<div class="bulb" id="bl">💡</div></div><div class="chips">${L.tray.map(v => `<span class="chip" data-v="${v}">${v}</span>`).join("")}</div><button type="button" class="btn" id="chk">Check circuit</button></section>`);
  const out = ins => { if (sl.some(x => !x)) return null; if (L.sl === 1) return GF[sl[0]](ins[0], ins[1] || 0); return GF[sl[1]](GF[sl[0]](ins[0], ins[1]), ins[2]); };
  const show = () => { const o = out(inp); $("bl").className = "bulb" + (o ? " on" : ""); };
  area.querySelectorAll(".tog").forEach(b => b.onclick = () => { const i = +b.dataset.i; inp[i] ^= 1; b.textContent = names[i] + ": " + inp[i]; b.classList.toggle("on", !!inp[i]); show(); });
  dd(area, (s, v) => { sl[+s.dataset.s] = v; s.textContent = v; s.classList.add("full"); beep(500, .05); show(); });
  $("chk").onclick = () => {
    if (lock()) return; if (sl.some(x => !x)) { S.wait = false; msg("Fill every slot first!"); return; }
    let ok = true; for (let m = 0; m < 1 << L.n; m++) { const ins = Array.from({ length: L.n }, (_, i) => m >> i & 1); if (out(ins) !== L.f(...ins)) ok = false; }
    if (ok) { award(20); msg("The bulb works for every input! ✅", "ok"); } else lose("Some inputs give the wrong output.");
    $("chk").disabled = true; after();
  };
}

/* 13. Robot Coder */
const RBL = [{ s: [0, 4, 1], g: [4, 4], w: [] }, { s: [0, 4, 1], g: [4, 0], w: [[2, 4], [2, 3], [2, 2]] }, { s: [0, 0, 2], g: [4, 4], w: [[1, 1], [1, 2], [3, 2], [3, 3]] }];
function robot() {
  const L = RBL[S.round % RBL.length]; let prog = [], run = false; const AR = ["▲", "►", "▼", "◄"], NM = { F: "⬆️ Forward", L: "↰ Left", R: "↱ Right", X: "🔁 ×3" };
  render(`<section class="card"><span class="tag">🤖 LEVEL ${S.round + 1} · REACH THE ⭐</span><h2>Build a program (max 10) and press Run</h2><div class="rg" id="rg"></div><div class="chips">${Object.entries(NM).map(([k, v]) => `<button type="button" class="btn alt cmd" data-c="${k}">${v}</button>`).join("")}</div><div class="prog" id="pg">Program: (empty)</div><div class="actions"><button type="button" class="btn alt" id="un">Undo</button><button type="button" class="btn" id="rn">▶ Run</button></div></section>`);
  let rx = L.s[0], ry = L.s[1], rd = L.s[2];
  const draw = () => { $("rg").innerHTML = Array.from({ length: 25 }, (_, i) => { const x = i % 5, y = i / 5 | 0, w = L.w.some(a => a[0] === x && a[1] === y); return `<div class="rc">${rx === x && ry === y ? `🤖<small>${AR[rd]}</small>` : w ? "🧱" : L.g[0] === x && L.g[1] === y ? "⭐" : ""}</div>`; }).join(""); $("pg").textContent = "Program: " + (prog.length ? prog.map(c => NM[c].split(" ")[0]).join(" ") : "(empty)"); };
  draw();
  area.querySelectorAll(".cmd").forEach(b => b.onclick = () => { if (run || prog.length >= 10) return; prog.push(b.dataset.c); beep(400, .04); draw(); });
  $("un").onclick = () => { if (!run) { prog.pop(); draw(); } };
  $("rn").onclick = () => {
    if (run || S.wait || S.done) return; run = true; const steps = []; for (let i = 0; i < prog.length; i++) { if (prog[i] === "X" && prog[i + 1]) { steps.push(prog[i + 1], prog[i + 1], prog[i + 1]); i++; } else if (prog[i] !== "X") steps.push(prog[i]); }
    let i = 0; const iv = setInterval(() => {
      if (!$("rg").isConnected || S.done) { clearInterval(iv); return; }
      const c = steps[i++];
      if (c) { if (c === "L") rd = (rd + 3) % 4; else if (c === "R") rd = (rd + 1) % 4; else { const nx = rx + [0, 1, 0, -1][rd], ny = ry + [-1, 0, 1, 0][rd]; if (nx < 0 || ny < 0 || nx > 4 || ny > 4 || L.w.some(a => a[0] === nx && a[1] === ny)) { clearInterval(iv); S.wait = true; lose("Bump! The robot hit a wall."); if (!S.done) { rx = L.s[0]; ry = L.s[1]; rd = L.s[2]; run = false; S.wait = false; draw(); } return; } rx = nx; ry = ny; } beep(350, .04); draw(); }
      if (rx === L.g[0] && ry === L.g[1]) { clearInterval(iv); S.wait = true; award(25); msg("The robot reached the star! ⭐", "ok"); after(); return; }
      if (i >= steps.length) { clearInterval(iv); S.wait = true; lose("The robot stopped before the star."); if (!S.done) { rx = L.s[0]; ry = L.s[1]; rd = L.s[2]; run = false; S.wait = false; draw(); } }
    }, 420);
  };
}

/* 14. Platform Adventure */
const TOP = [["🏝️ Network Island", ["Router", "IP", "DNS", "Wi-Fi", "LAN"], ["Excel", "SQL", "Python"]], ["🕳️ Database Cave", ["SQL", "Table", "Query", "Key", "Row"], ["Router", "Wi-Fi", "Mouse"]], ["🏰 Code Castle", ["Loop", "Variable", "Function", "Bug", "If"], ["Printer", "RAM", "Cable"]]];
function platform() {
  S.total = 3; const W = 480, H = 300, GY = 250, [nm, good, bad] = TOP[S.round % 3], LEN = 2400; let y = GY, vy = 0, f = 0, items = [], prog = 0, inv = 0;
  render(`<section class="card"><span class="tag">${nm}</span><h2>Jump! Collect green words, dodge bugs and wrong words</h2>${cvs(W, H, "width:100%;touch-action:none;")}</section>`);
  const cv = $("cv"), g = cv.getContext("2d"), jump = () => { if (y >= GY) { vy = -11.5; beep(600, .05); } };
  cv.onpointerdown = jump; kh = e => { if (e.key === " " || e.key === "ArrowUp") jump(); };
  const loop = () => {
    if (!alive(cv)) return; f++; prog += 4; vy += .65; y = Math.min(GY, y + vy); if (y >= GY) vy = 0; if (inv) inv--;
    if (f % 55 === 0) { const r = Math.random(); items.push(r < .35 ? { x: W + 20, y: GY - 14, w: 28, h: 28, k: 0, t: "🐛" } : { x: W + 20, y: 150 + Math.random() * 70, w: 62, h: 24, k: r < .75 ? 1 : 2, t: r < .75 ? R(good) : R(bad) }); }
    items.forEach(i => { i.x -= 4; if (!i.hit && Math.abs(i.x + i.w / 2 - 70) < i.w / 2 + 13 && Math.abs(i.y - (y - 17)) < i.h / 2 + 17) { i.hit = 1; if (i.k === 1) { award(10); msg("Nice! " + i.t, "ok"); } else if (!inv) { inv = 40; lose(i.k ? i.t + " does not belong here!" : "Ouch, a bug!"); } } });
    items = items.filter(i => i.x > -80 && !(i.hit && i.k === 1)); if (S.done) return;
    g.fillStyle = "#bfe8ff"; g.fillRect(0, 0, W, H); g.fillStyle = "#2ed573"; g.fillRect(0, GY, W, H - GY); g.fillStyle = "#17123b"; g.fillRect(0, GY, W, 4);
    g.fillStyle = "#fff"; g.fillRect(20, 14, 440, 10); g.fillStyle = "#ff4d5e"; g.fillRect(20, 14, 440 * Math.min(1, prog / LEN), 10);
    g.textAlign = "center"; g.textBaseline = "middle"; g.font = "bold 12px sans-serif";
    items.forEach(i => { if (!i.k) { g.font = "26px serif"; g.fillText("🐛", i.x + 14, i.y); } else { g.fillStyle = i.k === 1 ? "#17c97a" : "#ffd23f"; g.fillRect(i.x, i.y - 12, i.w, 24); g.fillStyle = "#17123b"; g.font = "bold 12px sans-serif"; g.fillText(i.t, i.x + i.w / 2, i.y); } });
    g.globalAlpha = inv && f % 6 < 3 ? .4 : 1; g.font = "32px serif"; g.fillText("🏃", 70, y - 17); g.globalAlpha = 1;
    if (prog >= LEN) { S.wait = true; award(20); if (S.round >= 2) confetti(); msg(nm + " cleared!", "ok"); after(); return; }
    requestAnimationFrame(loop);
  };
  loop();
}

/* 15. Escape Room 2.0 */
const ROOMS = [
  { n: "🖥️ Server Room", s: "The lights flicker. Drag each device to its job to power the door.", pairs: [["Router", "Connects networks"], ["CPU", "Runs instructions"], ["RAM", "Short-term memory"]] },
  { n: "🗄️ Data Vault", s: "The vault needs a web request in the right order.", pairs: [["Browser sends request", "Step 1"], ["Server processes it", "Step 2"], ["Page shown to user", "Step 3"]] },
  { n: "🔐 Control Room", s: "One last lock stands between you and freedom.", code: ["How many bits are in one byte?", "8", "Think of 2 × 2 × 2."] }
];
function escape2() {
  S.total = 3; const r = ROOMS[S.round % 3]; let done = 0;
  if (r.code) {
    render(`<section class="card"><span class="tag">${r.n} · ROOM 3 / 3</span><p>${r.s}</p><h2>🔐 ${r.code[0]}</h2><input id="ans" class="input" placeholder="Enter the code" autocomplete="off"><button type="button" class="btn" id="chk">Unlock</button><p class="hint">💡 ${r.code[2]}</p></section>`);
    const go = () => { if (lock()) return; if ($("ans").value.trim() === r.code[1]) { award(30); confetti(); msg("You escaped! 🎉", "ok"); } else lose("Wrong code. The answer was " + r.code[1] + "."); $("chk").disabled = true; after(); };
    $("chk").onclick = go; $("ans").onkeydown = e => { if (e.key === "Enter") go(); }; return;
  }
  render(`<section class="card"><span class="tag">${r.n} · ROOM ${S.round + 1} / 3</span><p>${r.s}</p><div class="slots">${r.pairs.map(p => `<div class="slot" data-a="${esc(p[0])}"><small>${esc(p[1])}</small><b></b></div>`).join("")}</div><div class="chips">${sh(r.pairs).map(p => `<span class="chip" data-v="${esc(p[0])}">${esc(p[0])}</span>`).join("")}</div></section>`);
  dd(area, (s, v) => {
    if (s.classList.contains("full") || S.done) return;
    if (s.dataset.a === v) { s.classList.add("full"); s.querySelector("b").textContent = v; area.querySelectorAll(".chip").forEach(c => c.dataset.v === v && c.remove()); award(10); beep(600, .06); if (++done === r.pairs.length) { award(15); msg("The door unlocks! 🚪", "ok"); S.wait = true; after(); } }
    else lose("That doesn't fit there!");
  });
}

/* ---------- dispatcher ---------- */
function launch() {
  S.wait = false; kh = null;
  const map = { snake_learner: snake, whack_concept: whack, typing_racer: typing, simon_memory: simon, tech_2048: g2048, flappy_brain: flappy, tetris_blocks: tetris, minesweeper_debug: mines, maze_runner: maze, tower_firewall: tower, pacman_data: pacman, logic_gates: gates, robot_coder: robot, platform_adventure: platform, escape_room_2: escape2, candy_match: candy, bubble_shooter: bubble, mind_match: memory, cosmic_quiz: quiz, knowledge_league: quiz, sprint_game: quiz, daily_brain_boost: daily, word_wizard: word, match_concept: concept, concept_detective: detective, code_builder: code, tech_escape_room: escape, listen_recall: listen, sequence_master: sequence };
  (map[key] || quiz)();
  $("stageTitle").textContent = (S.moves != null || !S.total || SPRINT) ? "Go go go!" : "Round " + (S.round + 1);
  ui();
}

/* ---------- finish + start ---------- */
async function finish() {
  if (S.done || !S.on) return;
  S.done = true; clearInterval(clock); if ("speechSynthesis" in window) speechSynthesis.cancel();
  S.secs = Math.floor((Date.now() - S.t0) / 1000);
  const newBest = S.score > best; if (newBest) { best = S.score; localStorage.setItem(bestKey, best); }
  const stars = S.score >= 150 ? 3 : S.score >= 60 ? 2 : S.score > 0 ? 1 : 0;
  $("next").hidden = true; $("finish").hidden = true; ui(); if (stars) { confetti(); sfx.win(); }
  render(`<section class="card"><div class="stars">${"⭐".repeat(stars)}${"☆".repeat(3 - stars)}</div><h2>${newBest && S.score ? "New best score! 🏆" : stars ? "Great work!" : "Good try, play again!"}</h2><div class="stats3"><div><b>${S.score}</b>Score</div><div><b>${S.correct}</b>Correct</div><div><b>${S.secs}s</b>Time</div></div><p id="saveStatus">Saving your result...</p><button type="button" class="btn" id="again">↻ Play again</button></section>`);
  $("again").onclick = start; $("result").textContent = "Score: " + S.score;
  const st = $("saveStatus");
  if (!url) { st.textContent = "Game completed."; return; }
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ game_key: key, score: S.score, level: 1 + Math.floor(S.score / 100), correct: S.correct, time_seconds: S.secs }) });
    const d = await res.json().catch(() => ({}));
    st.textContent = res.ok ? (d.message || "Result saved!") : (d.error || d.message || "Could not save your result.");
  } catch (e) { st.textContent = "Could not reach the server to save your result."; }
}
function begin() {
  S.on = true; S.t0 = Date.now(); $("restart").hidden = false; $("finish").hidden = SPRINT ? false : true;
  clock = setInterval(() => { if (!S.on || S.done) return; S.secs = Math.floor((Date.now() - S.t0) / 1000); ui(); if (SPRINT && S.secs >= 60) finish(); }, 1000);
  $("instruction").textContent = HOW[key] || "Do your best!"; launch();
}
function start() {
  clearInterval(clock);
  S = { score: 0, streak: 0, lives: MAXL, round: 0, correct: 0, secs: 0, t0: 0, wait: true, done: false, on: false, moves: null, total: TOTAL, qs: sh(Q) };
  $("startGame").hidden = true; $("next").hidden = true; $("finish").hidden = true; msg(""); $("result").textContent = ""; ui();
  let n = 3; render(`<div class="count">${n}</div>`); beep(440, .1);
  const t = setInterval(() => { n--; if (n > 0) { render(`<div class="count">${n}</div>`); beep(440, .1); } else { clearInterval(t); render(`<div class="count">GO!</div>`); beep(880, .25); setTimeout(begin, 450); } }, 700);
}

$("startGame").onclick = start;
$("restart").onclick = start;
$("next").onclick = advance;
$("finish").onclick = finish;
$("next").hidden = $("finish").hidden = $("restart").hidden = true;
const META = { snake_learner: ["🐍", "Snake Learner", "Grow by eating the right concepts."], whack_concept: ["🔨", "Whack-a-Concept", "Smash only the right category."], typing_racer: ["🏎️", "Typing Racer", "Type tech words to race."], simon_memory: ["🎵", "Simon Memory", "Repeat the colour and sound pattern."], tech_2048: ["💾", "2048 Tech Edition", "Merge Bit to TB."], flappy_brain: ["🐦", "Flappy Bird Brain", "Fly through the correct term."], tetris_blocks: ["🧱", "Tetris Blocks", "Clear lines, learn facts."], minesweeper_debug: ["🐞", "Minesweeper Debug", "Find the bugs with logic."], maze_runner: ["🗝️", "Maze Runner", "Collect keys, open the door."], tower_firewall: ["🛡️", "Tower Defense: Firewall", "Stop the viruses."], pacman_data: ["👾", "Pac-Man Data Hunt", "Eat data, dodge bugs."], logic_gates: ["⚡", "Logic Gates Lab", "Light the bulb with gates."], robot_coder: ["🤖", "Robot Coder", "Program the robot."], platform_adventure: ["🏃", "Platform Adventure", "Run through 3 topic worlds."], escape_room_2: ["🔐", "Escape Room 2.0", "Solve 3 story rooms."] };
const mt = META[key], gt = $("gameTitle");
if (mt && gt && /^(Learning Game|EduVision Game)?$/.test(gt.textContent.trim())) { $("gameIcon").textContent = mt[0]; $("welcomeIcon").textContent = mt[0]; gt.textContent = mt[1]; $("gameDescription").textContent = mt[2]; document.title = mt[1] + " | EduVision"; }
$("welcomeText").textContent = HOW[key] || "Play, learn and beat your best score.";
$("bestScore").textContent = best;
})();