/* =========================================================
   EDUVISION GAME ENGINE  ->  static/js/game.js
   14 games, mobile friendly, Time LEFT + Moves bar in every game
   Every level has a TIME LIMIT (countdown). Time up = level failed.

   LATEST UPDATE
   - Arrow Escape: the arrow head ALWAYS points the same way the arrow
     slides out (head direction = last body segment). Blocked arrows
     cost a heart. Every board can be cleared.
   - Level complete popup AND level failed popup both have a red X
     button (top right) that closes the game and goes back to the
     dashboard.
   - Level failed (wrong move, game over, time up) -> big red X popup
     in the CENTER of the screen: "Try Again" or "Back to Dashboard".
   - Tic-Tac-Toe: a draw no longer fails the level, the board resets.
     The computer can make mistakes at low levels so you can win.
   - No scrolling: board fits the screen, status sticks to the bottom.
   ========================================================= */

function onReady(fn) {
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
        fn();
    }
}

/* =========================================================
   PART 1: INFINITE LEVEL SYSTEM
   ========================================================= */

const EDUVISION_GAMES = {
    arrow_maze: "Arrow Finder: Arrow Maze",
    hologram_memory: "Hologram Memory Challenge",
    candy_match: "Candy Match Puzzle",
    memory_match: "Memory Card Matching",
    bubble_shooter: "Bubble Shooter",
    endless_runner: "Endless Runner",
    neon_tic_tac_toe: "Neon Tic-Tac-Toe",
    puzzle_2048: "2048 Number Puzzle",
    arrow_direction: "Arrow Direction Puzzle",
    sliding_puzzle: "Sliding Puzzle",
    quiz_battle: "Quiz Battle Arena",
    tetris_blocks: "Tetris Blocks",
    flappy_brain: "Flappy Brain",
    snake_game: "Snake Game"
};

const EduVisionLevels = (() => {
    const state = {
        gameId: "",
        level: 1,
        completedLevels: 0,
        bestScore: 0,
        completedThisLevel: false
    };

    function readPayload() {
        const element = document.getElementById("eduVisionGameData");

        try {
            return element
                ? JSON.parse(element.textContent || "{}")
                : (window.eduVisionGame?.payload || {});
        } catch (error) {
            console.error("Unable to read game data:", error);
            return {};
        }
    }

    function isKnown(id) {
        return Object.prototype.hasOwnProperty.call(EDUVISION_GAMES, id);
    }

    function getGameId() {
        const payload = readPayload();

        const fromPayload = String(payload.game_id || payload.id || payload.key || "");
        if (isKnown(fromPayload)) return fromPayload;

        const fromBody = String((document.body && document.body.dataset.gameKey) || "");
        if (isKnown(fromBody)) return fromBody;

        const parts = window.location.pathname.split("/").filter(Boolean);

        for (let i = parts.length - 1; i >= 0; i--) {
            if (isKnown(parts[i])) return parts[i];
        }

        return "";
    }

    function storageKey() {
        return `eduvision_progress_${state.gameId}`;
    }

    function load() {
        state.gameId = getGameId();

        if (!state.gameId) {
            console.error("Game ID missing. Check build_payload() in game_data.py.");
            return;
        }

        try {
            const saved = JSON.parse(localStorage.getItem(storageKey()) || "{}");

            state.level = Math.max(1, Math.floor(Number(saved.level) || 1));
            state.completedLevels = Math.max(0, Math.floor(Number(saved.completedLevels) || 0));
            state.bestScore = Math.max(0, Number(saved.bestScore) || 0);
        } catch (error) {
            console.warn("Could not load progress:", error);
        }

        state.completedThisLevel = false;
        updatePayload();
        render();
    }

    function updatePayload() {
        const payload = readPayload();

        window.eduVisionGame = window.eduVisionGame || {};
        window.eduVisionGame.payload = {
            ...payload,
            level: state.level,
            max_level: Infinity
        };
    }

    function save() {
        if (!state.gameId) return;

        try {
            localStorage.setItem(
                storageKey(),
                JSON.stringify({
                    level: state.level,
                    completedLevels: state.completedLevels,
                    bestScore: state.bestScore
                })
            );
        } catch (error) {
            console.warn("Could not save progress:", error);
        }
    }

    // Use the level stored in the database when it is ahead of the browser.
    // Returns true when the level actually changed.
    function setLevel(serverLevel, serverCompleted) {
        const lvl = Math.max(1, Math.floor(Number(serverLevel) || 1));
        let changed = false;
        let levelChanged = false;

        if (lvl > state.level) {
            state.level = lvl;
            changed = true;
            levelChanged = true;
        }

        const done = Math.max(0, Math.floor(Number(serverCompleted) || 0));
        if (done > state.completedLevels) {
            state.completedLevels = done;
            changed = true;
        }

        if (changed) {
            save();
            updatePayload();
            render();
        }

        return levelChanged;
    }

    function getDifficulty(levelNumber = state.level) {
        const level = Math.max(1, Math.floor(Number(levelNumber) || 1));

        return {
            level,
            difficultyMultiplier: 1 + (level - 1) * 0.05,
            mazeSize: 9 + Math.floor((level - 1) / 2) * 2,
            obstacles: level * 2,
            gridSize: 3 + Math.floor((level - 1) / 4),
            memoryPairs: 3 + level,
            sequenceLength: 2 + level,
            questionCount: 5 + level,
            targetScore: level * 100,
            bubbleCount: 20 + level * 5,
            speedMultiplier: 1 + (level - 1) * 0.05,
            moveDelay: Math.max(25, 180 - level * 3),
            timeLimit: Math.max(1, 20 - level)
        };
    }

    function render() {
        const current = document.getElementById("currentLevel");
        const completed = document.getElementById("completedCount");
        const bar = document.getElementById("progressFill");
        const message = document.getElementById("levelMessage");
        const badge = document.getElementById("difficultyBadge");

        if (current) current.textContent = `Level ${state.level}`;
        if (completed) completed.textContent = `${state.completedLevels} completed`;

        if (bar) {
            const progress = ((state.level - 1) % 10) + 1;
            bar.style.width = `${progress * 10}%`;
        }

        if (message) {
            message.textContent = `Complete Level ${state.level} before the timer ends to unlock Level ${state.level + 1}.`;
        }

        if (badge) {
            const multiplier = getDifficulty().difficultyMultiplier;

            badge.textContent =
                multiplier < 1.5 ? "Beginner" :
                multiplier < 2.5 ? "Intermediate" :
                multiplier < 5 ? "Advanced" :
                "Expert";
        }
    }

    function complete(won, score = 0) {
        if (!won || !state.gameId || state.completedThisLevel) return false;

        state.completedThisLevel = true;
        state.completedLevels += 1;
        state.bestScore = Math.max(state.bestScore, Number(score) || 0);
        state.level += 1;

        save();
        updatePayload();
        render();

        window.dispatchEvent(
            new CustomEvent("eduvision:level-unlocked", {
                detail: {
                    gameId: state.gameId,
                    level: state.level,
                    completedLevels: state.completedLevels,
                    bestScore: state.bestScore,
                    difficulty: getDifficulty()
                }
            })
        );

        return true;
    }

    return {
        load,
        save,
        render,
        complete,
        setLevel,
        getDifficulty,
        allowReplay() { state.completedThisLevel = false; },
        get level() { return state.level; },
        get gameId() { return state.gameId; },
        get completedLevels() { return state.completedLevels; }
    };
})();

window.EduVisionLevels = EduVisionLevels;

/* ---------- DAILY PLAY LIMIT (shared by all games) ----------
   The server (MySQL) is the real counter. localStorage is only a fast cache. */
const DailyLimit = (() => {
    const KEY = "eduvision_daily_plays";
    let limit = 10;                      // replaced by the server value (DAILY_GAME_LIMIT in .env)

    const today = () => {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    };

    const read = () => {
        try {
            const s = JSON.parse(localStorage.getItem(KEY) || "{}");
            if (s.date === today()) {
                if (Number(s.limit) > 0) limit = Number(s.limit);
                return Math.max(0, Number(s.count) || 0);
            }
        } catch (e) { /* ignore */ }
        return 0;
    };

    let count = read();

    const write = () => {
        try { localStorage.setItem(KEY, JSON.stringify({ date: today(), count, limit })); } catch (e) { /* ignore */ }
    };

    return {
        get limit() { return limit; },
        used: () => count,
        remaining: () => Math.max(0, limit - count),
        reached: () => count >= limit,
        record() { count += 1; write(); },
        set(used, newLimit) {
            if (Number.isFinite(newLimit) && newLimit > 0) limit = newLimit;
            count = Math.max(0, Number(used) || 0);
            write();
        },
        fill() { count = limit; write(); }
    };
})();

window.EduVisionDaily = DailyLimit;

onReady(() => EduVisionLevels.load());

/* =========================================================
   PART 2: ENGINE + ALL 14 GAMES + CREDITS
   ========================================================= */

onReady(() => {
"use strict";

const $ = selector => document.querySelector(selector);

const area = $("#playArea");
const scoreEl = $("#scoreValue");

if (!area || !scoreEl) {
    console.error("EduVision: Missing #playArea or #scoreValue in game.html");
    document.body.insertAdjacentHTML(
        "beforeend",
        '<p style="padding:20px;color:#dc2626;">' +
        "Game could not load. Check the HTML element IDs (#playArea, #scoreValue)." +
        "</p>"
    );
    return;
}

const Levels = window.EduVisionLevels;
if (!Levels.gameId) Levels.load();

/* ---------- small helpers ---------- */
const rnd = n => Math.floor(Math.random() * n);
const pick = array => array[rnd(array.length)];

const shuffle = items => {
    const result = [...items];
    for (let i = result.length - 1; i > 0; i--) {
        const j = rnd(i + 1);
        [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
};

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const lerp = (a, b, t) => a + (b - a) * t;

const el = (tag, cls, html) => {
    const element = document.createElement(tag);
    if (cls) element.className = cls;
    if (html != null) element.innerHTML = html;
    return element;
};

// Canvas drawn at full size and scaled down so the WHOLE board fits on the screen
// (no scrolling up and down). Height is limited so the board + time bar fit in one screen.
const cv = (root, width, height, maxW) => {
    const canvas = el("canvas", "gcanvas");
    canvas.width = width;
    canvas.height = height;
    canvas.style.width = `min(100%, ${maxW || width}px, calc(max(240px, 100vh - 300px) * ${width} / ${height}))`;
    canvas.style.height = "auto";
    canvas.style.touchAction = "none";
    root.append(canvas);
    return [canvas, canvas.getContext("2d")];
};

const txt = (ctx, value, x, y, font = "14px sans-serif", color = "#fff", align = "center") => {
    ctx.font = font;
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.fillText(value, x, y);
};

const rr = (ctx, x, y, w, h, r) => {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
};

const makeFX = () => {
    const ps = [];

    return {
        burst(x, y, color, n = 12, power = 4) {
            for (let i = 0; i < n; i++) {
                const a = Math.random() * Math.PI * 2;
                const s = (0.4 + Math.random()) * power;

                ps.push({
                    x, y, color,
                    vx: Math.cos(a) * s,
                    vy: Math.sin(a) * s - 1,
                    life: 1,
                    decay: 0.02 + Math.random() * 0.03,
                    size: 2 + Math.random() * 4
                });
            }
        },
        text(x, y, str, color = "#fff") {
            ps.push({ x, y, vx: 0, vy: -1.3, life: 1, decay: 0.018, text: str, color, size: 24 });
        },
        update(dt = 1) {
            for (let i = ps.length - 1; i >= 0; i--) {
                const p = ps[i];

                p.x += p.vx * dt;
                p.y += p.vy * dt;
                if (!p.text) p.vy += 0.12 * dt;
                p.life -= p.decay * dt;

                if (p.life <= 0) ps.splice(i, 1);
            }
        },
        draw(ctx) {
            for (const p of ps) {
                ctx.globalAlpha = Math.max(0, p.life);

                if (p.text) {
                    ctx.font = `bold ${p.size}px sans-serif`;
                    ctx.textAlign = "center";
                    ctx.lineWidth = 4;
                    ctx.strokeStyle = "rgba(0,0,0,.55)";
                    ctx.strokeText(p.text, p.x, p.y);
                    ctx.fillStyle = p.color;
                    ctx.fillText(p.text, p.x, p.y);
                } else {
                    ctx.fillStyle = p.color;
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, Math.max(0.5, p.size * p.life), 0, Math.PI * 2);
                    ctx.fill();
                }
            }

            ctx.globalAlpha = 1;
        }
    };
};

const shake = node => {
    node.classList.remove("ev-shake");
    void node.offsetWidth;
    node.classList.add("ev-shake");
};

// Red alert banner + red screen edge, used when the player goes the wrong way / answers wrong.
let wrongTimer = 0;
const wrongAlert = (message = "Wrong way!", kind = "wrong") => {
    document.querySelectorAll(".ev-wrong-alert,.ev-wrong-flash").forEach(n => n.remove());

    const info = kind === "info";
    const flash = el("div", "ev-wrong-flash");
    const banner = el("div", "ev-wrong-alert" + (info ? " info" : ""), `<b>${info ? "💡" : "✕"}</b><span></span>`);
    banner.querySelector("span").textContent = message;
    banner.setAttribute("role", "alert");

    if (!info) document.body.append(flash);
    document.body.append(banner);

    clearTimeout(wrongTimer);
    wrongTimer = setTimeout(() => {
        flash.remove();
        banner.remove();
    }, 1300);
};

// blue tip banner (hints, info)
const infoAlert = message => wrongAlert(message, "info");

/* =========================================================
   STYLES
   ========================================================= */

const ensureGameStyle = () => {
    if (document.getElementById("evGameStyle")) return;

    const style = el("style");
    style.id = "evGameStyle";

    style.textContent = `
@keyframes evDrop{from{opacity:0;transform:translateY(-18px)}to{opacity:1;transform:none}}
@keyframes evFade{from{opacity:0}to{opacity:1}}
@keyframes evPop{0%{transform:scale(.2);opacity:0}70%{transform:scale(1.14);opacity:1}100%{transform:scale(1)}}
@keyframes evShake{0%,100%{transform:translateX(0)}20%{transform:translateX(-9px)}40%{transform:translateX(9px)}60%{transform:translateX(-6px)}80%{transform:translateX(6px)}}
@keyframes evPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.06)}}
@keyframes evFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes evFlash{0%,100%{filter:none}50%{filter:brightness(2) saturate(.4)}}

#playArea{-webkit-tap-highlight-color:transparent;-webkit-user-select:none;user-select:none}
#playArea button{touch-action:manipulation}
#playArea.ev-in{animation:evFade .4s ease}
.game-heading{animation:evDrop .5s cubic-bezier(.2,1.4,.4,1) both}
.game-status{transition:background .25s,color .25s}
.game-status.win{animation:evPulse .7s ease 2}
.game-status.lose{animation:evShake .45s}
.gcanvas{display:block;margin:8px auto;border-radius:20px;max-width:100%;box-shadow:0 14px 34px rgba(20,25,60,.35),0 0 0 4px rgba(255,255,255,.75);animation:evDrop .5s ease both}
.ev-shake{animation:evShake .45s !important}
.ev-board{display:grid;justify-content:center;margin:10px auto;gap:10px}
.ev-board button:disabled{opacity:1;cursor:default}

/* ---------- time left + moves bar ---------- */
.ev-hud{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin:8px auto 4px}
.ev-chip{min-width:96px;padding:6px 16px;border-radius:16px;background:linear-gradient(180deg,#fff,#eef2ff);box-shadow:0 4px 0 #c7d2fe,0 8px 14px rgba(99,102,241,.18);text-align:center;font-weight:900;color:#4338ca}
.ev-chip small{display:block;font-size:.62rem;letter-spacing:.08em;color:#818cf8}
.ev-chip b{display:block;font-size:1.35rem;line-height:1.15;font-variant-numeric:tabular-nums}
.ev-chip.low b{color:#e11d48;animation:evPulse .6s infinite}
.ev-chip.low{background:linear-gradient(180deg,#fff,#ffe4e6);box-shadow:0 4px 0 #fda4af,0 8px 14px rgba(225,29,72,.18)}
.ev-limit{margin:6px auto 0;font-size:.9rem;font-weight:700;color:#4338ca}
.ev-limit b{color:#db2777}
.ev-timebar{max-width:320px;height:10px;margin:8px auto 2px;border-radius:99px;background:#e0e7ff;overflow:hidden;box-shadow:inset 0 1px 3px rgba(0,0,0,.15)}
.ev-timebar i{display:block;height:100%;width:100%;border-radius:99px;background:linear-gradient(90deg,#22c55e,#a3e635);transition:width .25s linear,background .3s}
.ev-timebar.mid i{background:linear-gradient(90deg,#facc15,#fb923c)}
.ev-timebar.warn i{background:linear-gradient(90deg,#f97316,#ef4444)}

/* ---------- memory cards ---------- */
.mem-board{--card:clamp(52px,17vw,96px);gap:10px;perspective:900px}
.mcard{position:relative;width:var(--card);aspect-ratio:1/1;padding:0;border:0;background:none;cursor:pointer;transform-style:preserve-3d;transition:transform .5s cubic-bezier(.4,1.5,.5,1);animation:evPop .45s backwards}
.mcard:not(.flipped):hover{transform:translateY(-5px)}
.mcard.flipped{transform:rotateY(180deg)}
.mface{position:absolute;inset:0;display:grid;place-items:center;border-radius:18px;backface-visibility:hidden;-webkit-backface-visibility:hidden;font-size:calc(var(--card)*.5);box-shadow:0 6px 14px rgba(0,0,0,.2)}
.mback{background:linear-gradient(145deg,#6366f1,#a855f7);color:#fff;font-weight:900;border:3px solid rgba(255,255,255,.65)}
.mfront{background:#fff;transform:rotateY(180deg);border:3px solid #e0e7ff}
.mcard.matched .mfront{background:linear-gradient(145deg,#bbf7d0,#86efac);border-color:#22c55e;animation:memGlow .7s ease}
.mcard.wrong .mfront{background:#fee2e2;border-color:#ef4444}
@keyframes memGlow{0%,100%{filter:brightness(1)}50%{filter:brightness(1.25) drop-shadow(0 0 14px #22c55e)}}
.mem-moves{text-align:center;font-weight:800}

/* ---------- hologram ---------- */
.holo-board{--holo:clamp(68px,22vw,116px);grid-template-columns:repeat(3,var(--holo));gap:12px;padding:16px;border-radius:28px;background:radial-gradient(circle at 30% 20%,#312e81,#0b1020);width:max-content;max-width:100%;box-shadow:0 0 40px rgba(99,102,241,.45)}
.holo-cell{width:var(--holo);height:var(--holo);border:2px solid rgba(165,180,252,.5);border-radius:24px;background:linear-gradient(145deg,#1e1b4b,#312e81);color:#a5b4fc;font-size:calc(var(--holo)*.4);cursor:pointer;transition:transform .15s,background .15s,box-shadow .15s;animation:evPop .4s backwards}
.holo-cell:hover:not(:disabled){transform:scale(1.06)}
.holo-cell.lit{background:linear-gradient(145deg,#c4b5fd,#7c3aed);color:#fff;transform:scale(1.12);box-shadow:0 0 30px #8b5cf6,0 0 70px rgba(139,92,246,.7)}
.holo-cell.good{background:linear-gradient(145deg,#86efac,#16a34a);color:#fff;box-shadow:0 0 26px #22c55e}
.holo-cell.bad{background:linear-gradient(145deg,#fca5a5,#dc2626);color:#fff;animation:evShake .4s}

/* ---------- tic tac toe ---------- */
.ttt-board{--ttt:clamp(78px,24vw,120px);grid-template-columns:repeat(3,var(--ttt));gap:10px;padding:14px;border-radius:26px;background:radial-gradient(circle at 30% 20%,#312e81,#0f172a);width:max-content;max-width:100%;box-shadow:0 0 40px rgba(99,102,241,.45)}
.ttt-cell{width:var(--ttt);height:var(--ttt);border:2px solid rgba(165,180,252,.35);border-radius:20px;background:rgba(15,23,42,.85);font-size:calc(var(--ttt)*.6);font-weight:900;cursor:pointer;transition:background .2s,transform .15s;color:#fff}
.ttt-cell:hover:not(.x):not(.o){background:rgba(99,102,241,.4);transform:scale(1.05)}
.ttt-cell span{display:block;animation:evPop .35s both}
.ttt-cell.x{color:#22d3ee;text-shadow:0 0 18px #22d3ee,0 0 36px #22d3ee}
.ttt-cell.o{color:#f472b6;text-shadow:0 0 18px #f472b6,0 0 36px #f472b6}
.ttt-cell.win{background:rgba(250,204,21,.28);border-color:#facc15;animation:tttWin .6s ease infinite}
@keyframes tttWin{50%{transform:scale(1.12)}}

/* ---------- 2048 ---------- */
.p48-board{--t:clamp(52px,17vw,96px);grid-template-columns:repeat(var(--n),var(--t));gap:8px;padding:10px;border-radius:18px;background:#bbada0;width:max-content;max-width:100%;touch-action:none;box-shadow:0 12px 30px rgba(0,0,0,.25)}
.p48-cell{width:var(--t);height:var(--t);display:grid;place-items:center;border-radius:12px;background:rgba(238,228,218,.35);font-weight:900;font-size:calc(var(--t)*.4)}
.p48-cell.big{font-size:calc(var(--t)*.3)}
.p48-cell.has{box-shadow:0 4px 10px rgba(0,0,0,.2)}
.p48-cell.spawn{animation:evPop .22s ease backwards}
.p48-cell.merge{animation:p48Bump .22s ease}
@keyframes p48Bump{0%{transform:scale(1)}50%{transform:scale(1.22)}100%{transform:scale(1)}}
.p48-board[data-slide=left] .p48-cell.has:not(.spawn):not(.merge){animation:p48L .13s ease-out}
.p48-board[data-slide=right] .p48-cell.has:not(.spawn):not(.merge){animation:p48R .13s ease-out}
.p48-board[data-slide=up] .p48-cell.has:not(.spawn):not(.merge){animation:p48U .13s ease-out}
.p48-board[data-slide=down] .p48-cell.has:not(.spawn):not(.merge){animation:p48D .13s ease-out}
@keyframes p48L{from{transform:translateX(30px)}}
@keyframes p48R{from{transform:translateX(-30px)}}
@keyframes p48U{from{transform:translateY(30px)}}
@keyframes p48D{from{transform:translateY(-30px)}}

/* ---------- arrow direction ---------- */
.arw-stage{display:grid;place-items:center;width:clamp(150px,42vw,240px);height:clamp(150px,42vw,240px);margin:10px auto;border-radius:50%;background:radial-gradient(circle,#fff,#e0e7ff);box-shadow:0 0 0 8px #c7d2fe,0 18px 40px rgba(99,102,241,.35);transition:background .2s,box-shadow .2s}
.arw-stage.ok{background:radial-gradient(circle,#dcfce7,#86efac);box-shadow:0 0 0 8px #4ade80,0 0 50px rgba(34,197,94,.6)}
.arw-stage.bad{background:radial-gradient(circle,#fee2e2,#fca5a5);box-shadow:0 0 0 8px #f87171;animation:evShake .4s}
.arw-sym{font-size:clamp(60px,18vw,120px);line-height:1;animation:evPop .35s cubic-bezier(.2,1.6,.4,1) both}
.arw-bar{max-width:420px;height:14px;margin:8px auto;border-radius:99px;background:#e0e7ff;overflow:hidden}
.arw-bar i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#6366f1,#ec4899);transition:width .4s}
.arw-round{text-align:center;font-weight:800;margin:4px 0}

/* ---------- sliding puzzle ---------- */
.sl-board{--cell:clamp(50px,17vw,96px);--gap:8px;position:relative;box-sizing:content-box;margin:10px auto;padding:12px;border-radius:22px;background:linear-gradient(145deg,#1e293b,#334155);width:calc(var(--n)*var(--cell) + (var(--n) - 1)*var(--gap));height:calc(var(--n)*var(--cell) + (var(--n) - 1)*var(--gap));max-width:100%;box-shadow:0 14px 34px rgba(15,23,42,.45)}
.sl-tile{position:absolute;left:12px;top:12px;width:var(--cell);height:var(--cell);border:0;border-radius:16px;color:#fff;font-size:calc(var(--cell)*.4);font-weight:900;cursor:pointer;text-shadow:0 2px 4px rgba(0,0,0,.3);box-shadow:inset 0 -5px 0 rgba(0,0,0,.2),0 6px 12px rgba(0,0,0,.3);transform:translate(calc(var(--c)*(var(--cell) + var(--gap))),calc(var(--r)*(var(--cell) + var(--gap))));transition:transform .2s cubic-bezier(.3,1.3,.5,1),filter .15s;animation:evFade .4s backwards}
.sl-tile:hover{filter:brightness(1.12)}

/* ---------- quiz battle ---------- */
.qb-arena{display:flex;align-items:center;justify-content:space-between;gap:12px;max-width:760px;margin:10px auto;padding:12px 20px;border-radius:24px;background:linear-gradient(135deg,#1e1b4b,#4c1d95);color:#fff;box-shadow:0 14px 34px rgba(76,29,149,.4)}
.qb-fighter{flex:1;text-align:center;font-weight:800}
.qb-sprite{font-size:clamp(40px,9vw,72px);line-height:1;display:inline-block;animation:evFloat 2.2s ease-in-out infinite}
.qb-sprite.hit{animation:evShake .4s,evFlash .4s}
.qb-hp{height:14px;border-radius:99px;background:rgba(255,255,255,.2);overflow:hidden;margin-top:8px}
.qb-hp i{display:block;height:100%;width:100%;border-radius:99px;transition:width .5s}
.qb-hp.me i{background:linear-gradient(90deg,#34d399,#10b981)}
.qb-hp.foe i{background:linear-gradient(90deg,#f87171,#ef4444)}
.qb-vs{font-weight:900;font-size:24px;color:#fcd34d}
.qb-q{max-width:760px;margin:10px auto;padding:12px 18px;border-radius:20px;background:#f5f3ff;text-align:center;animation:evDrop .35s both}
.qb-q h3{margin:0 0 6px;color:#6d28d9}
.qb-q p{margin:0;font-size:1.15rem;font-weight:700}
.qb-opts{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;max-width:760px;margin:0 auto}
.qb-opt{padding:14px;border:0;border-radius:16px;font-size:1rem;font-weight:700;cursor:pointer;background:#fff;box-shadow:0 4px 0 #c7d2fe,0 8px 16px rgba(0,0,0,.08);transition:transform .15s,box-shadow .15s;animation:evPop .35s backwards}
.qb-opt:hover:not(:disabled){transform:translateY(-3px)}
.qb-opt.ok{background:#bbf7d0;box-shadow:0 4px 0 #22c55e}
.qb-opt.bad{background:#fecaca;box-shadow:0 4px 0 #ef4444;animation:evShake .4s}
@media(max-width:560px){.qb-opts{grid-template-columns:1fr}.ev-chip{min-width:84px;padding:5px 12px}}

/* ---------- look & feel for every game ---------- */
#playArea{min-height:60vh;padding:6px 6px 70px;scroll-margin-top:96px}
/* the page header already shows the game title, so keep the in-game bar small */
.game-heading>h2,.game-heading>p{display:none}
.ev-hud{align-items:center}
.ev-hud .ev-restart{padding:8px 16px !important;font-size:.9rem !important;box-shadow:0 4px 0 #c7d2fe !important}

/* RED "WRONG" ALERT (all games) */
@keyframes evWrongIn{0%{opacity:0;transform:translate(-50%,-20px) scale(.7)}25%{opacity:1;transform:translate(-50%,0) scale(1.08)}40%{transform:translate(-50%,0) scale(1)}85%{opacity:1}100%{opacity:0;transform:translate(-50%,0) scale(1)}}
@keyframes evRedFlash{0%{opacity:1}100%{opacity:0}}
.ev-wrong-alert{position:fixed;left:50%;top:110px;z-index:99990;display:flex;align-items:center;gap:10px;padding:12px 26px;border-radius:99px;background:linear-gradient(180deg,#ef4444,#b91c1c);color:#fff;font-weight:900;font-size:1.15rem;white-space:nowrap;box-shadow:0 8px 0 #7f1d1d,0 16px 30px rgba(185,28,28,.5);pointer-events:none;animation:evWrongIn 1.3s ease forwards}
.ev-wrong-alert b{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#fff;color:#dc2626;font-size:1.05rem}
.ev-wrong-alert.info{background:linear-gradient(180deg,#6366f1,#4338ca);box-shadow:0 8px 0 #312e81,0 16px 30px rgba(67,56,202,.5)}
.ev-wrong-alert.info b{background:#fff;color:#4338ca}
.ev-hint-glow{box-shadow:0 0 0 4px #22c55e,0 0 26px 6px #22c55e !important;outline:3px solid #22c55e}
.ev-hearts{display:flex;justify-content:center;align-items:center;gap:18px;font-size:1.25rem;font-weight:900;color:#4338ca;margin:6px 0}
.ev-hint:disabled{opacity:.45;cursor:not-allowed}
.ev-daily{display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;margin:4px 0;font-size:.78rem;font-weight:800;color:#4338ca}
.edu-marks{display:flex;justify-content:center;gap:4px;flex-wrap:wrap}
.edu-mark{width:20px;height:20px;display:grid;place-items:center;border-radius:6px;background:#eef2ff;color:#a5b4fc;font-size:.75rem}
.edu-mark.on{background:#dc2626;color:#fff}
.edu-mark.stamp{animation:evStamp .6s cubic-bezier(.2,1.4,.4,1) both}
@keyframes evStamp{0%{transform:scale(3.2) rotate(-25deg);opacity:0}60%{transform:scale(.85) rotate(4deg);opacity:1}100%{transform:scale(1) rotate(0)}}
.ev-wrong-flash{position:fixed;inset:0;z-index:99989;pointer-events:none;box-shadow:inset 0 0 140px 40px rgba(220,38,38,.55);animation:evRedFlash .7s ease-out forwards}
#playArea .game-heading{text-align:center;margin:2px 0 4px}
#playArea .game-heading h2{margin:0;font-size:clamp(1.3rem,4.5vw,2rem);font-weight:900;letter-spacing:-.01em;background:linear-gradient(90deg,#6366f1,#ec4899,#f59e0b);-webkit-background-clip:text;background-clip:text;color:transparent}
#playArea .game-heading p{margin:4px auto 0;max-width:560px;opacity:.78;font-size:.95rem}
.ev-toolbar{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin:8px 0 2px}
#playArea .gbtn{border:0;border-radius:14px;padding:12px 22px;font:inherit;font-weight:800;font-size:1rem;color:#fff;cursor:pointer;background:linear-gradient(180deg,#8b5cf6,#6366f1);box-shadow:0 5px 0 #4338ca,0 10px 18px rgba(67,56,202,.35);transition:transform .1s,box-shadow .1s,filter .15s}
#playArea .gbtn:hover{filter:brightness(1.08)}
#playArea .gbtn:active{transform:translateY(4px);box-shadow:0 1px 0 #4338ca}
#playArea .gbtn.secondary{color:#4338ca;background:linear-gradient(180deg,#fff,#eef2ff);box-shadow:0 5px 0 #c7d2fe,0 10px 18px rgba(99,102,241,.2)}
#playArea .gbtn.secondary:active{box-shadow:0 1px 0 #c7d2fe}

/* status message sticks to the bottom of the screen, so the player never scrolls to read it */
#playArea .game-status{position:sticky;bottom:10px;z-index:20;display:table;margin:10px auto;padding:8px 18px;border-radius:99px;background:#eef2ff;color:#3730a3;font-weight:700;text-align:center;max-width:94%;box-shadow:0 6px 18px rgba(30,27,75,.22)}
#playArea .game-status.win{background:#dcfce7;color:#166534}
#playArea .game-status.lose{background:#fee2e2;color:#991b1b}
#playArea .game-result-panel{max-width:420px;margin:18px auto;padding:24px;border-radius:24px;text-align:center;background:#fff;box-shadow:0 18px 40px rgba(30,27,75,.25);animation:evPop .4s both}
#playArea .game-result-panel h3{margin:0 0 6px;font-size:1.6rem}
#playArea .game-result-panel .gbtn{margin-top:12px}
#playArea .game-result-panel .ev-big{font-size:56px;line-height:1;margin-bottom:6px}
`;

    document.head.append(style);
};

ensureGameStyle();

/* ---------- FAILED LEVEL POPUP (big red X in the middle of the screen) ---------- */
const ensureFailStyle = () => {
    if (document.getElementById("evFailStyle")) return;

    const style = el("style");
    style.id = "evFailStyle";

    style.textContent = `
@keyframes evFailPop{0%{opacity:0;transform:scale(.7) translateY(20px)}60%{transform:scale(1.05)}100%{opacity:1;transform:none}}
@keyframes evFailX{0%{transform:scale(0) rotate(-90deg)}60%{transform:scale(1.25) rotate(8deg)}100%{transform:scale(1) rotate(0)}}
.edu-fail-overlay{position:fixed;inset:0;z-index:99998;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(15,23,42,.62);backdrop-filter:blur(4px);-webkit-user-select:none;user-select:none}
.edu-fail-card{position:relative;width:min(380px,100%);padding:26px 22px 22px;border-radius:26px;text-align:center;color:#1f2a44;background:#fff;box-shadow:0 24px 60px rgba(15,23,42,.45);animation:evFailPop .4s ease-out both}
.edu-fail-x{width:92px;height:92px;margin:0 auto 10px;display:grid;place-items:center;border-radius:50%;background:linear-gradient(145deg,#f87171,#dc2626);color:#fff;font-size:58px;font-weight:900;line-height:1;box-shadow:0 8px 0 #991b1b,0 14px 28px rgba(220,38,38,.45);animation:evFailX .55s cubic-bezier(.2,1.6,.4,1) both}
.edu-fail-card h2{margin:10px 0 6px;font-size:1.6rem;color:#b91c1c}
.edu-fail-card p{margin:0 0 4px;color:#4b5563;line-height:1.5}
.edu-fail-level{display:inline-block;margin:8px 0 2px;padding:4px 14px;border-radius:99px;background:#fee2e2;color:#991b1b;font-weight:800;font-size:.9rem}
.edu-fail-actions{display:grid;gap:12px;margin-top:18px}
.edu-fail-actions button{width:100%;padding:14px;border:0;border-radius:14px;font:inherit;font-size:1.05rem;font-weight:800;cursor:pointer;transition:transform .1s,filter .15s}
.edu-fail-actions button:hover{filter:brightness(1.07)}
.edu-fail-actions button:active{transform:translateY(3px)}
.edu-fail-retry{color:#fff;background:linear-gradient(180deg,#8b5cf6,#6366f1);box-shadow:0 5px 0 #4338ca}
.edu-fail-back{color:#4338ca;background:#eef2ff;box-shadow:0 5px 0 #c7d2fe}
.edu-x-close{position:absolute;top:10px;right:10px;z-index:2;width:38px;height:38px;display:grid;place-items:center;padding:0;border:0;border-radius:50%;background:#fee2e2;color:#dc2626;font-size:20px;font-weight:900;line-height:1;cursor:pointer;box-shadow:0 3px 0 #fca5a5;transition:transform .1s,background .15s}
.edu-x-close:hover{background:#fecaca}
.edu-x-close:active{transform:translateY(2px);box-shadow:0 1px 0 #fca5a5}
`;

    document.head.append(style);
};

const ensureCandyStyle = () => {
    if (document.getElementById("evCandyStyle")) return;

    const style = el("style");
    style.id = "evCandyStyle";

    style.textContent = `
@keyframes ccIdle{0%,100%{transform:scale(1,1)}30%{transform:scale(1.04,.96)}60%{transform:scale(.97,1.04)}}
@keyframes ccBounce{0%,100%{transform:translateY(0) scale(1.08,.94)}50%{transform:translateY(-10%) scale(.96,1.08)}}
@keyframes ccHint{0%,100%{transform:scale(1)}50%{transform:scale(1.22) rotate(6deg)}}
@keyframes ccPop{0%{transform:scale(1)}35%{transform:scale(1.35,.75)}100%{transform:scale(0) rotate(40deg);opacity:0}}
@keyframes ccBorn{0%{transform:scale(.2) rotate(-90deg)}100%{transform:scale(1) rotate(0)}}
@keyframes ccSpin{to{transform:rotate(360deg)}}
@keyframes ccBeamH{0%{opacity:1;transform:scaleY(.2)}60%{opacity:1;transform:scaleY(1)}100%{opacity:0;transform:scaleY(1.2)}}
@keyframes ccBeamV{0%{opacity:1;transform:scaleX(.2)}60%{opacity:1;transform:scaleX(1)}100%{opacity:0;transform:scaleX(1.2)}}
@keyframes ccRing{0%{opacity:1;transform:translate(-50%,-50%) scale(.2)}100%{opacity:0;transform:translate(-50%,-50%) scale(1.3)}}
@keyframes ccFlash{0%{opacity:.95}100%{opacity:0}}
@keyframes ccSpark{to{transform:translate(calc(-50% + var(--dx)),calc(-50% + var(--dy))) scale(.2);opacity:0}}
@keyframes ccFloat{0%{opacity:1;transform:translate(-50%,0) scale(.8)}100%{opacity:0;transform:translate(-50%,-70px) scale(1.25)}}
@keyframes ccPraise{0%{opacity:0;transform:translate(-50%,-50%) scale(.3) rotate(-8deg)}25%{opacity:1;transform:translate(-50%,-50%) scale(1.15) rotate(3deg)}75%{opacity:1;transform:translate(-50%,-50%) scale(1)}100%{opacity:0;transform:translate(-50%,-80%) scale(1)}}

.cc-hud{display:flex;align-items:stretch;justify-content:center;gap:10px;flex-wrap:wrap;max-width:600px;margin:8px auto}
.cc-chip{min-width:70px;padding:6px 14px;border-radius:16px;background:linear-gradient(180deg,#fff,#f3e8ff);box-shadow:0 4px 0 #d8b4fe,0 8px 14px rgba(124,58,237,.18);text-align:center;font-weight:900;color:#6d28d9}
.cc-chip small{display:block;font-size:.65rem;letter-spacing:.08em;color:#a78bfa}
.cc-chip b{font-size:1.5rem;line-height:1.1}
.cc-chip.big{flex:1;min-width:170px;display:flex;flex-direction:column;justify-content:center}
.cc-bar{position:relative;height:16px;border-radius:99px;background:#ede9fe;margin-top:10px;box-shadow:inset 0 2px 4px rgba(0,0,0,.15)}
.cc-bar i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#fb7185,#fbbf24,#34d399);transition:width .5s cubic-bezier(.3,1.4,.5,1)}
.cc-bar span{position:absolute;top:-10px;font-size:20px;color:#d4d4d8;transform:translateX(-50%);transition:.3s;text-shadow:0 1px 0 #fff}
.cc-bar span.on{color:#fbbf24;transform:translateX(-50%) scale(1.3)}
.cc-snd{border:0;border-radius:14px;padding:0 14px;font-size:1.3rem;cursor:pointer;background:#fff;box-shadow:0 4px 0 #d8b4fe}
.cc-wrap{--cell:clamp(34px,min(10.2vw,6.4vh),62px);width:max-content;max-width:100%;margin:10px auto;padding:12px;border-radius:30px;background:linear-gradient(160deg,#a855f7,#ec4899 55%,#fb923c);box-shadow:0 20px 44px rgba(168,85,247,.45),inset 0 0 0 4px rgba(255,255,255,.4)}
.cc-board{position:relative;overflow:hidden;width:calc(var(--cols) * var(--cell));height:calc(var(--rows) * var(--cell));border-radius:20px;touch-action:none;user-select:none;-webkit-user-select:none;cursor:pointer;background:repeating-conic-gradient(rgba(255,255,255,.2) 0 25%,rgba(255,255,255,.08) 0 50%) 0 0/calc(var(--cell) * 2) calc(var(--cell) * 2),rgba(76,29,149,.6)}
.cc-board.nope{animation:evShake .35s}
.cc-candy{position:absolute;left:0;top:0;width:var(--cell);height:var(--cell);padding:calc(var(--cell) * .06);box-sizing:border-box;pointer-events:none;will-change:transform;transform:translate(calc(var(--x) * var(--cell)),calc(var(--y) * var(--cell)));transition:transform .36s cubic-bezier(.34,1.28,.64,1)}
.cc-candy svg{display:block;width:100%;height:100%;overflow:visible;transform-origin:50% 90%;filter:drop-shadow(0 3px 2px rgba(0,0,0,.35));animation:ccIdle 3s ease-in-out infinite}
.cc-candy.sel svg{animation:ccBounce .5s ease-in-out infinite;filter:drop-shadow(0 0 8px #fff) brightness(1.15)}
.cc-candy.hint svg{animation:ccHint .7s ease-in-out infinite}
.cc-candy.pop svg{animation:ccPop .3s ease-in forwards}
.cc-candy.born svg{animation:ccBorn .5s cubic-bezier(.2,1.6,.4,1)}
.cc-candy.sp-h svg,.cc-candy.sp-v svg{filter:drop-shadow(0 0 6px rgba(255,255,255,.95))}
.cc-candy.sp-w svg{filter:drop-shadow(0 0 7px #fff) drop-shadow(0 0 4px gold)}
.cc-candy.sp-b svg{animation:ccSpin 4s linear infinite;filter:drop-shadow(0 0 9px #f0abfc)}
.cc-beam{position:absolute;pointer-events:none;z-index:5}
.cc-beam.h{left:0;width:100%;height:var(--cell);background:linear-gradient(90deg,transparent,#fff,#fde68a,#fff,transparent);animation:ccBeamH .6s ease-out forwards}
.cc-beam.v{top:0;height:100%;width:var(--cell);background:linear-gradient(180deg,transparent,#fff,#fde68a,#fff,transparent);animation:ccBeamV .6s ease-out forwards}
.cc-ring{position:absolute;z-index:5;pointer-events:none;width:calc(var(--cell) * 3);height:calc(var(--cell) * 3);border-radius:50%;border:6px solid #fff;box-shadow:0 0 24px #fde68a;animation:ccRing .6s ease-out forwards}
.cc-flash{position:absolute;inset:0;z-index:5;pointer-events:none;background:radial-gradient(circle,#fff,rgba(255,255,255,0));animation:ccFlash .6s ease-out forwards}
.cc-spark{position:absolute;z-index:6;width:10px;height:10px;border-radius:50%;pointer-events:none;transform:translate(-50%,-50%);animation:ccSpark .6s ease-out forwards}
.cc-float{position:absolute;z-index:7;pointer-events:none;font-weight:900;font-size:22px;color:#fff;white-space:nowrap;text-shadow:0 2px 0 #7c3aed,0 0 10px rgba(0,0,0,.4);animation:ccFloat .95s ease-out forwards}
.cc-praise{position:absolute;z-index:8;left:50%;top:45%;pointer-events:none;font-weight:900;font-size:clamp(26px,7vw,44px);color:#fff;white-space:nowrap;-webkit-text-stroke:2px #7c3aed;text-shadow:0 4px 0 #7c3aed,0 0 20px rgba(255,255,255,.7);animation:ccPraise 1s ease-out forwards}
`;

    document.head.append(style);
};

const currentLevel = () => Math.max(1, Number(Levels.level) || 1);

/* =========================================================
   TIME LIMIT PER LEVEL
   [base seconds, extra seconds per level, maximum seconds]
   Change these numbers to make levels easier or harder.
   ========================================================= */

const TIME_LIMITS = {
    arrow_maze:       [90, 10, 600],
    hologram_memory:  [60, 8, 300],
    candy_match:      [150, 10, 420],
    memory_match:     [60, 10, 300],
    bubble_shooter:   [180, 10, 480],
    endless_runner:   [45, 5, 240],
    neon_tic_tac_toe: [90, 0, 90],
    puzzle_2048:      [180, 20, 900],
    arrow_direction:  [20, 3, 150],
    sliding_puzzle:   [120, 15, 600],
    quiz_battle:      [60, 15, 420],
    tetris_blocks:    [150, 15, 600],
    flappy_brain:     [40, 4, 150],
    snake_game:       [60, 8, 300]
};

const timeLimitFor = (gameId, level) => {
    const [base, perLevel, max] = TIME_LIMITS[gameId] || [120, 10, 600];
    return Math.round(Math.min(max, base + perLevel * (Math.max(1, level) - 1)));
};

/* ---------- engine state ---------- */
let session = 0;
let score = 0;
let over = false;
let cleanups = [];
let moveCount = 0;
let hudTimeEl = null;
let hudTimeChip = null;
let hudTimeBar = null;
let hudMovesEl = null;
let hudMovesLabel = null;
let hudMovesChip = null;
let timeLimit = 0;       // seconds allowed for this level
let elapsedSec = 0;      // seconds used so far
let winPending = false;  // true once the level is won (stops the clock)
let hintsLeft = 3;       // hints per level
let hintFn = null;       // each game registers its own hint with onHint()
let hintBtn = null;

const onClean = fn => cleanups.push(fn);

const on = (target, type, fn, opts) => {
    target.addEventListener(type, fn, opts);
    onClean(() => target.removeEventListener(type, fn, opts));
};

const every = (ms, fn) => {
    const id = setInterval(fn, ms);
    onClean(() => clearInterval(id));
    return id;
};

const later = (ms, fn) => {
    const id = setTimeout(fn, ms);
    onClean(() => clearTimeout(id));
    return id;
};

const loop = fn => {
    let id = 0;
    let alive = true;
    let last = performance.now();

    const tick = now => {
        if (!alive || over) return;

        const dt = clamp((now - last) / 16.667, 0, 3);
        last = now;
        fn(dt);

        if (alive && !over) id = requestAnimationFrame(tick);
    };

    id = requestAnimationFrame(tick);

    onClean(() => {
        alive = false;
        cancelAnimationFrame(id);
    });
};

const setScore = (value, bump = true) => {
    score = Math.max(0, Math.round(Number(value) || 0));
    scoreEl.textContent = score;

    if (bump) {
        scoreEl.classList.remove("bump");
        void scoreEl.offsetWidth;
        scoreEl.classList.add("bump");
    }
};

const addScore = n => setScore(score + (Number(n) || 0));

/* ---------- time left + moves bar (every game) ---------- */
const fmtTime = s => {
    s = Math.max(0, Math.floor(s));
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

// "3 min", "1 min 30 sec", "45 sec"
const fmtMinutes = s => {
    const m = Math.floor(s / 60);
    const r = s % 60;

    if (m === 0) return `${r} sec`;
    return r ? `${m} min ${r} sec` : `${m} min`;
};

// Show an exact value (and optionally rename the label, e.g. "MOVES LEFT").
const setMoves = (value, label) => {
    if (!hudMovesEl) return;

    hudMovesEl.textContent = value;

    if (label && hudMovesLabel) hudMovesLabel.textContent = "👣 " + label;

    if (hudMovesChip) {
        hudMovesChip.classList.toggle("low", Boolean(label) && typeof value === "number" && value <= 5);
    }
};

// Count one more move.
const addMove = (n = 1) => {
    moveCount += n;
    setMoves(moveCount);
};

const resetGame = () => {
    session++;

    const fns = cleanups;
    cleanups = [];

    fns.forEach(fn => {
        try { fn(); } catch (e) { /* ignore */ }
    });

    over = false;
    score = 0;
    moveCount = 0;
    timeLimit = 0;
    elapsedSec = 0;
    winPending = false;
    hintsLeft = 3;
    hintFn = null;
    hintBtn = null;
    hudTimeEl = hudTimeChip = hudTimeBar = null;
    hudMovesEl = hudMovesLabel = hudMovesChip = null;

    area.innerHTML = "";
    scoreEl.textContent = "0";

    area.classList.remove("ev-in");
    void area.offsetWidth;
    area.classList.add("ev-in");

    document.getElementById("eduRewardPopup")?.remove();
    document.getElementById("eduFailPopup")?.remove();
    document.querySelectorAll(".ev-wrong-alert,.ev-wrong-flash").forEach(n => n.remove());
};

/* ---------- UI helpers ---------- */
const makeButton = (label, callback, className = "gbtn") => {
    const button = el("button", className);
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", e => {
        callback(e);
        button.blur();   // so Space / Enter keep controlling the game
    });
    return button;
};

/* ---------- HINT (every game, 3 hints per level) ---------- */
const hintLabel = () => `💡 Hint (${hintsLeft})`;

const onHint = fn => { hintFn = fn; };

const useHint = () => {
    if (over || winPending) return;

    if (hintsLeft <= 0) {
        infoAlert("No hints left in this level");
        return;
    }

    let ok = false;
    try { ok = hintFn ? hintFn() : false; } catch (e) { ok = false; }

    if (ok === false) {
        infoAlert("No hint available right now");
        return;
    }

    hintsLeft--;

    if (hintBtn) {
        hintBtn.textContent = hintLabel();
        hintBtn.disabled = hintsLeft <= 0;
    }
};

/* ---------- today's rounds: one red cut mark for every finished round ---------- */
const dailyHTML = () => {
    const used = Math.min(DailyLimit.used(), DailyLimit.limit);
    const marks = Array.from({ length: DailyLimit.limit }, (_, i) =>
        i < used ? '<b class="edu-mark on">✕</b>' : '<b class="edu-mark">·</b>').join("");

    return `<span>Today's rounds</span><div class="edu-marks">${marks}</div><span>${used}/${DailyLimit.limit}</span>`;
};

const refreshDailyStrip = () => {
    document.querySelectorAll(".ev-daily").forEach(n => { n.innerHTML = dailyHTML(); });
};

// Called when the countdown reaches zero.
const timeUp = () => {
    if (over || winPending) return;

    finishLose(
        `You had ${fmtMinutes(timeLimit)} to finish Level ${currentLevel()}. Try again, you can do it!`,
        "Time's Up!"
    );
};

const addHeading = (title, description = "") => {
    const wrapper = el("div", "game-heading");

    const h = el("h2");
    h.textContent = title;
    wrapper.append(h);

    if (description) {
        const p = el("p");
        p.textContent = description;
        wrapper.append(p);
    }

    // How long the player has for this level
    timeLimit = timeLimitFor(Levels.gameId, currentLevel());

    // Time LEFT + Moves bar (the time limit is shown in the TIME LEFT chip, no extra line)
    const hud = el("div", "ev-hud",
        `<div class="ev-chip ev-tchip"><small>⏱ TIME LEFT</small><b class="ev-time">${fmtTime(timeLimit)}</b></div>
         <div class="ev-chip ev-mchip"><small class="ev-mlabel">👣 MOVES</small><b class="ev-moves">0</b></div>`);

    hudTimeEl = hud.querySelector(".ev-time");
    hudTimeChip = hud.querySelector(".ev-tchip");
    hudMovesEl = hud.querySelector(".ev-moves");
    hudMovesLabel = hud.querySelector(".ev-mlabel");
    hudMovesChip = hud.querySelector(".ev-mchip");

    wrapper.append(hud);

    // Shrinking time bar (green -> orange -> red)
    const timeBar = el("div", "ev-timebar", "<i></i>");
    hudTimeBar = timeBar;
    wrapper.append(timeBar);

    const daily = el("div", "ev-daily", dailyHTML());
    wrapper.append(daily);

    const fill = timeBar.querySelector("i");
    const startedAt = performance.now();

    every(250, () => {
        if (over || winPending || !hudTimeEl) return;

        elapsedSec = Math.floor((performance.now() - startedAt) / 1000);

        const left = Math.max(0, timeLimit - elapsedSec);
        const ratio = timeLimit ? left / timeLimit : 0;

        hudTimeEl.textContent = fmtTime(left);
        fill.style.width = `${ratio * 100}%`;

        hudTimeChip.classList.toggle("low", left <= 10);
        timeBar.classList.toggle("mid", ratio <= 0.5 && ratio > 0.25);
        timeBar.classList.toggle("warn", ratio <= 0.25);

        if (left <= 0) timeUp();
    });

    // Hint + Restart in the same row as time + moves (saves space)
    hintBtn = makeButton(hintLabel(), () => useHint(), "gbtn secondary ev-restart ev-hint");
    hud.append(hintBtn);
    hud.append(makeButton("🔄 Restart", () => restartLevel(), "gbtn secondary ev-restart"));

    // press H for a hint
    on(window, "keydown", e => {
        if (e.code !== "KeyH" || e.ctrlKey || e.metaKey || e.altKey) return;
        const tg = e.target;
        if (tg && (tg.tagName === "INPUT" || tg.tagName === "TEXTAREA" || tg.isContentEditable)) return;
        useHint();
    });

    area.append(wrapper);
    return wrapper;
};

const makeStatus = (text = "") => {
    const p = el("p", "game-status");
    p.textContent = text;
    area.append(p);

    return (t, cls = "") => {
        p.textContent = t;
        p.className = ("game-status " + cls).trim();
    };
};

/* ---------- keyboard + touch controls ---------- */
const KEY_DIRS = {
    ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
    KeyW: "up", KeyS: "down", KeyA: "left", KeyD: "right",
    Numpad8: "up", Numpad2: "down", Numpad4: "left", Numpad6: "right",
    Up: "up", Down: "down", Left: "left", Right: "right",
    w: "up", s: "down", a: "left", d: "right",
    W: "up", S: "down", A: "left", D: "right"
};

const dirFromEvent = e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return null;

    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
        return null;
    }

    return KEY_DIRS[e.code] || KEY_DIRS[e.key] || null;
};

const isTouchDevice = () =>
    !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches) ||
    "ontouchstart" in window;

const keys = handler => {
    on(window, "keydown", e => {
        const dir = dirFromEvent(e);
        if (!dir) return;
        e.preventDefault();
        handler(dir);
    });
};

const dpad = handler => {
    const call = dir => {
        if (typeof handler === "function") handler(dir);
        else if (handler && typeof handler[dir] === "function") handler[dir]();
    };

    if (!isTouchDevice()) return null;

    const pad = el("div", "game-dpad");

    pad.style.display = "grid";
    pad.style.gridTemplateColumns = "repeat(3, 70px)";
    pad.style.gridTemplateRows = "repeat(2, 62px)";
    pad.style.gap = "8px";
    pad.style.justifyContent = "center";
    pad.style.marginTop = "10px";

    [["up", "▲", "2 / 1"], ["left", "◀", "1 / 2"], ["down", "▼", "2 / 2"], ["right", "▶", "3 / 2"]]
        .forEach(([dir, label, cellPos]) => {
            const button = el("button", "gbtn secondary", label);
            const [col, row] = cellPos.split(" / ");

            button.type = "button";
            button.setAttribute("aria-label", dir);
            button.style.gridColumn = col;
            button.style.gridRow = row;
            button.style.fontSize = "22px";
            button.style.padding = "0";

            button.addEventListener("pointerdown", e => {
                e.preventDefault();
                call(dir);
            });

            pad.append(button);
        });

    area.append(pad);
    return pad;
};

const swipe = (target, handler) => {
    let sx = 0;
    let sy = 0;

    on(target, "touchstart", e => {
        const t = e.changedTouches[0];
        sx = t.clientX;
        sy = t.clientY;
    }, { passive: true });

    on(target, "touchend", e => {
        const t = e.changedTouches[0];
        const dx = t.clientX - sx;
        const dy = t.clientY - sy;

        if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;

        handler(
            Math.abs(dx) > Math.abs(dy)
                ? (dx > 0 ? "right" : "left")
                : (dy > 0 ? "down" : "up")
        );
    }, { passive: true });
};

/* =========================================================
   CREDITS, SOUND, REWARD POPUP, SAVING TO FLASK
   ========================================================= */

const CREDIT_KEY = "eduvision_credits_earned";

const showCredits = serverBalance => {
    if (serverBalance === undefined || serverBalance === null) return;

    const balance = Math.max(0, Number(serverBalance) || 0);

    ["creditValue", "creditBalance", "creditsBalance", "userCredits"]
        .forEach(id => {
            const node = document.getElementById(id);
            if (node) node.textContent = String(balance);
        });

    try {
        localStorage.setItem(CREDIT_KEY, String(balance));
    } catch (e) { /* ignore */ }
};

const playCreditRewardSound = () => {
    try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;

        const audio = new AudioContextClass();

        [523.25, 659.25, 783.99].forEach((frequency, index) => {
            const start = audio.currentTime + index * 0.13;
            const oscillator = audio.createOscillator();
            const gain = audio.createGain();

            oscillator.type = "sine";
            oscillator.frequency.setValueAtTime(frequency, start);

            gain.gain.setValueAtTime(0.0001, start);
            gain.gain.exponentialRampToValueAtTime(0.14, start + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.22);

            oscillator.connect(gain);
            gain.connect(audio.destination);

            oscillator.start(start);
            oscillator.stop(start + 0.24);
        });

        setTimeout(() => audio.close().catch(() => {}), 1000);
    } catch (error) {
        console.warn("EduVision: reward sound unavailable", error);
    }
};

const countUp = (target, to, ms = 900) => {
    if (!target) return;

    const start = performance.now();

    const step = now => {
        const t = clamp((now - start) / ms, 0, 1);
        target.textContent = Math.round(to * (1 - Math.pow(1 - t, 3)));
        if (t < 1) requestAnimationFrame(step);
    };

    requestAnimationFrame(step);
};

const ensureRewardStyle = () => {
    if (document.getElementById("eduRewardStyle")) return;

    const style = el("style");
    style.id = "eduRewardStyle";

    style.textContent = `
        .edu-reward-overlay{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(31,42,68,.55);backdrop-filter:blur(4px)}
        .edu-reward-card{position:relative;width:min(400px,100%);max-height:94vh;overflow:auto;padding:26px 22px;border-radius:22px;text-align:center;color:#1f2a44;background:#fff;box-shadow:0 20px 50px rgba(31,42,68,.3);animation:eduRewardPop .35s ease-out}
        .edu-reward-confetti{font-size:26px;margin-bottom:6px}
        .edu-reward-trophy{font-size:62px;margin:6px 0}
        .edu-reward-card h2{margin:8px 0;font-size:26px}
        .edu-reward-message{color:#6b7794;line-height:1.5;margin:0}
        .edu-reward-stats{display:flex;justify-content:center;gap:18px;margin:12px 0 0;color:#4338ca;font-weight:800}
        .edu-reward-earned{margin:18px 0;padding:14px;border-radius:16px;background:#fff6dd}
        .edu-reward-earned span,.edu-reward-balance span{display:block;font-size:13px;color:#6b7794}
        .edu-reward-earned strong{display:block;margin-top:4px;color:#e8920a;font-size:36px}
        .edu-reward-balance{margin:12px 0 18px}
        .edu-reward-balance strong{display:inline-block;margin:6px;color:#22b573;font-size:28px}
        #eduRewardContinue{width:100%;padding:14px;border:0;border-bottom:4px solid #178a57;border-radius:12px;background:#22b573;color:#fff;font-size:16px;font-weight:700;cursor:pointer}
        #eduRewardContinue:hover{filter:brightness(1.08)}
        #eduRewardBack{width:100%;margin-top:10px;padding:12px;border:0;border-radius:12px;background:#eef2ff;color:#4338ca;font-size:15px;font-weight:700;cursor:pointer}
        @keyframes eduRewardPop{from{opacity:0;transform:scale(.88) translateY(12px)}to{opacity:1;transform:none}}
        .edu-daily{margin:0 0 14px;padding:12px;border-radius:16px;background:#f5f3ff;color:#4338ca;text-align:center}
        .edu-daily span{display:block;margin-bottom:8px;font-size:14px;font-weight:700}
        .edu-daily small{display:block;margin-top:8px;color:#6b7794;font-weight:700}
        .edu-limit-box{margin:14px 0;padding:14px;border-radius:16px;background:#fee2e2;color:#991b1b}
        .edu-limit-box p{margin:6px 0;font-size:.9rem}
        .edu-limit-x{font-size:44px;font-weight:900;line-height:1;color:#dc2626}
        .edu-marks{display:flex;justify-content:center;gap:4px;flex-wrap:wrap;margin-top:8px}
        .edu-mark{width:22px;height:22px;display:grid;place-items:center;border-radius:6px;background:#fff;color:#fca5a5;font-size:.8rem}
        .edu-mark.on{background:#dc2626;color:#fff}
    `;

    document.head.append(style);
};

const showRewardPopup = ({ level, earned, balance, duplicate = false, time = "", moves = 0, blocked = false, capped = false }) => {
    ensureRewardStyle();
    ensureFailStyle();   // for the shared red X close button style

    document.getElementById("eduRewardPopup")?.remove();

    const overlay = el("div", "edu-reward-overlay");
    overlay.id = "eduRewardPopup";

    const used = Math.min(DailyLimit.used(), DailyLimit.limit);
    const marks = Array.from({ length: DailyLimit.limit }, (_, i) =>
        i < used
            ? `<b class="edu-mark on${i === used - 1 && !blocked ? " stamp" : ""}">✕</b>`
            : '<b class="edu-mark">·</b>').join("");

    // every finished round gets one red cut mark, so the player can see how much was played today
    const left = DailyLimit.remaining();
    const dailyBlock = (blocked || capped) ? "" : `
        <div class="edu-daily">
            <span>Rounds played today: <b>${used} / ${DailyLimit.limit}</b></span>
            <div class="edu-marks">${marks}</div>
            <small>${left} round${left === 1 ? "" : "s"} left today</small>
        </div>`;

    const limitBox = (blocked || capped) ? `
        <div class="edu-limit-box">
            <div class="edu-limit-x">✕</div>
            <strong>Enough playing for today!</strong>
            <p>You have used all ${DailyLimit.limit} game rounds. Time to learn something new 📚</p>
            <div class="edu-marks">${marks}</div>
        </div>` : "";

    const rewardBlock = blocked ? "" : `
        <div class="edu-reward-stats"><span>⏱ Time used: ${time}</span><span>👣 ${moves}</span></div>
        <div class="edu-reward-earned">
            <span>Credits ${duplicate ? "already claimed" : "earned"}</span>
            <strong id="eduRewardEarned">${duplicate ? 0 : earned}</strong>
        </div>
        <div class="edu-reward-balance">
            <span>Your total balance</span>
            <strong id="eduRewardBalance">${balance}</strong>
            <span>⭐ Credits</span>
        </div>`;

    overlay.innerHTML = `
        <div class="edu-reward-card" role="dialog" aria-modal="true">
            <button type="button" class="edu-x-close" id="eduRewardClose" aria-label="Close and go back to dashboard" title="Close">✕</button>
            <div class="edu-reward-confetti">${blocked ? "✕ ✕ ✕" : "🎉 ✨ 🎊"}</div>
            <div class="edu-reward-trophy">${blocked ? "🛑" : "🏆"}</div>
            <h2>${blocked ? "Daily limit reached" : `Level ${level} Completed!`}</h2>
            <p class="edu-reward-message">
                ${blocked
                    ? "No credits this round. Come back tomorrow!"
                    : duplicate
                        ? "You have already received the reward for this level."
                        : "Amazing work! Keep learning and playing."}
            </p>
            ${rewardBlock}
            ${dailyBlock}
            ${limitBox}
            <button type="button" id="eduRewardContinue">
                ${(blocked || capped) ? "OK" : `Continue to Level ${level + 1} →`}
            </button>
        </div>
    `;

    document.body.append(overlay);

    if (!blocked) {
        if (!duplicate) countUp(document.getElementById("eduRewardEarned"), earned);
        countUp(document.getElementById("eduRewardBalance"), balance);
    }

    // stay on the same game page (reload shows the next level, or the daily-limit screen)
    const stayHere = () => {
        overlay.remove();
        window.location.reload();
    };

    document.getElementById("eduRewardContinue").addEventListener("click", stayHere);

    // red X in the corner: close the popup and stay on the same page
    document.getElementById("eduRewardClose").addEventListener("click", stayHere);
};

const completeLevelAndAwardCredits = async (completedLevel, finalScore) => {
    if (over) return;

    over = true;
    winPending = true;

    const mySession = session;
    const stillHere = () => session === mySession;

    // daily limit already used up: no credits, show the X screen
    if (DailyLimit.reached()) {
        showRewardPopup({ level: completedLevel, earned: 0, balance: 0, blocked: true });
        return;
    }

    const finalTime = fmtTime(elapsedSec);
    const finalMoves = hudMovesEl ? hudMovesEl.textContent : String(moveCount);

    const status = makeStatus("⏳ Checking your level and saving credits...");

    try {
        const response = await fetch("/api/game-level/complete", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            },
            body: JSON.stringify({
                game_key: Levels.gameId,
                level: completedLevel,
                score: finalScore
            })
        });

        let result = {};

        try {
            result = await response.json();
        } catch (error) {
            throw new Error(
                response.redirected || response.status === 401
                    ? "Your session expired. Please log in again."
                    : `Server returned an invalid response (${response.status}).`
            );
        }

        console.log("Reward API status:", response.status, result);

        // server says the daily limit is used up
        if (response.status === 429 || result.limit_reached) {
            if (Number.isFinite(Number(result.daily_used))) {
                DailyLimit.set(Number(result.daily_used), Number(result.daily_limit));
            } else {
                DailyLimit.fill();
            }

            refreshDailyStrip();

            if (stillHere()) {
                showRewardPopup({ level: completedLevel, earned: 0, balance: 0, blocked: true });
            }

            return;
        }

        if (!response.ok || !result.success) {
            throw new Error(
                result.message || result.error ||
                `Could not save reward (${response.status}).`
            );
        }

        const earned = Math.max(0, Number(result.earned) || 0);
        const balance = Math.max(0, Number(result.balance) || 0);

        showCredits(balance);

        // keep the local counter in step with the server
        if (Number.isFinite(Number(result.daily_used))) {
            DailyLimit.set(Number(result.daily_used), Number(result.daily_limit));
        } else if (!result.duplicate) {
            DailyLimit.record();
        }

        refreshDailyStrip();

        Levels.complete(true, finalScore);

        if (earned > 0 && !result.duplicate) {
            window.dispatchEvent(
                new CustomEvent("eduvision:credits-earned", {
                    detail: {
                        gameKey: Levels.gameId,
                        level: completedLevel,
                        earned,
                        balance
                    }
                })
            );
        }

        if (!stillHere()) return;

        if (earned > 0 && !result.duplicate) playCreditRewardSound();

        status(
            `🎉 Level ${completedLevel} completed! ` +
            (result.duplicate ? "Reward already claimed." : `+${earned} credits!`),
            "win"
        );

        showRewardPopup({
            level: completedLevel,
            earned,
            balance,
            duplicate: Boolean(result.duplicate),
            capped: DailyLimit.reached(),
            time: finalTime,
            moves: finalMoves
        });
    } catch (error) {
        console.error("EduVision reward error:", error);

        if (!stillHere()) return;

        over = false;

        status("⚠️ Reward could not be saved: " + error.message, "lose");

        const retry = makeButton("Retry Saving Reward", () => {
            retry.remove();
            completeLevelAndAwardCredits(completedLevel, finalScore);
        });

        area.append(retry);
    }
};

/* ---------- win / lose ---------- */
const finishWin = finalScore => {
    if (over) return;

    winPending = true;
    completeLevelAndAwardCredits(currentLevel(), Math.max(0, Number(finalScore) || 0));
};

/* LEVEL FAILED: a big red X popup appears in the middle of the screen.
   The player chooses "Try Again" (same level) or "Back to Dashboard"
   (or the small red X in the corner, which also goes back).
   The next level is NOT opened. No scrolling needed. */
function finishLose(message = "Game over! Try again.", title = "Level Failed") {
    if (over) return;

    over = true;

    ensureFailStyle();
    document.getElementById("eduFailPopup")?.remove();

    const overlay = el("div", "edu-fail-overlay");
    overlay.id = "eduFailPopup";

    overlay.innerHTML = `
        <div class="edu-fail-card" role="alertdialog" aria-modal="true">
            <button type="button" class="edu-x-close" aria-label="Close and go back to dashboard" title="Close">✕</button>
            <div class="edu-fail-x">✕</div>
            <h2></h2>
            <div class="edu-fail-level"></div>
            <p></p>
            <div class="edu-fail-actions"></div>
        </div>`;

    overlay.querySelector("h2").textContent = title;
    overlay.querySelector(".edu-fail-level").textContent = `Level ${currentLevel()} not completed`;
    overlay.querySelector("p").textContent = message;

    const actions = overlay.querySelector(".edu-fail-actions");

    const retry = el("button", "edu-fail-retry");
    retry.type = "button";
    retry.textContent = "🔄 Try Again";
    retry.addEventListener("click", () => {
        overlay.remove();
        restartLevel();
    });

    // red X in the corner: close the popup and stay on the same page (same level restarts)
    overlay.querySelector(".edu-x-close").addEventListener("click", () => {
        overlay.remove();
        restartLevel();
    });

    actions.append(retry);
    document.body.append(overlay);

    try { retry.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
}

const winLater = (finalScore, ms = 700) => {
    winPending = true;   // stop the clock, the level is already won
    return later(ms, () => finishWin(finalScore));
};

const loseLater = (message, ms = 600) => later(ms, () => finishLose(message));

/* =========================================================
   GAME 1: ARROW ESCAPE  (key: arrow_maze)
   Style of arrowsgames.io: the board is full of arrows (snake lines
   with an arrow head). Tap an arrow to slide it out of the board.

   RULES (all perfect now)
   - The arrow head ALWAYS points the same way the arrow slides out
     (head direction = direction of the last body segment).
   - If another arrow is in its way, it is BLOCKED: red alert, red
     arrow, and you lose a heart.
   - Arrows are placed one by one and every arrow has a free line to
     the border from every arrow placed BEFORE it, so removing them in
     reverse order always clears the board. Every level is solvable.
   ========================================================= */

function gameArrowMaze() {
    resetGame();

    addHeading("🏹 Arrow Escape", "Tap an arrow to slide it out of the board.");

    const level = currentLevel();
    const N = Math.min(5 + Math.floor((level - 1) / 2), 12);          // board size
    const maxLen = Math.min(3 + Math.floor(level / 3), 8);            // longest arrow
    const cell = clamp(Math.floor(640 / N), 40, 96);
    const W = N * cell;
    const MAX_HEARTS = 3;
    const DIRS = [[0, -1], [1, 0], [0, 1], [-1, 0]];

    const heartsBox = el("div", "ev-hearts");
    area.append(heartsBox);

    const [canvas, ctx] = cv(area, W, W, 700);
    const status = makeStatus("Tap an arrow with a clear path. A blocked arrow costs a heart!");
    const fx = makeFX();

    const inside = (x, y) => x >= 0 && y >= 0 && x < N && y < N;

    let owner = [];
    let arrows = [];

    // The ray from the head to the border must not touch arrows that were placed
    // earlier (and not the arrow's own body). Arrows are removed in the reverse
    // order of placement, so the board can always be cleared.
    function rayFree(x, y, d, own) {
        let cx = x + d[0];
        let cy = y + d[1];

        while (inside(cx, cy)) {
            if (owner[cy][cx] !== -1 || own.has(cx + "," + cy)) return false;
            cx += d[0];
            cy += d[1];
        }

        return true;
    }

    function makeArrow(sx, sy) {
        for (let attempt = 0; attempt < 10; attempt++) {
            const len = 2 + rnd(maxLen - 1);
            const path = [{ x: sx, y: sy }];
            const used = new Set([sx + "," + sy]);
            let cx = sx;
            let cy = sy;

            while (path.length < len) {
                const options = shuffle(DIRS).filter(([dx, dy]) => {
                    const nx = cx + dx;
                    const ny = cy + dy;
                    return inside(nx, ny) && owner[ny][nx] === -1 && !used.has(nx + "," + ny);
                });

                if (!options.length) break;

                cx += options[0][0];
                cy += options[0][1];
                path.push({ x: cx, y: cy });
                used.add(cx + "," + cy);
            }

            if (path.length < 2) continue;

            const head = path[path.length - 1];
            const prev = path[path.length - 2];

            // The head points the SAME way as the last body segment, so what you see
            // is exactly how the arrow will slide out.
            const dir = [head.x - prev.x, head.y - prev.y];

            if (!rayFree(head.x, head.y, dir, used)) continue;

            return {
                cells: path,
                dir,
                state: "idle",
                flash: 0,
                s: 0
            };
        }

        return null;
    }

    function generate() {
        owner = Array.from({ length: N }, () => Array(N).fill(-1));
        arrows = [];

        const spots = shuffle(Array.from({ length: N * N }, (_, i) => i));

        for (let pass = 0; pass < 3; pass++) {
            for (const i of spots) {
                const sx = i % N;
                const sy = Math.floor(i / N);

                if (owner[sy][sx] !== -1) continue;

                const a = makeArrow(sx, sy);
                if (!a) continue;

                a.id = arrows.length;
                a.cells.forEach(c => { owner[c.y][c.x] = a.id; });
                arrows.push(a);
            }
        }
    }

    const wanted = Math.min(4 + level, Math.floor(N * N / 4));

    for (let tries = 0; tries < 40; tries++) {
        generate();
        if (arrows.length >= wanted) break;
    }

    let remaining = arrows.length;
    let hearts = MAX_HEARTS;
    let dead = false, won = false, t = 0;
    let hintId = -1, hintUntil = 0;

    const drawHearts = () => {
        heartsBox.innerHTML =
            `<span>${"❤️".repeat(hearts)}${"🖤".repeat(MAX_HEARTS - hearts)}</span>` +
            `<span>🏹 ${remaining} left</span>`;
    };

    drawHearts();

    // first arrow in the way of this arrow (null = the way is clear)
    function blockerOf(a) {
        const head = a.cells[a.cells.length - 1];
        let cx = head.x + a.dir[0];
        let cy = head.y + a.dir[1];

        while (inside(cx, cy)) {
            if (owner[cy][cx] !== -1) return arrows[owner[cy][cx]];
            cx += a.dir[0];
            cy += a.dir[1];
        }

        return null;
    }

    // path of the arrow when it slides out (cell centres, then off the board)
    function buildExit(a) {
        const pts = a.cells.map(c => [(c.x + 0.5) * cell, (c.y + 0.5) * cell]);
        const head = a.cells[a.cells.length - 1];
        let cx = head.x;
        let cy = head.y;
        let beyond = 0;

        do {
            cx += a.dir[0];
            cy += a.dir[1];
            pts.push([(cx + 0.5) * cell, (cy + 0.5) * cell]);
            if (!inside(cx, cy)) beyond++;
        } while (beyond < a.cells.length + 2);

        const cum = [0];
        for (let i = 1; i < pts.length; i++) {
            cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
        }

        a.pts = pts;
        a.cum = cum;
        a.total = cum[cum.length - 1];
        a.bodyLen = (a.cells.length - 1) * cell;
        a.s = 0;
    }

    function pointAt(a, d) {
        d = clamp(d, 0, a.total);

        for (let i = 1; i < a.cum.length; i++) {
            if (d <= a.cum[i]) {
                const k = (d - a.cum[i - 1]) / ((a.cum[i] - a.cum[i - 1]) || 1);
                return [lerp(a.pts[i - 1][0], a.pts[i][0], k), lerp(a.pts[i - 1][1], a.pts[i][1], k)];
            }
        }

        return a.pts[a.pts.length - 1];
    }

    function slice(a, from, to) {
        const out = [pointAt(a, from)];

        for (let i = 0; i < a.pts.length; i++) {
            if (a.cum[i] > from && a.cum[i] < to) out.push(a.pts[i]);
        }

        out.push(pointAt(a, to));
        return out;
    }

    function tap(a) {
        if (over || dead || won || !a || a.state !== "idle") return;

        addMove();

        const blocker = blockerOf(a);

        if (blocker) {
            a.flash = 1;
            blocker.flash = 0.7;
            hearts--;
            drawHearts();
            shake(canvas);
            wrongAlert("Wrong way! This arrow is blocked");
            status("❌ Blocked! Free the other arrow first.", "lose");

            if (hearts <= 0) {
                dead = true;
                loseLater("You ran out of hearts. Think before you tap!", 800);
            }

            return;
        }

        a.cells.forEach(c => { owner[c.y][c.x] = -1; });
        buildExit(a);
        a.state = "leaving";
        remaining--;
        drawHearts();
        addScore(100);

        const head = a.cells[a.cells.length - 1];
        fx.burst((head.x + 0.5) * cell, (head.y + 0.5) * cell, "#22c55e", 8, 3);

        if (remaining <= 0) {
            won = true;
            status("🎉 Board cleared! Saving your reward...", "win");
            setScore(score + hearts * 100);
            winLater(score, 1100);
        } else {
            status(`✅ Out! ${remaining} arrow${remaining === 1 ? "" : "s"} left.`);
        }
    }

    on(canvas, "pointerdown", e => {
        e.preventDefault();
        if (over || dead || won) return;

        const rect = canvas.getBoundingClientRect();
        const x = Math.floor(((e.clientX - rect.left) / rect.width) * N);
        const y = Math.floor(((e.clientY - rect.top) / rect.height) * N);

        if (!inside(x, y) || owner[y][x] === -1) return;

        tap(arrows[owner[y][x]]);
    });

    // HINT: glow a free arrow (the one that unblocks the most other arrows)
    onHint(() => {
        if (over || dead || won) return false;

        const free = arrows.filter(a => a.state === "idle" && !blockerOf(a));
        if (!free.length) return false;

        const score2 = a => arrows.filter(b => b.state === "idle" && blockerOf(b) === a).length;
        free.sort((a, b) => score2(b) - score2(a));

        hintId = free[0].id;
        hintUntil = t + 200;

        infoAlert("Tap the green arrow");
        status("💡 The green arrow can leave now.");
        return true;
    });

    function drawArrow(a) {
        if (a.state === "gone") return;

        const poly = a.state === "leaving"
            ? slice(a, a.s, a.s + a.bodyLen)
            : a.cells.map(c => [(c.x + 0.5) * cell, (c.y + 0.5) * cell]);

        const hinted = a.id === hintId && t < hintUntil;
        const color = a.flash > 0 ? "#dc2626" : hinted ? "#16a34a" : "#1f2937";
        const shakeX = a.flash > 0 ? Math.sin(t * 1.6) * 4 * a.flash : 0;

        ctx.save();
        ctx.translate(shakeX, 0);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";

        const path = () => {
            ctx.beginPath();
            poly.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
        };

        if (hinted) {
            ctx.strokeStyle = `rgba(34,197,94,${0.25 + (0.5 + Math.sin(t * 0.3) * 0.5) * 0.3})`;
            ctx.lineWidth = cell * 0.5;
            path();
            ctx.stroke();
        }

        ctx.strokeStyle = color;
        ctx.lineWidth = cell * 0.17;
        path();
        ctx.stroke();

        const [hx, hy] = poly[poly.length - 1];

        // arrow head: points exactly along a.dir (same way the arrow leaves)
        ctx.fillStyle = color;
        ctx.translate(hx, hy);
        ctx.rotate(Math.atan2(a.dir[1], a.dir[0]));
        ctx.beginPath();
        ctx.moveTo(cell * 0.36, 0);
        ctx.lineTo(-cell * 0.04, -cell * 0.22);
        ctx.lineTo(-cell * 0.04, cell * 0.22);
        ctx.closePath();
        ctx.fill();

        ctx.restore();
    }

    function draw() {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, W, W);

        ctx.fillStyle = "#e5e7eb";
        for (let y = 0; y < N; y++) {
            for (let x = 0; x < N; x++) {
                ctx.beginPath();
                ctx.arc((x + 0.5) * cell, (y + 0.5) * cell, 2.5, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        arrows.filter(a => a.state === "idle").forEach(drawArrow);
        arrows.filter(a => a.state === "leaving").forEach(drawArrow);

        fx.draw(ctx);
    }

    loop(dt => {
        t += dt;

        arrows.forEach(a => {
            if (a.flash > 0) a.flash = Math.max(0, a.flash - 0.035 * dt);

            if (a.state === "leaving") {
                a.s += cell * 0.55 * dt;
                if (a.s >= a.total - a.bodyLen) a.state = "gone";
            }
        });

        fx.update(dt);
        draw();
    });

    draw();
}

/* =========================================================
   GAME 2: HOLOGRAM MEMORY
   ========================================================= */

function gameHologramMemory() {
    resetGame();

    addHeading("🧠 Hologram Memory Challenge", "Memorize the glowing sequence and repeat it.");

    const level = currentLevel();
    const mySession = session;
    const sequenceLength = Math.min(3 + level, 12);
    const symbols = ["◆", "●", "▲", "■", "★", "⬟"];

    const board = el("div", "ev-board holo-board");
    area.append(board);

    const status = makeStatus("Watch the sequence carefully.");
    const cells = [];

    for (let i = 0; i < 9; i++) {
        const button = makeButton(symbols[i % symbols.length], () => choose(i), "holo-cell");

        button.style.animationDelay = `${i * 50}ms`;
        button.disabled = true;

        board.append(button);
        cells.push(button);
    }

    const sequence = Array.from({ length: sequenceLength }, () => rnd(9));

    let position = 0;
    let accepting = false;

    const stale = () => over || session !== mySession;

    async function showSequence() {
        accepting = false;
        cells.forEach(button => { button.disabled = true; });
        status("Memorize the glowing tiles...");

        await wait(700);

        for (const index of sequence) {
            if (stale()) return;

            cells[index].classList.add("lit");
            await wait(Math.max(260, 520 - level * 12));
            if (stale()) return;

            cells[index].classList.remove("lit");
            await wait(Math.max(120, 300 - level * 10));
        }

        if (stale()) return;

        accepting = true;
        cells.forEach(button => { button.disabled = false; });
        status("Now repeat the sequence!");
    }

    function choose(index) {
        if (!accepting || over) return;

        addMove();

        if (index !== sequence[position]) {
            accepting = false;
            cells[index].classList.add("bad");
            wrongAlert("Wrong tile!");
            status("Wrong tile!", "lose");
            loseLater("Wrong tile! Memory challenge failed. Try again.", 600);
            return;
        }

        cells[index].classList.add("good");
        later(260, () => cells[index].classList.remove("good"));

        position++;
        setScore(position * 100);

        if (position >= sequence.length) {
            accepting = false;

            const finalScore = sequenceLength * 100;

            setScore(finalScore);
            status("Excellent memory! Saving your reward...", "win");
            cells.forEach((c, i) => later(i * 70, () => c.classList.add("good")));
            winLater(finalScore, 800);
        }
    }

    // HINT: show the glowing sequence again
    let replaying = false;

    onHint(() => {
        if (!accepting || replaying || over) return false;

        replaying = true;
        position = 0;
        setScore(0);
        showSequence().then(() => { replaying = false; });

        return true;
    });

    showSequence();
}

/* =========================================================
   GAME 3: CANDY CRUSH
   ========================================================= */

function gameCandyMatch() {
    resetGame();
    ensureCandyStyle();

    addHeading("🍬 Candy Match", "Swap or drag neighbouring candies to match 3. Match 4 or 5 to make special candies!");

    const level = currentLevel();
    const mySession = session;
    const R = 8, C = 8, N = R * C, TYPES = 6;
    const target = Math.min(500 + level * 90, 7000);
    let moves = Math.min(20 + Math.floor(level / 2), 40);

    const COLORS = [
        ["#ff9db1", "#e11d48"], ["#ffc46b", "#ea580c"], ["#fff08a", "#eab308"],
        ["#9af5b8", "#16a34a"], ["#8fd8ff", "#0284c7"], ["#dcb8ff", "#7c3aed"]
    ];

    const SHAPES = [
        '<path d="M32 57C10 41 6 27 12 18c6-8 16-6 20 2 4-8 14-10 20-2 6 9 2 23-20 39z"/>',
        '<circle cx="32" cy="32" r="23"/>',
        '<path d="M32 5l8 17.5 19 2-14.3 12.7 4.2 18.8L32 46.6 15.1 56l4.2-18.8L5 24.5l19-2z"/>',
        '<rect x="9" y="9" width="46" height="46" rx="13"/>',
        '<path d="M32 5c10 14 21 23 21 35a21 21 0 0 1-42 0C11 28 22 19 32 5z"/>',
        '<path d="M32 5l23 13v28L32 59 9 46V18z" stroke-linejoin="round"/>'
    ];

    const PRAISE = ["Sweet!", "Tasty!", "Delicious!", "Divine!", "Sugar Crush!"];

    const defs =
        '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>' +
        COLORS.map((c, i) =>
            `<radialGradient id="ccg${i}" cx="35%" cy="28%" r="80%"><stop offset="0" stop-color="${c[0]}"/><stop offset="1" stop-color="${c[1]}"/></radialGradient>`
        ).join("") +
        '<radialGradient id="ccgB" cx="35%" cy="28%" r="80%"><stop offset="0" stop-color="#8b5a3c"/><stop offset="1" stop-color="#3b200f"/></radialGradient>' +
        "</defs></svg>";

    let busy = false;
    let selected = -1;
    let down = null;
    let hintTimer = 0;
    let hinted = [];
    let sound = true;
    let ac = null;

    const stale = () => over || session !== mySession;

    const hud = el("div", "cc-hud",
        `<div class="cc-chip"><small>LEVEL</small><b>${level}</b></div>
         <div class="cc-chip big"><small>GOAL ${target}</small>
            <div class="cc-bar"><i></i><span style="left:40%">★</span><span style="left:70%">★</span><span style="left:100%">★</span></div></div>
         <button class="cc-snd" type="button" aria-label="Sound on or off">🔊</button>`);
    area.append(hud);

    const barFill = hud.querySelector(".cc-bar i");
    const stars = [...hud.querySelectorAll(".cc-bar span")];
    const sndBtn = hud.querySelector(".cc-snd");

    // the shared bar counts the moves that are left
    setMoves(moves, "MOVES LEFT");

    sndBtn.addEventListener("click", () => {
        sound = !sound;
        sndBtn.textContent = sound ? "🔊" : "🔇";
    });

    const wrap = el("div", "cc-wrap");
    const board = el("div", "cc-board");

    board.style.setProperty("--cols", C);
    board.style.setProperty("--rows", R);
    board.innerHTML = defs;
    wrap.append(board);
    area.append(wrap);

    const status = makeStatus("Swap two neighbouring candies to start.");

    const grid = new Array(N).fill(null);

    function blip(freq, dur = 0.09, type = "sine", vol = 0.05) {
        if (!sound) return;

        try {
            ac = ac || new (window.AudioContext || window.webkitAudioContext)();
            if (ac.state === "suspended") ac.resume();
            const o = ac.createOscillator();
            const g = ac.createGain();

            o.type = type;
            o.frequency.value = freq;
            g.gain.setValueAtTime(vol, ac.currentTime);
            g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + dur);
            o.connect(g);
            g.connect(ac.destination);
            o.start();
            o.stop(ac.currentTime + dur);
        } catch (e) { /* sound is optional */ }
    }

    onClean(() => {
        try { if (ac) ac.close(); } catch (e) { /* ignore */ }
    });

    const setPos = (o, r, c) => {
        o.el.style.setProperty("--x", c);
        o.el.style.setProperty("--y", r);
    };

    function svgFor(o) {
        const shine = '<ellipse cx="22" cy="20" rx="8" ry="4.5" fill="#fff" opacity=".7" transform="rotate(-30 22 20)"/>';

        if (o.special === "b") {
            const dots = [[22, 24, 1], [40, 20, 4], [30, 36, 3], [44, 38, 0], [20, 42, 5], [36, 50, 2], [48, 28, 1], [14, 32, 4]]
                .map(d => `<circle cx="${d[0]}" cy="${d[1]}" r="3" fill="${COLORS[d[2]][1]}"/>`).join("");

            return `<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="25" fill="url(#ccgB)" stroke="rgba(0,0,0,.4)" stroke-width="2"/>${dots}${shine}</svg>`;
        }

        let overlay = "";

        if (o.special === "h") {
            overlay = '<path d="M14 24h36M12 33h40M14 42h36" stroke="rgba(255,255,255,.8)" stroke-width="4.5" stroke-linecap="round"/>';
        } else if (o.special === "v") {
            overlay = '<path d="M24 14v36M33 12v40M42 14v36" stroke="rgba(255,255,255,.8)" stroke-width="4.5" stroke-linecap="round"/>';
        } else if (o.special === "w") {
            overlay = '<circle cx="32" cy="32" r="29" fill="none" stroke="#fff" stroke-width="3.5" stroke-dasharray="5 4"/>';
        }

        return `<svg viewBox="0 0 64 64"><g fill="url(#ccg${o.type})" stroke="rgba(0,0,0,.3)" stroke-width="2.2">${SHAPES[o.type]}</g>${overlay}${shine}</svg>`;
    }

    function render(o) {
        o.el.className = "cc-candy" + (o.special ? " sp-" + o.special : "");
        o.el.innerHTML = svgFor(o);
    }

    function makeCandy(type, special, r, c) {
        const o = { type, special, r, c, el: el("div", "cc-candy") };

        render(o);
        setPos(o, r, c);
        board.append(o.el);

        return o;
    }

    const idxOf = o => grid.indexOf(o);

    const same = (i, j) => grid[i] && grid[j] && grid[i].type >= 0 && grid[i].type === grid[j].type;

    function runs() {
        const out = [];

        for (let r = 0; r < R; r++) {
            let s = 0;

            for (let c = 1; c <= C; c++) {
                if (c < C && same(r * C + c, r * C + s)) continue;

                if (c - s >= 3) {
                    out.push({ dir: "h", cells: Array.from({ length: c - s }, (_, k) => r * C + s + k) });
                }

                s = c;
            }
        }

        for (let c = 0; c < C; c++) {
            let s = 0;

            for (let r = 1; r <= R; r++) {
                if (r < R && same(r * C + c, s * C + c)) continue;

                if (r - s >= 3) {
                    out.push({ dir: "v", cells: Array.from({ length: r - s }, (_, k) => (s + k) * C + c) });
                }

                s = r;
            }
        }

        return out;
    }

    function analyze(prefer) {
        const rs = runs();
        const matched = new Set();
        const make = new Map();
        const byCell = new Map();

        rs.forEach(run => run.cells.forEach(i => {
            matched.add(i);
            if (!byCell.has(i)) byCell.set(i, []);
            byCell.get(i).push(run);
        }));

        const spot = run => {
            const free = run.cells.filter(i => !grid[i].special && !make.has(i));
            if (!free.length) return -1;

            for (const p of prefer || []) if (free.includes(p)) return p;

            return free[Math.floor(free.length / 2)];
        };

        rs.forEach(run => {
            if (run.cells.length >= 5) {
                const i = spot(run);
                if (i >= 0) make.set(i, { special: "b" });
            }
        });

        byCell.forEach((list, i) => {
            if (!make.has(i) && !grid[i].special &&
                list.some(x => x.dir === "h") && list.some(x => x.dir === "v")) {
                make.set(i, { special: "w" });
            }
        });

        rs.forEach(run => {
            if (run.cells.length === 4 && !run.cells.some(i => make.has(i))) {
                const i = spot(run);
                if (i >= 0) make.set(i, { special: run.dir === "h" ? "v" : "h" });
            }
        });

        return { matched, make };
    }

    function expand(start, keep) {
        const out = new Set(start);
        const queue = [...start];
        const fired = new Set();
        const beams = [];

        while (queue.length) {
            const i = queue.pop();
            const o = grid[i];

            if (!o || !o.special || fired.has(i)) continue;
            fired.add(i);

            const r = Math.floor(i / C);
            const c = i % C;
            const add = [];

            if (o.special === "h") {
                beams.push({ k: "h", r, c });
                for (let k = 0; k < C; k++) add.push(r * C + k);
            } else if (o.special === "v") {
                beams.push({ k: "v", r, c });
                for (let k = 0; k < R; k++) add.push(k * C + c);
            } else if (o.special === "w") {
                beams.push({ k: "w", r, c });

                for (let dr = -1; dr <= 1; dr++) {
                    for (let dc = -1; dc <= 1; dc++) {
                        const r2 = r + dr;
                        const c2 = c + dc;
                        if (r2 >= 0 && r2 < R && c2 >= 0 && c2 < C) add.push(r2 * C + c2);
                    }
                }
            } else if (o.special === "b") {
                beams.push({ k: "b", r, c });

                let t = o.target;

                if (t === undefined) {
                    const present = grid.filter(x => x && x.type >= 0);
                    t = present.length ? pick(present).type : "all";
                }

                for (let k = 0; k < N; k++) {
                    if (grid[k] && (t === "all" || grid[k].type === t)) add.push(k);
                }
            }

            add.forEach(j => {
                if (!out.has(j)) {
                    out.add(j);
                    queue.push(j);
                }
            });
        }

        keep.forEach(i => out.delete(i));

        return { out, beams };
    }

    const swapData = (a, b) => { [grid[a], grid[b]] = [grid[b], grid[a]]; };

    function findMove() {
        for (let r = 0; r < R; r++) {
            for (let c = 0; c < C; c++) {
                const a = r * C + c;
                const nbrs = [];

                if (c < C - 1) nbrs.push(a + 1);
                if (r < R - 1) nbrs.push(a + C);

                for (const b of nbrs) {
                    if (grid[a].special === "b" || grid[b].special === "b" ||
                        (grid[a].special && grid[b].special)) return [a, b];

                    swapData(a, b);
                    const ok = analyze().matched.size > 0;
                    swapData(a, b);

                    if (ok) return [a, b];
                }
            }
        }

        return null;
    }

    function sparks(i, type, n = 5) {
        const r = Math.floor(i / C);
        const c = i % C;
        const color = type >= 0 ? COLORS[type][1] : "#f0abfc";

        for (let k = 0; k < n; k++) {
            const a = Math.random() * Math.PI * 2;
            const s = el("i", "cc-spark");

            s.style.left = `${((c + 0.5) / C) * 100}%`;
            s.style.top = `${((r + 0.5) / R) * 100}%`;
            s.style.background = color;
            s.style.setProperty("--dx", `${Math.cos(a) * 50}px`);
            s.style.setProperty("--dy", `${Math.sin(a) * 50}px`);

            board.append(s);
            later(650, () => s.remove());
        }
    }

    function floatText(r, c, text) {
        const f = el("span", "cc-float", text);

        f.style.left = `${((c + 0.5) / C) * 100}%`;
        f.style.top = `${((r + 0.5) / R) * 100}%`;

        board.append(f);
        later(1000, () => f.remove());
    }

    function banner(text) {
        const b = el("div", "cc-praise", text);

        board.append(b);
        later(1000, () => b.remove());
    }

    function showBeam(b) {
        let e;

        if (b.k === "h") {
            e = el("div", "cc-beam h");
            e.style.top = `calc(${b.r} * var(--cell))`;
        } else if (b.k === "v") {
            e = el("div", "cc-beam v");
            e.style.left = `calc(${b.c} * var(--cell))`;
        } else if (b.k === "w") {
            e = el("div", "cc-ring");
            e.style.left = `calc(${b.c + 0.5} * var(--cell))`;
            e.style.top = `calc(${b.r + 0.5} * var(--cell))`;
        } else {
            e = el("div", "cc-flash");
        }

        board.append(e);
        later(700, () => e.remove());
    }

    function updateHud() {
        setMoves(moves, "MOVES LEFT");
    }

    function gain(points) {
        addScore(points);

        const p = clamp(score / target, 0, 1);

        barFill.style.width = `${p * 100}%`;
        stars.forEach((s, k) => s.classList.toggle("on", p >= [0.4, 0.7, 1][k]));
    }

    function clearHint() {
        hinted.forEach(o => o && o.el.classList.remove("hint"));
        hinted = [];
    }

    function scheduleHint() {
        clearTimeout(hintTimer);

        hintTimer = later(6000, () => {
            if (busy || stale()) return;

            const m = findMove();
            if (!m) return;

            hinted = [grid[m[0]], grid[m[1]]];
            hinted.forEach(o => o.el.classList.add("hint"));
        });
    }

    function gravity() {
        for (let c = 0; c < C; c++) {
            let write = R - 1;

            for (let r = R - 1; r >= 0; r--) {
                const o = grid[r * C + c];
                if (!o) continue;

                if (r !== write) {
                    grid[write * C + c] = o;
                    grid[r * C + c] = null;
                    o.r = write;
                    setPos(o, write, c);
                }

                write--;
            }

            const fresh = write + 1;

            for (let r = write; r >= 0; r--) {
                const o = makeCandy(rnd(TYPES), null, r - fresh, c);

                grid[r * C + c] = o;
                void o.el.offsetWidth;
                o.r = r;
                setPos(o, r, c);
            }
        }
    }

    async function resolve(forced, prefer) {
        let cascade = 0;
        let first = true;

        while (true) {
            const an = analyze(prefer);
            const matched = new Set(an.matched);

            if (first && forced) forced.forEach(i => matched.add(i));

            first = false;
            prefer = null;

            if (!matched.size) break;

            cascade++;

            const { out, beams } = expand(matched, new Set(an.make.keys()));

            beams.forEach(showBeam);

            let pts = 0;
            const many = out.size > 14;

            out.forEach(i => {
                const o = grid[i];
                if (!o) return;

                o.el.classList.add("pop");
                sparks(i, o.type, many ? 2 : 5);
                pts += 60;
            });

            const gained = Math.round(pts * (1 + (cascade - 1) * 0.5)) + beams.length * 150;

            gain(gained);

            const mid = [...out][Math.floor(out.size / 2)];

            floatText(Math.floor(mid / C), mid % C, `+${gained}`);

            if (cascade >= 2) banner(PRAISE[Math.min(cascade - 2, PRAISE.length - 1)]);
            else if (out.size >= 6) banner(PRAISE[0]);

            an.make.forEach((m, i) => {
                const o = grid[i];
                if (!o) return;

                if (m.special === "b") {
                    o.type = -1;
                    o.special = "b";
                } else {
                    o.special = m.special;
                }

                render(o);
                o.el.classList.add("born");
            });

            blip(520 + cascade * 90, 0.12, "triangle");

            await wait(300);
            if (stale()) return false;

            out.forEach(i => {
                if (grid[i]) {
                    grid[i].el.remove();
                    grid[i] = null;
                }
            });

            gravity();

            await wait(480);
            if (stale()) return false;
        }

        return true;
    }

    function reshuffle() {
        const objs = grid.filter(Boolean);
        let tries = 0;

        do {
            const list = shuffle(objs);

            list.forEach((o, i) => {
                grid[i] = o;
                o.r = Math.floor(i / C);
                o.c = i % C;
                setPos(o, o.r, o.c);
            });

            tries++;
        } while ((runs().length || !findMove()) && tries < 40);
    }

    async function afterMove() {
        if (score >= target) {
            winPending = true;   // goal reached: stop the clock
            status("🎉 Sugar Crush! Bonus points for the moves you have left...", "win");
            banner("Sugar Crush!");

            while (moves > 0) {
                moves--;
                updateHud();
                gain(100);
                sparks(rnd(N), rnd(TYPES), 4);
                blip(700 + (40 - moves) * 12, 0.07, "square", 0.03);

                await wait(130);
                if (stale()) return true;
            }

            await wait(500);

            if (!stale()) finishWin(score);

            return true;
        }

        if (moves <= 0) {
            status(`Out of moves! ${score} of ${target} points.`, "lose");
            shake(board);
            loseLater(`Out of moves! You scored ${score} but needed ${target}.`, 900);

            return true;
        }

        if (!findMove()) {
            status("No more moves, shuffling the candies!");
            await wait(500);
            if (stale()) return true;

            reshuffle();

            await wait(500);
            if (stale()) return true;
        }

        status(`${moves} moves left. Reach ${target} points!`);

        return false;
    }

    function swapGrid(a, b) {
        swapData(a, b);

        const A = grid[a];
        const B = grid[b];

        A.r = Math.floor(a / C); A.c = a % C; setPos(A, A.r, A.c);
        B.r = Math.floor(b / C); B.c = b % C; setPos(B, B.r, B.c);
    }

    async function trySwap(a, b) {
        if (busy || stale()) return;

        busy = true;
        clearHint();

        const A = grid[a];
        const B = grid[b];

        swapGrid(a, b);
        blip(330, 0.07);

        await wait(280);
        if (stale()) return;

        let forced = null;

        if (A.special === "b" || B.special === "b") {
            forced = new Set();

            const bombs = [A, B].filter(o => o.special === "b");

            if (bombs.length === 2) {
                bombs.forEach(o => { o.target = "all"; });
            } else {
                const bomb = bombs[0];
                const other = bomb === A ? B : A;

                bomb.target = other.type >= 0 ? other.type : "all";
                if (other.special) forced.add(idxOf(other));
            }

            bombs.forEach(o => forced.add(idxOf(o)));
        } else if (A.special && B.special) {
            forced = new Set([idxOf(A), idxOf(B)]);
        }

        if (!forced && analyze([a, b]).matched.size === 0) {
            swapGrid(a, b);
            blip(180, 0.12, "sawtooth", 0.03);
            wrongAlert("No match there!");

            board.classList.remove("nope");
            void board.offsetWidth;
            board.classList.add("nope");

            await wait(280);
            if (stale()) return;

            busy = false;
            scheduleHint();
            return;
        }

        moves--;
        updateHud();

        const ok = await resolve(forced, [a, b]);
        if (ok === false) return;

        const ended = await afterMove();
        if (ended || stale()) return;

        busy = false;
        scheduleHint();
    }

    function setSel(i) {
        if (selected >= 0 && grid[selected]) grid[selected].el.classList.remove("sel");

        selected = i;

        if (i >= 0 && grid[i]) grid[i].el.classList.add("sel");
    }

    function tap(i) {
        if (selected === -1) return setSel(i);
        if (selected === i) return setSel(-1);

        const a = selected;
        const dist = Math.abs(Math.floor(a / C) - Math.floor(i / C)) + Math.abs((a % C) - (i % C));

        setSel(-1);

        if (dist === 1) trySwap(a, i);
        else setSel(i);
    }

    function cellAt(e) {
        const rect = board.getBoundingClientRect();
        const c = Math.floor(((e.clientX - rect.left) / rect.width) * C);
        const r = Math.floor(((e.clientY - rect.top) / rect.height) * R);

        return (c < 0 || c >= C || r < 0 || r >= R) ? -1 : r * C + c;
    }

    on(board, "pointerdown", e => {
        if (busy || stale()) return;

        const i = cellAt(e);
        if (i < 0) return;

        clearHint();
        down = { i, x: e.clientX, y: e.clientY, done: false };

        try { board.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    });

    on(board, "pointermove", e => {
        if (!down || down.done || busy) return;

        const dx = e.clientX - down.x;
        const dy = e.clientY - down.y;
        const cellPx = board.getBoundingClientRect().width / C;

        if (Math.max(Math.abs(dx), Math.abs(dy)) < cellPx * 0.35) return;

        down.done = true;

        const from = down.i;
        const horizontal = Math.abs(dx) > Math.abs(dy);
        const r = Math.floor(from / C) + (horizontal ? 0 : (dy > 0 ? 1 : -1));
        const c = (from % C) + (horizontal ? (dx > 0 ? 1 : -1) : 0);

        setSel(-1);

        if (r >= 0 && r < R && c >= 0 && c < C) trySwap(from, r * C + c);
    });

    on(board, "pointerup", () => {
        if (!down) return;

        const d = down;
        down = null;

        if (!d.done && !busy && !stale()) tap(d.i);
    });

    on(board, "pointercancel", () => { down = null; });

    for (let i = 0; i < N; i++) {
        grid[i] = makeCandy(0, null, Math.floor(i / C), i % C);
    }

    do {
        grid.forEach(o => { o.type = rnd(TYPES); });
    } while (runs().length || !findMove());

    grid.forEach((o, i) => {
        render(o);
        o.el.classList.add("born");
        o.el.style.animationDelay = `${(i % C + Math.floor(i / C)) * 30}ms`;
    });

    // HINT: show a swap that makes a match
    onHint(() => {
        if (busy || stale()) return false;

        clearHint();

        const m = findMove();
        if (!m) return false;

        hinted = [grid[m[0]], grid[m[1]]];
        hinted.forEach(o => o.el.classList.add("hint"));

        return true;
    });

    status(`Reach ${target} points in ${moves} moves.`);
    scheduleHint();
}

/* =========================================================
   GAME 4: MEMORY CARD MATCHING
   ========================================================= */

function gameMemoryMatch() {
    resetGame();

    addHeading("🧩 Memory Card Matching", "Flip two cards at a time and find every matching pair.");

    const level = currentLevel();
    const pairCount = Math.min(6 + level, 18);

    const icons = [
        "🍎", "🚀", "🌟", "🎯", "🎵", "🐱",
        "🌈", "⚽", "🍕", "🦋", "🎮", "🌻",
        "🐼", "🚗", "💎", "🧠", "🔥", "🌍"
    ];

    const cards = shuffle([...icons.slice(0, pairCount), ...icons.slice(0, pairCount)]);
    const total = cards.length;
    const cols = total <= 12 ? 4 : total <= 20 ? 5 : 6;

    const board = el("div", "ev-board mem-board");
    board.style.gridTemplateColumns = `repeat(${cols}, var(--card))`;
    area.append(board);

    const status = makeStatus(`Find all ${pairCount} pairs.`);

    let first = -1;
    let second = -1;
    let moves = 0;
    let locked = false;
    let matchedCount = 0;

    const nodes = cards.map((symbol, index) => {
        const button = el("button", "mcard");

        button.type = "button";
        button.style.animationDelay = `${index * 35}ms`;
        button.innerHTML =
            `<span class="mface mback">?</span><span class="mface mfront">${symbol}</span>`;
        button.addEventListener("click", () => flip(index));

        board.append(button);
        return button;
    });

    function flip(index) {
        if (over || locked || index === first) return;
        if (nodes[index].classList.contains("matched")) return;

        nodes[index].classList.add("flipped");

        if (first === -1) {
            first = index;
            return;
        }

        second = index;
        moves++;
        addMove();

        if (cards[first] === cards[second]) {
            const a = first;
            const b = second;

            first = -1;
            second = -1;
            matchedCount += 2;

            later(350, () => {
                nodes[a].classList.add("matched");
                nodes[b].classList.add("matched");
            });

            addScore(100);

            if (matchedCount === total) {
                const finalScore = score + Math.max(0, (pairCount * 3 - moves) * 10);

                setScore(finalScore);
                status("🎉 Every pair matched! Saving your reward...", "win");
                winLater(finalScore, 1000);
            }

            return;
        }

        locked = true;
        wrongAlert("Not a match, try again");

        const a = first;
        const b = second;

        later(450, () => {
            nodes[a].classList.add("wrong");
            nodes[b].classList.add("wrong");
        });

        later(1000, () => {
            [a, b].forEach(i => nodes[i].classList.remove("flipped", "wrong"));
            first = -1;
            second = -1;
            locked = false;
        });
    }

    // HINT: peek at a matching pair for one second
    onHint(() => {
        if (locked || over) return false;

        const open = nodes.map((_, i) => i).filter(i => !nodes[i].classList.contains("matched"));

        if (first !== -1) {
            const b = open.find(i => i !== first && cards[i] === cards[first]);
            if (b === undefined) return false;

            locked = true;
            nodes[b].classList.add("flipped");

            later(900, () => {
                nodes[b].classList.remove("flipped");
                locked = false;
            });

            return true;
        }

        const pairs = open.filter(i => open.some(j => j !== i && cards[j] === cards[i]));
        if (!pairs.length) return false;

        const a = pick(pairs);
        const b = open.find(i => i !== a && cards[i] === cards[a]);

        locked = true;
        nodes[a].classList.add("flipped");
        nodes[b].classList.add("flipped");

        later(1000, () => {
            nodes[a].classList.remove("flipped");
            nodes[b].classList.remove("flipped");
            locked = false;
        });

        return true;
    });
}

/* =========================================================
   GAME 5: BUBBLE SHOOTER
   ========================================================= */

function gameBubbleShooter() {
    resetGame();

    addHeading("🫧 Bubble Shooter", "Touch and drag to aim, release to shoot. Match 3 or more!");

    const level = currentLevel();
    const W = 560, H = 660, R = 24, D = R * 2, ROWH = 42, COLS = 11, MAXROWS = 13;
    const OFFX = (W - (COLS * D + R)) / 2;
    const colors = ["#ff4d6d", "#38bdf8", "#facc15", "#34d399", "#a78bfa"];
    const target = Math.min(500 + level * 100, 10000);

    const [canvas, ctx] = cv(area, W, H, 620);
    const status = makeStatus("Aim and shoot. Pop groups of 3 or more!");
    const fx = makeFX();

    let parity = 0;
    const grid = [];
    const newRow = () => Array.from({ length: COLS }, () => pick(colors));

    const startRows = Math.min(3 + Math.floor(level / 3), 8);
    for (let r = 0; r < startRows; r++) grid.push(newRow());

    const bx = (r, c) => OFFX + R + c * D + (((r + parity) & 1) ? R : 0);
    const by = r => R + 10 + r * ROWH;
    const get = (r, c) => (grid[r] && grid[r][c]) || null;

    const nbrs = (r, c) => {
        const odd = (r + parity) & 1;
        const out = [[r, c - 1], [r, c + 1]];
        const dcs = odd ? [0, 1] : [-1, 0];

        [r - 1, r + 1].forEach(rr2 => dcs.forEach(d => out.push([rr2, c + d])));

        return out.filter(([rr2, cc]) => rr2 >= 0 && cc >= 0 && cc < COLS);
    };

    const sx = W / 2;
    const sy = H - 52;

    let angle = -Math.PI / 2;
    let cur = pick(colors);
    let next = pick(colors);
    let proj = null;
    let misses = 0;
    let won = false;
    let dead = false;
    let t = 0;

    const falling = [];
    const bgBubbles = Array.from({ length: 14 }, () => ({
        x: Math.random() * W, y: Math.random() * H, r: 6 + Math.random() * 16, s: 0.15 + Math.random() * 0.4
    }));

    const hitsBubble = (x, y) => {
        for (let r = 0; r < grid.length; r++) {
            for (let c = 0; c < COLS; c++) {
                if (grid[r][c] && Math.hypot(bx(r, c) - x, by(r) - y) < D * 0.88) return true;
            }
        }
        return false;
    };

    function flood(r, c) {
        const color = get(r, c);
        const seen = new Set([r * COLS + c]);
        const stack = [[r, c]];

        while (stack.length) {
            const [cr, cc] = stack.pop();

            for (const [nr, nc] of nbrs(cr, cc)) {
                const k = nr * COLS + nc;

                if (!seen.has(k) && get(nr, nc) === color) {
                    seen.add(k);
                    stack.push([nr, nc]);
                }
            }
        }

        return seen;
    }

    function dropFloating() {
        const keep = new Set();
        const stack = [];

        for (let c = 0; c < COLS; c++) {
            if (get(0, c)) {
                keep.add(c);
                stack.push([0, c]);
            }
        }

        while (stack.length) {
            const [cr, cc] = stack.pop();

            for (const [nr, nc] of nbrs(cr, cc)) {
                const k = nr * COLS + nc;

                if (!keep.has(k) && get(nr, nc)) {
                    keep.add(k);
                    stack.push([nr, nc]);
                }
            }
        }

        let count = 0;

        grid.forEach((row, r) => row.forEach((col, c) => {
            if (col && !keep.has(r * COLS + c)) {
                falling.push({ x: bx(r, c), y: by(r), vy: 0, vx: (Math.random() - 0.5) * 2, color: col });
                row[c] = null;
                count++;
            }
        }));

        return count;
    }

    const tooLow = () => grid.some((row, r) => r >= MAXROWS - 1 && row.some(Boolean));

    function endGame(win, message) {
        if (win) {
            won = true;
            status("🎉 Target reached! Saving your reward...", "win");

            for (let i = 0; i < 6; i++) {
                fx.burst(Math.random() * W, 120 + Math.random() * 200, pick(colors), 14, 6);
            }

            winLater(score, 900);
        } else {
            dead = true;
            shake(canvas);
            loseLater(message, 700);
        }
    }

    function land() {
        let r = clamp(Math.round((proj.y - by(0)) / ROWH), 0, MAXROWS - 1);
        let c = clamp(
            Math.round((proj.x - OFFX - R - (((r + parity) & 1) ? R : 0)) / D), 0, COLS - 1
        );

        if (get(r, c)) {
            let best = null;
            let bd = 1e9;

            for (const [nr, nc] of nbrs(r, c)) {
                if (nr > MAXROWS || get(nr, nc)) continue;

                const d = Math.hypot(bx(nr, nc) - proj.x, by(nr) - proj.y);
                if (d < bd) { bd = d; best = [nr, nc]; }
            }

            if (!best) {
                proj = null;
                endGame(false, "The bubbles reached the bottom!");
                return;
            }

            [r, c] = best;
        }

        while (grid.length <= r) grid.push(Array(COLS).fill(null));
        grid[r][c] = proj.color;

        const group = flood(r, c);

        if (group.size >= 3) {
            let popped = 0;

            group.forEach(k => {
                const gr = Math.floor(k / COLS);
                const gc = k % COLS;

                fx.burst(bx(gr, gc), by(gr), grid[gr][gc], 9, 5);
                grid[gr][gc] = null;
                popped++;
            });

            const dropped = dropFloating();
            const gained = popped * 100 + dropped * 150;

            addScore(gained);
            fx.text(proj.x, proj.y - 14, `+${gained}`);
        } else {
            misses++;

            if (misses % 6 === 0) {
                grid.unshift(newRow());
                parity ^= 1;
                shake(canvas);
                status("New row of bubbles!");
            }
        }

        while (grid.length && grid[grid.length - 1].every(v => !v)) grid.pop();

        proj = null;
        cur = next;
        next = pick(colors);

        if (tooLow()) {
            endGame(false, "The bubbles reached the bottom!");
        } else if (score >= target || grid.length === 0) {
            endGame(true);
        }
    }

    function setAim(event) {
        const rect = canvas.getBoundingClientRect();
        const px = (event.clientX - rect.left) * (W / rect.width);
        const py = (event.clientY - rect.top) * (H / rect.height);

        angle = clamp(Math.atan2(py - sy, px - sx), -Math.PI + 0.15, -0.15);
    }

    function shoot() {
        if (over || proj || won || dead) return;

        proj = { x: sx, y: sy, vx: Math.cos(angle), vy: Math.sin(angle), color: cur };
        addMove();
    }

    // mouse: click shoots. touch: drag to aim, lift finger to shoot.
    on(canvas, "pointermove", setAim);
    on(canvas, "pointerdown", e => {
        setAim(e);
        if (e.pointerType === "mouse") shoot();
    });
    on(canvas, "pointerup", e => {
        if (e.pointerType !== "mouse") {
            setAim(e);
            shoot();
        }
    });

    on(window, "keydown", e => {
        if (e.code === "ArrowLeft" || e.code === "KeyA") {
            angle = clamp(angle - 0.07, -Math.PI + 0.15, -0.15);
            e.preventDefault();
        } else if (e.code === "ArrowRight" || e.code === "KeyD") {
            angle = clamp(angle + 0.07, -Math.PI + 0.15, -0.15);
            e.preventDefault();
        } else if (e.code === "Space" || e.code === "ArrowUp") {
            e.preventDefault();
            shoot();
        }
    });

    area.append(makeButton("🎯 Shoot Bubble", shoot));

    // HINT: aim at the lowest bubble that has the same colour as the bubble in the cannon
    let hintRing = null;

    onHint(() => {
        if (proj || won || dead) return false;

        let best = null;

        grid.forEach((row, r) => row.forEach((col, c) => {
            if (col === cur && nbrs(r, c).some(([nr, nc]) => nr >= 0 && !get(nr, nc)) && (!best || r > best.r)) {
                best = { r, c };
            }
        }));

        if (!best) return false;

        angle = clamp(Math.atan2(by(best.r) - sy, bx(best.r, best.c) - sx), -Math.PI + 0.15, -0.15);
        hintRing = { x: bx(best.r, best.c), y: by(best.r), until: t + 150 };

        return true;
    });

    function drawBubble(x, y, color, r = R - 1) {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();

        const shade = ctx.createRadialGradient(x - r * 0.3, y - r * 0.3, r * 0.2, x, y, r);
        shade.addColorStop(0, "rgba(255,255,255,0)");
        shade.addColorStop(1, "rgba(0,0,0,.32)");
        ctx.fillStyle = shade;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "rgba(255,255,255,.85)";
        ctx.beginPath();
        ctx.ellipse(x - r * 0.35, y - r * 0.4, r * 0.25, r * 0.15, -0.6, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = "rgba(255,255,255,.45)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.stroke();
    }

    function draw() {
        const bg = ctx.createLinearGradient(0, 0, 0, H);
        bg.addColorStop(0, "#1e1b4b");
        bg.addColorStop(1, "#0f172a");
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, W, H);

        bgBubbles.forEach(b => {
            ctx.strokeStyle = "rgba(255,255,255,.1)";
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
            ctx.stroke();
        });

        ctx.setLineDash([10, 8]);
        ctx.strokeStyle = "rgba(248,113,113,.5)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(0, by(MAXROWS - 2) + R);
        ctx.lineTo(W, by(MAXROWS - 2) + R);
        ctx.stroke();
        ctx.setLineDash([]);

        grid.forEach((row, r) => row.forEach((color, c) => {
            if (color) drawBubble(bx(r, c), by(r), color);
        }));

        falling.forEach(f => drawBubble(f.x, f.y, f.color));

        if (!proj && !won && !dead) {
            let x = sx, y = sy, vx = Math.cos(angle), vy = Math.sin(angle);

            for (let i = 0; i < 60; i++) {
                x += vx * 9;
                y += vy * 9;

                if (x < R) { x = R; vx = Math.abs(vx); }
                if (x > W - R) { x = W - R; vx = -Math.abs(vx); }
                if (y <= by(0) || hitsBubble(x, y)) break;

                if (i % 2 === 0) {
                    ctx.fillStyle = `rgba(255,255,255,${Math.max(0.1, 0.75 - i * 0.011)})`;
                    ctx.beginPath();
                    ctx.arc(x, y, 3, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        }

        ctx.fillStyle = "#334155";
        ctx.beginPath();
        ctx.arc(sx, sy, 36, 0, Math.PI * 2);
        ctx.fill();

        ctx.save();
        ctx.translate(sx, sy);
        ctx.rotate(angle);
        ctx.fillStyle = "#64748b";
        rr(ctx, 0, -11, 56, 22, 9);
        ctx.fill();
        ctx.restore();

        drawBubble(sx, sy, cur, R - 3 + Math.sin(t * 0.1) * 1.2);
        drawBubble(sx - 96, sy + 10, next, 16);
        txt(ctx, "NEXT", sx - 96, sy - 18, "bold 12px sans-serif", "#cbd5e1");

        if (proj) drawBubble(proj.x, proj.y, proj.color);

        if (hintRing && t < hintRing.until) {
            ctx.strokeStyle = "#22c55e";
            ctx.lineWidth = 5;
            ctx.beginPath();
            ctx.arc(hintRing.x, hintRing.y, R + 4 + Math.sin(t * 0.3) * 3, 0, Math.PI * 2);
            ctx.stroke();
        }

        fx.draw(ctx);

        txt(ctx, `Score ${score} / ${target}`, W - 16, H - 14, "bold 16px sans-serif", "#e2e8f0", "right");
    }

    loop(dt => {
        t += dt;

        if (proj) {
            const total = 13 * dt;
            const steps = Math.max(1, Math.ceil(total / 6));
            const sd = total / steps;

            for (let s = 0; s < steps && proj; s++) {
                proj.x += proj.vx * sd;
                proj.y += proj.vy * sd;

                if (proj.x < R) { proj.x = R; proj.vx = Math.abs(proj.vx); }
                if (proj.x > W - R) { proj.x = W - R; proj.vx = -Math.abs(proj.vx); }

                if (proj.y <= by(0) || hitsBubble(proj.x, proj.y)) land();
            }
        }

        for (let i = falling.length - 1; i >= 0; i--) {
            const f = falling[i];

            f.vy += 0.5 * dt;
            f.y += f.vy * dt;
            f.x += f.vx * dt;

            if (f.y > H + 40) falling.splice(i, 1);
        }

        bgBubbles.forEach(b => {
            b.y -= b.s * dt;
            if (b.y < -30) { b.y = H + 30; b.x = Math.random() * W; }
        });

        fx.update(dt);
        draw();
    });

    draw();
}

/* =========================================================
   GAME 6: ENDLESS RUNNER
   ========================================================= */

function gameEndlessRunner() {
    resetGame();

    addHeading("🏃 Endless Runner", "Jump over the obstacles and reach the target score.");

    const level = currentLevel();
    const W = 780, H = 340, GROUND = 280;
    const target = Math.min(150 + level * 25, 1500);

    const [canvas, ctx] = cv(area, W, H, 840);
    const status = makeStatus(`Press Space or ↑, or tap the game to jump. Reach ${target} points.`);
    const fx = makeFX();

    const P = { x: 90, y: GROUND - 50, w: 34, h: 50, vy: 0, air: false, sq: 0 };

    let obstacles = [];
    let elapsed = 0, spawnT = 0, scroll = 0, run = 0, t = 0, dustT = 0;
    let nextSpawn = 60;
    let speed = 5 + level * 0.2;
    let dead = false, won = false;

    const clouds = Array.from({ length: 5 }, () => ({
        x: Math.random() * W, y: 20 + Math.random() * 90, s: 0.6 + Math.random() * 0.8
    }));

    function jump() {
        if (over || dead || won || P.air) return;

        P.vy = -13.5;
        P.air = true;
        addMove();
        fx.burst(P.x + 17, GROUND, "#d6c59a", 6, 2);
    }

    on(window, "keydown", event => {
        if (event.code === "Space" || event.code === "ArrowUp" || event.code === "KeyW") {
            event.preventDefault();
            jump();
        }
    });

    on(canvas, "pointerdown", e => { e.preventDefault(); jump(); });
    area.append(makeButton("⬆ Jump", jump));

    // HINT: show a JUMP marker over the next cactus
    let hintUntil = 0;

    onHint(() => {
        if (dead || won || !obstacles.some(o => o.x + o.width > P.x)) return false;
        hintUntil = t + 180;
        return true;
    });

    function drawCactus(o) {
        ctx.fillStyle = "#15803d";
        rr(ctx, o.x, o.y, o.width, o.height, 8);
        ctx.fill();

        ctx.fillStyle = "#16a34a";
        rr(ctx, o.x - 8, o.y + o.height * 0.35, 10, 8, 4);
        ctx.fill();
        rr(ctx, o.x + o.width - 2, o.y + o.height * 0.5, 10, 8, 4);
        ctx.fill();

        ctx.fillStyle = "rgba(255,255,255,.2)";
        rr(ctx, o.x + 3, o.y + 4, 4, o.height - 8, 2);
        ctx.fill();
    }

    function drawPlayer() {
        const cx = P.x + P.w / 2;
        const feet = P.y + P.h;

        ctx.fillStyle = "rgba(0,0,0,.2)";
        ctx.beginPath();
        ctx.ellipse(cx, GROUND + 4, Math.max(6, 18 - (GROUND - feet) * 0.05), 5, 0, 0, Math.PI * 2);
        ctx.fill();

        ctx.save();
        ctx.translate(cx, feet);
        ctx.scale(1 + P.sq * 0.25 - (P.air ? 0.06 : 0), 1 - P.sq * 0.25 + (P.air ? 0.1 : 0));

        const swing = P.air ? 0.5 : Math.sin(run) * 0.9;
        ctx.fillStyle = "#1d4ed8";
        rr(ctx, -12 + swing * 5, -14, 9, 14, 4); ctx.fill();
        rr(ctx, 3 - swing * 5, -14, 9, 14, 4); ctx.fill();

        const body = ctx.createLinearGradient(0, -P.h, 0, -10);
        body.addColorStop(0, "#93c5fd");
        body.addColorStop(1, "#2563eb");
        ctx.fillStyle = body;
        rr(ctx, -P.w / 2, -P.h, P.w, P.h - 10, 12);
        ctx.fill();

        ctx.fillStyle = "#fff";
        ctx.beginPath();
        ctx.arc(7, -P.h + 16, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#111827";
        ctx.beginPath();
        ctx.arc(9, -P.h + 16, 3, 0, Math.PI * 2);
        ctx.fill();

        ctx.restore();
    }

    function draw() {
        const sky = ctx.createLinearGradient(0, 0, 0, GROUND);
        sky.addColorStop(0, "#38bdf8");
        sky.addColorStop(1, "#e0f2fe");
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, W, H);

        ctx.fillStyle = "#fde047";
        ctx.beginPath();
        ctx.arc(660, 70, 34, 0, Math.PI * 2);
        ctx.fill();

        clouds.forEach(c => {
            ctx.fillStyle = "rgba(255,255,255,.85)";
            ctx.beginPath();
            ctx.ellipse(c.x, c.y, 44 * c.s, 16 * c.s, 0, 0, Math.PI * 2);
            ctx.ellipse(c.x + 24 * c.s, c.y - 8 * c.s, 28 * c.s, 14 * c.s, 0, 0, Math.PI * 2);
            ctx.fill();
        });

        ctx.fillStyle = "#86efac";
        ctx.beginPath();
        ctx.moveTo(0, GROUND);
        for (let x = 0; x <= W; x += 20) {
            ctx.lineTo(x, GROUND - 40 - Math.sin((x + scroll * 0.25) / 70) * 22);
        }
        ctx.lineTo(W, GROUND);
        ctx.closePath();
        ctx.fill();

        ctx.fillStyle = "#854d0e";
        ctx.fillRect(0, GROUND, W, H - GROUND);
        ctx.fillStyle = "#65a30d";
        ctx.fillRect(0, GROUND, W, 8);

        ctx.fillStyle = "rgba(0,0,0,.18)";
        for (let x = -((scroll) % 60); x < W; x += 60) ctx.fillRect(x, GROUND + 24, 28, 4);

        obstacles.forEach(drawCactus);

        if (t < hintUntil) {
            const o = obstacles.find(ob => ob.x + ob.width > P.x);

            if (o) {
                const cx = o.x + o.width / 2;

                ctx.fillStyle = "#16a34a";
                rr(ctx, cx - 40, o.y - 62, 80, 30, 15);
                ctx.fill();
                ctx.beginPath();
                ctx.moveTo(cx - 8, o.y - 33);
                ctx.lineTo(cx + 8, o.y - 33);
                ctx.lineTo(cx, o.y - 22);
                ctx.fill();
                txt(ctx, "JUMP!", cx, o.y - 41, "bold 16px sans-serif", "#fff");
            }
        }

        drawPlayer();
        fx.draw(ctx);

        ctx.fillStyle = "rgba(15,23,42,.55)";
        rr(ctx, 14, 12, 250, 22, 11);
        ctx.fill();
        ctx.fillStyle = "#facc15";
        rr(ctx, 14, 12, Math.max(0.1, 250 * clamp(score / target, 0, 1)), 22, 11);
        ctx.fill();

        txt(ctx, `Score ${score} / ${target}`, W - 16, 30, "bold 18px sans-serif", "#0f172a", "right");
    }

    loop(dt => {
        t += dt;
        scroll += speed * dt;
        clouds.forEach(c => { c.x -= c.s * 0.35 * dt; if (c.x < -80) c.x = W + 60; });

        if (!dead && !won) {
            elapsed += dt;
            spawnT += dt;
            run += 0.35 * dt;
            dustT += dt;

            setScore(Math.floor(elapsed / 6), false);

            const was = P.air;

            P.vy += 0.7 * dt;
            P.y += P.vy * dt;

            if (P.y >= GROUND - P.h) {
                P.y = GROUND - P.h;
                P.vy = 0;
                P.air = false;

                if (was) {
                    P.sq = 1;
                    fx.burst(P.x + 17, GROUND, "#d6c59a", 8, 2.5);
                }
            }

            P.sq = Math.max(0, P.sq - 0.07 * dt);

            if (!P.air && dustT > 7) {
                dustT = 0;
                fx.burst(P.x + 4, GROUND, "#d6c59a", 1, 1.2);
            }

            if (spawnT > nextSpawn) {
                spawnT = 0;
                nextSpawn = Math.max(48, 95 - level * 2) + rnd(40);

                const h = 36 + rnd(30);

                obstacles.push({ x: W + 10, y: GROUND - h, width: 20 + rnd(14), height: h });
            }

            obstacles.forEach(o => { o.x -= speed * dt; });
            obstacles = obstacles.filter(o => o.x + o.width > -20);

            const hit = obstacles.some(o =>
                P.x + 6 < o.x + o.width &&
                P.x + P.w - 6 > o.x &&
                P.y + 6 < o.y + o.height &&
                P.y + P.h > o.y
            );

            speed += 0.0015 * dt;

            if (hit) {
                dead = true;
                fx.burst(P.x + 17, P.y + 25, "#ef4444", 28, 6);
                shake(canvas);
                loseLater(`You hit an obstacle! You scored ${score}.`, 700);
            } else if (score >= target) {
                won = true;
                status("🎉 Target reached! Saving your reward...", "win");

                for (let i = 0; i < 5; i++) {
                    fx.burst(P.x + 20 + i * 90, 120, pick(["#facc15", "#22c55e", "#f472b6", "#38bdf8"]), 14, 6);
                }

                winLater(score, 900);
            }
        }

        fx.update(dt);
        draw();
    });

    draw();
}

/* =========================================================
   GAME 7: NEON TIC-TAC-TOE
   - You are X, the computer is O.
   - Win = level complete. Computer win = level failed.
   - A DRAW is not a failure: the board is cleared and you play again
     (as long as the time lasts).
   - At low levels the computer sometimes makes a mistake, so the
     game can be won. The computer gets smarter every level.
   ========================================================= */

function gameNeonTicTacToe() {
    resetGame();

    addHeading("⭕ Neon Tic-Tac-Toe", "Get three marks in a row before the computer.");

    const level = currentLevel();
    // chance that the computer plays a random (weak) move
    const mistakeChance = Math.max(0.08, 0.5 - level * 0.04);

    const board = el("div", "ev-board ttt-board");
    area.append(board);

    const status = makeStatus("Your turn: X");

    let cells = Array(9).fill("");
    let playerTurn = true;
    let busy = false;

    const wins = [
        [0, 1, 2], [3, 4, 5], [6, 7, 8],
        [0, 3, 6], [1, 4, 7], [2, 5, 8],
        [0, 4, 8], [2, 4, 6]
    ];

    const buttons = cells.map((_, index) => {
        const button = el("button", "ttt-cell");

        button.type = "button";
        button.addEventListener("click", () => move(index));
        board.append(button);

        return button;
    });

    function winnerOf(b) {
        for (const line of wins) {
            const [a, c, d] = line;
            if (b[a] && b[a] === b[c] && b[a] === b[d]) return { mark: b[a], line };
        }

        return null;
    }

    const getWin = () => winnerOf(cells);

    function draw(lastIndex = -1) {
        cells.forEach((value, index) => {
            const button = buttons[index];

            button.className = "ttt-cell" + (value ? " " + value.toLowerCase() : "");

            if (value && index === lastIndex) {
                button.innerHTML = `<span>${value}</span>`;
            } else if (value && !button.firstChild) {
                button.innerHTML = `<span>${value}</span>`;
            } else if (!value) {
                button.innerHTML = "";
            }
        });
    }

    function checkEnd() {
        const result = getWin();

        if (result) {
            busy = true;
            result.line.forEach(i => buttons[i].classList.add("win"));

            if (result.mark === "X") {
                setScore(100);
                status("🎉 You won! Saving your reward...", "win");
                winLater(100, 1100);
            } else {
                status("The computer wins this round.", "lose");
                loseLater("The computer won this round. Try again.", 900);
            }

            return true;
        }

        if (cells.every(Boolean)) {
            // draw: not a failure, clear the board and play again
            busy = true;
            status("It's a draw! New board...", "lose");
            wrongAlert("Draw! Play again", "info");

            later(1100, () => {
                cells = Array(9).fill("");
                buttons.forEach(b => { b.className = "ttt-cell"; b.innerHTML = ""; });
                busy = false;
                playerTurn = true;
                status("Your turn: X");
            });

            return true;
        }

        return false;
    }

    function findWinningMove(mark) {
        for (let i = 0; i < 9; i++) {
            if (cells[i]) continue;

            cells[i] = mark;
            const result = getWin();
            cells[i] = "";

            if (result && result.mark === mark) return i;
        }

        return -1;
    }

    // minimax: computer (O) is the maximiser
    function minimax(b, isO) {
        const w = winnerOf(b);
        if (w) return w.mark === "O" ? 10 : -10;
        if (b.every(Boolean)) return 0;

        let best = isO ? -99 : 99;

        for (let i = 0; i < 9; i++) {
            if (b[i]) continue;

            b[i] = isO ? "O" : "X";
            const s = minimax(b, !isO);
            b[i] = "";

            best = isO ? Math.max(best, s) : Math.min(best, s);
        }

        return best;
    }

    function computerChoice() {
        const empty = cells.map((v, i) => (v ? -1 : i)).filter(i => i !== -1);

        // sometimes a weak (random) move, less often at higher levels
        if (Math.random() < mistakeChance) return pick(empty);

        let bestScore = -99;
        let bestMoves = [];

        for (const i of empty) {
            cells[i] = "O";
            const s = minimax(cells, false);
            cells[i] = "";

            if (s > bestScore) { bestScore = s; bestMoves = [i]; }
            else if (s === bestScore) bestMoves.push(i);
        }

        return pick(bestMoves);
    }

    function move(index) {
        if (over || busy || !playerTurn) return;

        if (cells[index]) {
            wrongAlert("Already taken!");
            return;
        }

        cells[index] = "X";
        addMove();
        draw(index);

        if (checkEnd()) return;

        playerTurn = false;
        busy = true;
        status("Computer is thinking...");

        later(550, () => {
            if (over) return;

            const choice = computerChoice();

            cells[choice] = "O";
            draw(choice);

            busy = false;
            playerTurn = true;

            if (!checkEnd()) status("Your turn: X");
        });
    }

    // HINT: glow the best square (win, else block, else best by minimax for X)
    function bestMove() {
        let c = findWinningMove("X");
        if (c === -1) c = findWinningMove("O");
        if (c !== -1) return c;

        let bestScore = 99;
        let best = [];

        cells.forEach((v, i) => {
            if (v) return;

            cells[i] = "X";
            const s = minimax(cells, true);
            cells[i] = "";

            if (s < bestScore) { bestScore = s; best = [i]; }
            else if (s === bestScore) best.push(i);
        });

        return best.length ? pick(best) : -1;
    }

    onHint(() => {
        if (over || busy || !playerTurn) return false;

        const i = bestMove();
        if (i < 0) return false;

        buttons[i].classList.add("ev-hint-glow");
        later(2200, () => buttons[i].classList.remove("ev-hint-glow"));

        return true;
    });

    draw();
}

/* =========================================================
   GAME 8: 2048
   ========================================================= */

function gamePuzzle2048() {
    resetGame();

    addHeading("🔢 2048 Number Puzzle", "Swipe or use arrows. Combine matching numbers to reach the target tile.");

    const level = currentLevel();
    const size = Math.min(4 + Math.floor(level / 8), 6);
    const target = Math.min(256 * Math.pow(2, Math.floor((level - 1) / 3)), 2048);

    const PALETTE = {
        2: ["#eee4da", "#776e65"], 4: ["#ede0c8", "#776e65"], 8: ["#f2b179", "#fff"],
        16: ["#f59563", "#fff"], 32: ["#f67c5f", "#fff"], 64: ["#f65e3b", "#fff"],
        128: ["#edcf72", "#fff"], 256: ["#edcc61", "#fff"], 512: ["#edc850", "#fff"],
        1024: ["#edc53f", "#fff"], 2048: ["#edc22e", "#fff"]
    };

    const board = el("div", "ev-board p48-board");
    board.style.setProperty("--n", size);
    area.append(board);

    const status = makeStatus(`Reach ${target} to complete this level.`);

    const grid = Array.from({ length: size }, () => Array(size).fill(0));

    let spawned = null;
    let merged = new Set();

    function emptyCells() {
        const result = [];

        for (let r = 0; r < size; r++) {
            for (let c = 0; c < size; c++) {
                if (!grid[r][c]) result.push([r, c]);
            }
        }

        return result;
    }

    function spawn() {
        const empty = emptyCells();
        if (!empty.length) return;

        const [r, c] = pick(empty);
        grid[r][c] = Math.random() < 0.9 ? 2 : 4;
        spawned = r + "," + c;
    }

    function draw() {
        board.innerHTML = "";

        grid.forEach((row, r) => {
            row.forEach((value, c) => {
                const key = r + "," + c;
                const cell = el("div", "p48-cell");

                if (value) {
                    const [bg, fg] = PALETTE[value] || ["#3c3a32", "#fff"];

                    cell.classList.add("has");
                    if (value > 999) cell.classList.add("big");
                    if (spawned === key) cell.classList.add("spawn");
                    if (merged.has(key)) cell.classList.add("merge");

                    cell.style.background = bg;
                    cell.style.color = fg;
                    cell.textContent = value;
                }

                board.append(cell);
            });
        });
    }

    function slideLine(line) {
        const filtered = line.filter(Boolean);
        const result = [];
        const mergedAt = [];
        let gained = 0;

        for (let i = 0; i < filtered.length; i++) {
            if (filtered[i] === filtered[i + 1]) {
                const value = filtered[i] * 2;

                mergedAt.push(result.length);
                result.push(value);
                gained += value;
                i++;
            } else {
                result.push(filtered[i]);
            }
        }

        while (result.length < size) result.push(0);

        return { result, gained, mergedAt };
    }

    function canMove() {
        for (let r = 0; r < size; r++) {
            for (let c = 0; c < size; c++) {
                if (!grid[r][c]) return true;
                if (c + 1 < size && grid[r][c] === grid[r][c + 1]) return true;
                if (r + 1 < size && grid[r][c] === grid[r + 1][c]) return true;
            }
        }

        return false;
    }

    let locked = false;

    function move(direction) {
        if (over) return;

        const old = JSON.stringify(grid);
        const mergedNow = new Set();
        let gained = 0;

        for (let i = 0; i < size; i++) {
            if (direction === "left" || direction === "right") {
                const line = [...grid[i]];
                const rev = direction === "right";
                if (rev) line.reverse();

                const moved = slideLine(line);
                gained += moved.gained;

                grid[i] = rev ? [...moved.result].reverse() : moved.result;
                moved.mergedAt.forEach(k => mergedNow.add(i + "," + (rev ? size - 1 - k : k)));
            } else {
                const line = grid.map(row => row[i]);
                const rev = direction === "down";
                if (rev) line.reverse();

                const moved = slideLine(line);
                gained += moved.gained;

                const values = rev ? [...moved.result].reverse() : moved.result;

                for (let r = 0; r < size; r++) grid[r][i] = values[r];
                moved.mergedAt.forEach(k => mergedNow.add((rev ? size - 1 - k : k) + "," + i));
            }
        }

        if (JSON.stringify(grid) === old) return;

        addMove();
        addScore(gained);
        merged = mergedNow;
        spawn();

        board.dataset.slide = direction;
        draw();

        if (grid.some(row => row.some(v => v >= target))) {
            status("🎉 Target tile reached! Saving reward...", "win");
            locked = true;
            winLater(score, 800);
            return;
        }

        if (!emptyCells().length && !canMove()) {
            shake(board);
            loseLater("No moves remain. Try again.", 600);
        }
    }

    const safeMove = dir => { if (!locked) move(dir); };

    keys(safeMove);
    swipe(board, safeMove);
    dpad(safeMove);

    // HINT: try every swipe on a copy of the board and suggest the best one
    function preview(direction) {
        const g = grid.map(r => [...r]);
        let gained = 0;

        for (let i = 0; i < size; i++) {
            if (direction === "left" || direction === "right") {
                const line = [...g[i]];
                const rev = direction === "right";
                if (rev) line.reverse();

                const m = slideLine(line);
                gained += m.gained;
                g[i] = rev ? [...m.result].reverse() : m.result;
            } else {
                const line = g.map(row => row[i]);
                const rev = direction === "down";
                if (rev) line.reverse();

                const m = slideLine(line);
                gained += m.gained;

                const values = rev ? [...m.result].reverse() : m.result;
                for (let r = 0; r < size; r++) g[r][i] = values[r];
            }
        }

        return {
            changed: JSON.stringify(g) !== JSON.stringify(grid),
            gained,
            empties: g.flat().filter(v => !v).length
        };
    }

    onHint(() => {
        if (over || locked) return false;

        let best = null;

        ["left", "up", "right", "down"].forEach(d => {
            const p = preview(d);
            if (!p.changed) return;

            const sc = p.gained * 2 + p.empties * 8;
            if (!best || sc > best.sc) best = { d, sc };
        });

        if (!best) return false;

        const arrow = { left: "⬅", right: "➡", up: "⬆", down: "⬇" }[best.d];

        status(`💡 Hint: swipe ${arrow} ${best.d.toUpperCase()}`);
        infoAlert(`Try ${arrow} ${best.d}`);

        board.style.outline = "5px solid #22c55e";
        later(1800, () => { board.style.outline = ""; });

        return true;
    });

    spawn();
    spawn();
    draw();
}

/* =========================================================
   GAME 9: ARROW DIRECTION
   ========================================================= */

function gameArrowDirection() {
    resetGame();

    addHeading("🧭 Arrow Direction Puzzle", "Press the key matching the arrow shown on screen.");

    const level = currentLevel();
    const rounds = Math.min(5 + level, 40);

    const arrows = [
        { direction: "up", symbol: "⬆️" },
        { direction: "down", symbol: "⬇️" },
        { direction: "left", symbol: "⬅️" },
        { direction: "right", symbol: "➡️" }
    ];

    const stage = el("div", "arw-stage");
    area.append(stage);

    const bar = el("div", "arw-bar", "<i></i>");
    area.append(bar);

    const roundLabel = el("p", "arw-round");
    area.append(roundLabel);

    // on-screen arrow buttons for everyone (phones, tablets, mouse)
    const pad = el("div", "ev-toolbar");
    const padBtns = {};

    [["left", "◀"], ["up", "▲"], ["down", "▼"], ["right", "▶"]].forEach(([dir, label]) => {
        const b = makeButton(label, () => {}, "gbtn secondary");
        padBtns[dir] = b;
        b.style.minWidth = "64px";
        b.style.minHeight = "56px";
        b.style.fontSize = "22px";
        b.addEventListener("pointerdown", e => { e.preventDefault(); answer(dir); });
        pad.append(b);
    });

    area.append(pad);

    const status = makeStatus("Ready? Follow the arrows!");

    let round = 0;
    let current = null;
    let accepting = false;

    function nextRound() {
        if (over) return;

        if (round >= rounds) {
            status("🎉 All arrows completed! Saving reward...", "win");
            winLater(score, 700);
            return;
        }

        round++;
        current = pick(arrows);
        accepting = true;

        stage.className = "arw-stage";
        stage.innerHTML = `<span class="arw-sym">${current.symbol}</span>`;
        bar.firstChild.style.width = `${((round - 1) / rounds) * 100}%`;
        roundLabel.textContent = `Round ${round} of ${rounds}`;

        status("Press the matching arrow.");
    }

    function answer(direction) {
        if (over || !accepting || !current) return;

        accepting = false;
        addMove();

        if (direction === current.direction) {
            addScore(100);
            stage.classList.add("ok");
            bar.firstChild.style.width = `${(round / rounds) * 100}%`;
            status("Correct! ⭐", "win");
            later(420, nextRound);
        } else {
            stage.classList.add("bad");
            wrongAlert("Wrong arrow!");
            status("Wrong arrow!", "lose");
            loseLater("Wrong arrow! Try the level again.", 500);
        }
    }

    keys(answer);

    // HINT: glow the right button
    onHint(() => {
        if (!accepting || !current) return false;

        const b = padBtns[current.direction];
        b.classList.add("ev-hint-glow");
        later(2000, () => b.classList.remove("ev-hint-glow"));

        infoAlert(`Press ${current.symbol}`);
        return true;
    });

    nextRound();
}

/* =========================================================
   GAME 10: SLIDING PUZZLE
   ========================================================= */

function gameSlidingPuzzle() {
    resetGame();

    addHeading("🧩 Sliding Puzzle", "Arrange the numbers in order. Leave the empty space last.");

    const size = Math.min(3 + Math.floor((currentLevel() - 1) / 5), 5);
    const total = size * size;

    const board = el("div", "sl-board");
    board.style.setProperty("--n", size);
    area.append(board);

    const status = makeStatus("Tap a tile next to the gap to slide it.");

    const tiles = Array.from({ length: total }, (_, i) => (i + 1) % total);
    const nodes = {};

    function neighbors(index) {
        const r = Math.floor(index / size);
        const c = index % size;
        const result = [];

        if (r > 0) result.push(index - size);
        if (r < size - 1) result.push(index + size);
        if (c > 0) result.push(index - 1);
        if (c < size - 1) result.push(index + 1);

        return result;
    }

    const solved = () => tiles.every((value, index) => value === (index + 1) % total);

    // shuffle by making real moves, so the puzzle can always be solved
    let empty = total - 1;

    do {
        for (let i = 0; i < total * 30; i++) {
            const next = pick(neighbors(empty));
            [tiles[empty], tiles[next]] = [tiles[next], tiles[empty]];
            empty = next;
        }
    } while (solved());

    for (let value = 1; value < total; value++) {
        const button = el("button", "sl-tile");

        button.type = "button";
        button.textContent = value;
        button.style.background = `linear-gradient(145deg, hsl(${(value * 360) / total},85%,66%), hsl(${(value * 360) / total},75%,50%))`;
        button.style.animationDelay = `${value * 30}ms`;
        button.addEventListener("click", () => move(tiles.indexOf(value)));

        board.append(button);
        nodes[value] = button;
    }

    function place() {
        tiles.forEach((value, index) => {
            if (!value) return;

            nodes[value].style.setProperty("--r", Math.floor(index / size));
            nodes[value].style.setProperty("--c", index % size);
        });
    }

    function move(index) {
        if (over || index < 0 || tiles[index] === 0) return;

        const emptyIndex = tiles.indexOf(0);

        if (!neighbors(emptyIndex).includes(index)) {
            wrongAlert("This tile can't move");
            return;
        }

        [tiles[index], tiles[emptyIndex]] = [tiles[emptyIndex], tiles[index]];

        addMove();
        addScore(10);
        place();

        if (solved()) {
            status("🎉 Puzzle solved! Saving your reward...", "win");
            Object.values(nodes).forEach((n, i) => later(i * 40, () => { n.style.filter = "brightness(1.3)"; }));
            winLater(score + 500, 900);
        }
    }

    keys(dir => {
        const e = tiles.indexOf(0);
        const r = Math.floor(e / size);
        const c = e % size;

        const from = {
            up: r < size - 1 ? e + size : -1,
            down: r > 0 ? e - size : -1,
            left: c < size - 1 ? e + 1 : -1,
            right: c > 0 ? e - 1 : -1
        }[dir];

        move(from);
    });

    // HINT: glow a tile that gets closer to its place
    onHint(() => {
        if (over) return false;

        const e = tiles.indexOf(0);
        const far = (idx, v) => {
            const tr = Math.floor((v - 1) / size);
            const tc = (v - 1) % size;
            return Math.abs(Math.floor(idx / size) - tr) + Math.abs((idx % size) - tc);
        };

        let best = -1;
        let bestGain = -99;

        neighbors(e).forEach(i => {
            const v = tiles[i];
            const gain = far(i, v) - far(e, v);

            if (gain > bestGain) {
                bestGain = gain;
                best = i;
            }
        });

        if (best < 0) return false;

        const node = nodes[tiles[best]];
        node.classList.add("ev-hint-glow");
        later(2200, () => node.classList.remove("ev-hint-glow"));

        infoAlert(`Slide tile ${tiles[best]}`);
        return true;
    });

    place();
}

/* =========================================================
   QUIZ BANK + LEVEL-WISE QUESTION BUILDER
   - Every level gets a different set of questions.
   - No question is repeated inside a level.
   - Part of each level is generated (maths, binary, hex, sequences...),
     so there are always fresh questions at any level.
   - To add more questions, just add rows to QUIZ_BANK:
     [ "Question?", "Correct answer", ["Wrong 1", "Wrong 2", "Wrong 3"] ]
   ========================================================= */

const QUIZ_BANK = [
    ["Which language is mainly used to style web pages?", "CSS", ["HTML", "SQL", "Python"]],
    ["Which data structure follows FIFO?", "Queue", ["Stack", "Tree", "Graph"]],
    ["What does CPU stand for?", "Central Processing Unit", ["Computer Primary Utility", "Central Program User", "Control Processing Utility"]],
    ["Which SQL command retrieves data?", "SELECT", ["GET", "PUSH", "FETCHALL"]],
    ["Which Python collection stores key-value pairs?", "Dictionary", ["List", "Tuple", "String"]],
    ["Which protocol is commonly used for secure web browsing?", "HTTPS", ["FTP", "SMTP", "Telnet"]],
    ["Which number system uses only 0 and 1?", "Binary", ["Decimal", "Octal", "Hexadecimal"]],
    ["Which of these is a relational database?", "MySQL", ["HTML", "CSS", "React"]],
    ["Which keyword declares a constant in JavaScript?", "const", ["let", "var", "static"]],
    ["What is the full form of AI?", "Artificial Intelligence", ["Automated Internet", "Advanced Interface", "Applied Integration"]],
    ["Which data structure follows LIFO?", "Stack", ["Queue", "Array", "Graph"]],
    ["What does RAM stand for?", "Random Access Memory", ["Read Access Memory", "Rapid Action Memory", "Run Anytime Memory"]],
    ["What does HTML stand for?", "HyperText Markup Language", ["High Tech Modern Language", "Hyperlinks Text Mode Language", "Home Tool Markup Language"]],
    ["Which HTML tag creates the largest heading?", "<h1>", ["<h6>", "<head>", "<title>"]],
    ["Which symbol starts a single-line comment in Python?", "#", ["//", "/*", "--"]],
    ["Which SQL clause filters rows?", "WHERE", ["ORDER BY", "GROUP BY", "LIMIT"]],
    ["Which of these is NOT a programming language?", "HTTP", ["Python", "Java", "Ruby"]],
    ["Which company created the Java language?", "Sun Microsystems", ["Microsoft", "Apple", "Google"]],
    ["Who is known as the father of the computer?", "Charles Babbage", ["Isaac Newton", "Thomas Edison", "Nikola Tesla"]],
    ["What is the time complexity of binary search?", "O(log n)", ["O(n)", "O(n²)", "O(1)"]],
    ["Which key uniquely identifies each row in a table?", "Primary key", ["Foreign key", "Index", "View"]],
    ["Which Python function shows output on the screen?", "print()", ["echo()", "write()", "show()"]],
    ["Which HTML tag creates a hyperlink?", "<a>", ["<link>", "<href>", "<url>"]],
    ["What does URL stand for?", "Uniform Resource Locator", ["Universal Reference Link", "Uniform Retrieval Logic", "United Resource Locator"]],
    ["How many bits are in one byte?", "8", ["4", "16", "2"]],
    ["Which of these is an operating system?", "Linux", ["Oracle", "Python", "Excel"]],
    ["Which HTTP status code means Not Found?", "404", ["200", "500", "301"]],
    ["Which HTTP status code means OK?", "200", ["404", "500", "403"]],
    ["Which Git command saves changes to the local repository?", "git commit", ["git push", "git clone", "git pull"]],
    ["Which CSS property changes the text colour?", "color", ["font-style", "text-align", "background"]],
    ["Which loop always runs at least once?", "do...while", ["for", "while", "foreach"]],
    ["Which data type stores True or False?", "Boolean", ["Integer", "String", "Float"]],
    ["Which sorting algorithm repeatedly swaps neighbouring items?", "Bubble sort", ["Merge sort", "Quick sort", "Heap sort"]],
    ["Which of these is NOT a JavaScript framework or library?", "Django", ["React", "Vue", "Angular"]],
    ["Flask is a web framework written in which language?", "Python", ["Java", "PHP", "Ruby"]],
    ["Which SQL statement adds a new row to a table?", "INSERT INTO", ["ADD NEW", "APPEND", "PUT"]],
    ["Which operator checks strict equality in JavaScript?", "===", ["=", "==", "!="]],
    ["Which of these is an input device?", "Keyboard", ["Monitor", "Printer", "Speaker"]],
    ["Which of these is an output device?", "Printer", ["Mouse", "Scanner", "Keyboard"]],
    ["What does GPU stand for?", "Graphics Processing Unit", ["General Program Unit", "Graphical Power Utility", "Game Processing Unit"]],
    ["Which Python keyword defines a function?", "def", ["func", "function", "define"]],
    ["What does CSS stand for?", "Cascading Style Sheets", ["Creative Style System", "Computer Style Sheets", "Colorful Style Syntax"]],
    ["Which JavaScript method adds an item to the end of an array?", "push()", ["pop()", "shift()", "unshift()"]],
    ["Which Python function returns the length of a list?", "len()", ["size()", "count()", "length()"]],
    ["In a Python list, the first item has which index?", "0", ["1", "-1", "2"]],
    ["Which HTML tag inserts an image?", "<img>", ["<image>", "<pic>", "<src>"]],
    ["Which CSS feature is designed for two-dimensional layouts?", "Grid", ["Flexbox", "Float", "Position"]],
    ["Which of these is a NoSQL database?", "MongoDB", ["MySQL", "PostgreSQL", "Oracle"]],
    ["Which company developed the Windows operating system?", "Microsoft", ["Apple", "IBM", "Google"]],
    ["Which operator means logical AND in JavaScript?", "&&", ["||", "!", "=="]],
    ["What does DNS do?", "Turns domain names into IP addresses", ["Encrypts files", "Compresses images", "Blocks viruses"]],
    ["What does API stand for?", "Application Programming Interface", ["Applied Program Integration", "Automated Page Index", "Advanced Python Interface"]],
    ["Which language is officially preferred by Google for Android apps?", "Kotlin", ["Swift", "Objective-C", "Perl"]],
    ["What is the capital of India?", "New Delhi", ["Mumbai", "Kolkata", "Chennai"]],
    ["Which planet is known as the Red Planet?", "Mars", ["Venus", "Jupiter", "Saturn"]],
    ["What is the chemical formula of water?", "H2O", ["CO2", "O2", "NaCl"]],
    ["Which is the largest planet in our solar system?", "Jupiter", ["Saturn", "Earth", "Neptune"]],
    ["Which gas do plants absorb for photosynthesis?", "Carbon dioxide", ["Oxygen", "Nitrogen", "Hydrogen"]],
    ["Which star is closest to the Earth?", "The Sun", ["Proxima Centauri", "Sirius", "Polaris"]],
    ["How many continents are there on Earth?", "7", ["5", "6", "8"]],
    ["Which is the largest ocean?", "Pacific Ocean", ["Atlantic Ocean", "Indian Ocean", "Arctic Ocean"]],
    ["What is the square root of 144?", "12", ["14", "11", "13"]],
    ["What is the sum of the angles of a triangle?", "180°", ["90°", "360°", "270°"]],
    ["Which value is closest to pi?", "3.14", ["2.71", "1.62", "4.13"]],
    ["Which is the hardest natural substance?", "Diamond", ["Gold", "Iron", "Quartz"]],
    ["Who is credited with writing the original Sanskrit Ramayana?", "Valmiki", ["Vyasa", "Kalidasa", "Tulsidas"]],
    ["What is the national animal of India?", "Tiger", ["Lion", "Elephant", "Leopard"]],
    ["Which organ pumps blood around the body?", "Heart", ["Lungs", "Liver", "Kidney"]],
    ["What is the approximate speed of light?", "300,000 km/s", ["150,000 km/s", "30,000 km/s", "3,000 km/s"]],
    ["Which vitamin does the body make from sunlight?", "Vitamin D", ["Vitamin C", "Vitamin A", "Vitamin B12"]],
    ["What is the smallest prime number?", "2", ["1", "3", "0"]],
    ["Which Roman numeral stands for 50?", "L", ["C", "X", "D"]],
    ["How many sides does a hexagon have?", "6", ["5", "8", "7"]],
    ["At what temperature (°C) does water boil at sea level?", "100", ["90", "212", "120"]]
];

// Small seeded random generator: the same seed always gives the same order.
const seededRandom = seed => {
    let a = seed >>> 0;

    return () => {
        a = (a + 0x6D2B79F5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
};

// Fixed shuffled order of the bank, so levels take different slices of it.
const QUIZ_ORDER = (() => {
    const rand = seededRandom(20260614);
    const idx = QUIZ_BANK.map((_, i) => i);

    for (let i = idx.length - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [idx[i], idx[j]] = [idx[j], idx[i]];
    }

    return idx;
})();

const quizCount = lvl => Math.min(5 + lvl, 20);
const quizStaticTake = lvl => Math.ceil(quizCount(lvl) * 0.4);

const makeQuestion = (q, correct, wrongs) => {
    const right = String(correct);
    const options = shuffle([right, ...wrongs.map(String)]);

    return { q, options, answer: options.indexOf(right) };
};

// Three different wrong numbers close to the right one.
const numOptions = (correct, spread = 10) => {
    const set = new Set([correct]);
    let guard = 0;

    while (set.size < 4 && guard++ < 200) {
        const d = (1 + rnd(spread)) * (Math.random() < 0.5 ? -1 : 1);
        if (correct + d >= 0) set.add(correct + d);
    }

    let k = 1;
    while (set.size < 4) set.add(correct + spread + k++);

    return [...set].filter(v => v !== correct).slice(0, 3);
};

// A fresh question that gets harder as the level grows.
const generateQuestion = level => {
    const n = (min, max) => min + rnd(max - min + 1);
    const scale = 10 + level * 5;

    switch (pick(["add", "sub", "mul", "bin2dec", "dec2bin", "hex", "percent", "seq", "square", "pow2"])) {
        case "add": {
            const a = n(10, scale), b = n(10, scale);
            return makeQuestion(`What is ${a} + ${b}?`, a + b, numOptions(a + b));
        }
        case "sub": {
            const a = n(20, scale * 2), b = n(5, a - 1);
            return makeQuestion(`What is ${a} − ${b}?`, a - b, numOptions(a - b));
        }
        case "mul": {
            const a = n(3, 5 + level), b = n(3, 9 + Math.floor(level / 2));
            return makeQuestion(`What is ${a} × ${b}?`, a * b, numOptions(a * b));
        }
        case "bin2dec": {
            const bits = Math.min(3 + Math.floor(level / 3), 8);
            const v = n(1 << (bits - 1), (1 << bits) - 1);
            return makeQuestion(`Binary ${v.toString(2)} equals which decimal number?`, v, numOptions(v, 6));
        }
        case "dec2bin": {
            const v = n(5, Math.min(15 + level * 6, 250));
            return makeQuestion(
                `What is the decimal number ${v} in binary?`,
                v.toString(2),
                numOptions(v, 4).map(x => x.toString(2))
            );
        }
        case "hex": {
            const v = n(16, 255);
            return makeQuestion(`Hex ${v.toString(16).toUpperCase()} equals which decimal number?`, v, numOptions(v, 12));
        }
        case "percent": {
            const p = pick([10, 20, 25, 50, 75]);
            const v = 20 * n(1, 5 + level * 2);
            const r = (p * v) / 100;
            return makeQuestion(`What is ${p}% of ${v}?`, r, numOptions(r, Math.max(3, Math.round(r / 4))));
        }
        case "seq": {
            const a = n(1, 10), d = n(2, 3 + Math.floor(level / 2));
            return makeQuestion(
                `What comes next? ${a}, ${a + d}, ${a + 2 * d}, ${a + 3 * d}, ?`,
                a + 4 * d,
                numOptions(a + 4 * d, 6)
            );
        }
        case "square": {
            const m = n(3, 12 + level);
            return makeQuestion(`What is ${m}²?`, m * m, numOptions(m * m, Math.max(4, m)));
        }
        default: {
            const k = n(3, Math.min(4 + Math.floor(level / 2), 16));
            return makeQuestion(`What is 2 to the power ${k}?`, 2 ** k, numOptions(2 ** k, Math.max(2, 2 ** (k - 2))));
        }
    }
};

// Builds the question list for one level.
const buildQuizSet = level => {
    const count = quizCount(level);

    // each level continues where the previous level stopped in the bank
    let offset = 0;
    for (let l = 1; l < level; l++) offset += quizStaticTake(l);
    offset %= QUIZ_ORDER.length;

    const take = Math.min(quizStaticTake(level), QUIZ_ORDER.length);
    const picked = [];

    for (let i = 0; i < take; i++) {
        const [q, correct, wrongs] = QUIZ_BANK[QUIZ_ORDER[(offset + i) % QUIZ_ORDER.length]];
        picked.push(makeQuestion(q, correct, wrongs));
    }

    const seen = new Set(picked.map(x => x.q));
    let guard = 0;

    while (picked.length < count && guard++ < 1000) {
        const g = generateQuestion(level);

        if (g && !seen.has(g.q)) {
            seen.add(g.q);
            picked.push(g);
        }
    }

    return shuffle(picked);
};

/* =========================================================
   GAME 11: QUIZ BATTLE
   ========================================================= */

function gameQuizBattle() {
    resetGame();

    addHeading("⚔️ Quiz Battle Arena", "Answer correctly to damage the monster. Win at 60% or more!");

    const level = currentLevel();

    // different questions for every level, never repeated inside a level
    const selected = buildQuizSet(level);

    const needed = Math.ceil(selected.length * 0.6);
    const allowedWrong = selected.length - needed;

    const arena = el("div", "qb-arena",
        `<div class="qb-fighter"><div class="qb-sprite">🧙</div><div class="qb-hp me"><i></i></div>You</div>
         <div class="qb-vs">VS</div>
         <div class="qb-fighter"><div class="qb-sprite">👾</div><div class="qb-hp foe"><i></i></div>Monster</div>`);

    const [meSprite, foeSprite] = arena.querySelectorAll(".qb-sprite");
    const meHp = arena.querySelector(".qb-hp.me i");
    const foeHp = arena.querySelector(".qb-hp.foe i");

    const questionBox = el("div", "qb-q");
    const optionsBox = el("div", "qb-opts");

    area.append(arena, questionBox, optionsBox);

    const status = makeStatus("Choose the correct answer.");

    let position = 0;
    let correct = 0;
    let wrong = 0;
    let answered = false;

    const hit = sprite => {
        sprite.classList.remove("hit");
        void sprite.offsetWidth;
        sprite.classList.add("hit");
    };

    function renderQuestion() {
        if (over) return;

        if (position >= selected.length) {
            const finalScore = correct * 100;

            setScore(finalScore);

            if (correct >= needed) {
                status("🎉 Battle won! Saving your reward...", "win");
                winLater(finalScore, 600);
            } else {
                loseLater("Quiz battle lost. You need at least 60% correct.", 300);
            }

            return;
        }

        answered = false;

        const item = selected[position];

        questionBox.innerHTML = "";
        questionBox.style.animation = "none";
        void questionBox.offsetWidth;
        questionBox.style.animation = "";

        const heading = el("h3");
        heading.textContent = `Question ${position + 1} of ${selected.length}`;

        const questionText = el("p");
        questionText.textContent = item.q;

        questionBox.append(heading, questionText);

        optionsBox.innerHTML = "";

        item.options.forEach((option, index) => {
            const button = makeButton(option, () => choose(index, button), "qb-opt");
            button.style.animationDelay = `${index * 70}ms`;
            optionsBox.append(button);
        });

        status("Choose your answer.");
    }

    function choose(index, button) {
        if (over || answered) return;

        answered = true;
        addMove();

        const item = selected[position];
        const buttons = [...optionsBox.children];

        buttons.forEach(b => { b.disabled = true; });
        buttons[item.answer].classList.add("ok");

        if (index === item.answer) {
            correct++;
            addScore(100);
            hit(foeSprite);
            foeHp.style.width = `${Math.max(0, 1 - correct / needed) * 100}%`;
            status("⚔️ Direct hit! +100 points", "win");
        } else {
            wrong++;
            button.classList.add("bad");
            wrongAlert("Wrong answer!");
            hit(meSprite);
            meHp.style.width = `${Math.max(0, 1 - wrong / (allowedWrong + 1)) * 100}%`;
            status(`Ouch! Correct answer: ${item.options[item.answer]}`, "lose");

            // too many wrong answers: the level can no longer be won, show the X popup now
            if (wrong > allowedWrong) {
                later(1300, () => finishLose(
                    `Too many wrong answers. You need at least ${needed} of ${selected.length} correct.`,
                    "Level Failed"
                ));
                return;
            }
        }

        later(1100, () => {
            position++;
            renderQuestion();
        });
    }

    // HINT: 50-50, two wrong answers fade away
    onHint(() => {
        if (over || answered) return false;

        const item = selected[position];
        const buttons = [...optionsBox.children];
        const wrongs = buttons.map((_, i) => i).filter(i => i !== item.answer && !buttons[i].disabled);

        if (wrongs.length <= 1) return false;

        shuffle(wrongs).slice(0, 2).forEach(i => {
            buttons[i].disabled = true;
            buttons[i].style.opacity = ".25";
        });

        return true;
    });

    renderQuestion();
}

/* =========================================================
   GAME 12: TETRIS
   ========================================================= */

function gameTetrisBlocks() {
    resetGame();

    addHeading("🧱 Tetris Blocks", "Move and rotate blocks to complete horizontal lines.");

    const cols = 10, rows = 16, cell = 38;
    const W = cols * cell, H = rows * cell;
    const level = currentLevel();
    const target = Math.min(900 + level * 100, 6000);
    const interval = Math.max(120, 650 - level * 30);

    const [canvas, ctx] = cv(area, W, H, 420);
    const status = makeStatus(`Reach ${target} points. ← → move, ↑ rotate, ↓ drop, Space = hard drop.`);
    const fx = makeFX();

    const shapes = [
        [[1, 1, 1, 1]],
        [[1, 1], [1, 1]],
        [[0, 1, 0], [1, 1, 1]],
        [[1, 0, 0], [1, 1, 1]],
        [[0, 0, 1], [1, 1, 1]],
        [[1, 1, 0], [0, 1, 1]],
        [[0, 1, 1], [1, 1, 0]]
    ];

    const colors = ["#22d3ee", "#facc15", "#a78bfa", "#fb923c", "#60a5fa", "#4ade80", "#f472b6"];

    let grid = Array.from({ length: rows }, () => Array(cols).fill(0));
    let piece = null;
    let dropTimer = 0;
    let dead = false, won = false;
    const flashes = [];

    function collides(px, py, shape) {
        for (let y = 0; y < shape.length; y++) {
            for (let x = 0; x < shape[y].length; x++) {
                if (!shape[y][x]) continue;

                const gx = px + x;
                const gy = py + y;

                if (gx < 0 || gx >= cols || gy >= rows || (gy >= 0 && grid[gy][gx])) return true;
            }
        }

        return false;
    }

    function newPiece() {
        const index = rnd(shapes.length);
        const shape = shapes[index].map(row => [...row]);

        piece = {
            shape,
            color: colors[index],
            x: Math.floor((cols - shape[0].length) / 2),
            y: 0
        };

        if (collides(piece.x, piece.y, piece.shape)) {
            dead = true;
            shake(canvas);
            loseLater("No space left! Game over.", 600);
        }
    }

    const rotate = shape => shape[0].map((_, col) => shape.map(row => row[col]).reverse());

    function merge() {
        piece.shape.forEach((row, y) => {
            row.forEach((value, x) => {
                if (!value) return;

                const gy = piece.y + y;
                const gx = piece.x + x;

                if (gy >= 0) grid[gy][gx] = piece.color;
            });
        });

        addMove();   // one move = one block placed

        const clearedRows = [];

        grid.forEach((row, r) => { if (row.every(Boolean)) clearedRows.push(r); });

        if (clearedRows.length) {
            clearedRows.forEach(r => {
                flashes.push({ row: r, t: 1 });

                for (let c = 0; c < cols; c++) {
                    fx.burst(c * cell + cell / 2, r * cell + cell / 2, grid[r][c], 3, 4);
                }
            });

            grid = grid.filter(row => !row.every(Boolean));
            while (grid.length < rows) grid.unshift(Array(cols).fill(0));

            addScore(clearedRows.length * clearedRows.length * 100);
            fx.text(W / 2, clearedRows[0] * cell, `+${clearedRows.length * clearedRows.length * 100}`, "#facc15");
        }

        if (score >= target) {
            won = true;
            piece = null;
            status("🎉 Target score reached! Saving reward...", "win");
            winLater(score, 900);
            return;
        }

        newPiece();
    }

    function drop() {
        if (over || dead || won || !piece) return;

        if (!collides(piece.x, piece.y + 1, piece.shape)) {
            piece.y++;
        } else {
            merge();
        }
    }

    function hardDrop() {
        if (over || dead || won || !piece) return;

        while (!collides(piece.x, piece.y + 1, piece.shape)) piece.y++;
        merge();
    }

    function block(x, y, color, alpha = 1) {
        ctx.globalAlpha = alpha;
        ctx.fillStyle = color;
        rr(ctx, x + 1, y + 1, cell - 2, cell - 2, 7);
        ctx.fill();

        ctx.fillStyle = "rgba(255,255,255,.35)";
        rr(ctx, x + 4, y + 4, cell - 8, (cell - 8) * 0.35, 4);
        ctx.fill();

        ctx.fillStyle = "rgba(0,0,0,.18)";
        ctx.fillRect(x + 4, y + cell - 8, cell - 8, 3);
        ctx.globalAlpha = 1;
    }

    // HINT ghost (declared before draw so draw can read it)
    let hintGhost = null;

    function draw() {
        const bg = ctx.createLinearGradient(0, 0, 0, H);
        bg.addColorStop(0, "#111827");
        bg.addColorStop(1, "#1e1b4b");
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, W, H);

        ctx.strokeStyle = "rgba(255,255,255,.05)";
        ctx.lineWidth = 1;

        for (let x = 1; x < cols; x++) {
            ctx.beginPath(); ctx.moveTo(x * cell, 0); ctx.lineTo(x * cell, H); ctx.stroke();
        }
        for (let y = 1; y < rows; y++) {
            ctx.beginPath(); ctx.moveTo(0, y * cell); ctx.lineTo(W, y * cell); ctx.stroke();
        }

        for (let y = 0; y < rows; y++) {
            for (let x = 0; x < cols; x++) {
                if (grid[y][x]) block(x * cell, y * cell, grid[y][x]);
            }
        }

        if (piece) {
            let gy = piece.y;
            while (!collides(piece.x, gy + 1, piece.shape)) gy++;

            piece.shape.forEach((row, y) => row.forEach((value, x) => {
                if (value) block((piece.x + x) * cell, (gy + y) * cell, piece.color, 0.22);
            }));

            piece.shape.forEach((row, y) => row.forEach((value, x) => {
                if (value) block((piece.x + x) * cell, (piece.y + y) * cell, piece.color);
            }));
        }

        if (hintGhost && performance.now() < hintGhost.until) {
            ctx.save();
            ctx.strokeStyle = "#22c55e";
            ctx.lineWidth = 4;
            ctx.setLineDash([8, 5]);

            hintGhost.shape.forEach((row, y) => row.forEach((v, x) => {
                if (!v) return;
                rr(ctx, (hintGhost.x + x) * cell + 3, (hintGhost.y + y) * cell + 3, cell - 6, cell - 6, 7);
                ctx.stroke();
            }));

            ctx.restore();
        }

        flashes.forEach(f => {
            ctx.fillStyle = `rgba(255,255,255,${f.t * 0.8})`;
            ctx.fillRect(0, f.row * cell, W, cell);
        });

        fx.draw(ctx);

        txt(ctx, `${score} / ${target}`, W - 10, 24, "bold 18px sans-serif", "#e2e8f0", "right");
    }

    function control(action) {
        if (over || dead || won || !piece) return;

        if (action === "left" && !collides(piece.x - 1, piece.y, piece.shape)) {
            piece.x--;
        } else if (action === "right" && !collides(piece.x + 1, piece.y, piece.shape)) {
            piece.x++;
        } else if (action === "down") {
            drop();
        } else if (action === "rotate") {
            const rotated = rotate(piece.shape);

            if (!collides(piece.x, piece.y, rotated)) piece.shape = rotated;
            else if (!collides(piece.x - 1, piece.y, rotated)) { piece.x--; piece.shape = rotated; }
            else if (!collides(piece.x + 1, piece.y, rotated)) { piece.x++; piece.shape = rotated; }
        }
    }

    on(window, "keydown", event => {
        if (event.code === "Space") {
            event.preventDefault();
            hardDrop();
            return;
        }

        const dir = dirFromEvent(event);
        if (!dir) return;

        event.preventDefault();
        control(dir === "up" ? "rotate" : dir);
    });

    // swipe on the board: left/right move, down drops, up rotates
    swipe(canvas, dir => control(dir === "up" ? "rotate" : dir));

    // on-screen buttons (always shown, so phones and tablets work)
    const controls = el("div", "tetris-controls");

    controls.style.display = "flex";
    controls.style.flexWrap = "wrap";
    controls.style.justifyContent = "center";
    controls.style.gap = "10px";
    controls.style.marginTop = "8px";

    [["◀", "left"], ["⟳", "rotate"], ["▼", "down"], ["▶", "right"], ["⏬", "hard"]].forEach(([label, action]) => {
        const button = el("button", "gbtn secondary", label);

        button.type = "button";
        button.style.minWidth = "58px";
        button.style.minHeight = "56px";
        button.style.fontSize = "22px";
        button.style.padding = "0 12px";
        button.addEventListener("pointerdown", e => {
            e.preventDefault();
            if (action === "hard") hardDrop();
            else control(action);
        });

        controls.append(button);
    });

    area.append(controls);

    // HINT: show (dotted green) the best place for the falling block
    function evaluate(shape, x, y) {
        const g = grid.map(r => [...r]);

        shape.forEach((row, sy) => row.forEach((v, sx) => {
            if (v && y + sy >= 0) g[y + sy][x + sx] = 1;
        }));

        let lines = 0;
        g.forEach(r => { if (r.every(Boolean)) lines++; });

        let holes = 0;
        let height = 0;

        for (let c = 0; c < cols; c++) {
            let seen = false;

            for (let r = 0; r < rows; r++) {
                if (g[r][c]) {
                    if (!seen) { seen = true; height += rows - r; }
                } else if (seen) {
                    holes++;
                }
            }
        }

        return lines * 8 - holes * 5 - height * 0.3;
    }

    onHint(() => {
        if (!piece || over || dead || won) return false;

        let shape = piece.shape;
        let best = null;

        for (let rot = 0; rot < 4; rot++) {
            for (let x = 0; x < cols; x++) {
                if (collides(x, 0, shape)) continue;

                let y = 0;
                while (!collides(x, y + 1, shape)) y++;

                const s = evaluate(shape, x, y);
                if (!best || s > best.s) best = { s, shape, x, y };
            }

            shape = rotate(shape);
        }

        if (!best) return false;

        hintGhost = { shape: best.shape, x: best.x, y: best.y, until: performance.now() + 4000 };
        return true;
    });

    loop(dt => {
        dropTimer += dt * 16.667;

        if (dropTimer >= interval) {
            dropTimer = 0;
            drop();
        }

        for (let i = flashes.length - 1; i >= 0; i--) {
            flashes[i].t -= 0.07 * dt;
            if (flashes[i].t <= 0) flashes.splice(i, 1);
        }

        fx.update(dt);
        draw();
    });

    newPiece();
    draw();
}

/* =========================================================
   GAME 13: FLAPPY BRAIN
   ========================================================= */

function gameFlappyBrain() {
    resetGame();

    addHeading("🐦 Flappy Brain", "Tap, click or press Space to flap through the gaps.");

    const W = 460, H = 600, GROUND = 70;
    const level = currentLevel();
    const goal = Math.min(5 + level, 20);

    const [canvas, ctx] = cv(area, W, H, 480);
    const status = makeStatus(`Tap the game or press Space to start. Pass ${goal} gates.`);
    const fx = makeFX();

    const BX = 110, BR = 16, PW = 70;
    const gap = Math.max(165, 215 - level * 3);
    const speed = Math.min(2.8 + level * 0.1, 4.6);

    let birdY = H / 2 - 40;
    let vel = 0;
    let started = false, dead = false, won = false;
    let passed = 0, t = 0, scroll = 0, spawnDist = 999, flapT = 0;
    let obstacles = [];

    const clouds = Array.from({ length: 5 }, () => ({
        x: Math.random() * W, y: 30 + Math.random() * 200, s: 0.7 + Math.random() * 0.8
    }));

    function addObstacle() {
        const margin = 70;
        const top = margin + Math.random() * (H - GROUND - gap - margin * 2);

        obstacles.push({ x: W + 30, top, bottom: top + gap, counted: false });
    }

    function flap() {
        if (over || dead || won) return;

        if (!started) {
            started = true;
            status(`Pass ${goal} gates!`);
        }

        vel = -6.8;
        flapT = 1;
        addMove();
        fx.burst(BX - 12, birdY + 8, "#ffffff", 5, 2);
    }

    on(window, "keydown", event => {
        if (event.code === "Space" || event.code === "ArrowUp" || event.code === "KeyW") {
            event.preventDefault();
            flap();
        }
    });

    on(canvas, "pointerdown", e => { e.preventDefault(); flap(); });
    area.append(makeButton("⬆ Flap", flap));

    // HINT: dotted green line to the middle of the next gap
    let hintUntil = 0;

    onHint(() => {
        if (!started || dead || won || !obstacles.some(o => o.x + PW > BX - BR)) return false;
        hintUntil = t + 220;
        return true;
    });

    function drawPipe(x, y, h, capAtBottom) {
        const g = ctx.createLinearGradient(x, 0, x + PW, 0);
        g.addColorStop(0, "#15803d");
        g.addColorStop(0.5, "#4ade80");
        g.addColorStop(1, "#15803d");
        ctx.fillStyle = g;
        ctx.fillRect(x, y, PW, h);

        const capY = capAtBottom ? y + h - 28 : y;
        ctx.fillStyle = g;
        rr(ctx, x - 6, capY, PW + 12, 28, 8);
        ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,.25)";
        ctx.lineWidth = 2;
        ctx.stroke();
    }

    function draw() {
        const sky = ctx.createLinearGradient(0, 0, 0, H);
        sky.addColorStop(0, "#60a5fa");
        sky.addColorStop(1, "#dbeafe");
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, W, H);

        ctx.fillStyle = "#fde047";
        ctx.beginPath();
        ctx.arc(370, 90, 34, 0, Math.PI * 2);
        ctx.fill();

        clouds.forEach(c => {
            ctx.fillStyle = "rgba(255,255,255,.85)";
            ctx.beginPath();
            ctx.ellipse(c.x, c.y, 46 * c.s, 16 * c.s, 0, 0, Math.PI * 2);
            ctx.ellipse(c.x + 26 * c.s, c.y - 8 * c.s, 28 * c.s, 14 * c.s, 0, 0, Math.PI * 2);
            ctx.fill();
        });

        ctx.fillStyle = "#86efac";
        ctx.beginPath();
        ctx.moveTo(0, H - GROUND);
        for (let x = 0; x <= W; x += 20) {
            ctx.lineTo(x, H - GROUND - 50 - Math.sin((x + scroll * 0.3) / 60) * 24);
        }
        ctx.lineTo(W, H - GROUND);
        ctx.closePath();
        ctx.fill();

        obstacles.forEach(o => {
            drawPipe(o.x, 0, o.top, true);
            drawPipe(o.x, o.bottom, H - GROUND - o.bottom, false);
        });

        ctx.fillStyle = "#854d0e";
        ctx.fillRect(0, H - GROUND, W, GROUND);
        ctx.fillStyle = "#65a30d";
        ctx.fillRect(0, H - GROUND, W, 12);
        ctx.fillStyle = "rgba(0,0,0,.18)";
        for (let x = -(scroll % 40); x < W; x += 40) ctx.fillRect(x, H - GROUND + 30, 20, 5);

        ctx.save();
        ctx.translate(BX, birdY);
        ctx.rotate(clamp(vel * 0.06, -0.5, 1));

        const wing = Math.sin(t * 0.5) * 8 * (started ? 1 : 0.4) - flapT * 6;
        ctx.fillStyle = "rgba(255,255,255,.95)";
        ctx.beginPath();
        ctx.ellipse(-10, 4 + wing, 14, 7, -0.5, 0, Math.PI * 2);
        ctx.fill();

        ctx.textBaseline = "middle";
        ctx.font = "36px serif";
        ctx.textAlign = "center";
        ctx.fillText("🧠", 0, 0);
        ctx.restore();

        if (t < hintUntil) {
            const o = obstacles.find(ob => ob.x + PW > BX - BR);

            if (o) {
                const gx = o.x + PW / 2;
                const gy = (o.top + o.bottom) / 2;

                ctx.save();
                ctx.strokeStyle = "#16a34a";
                ctx.lineWidth = 4;
                ctx.setLineDash([10, 8]);
                ctx.beginPath();
                ctx.moveTo(BX, birdY);
                ctx.lineTo(gx, gy);
                ctx.stroke();
                ctx.restore();

                ctx.fillStyle = "rgba(34,197,94,.35)";
                ctx.beginPath();
                ctx.arc(gx, gy, 30, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        fx.draw(ctx);

        if (!started && !dead) {
            txt(ctx, "TAP TO START", W / 2, H / 2 + 60 + Math.sin(t * 0.1) * 6, "bold 28px sans-serif", "#1e3a8a");
        }

        txt(ctx, `Gates: ${passed} / ${goal}`, 16, 34, "bold 22px sans-serif", "#0f172a", "left");
    }

    loop(dt => {
        t += dt;
        flapT = Math.max(0, flapT - 0.1 * dt);
        clouds.forEach(c => { c.x -= c.s * 0.3 * dt; if (c.x < -80) c.x = W + 60; });

        if (!started && !dead) {
            birdY = H / 2 - 40 + Math.sin(t * 0.08) * 8;
        } else if (!won) {
            if (!dead) scroll += speed * dt;

            vel = Math.min(vel + 0.38 * dt, 10);
            birdY += vel * dt;

            if (birdY < BR) { birdY = BR; vel = Math.max(vel, 0); }

            if (!dead) {
                spawnDist += speed * dt;

                if (spawnDist >= 270) {
                    spawnDist = 0;
                    addObstacle();
                }

                for (const o of obstacles) {
                    o.x -= speed * dt;

                    if (!o.counted && o.x + PW < BX - BR) {
                        o.counted = true;
                        passed++;
                        addScore(100);
                        fx.text(BX + 30, birdY - 30, "+100", "#16a34a");
                        status(`Great! ${passed} gate${passed === 1 ? "" : "s"} passed.`);
                    }

                    const overlapsX = BX + BR - 3 > o.x && BX - BR + 3 < o.x + PW;
                    const hitsPipe = birdY - BR + 3 < o.top || birdY + BR - 3 > o.bottom;

                    if (overlapsX && hitsPipe) {
                        dead = true;
                        fx.burst(BX, birdY, "#f472b6", 22, 5);
                        shake(canvas);
                        loseLater("You hit an obstacle!", 700);
                        break;
                    }
                }

                obstacles = obstacles.filter(o => o.x > -PW - 20);

                if (!dead && birdY + BR > H - GROUND) {
                    dead = true;
                    birdY = H - GROUND - BR;
                    fx.burst(BX, birdY, "#f472b6", 22, 5);
                    shake(canvas);
                    loseLater("The brain hit the ground!", 700);
                } else if (!dead && passed >= goal) {
                    won = true;
                    status("🎉 Flight target completed! Saving reward...", "win");

                    for (let i = 0; i < 5; i++) {
                        fx.burst(80 + i * 75, 140 + rnd(120), pick(["#facc15", "#22c55e", "#f472b6", "#38bdf8"]), 14, 6);
                    }

                    winLater(score, 900);
                }
            } else if (birdY + BR > H - GROUND) {
                birdY = H - GROUND - BR;
                vel = 0;
            }
        }

        fx.update(dt);
        draw();
    });

    draw();
}

/* =========================================================
   GAME 14: SNAKE
   ========================================================= */

function gameSnake() {
    resetGame();

    addHeading("🐍 Snake Game", "Collect food, grow longer, and avoid hitting yourself.");

    const cols = 22, rows = 22, cell = 26;
    const W = cols * cell, H = rows * cell;
    const level = currentLevel();
    const target = Math.min(5 + level, 25);
    const interval = Math.max(65, 150 - level * 3);

    const [canvas, ctx] = cv(area, W, H, 600);
    const status = makeStatus(`Eat ${target} apples. Use arrow keys, WASD, swipe or the pad.`);
    const fx = makeFX();

    let snake = [{ x: 9, y: 11 }, { x: 8, y: 11 }, { x: 7, y: 11 }];
    let old = snake.map(s => ({ ...s }));

    let direction = { x: 1, y: 0 };
    let nextDirection = { x: 1, y: 0 };
    let collected = 0;
    let acc = 0, t = 0;
    let dead = false, won = false;

    function makeFood() {
        let position;

        do {
            position = { x: rnd(cols), y: rnd(rows) };
        } while (snake.some(part => part.x === position.x && part.y === position.y));

        return position;
    }

    let food = makeFood();

    function setDirection(x, y) {
        if (over || dead || won) return;
        // cannot turn back on yourself (checked against the direction already moving)
        if (x === -direction.x && y === -direction.y) return;

        nextDirection = { x, y };
    }

    const DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

    keys(dir => setDirection(...DIRS[dir]));
    swipe(canvas, dir => setDirection(...DIRS[dir]));

    dpad({
        up: () => setDirection(0, -1),
        down: () => setDirection(0, 1),
        left: () => setDirection(-1, 0),
        right: () => setDirection(1, 0)
    });

    // HINT: dotted yellow line from the head to the apple
    let hintUntil = 0;

    onHint(() => {
        if (dead || won) return false;
        hintUntil = t + 260;
        return true;
    });

    function tick() {
        direction = nextDirection;
        old = snake.map(s => ({ ...s }));

        const head = { x: snake[0].x + direction.x, y: snake[0].y + direction.y };

        if (head.x < 0 || head.x >= cols || head.y < 0 || head.y >= rows) {
            dead = true;
            shake(canvas);
            fx.burst(snake[0].x * cell + cell / 2, snake[0].y * cell + cell / 2, "#22c55e", 20, 5);
            loseLater("The snake hit the wall!", 600);
            return;
        }

        const eating = head.x === food.x && head.y === food.y;
        const bodyToCheck = eating ? snake : snake.slice(0, -1);

        if (bodyToCheck.some(part => part.x === head.x && part.y === head.y)) {
            dead = true;
            shake(canvas);
            fx.burst(head.x * cell + cell / 2, head.y * cell + cell / 2, "#22c55e", 20, 5);
            loseLater("The snake collided with itself!", 600);
            return;
        }

        addMove();   // one move = one step
        snake.unshift(head);

        if (eating) {
            collected++;
            addScore(100);
            fx.burst(food.x * cell + cell / 2, food.y * cell + cell / 2, "#ef4444", 14, 4);
            fx.text(food.x * cell + cell / 2, food.y * cell, "+100", "#fde047");
            food = makeFood();

            status(`Apples: ${collected}/${target}`);

            if (collected >= target) {
                won = true;
                status("🎉 Target reached! Saving your reward...", "win");
                winLater(score, 900);
            }
        } else {
            snake.pop();
        }
    }

    function draw(p) {
        for (let y = 0; y < rows; y++) {
            for (let x = 0; x < cols; x++) {
                ctx.fillStyle = (x + y) % 2 ? "#14532d" : "#166534";
                ctx.fillRect(x * cell, y * cell, cell, cell);
            }
        }

        const fy = food.y * cell + cell / 2 + Math.sin(t * 0.15) * 2;
        const fxp = food.x * cell + cell / 2;

        ctx.fillStyle = "rgba(0,0,0,.25)";
        ctx.beginPath();
        ctx.ellipse(fxp, food.y * cell + cell - 4, 8, 3, 0, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#ef4444";
        ctx.beginPath();
        ctx.arc(fxp, fy, cell * 0.36, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,.7)";
        ctx.beginPath();
        ctx.arc(fxp - 3, fy - 4, 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#4ade80";
        ctx.beginPath();
        ctx.ellipse(fxp + 3, fy - cell * 0.38, 5, 3, -0.6, 0, Math.PI * 2);
        ctx.fill();

        const pts = snake.map((s, j) => {
            const from = old[j] || s;
            return {
                x: (lerp(from.x, s.x, p) + 0.5) * cell,
                y: (lerp(from.y, s.y, p) + 0.5) * cell
            };
        });

        ctx.lineCap = "round";
        ctx.lineJoin = "round";

        ctx.strokeStyle = "#15803d";
        ctx.lineWidth = cell * 0.86;
        ctx.beginPath();
        pts.forEach((pt, i) => (i ? ctx.lineTo(pt.x, pt.y) : ctx.moveTo(pt.x, pt.y)));
        ctx.stroke();

        ctx.strokeStyle = "#4ade80";
        ctx.lineWidth = cell * 0.62;
        ctx.stroke();

        ctx.strokeStyle = "rgba(255,255,255,.22)";
        ctx.lineWidth = cell * 0.2;
        ctx.stroke();

        const h = pts[0];

        ctx.fillStyle = "#86efac";
        ctx.beginPath();
        ctx.arc(h.x, h.y, cell * 0.44, 0, Math.PI * 2);
        ctx.fill();

        const px = -direction.y;
        const py = direction.x;

        [-1, 1].forEach(side => {
            const ex = h.x + direction.x * 5 + px * 6 * side;
            const ey = h.y + direction.y * 5 + py * 6 * side;

            ctx.fillStyle = "#fff";
            ctx.beginPath();
            ctx.arc(ex, ey, 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = "#111827";
            ctx.beginPath();
            ctx.arc(ex + direction.x * 1.5, ey + direction.y * 1.5, 2, 0, Math.PI * 2);
            ctx.fill();
        });

        if (t < hintUntil) {
            const h0 = pts[0];

            ctx.save();
            ctx.strokeStyle = "#facc15";
            ctx.lineWidth = 4;
            ctx.setLineDash([10, 8]);
            ctx.beginPath();
            ctx.moveTo(h0.x, h0.y);
            ctx.lineTo(fxp, fy);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.beginPath();
            ctx.arc(fxp, fy, cell * 0.7, 0, Math.PI * 2);
            ctx.stroke();
            ctx.restore();
        }

        fx.draw(ctx);

        txt(ctx, `🍎 ${collected} / ${target}`, W - 12, 24, "bold 18px sans-serif", "#f0fdf4", "right");
    }

    loop(dt => {
        t += dt;

        if (!dead && !won) {
            acc += dt * 16.667;

            while (acc >= interval && !dead && !won) {
                acc -= interval;
                tick();
            }
        }

        fx.update(dt);
        draw(dead || won ? 1 : clamp(acc / interval, 0, 1));
    });

    draw(1);
}

/* =========================================================
   REGISTRY + LAUNCHER
   ========================================================= */

const GAME_REGISTRY = {
    arrow_maze: gameArrowMaze,
    hologram_memory: gameHologramMemory,
    candy_match: gameCandyMatch,
    memory_match: gameMemoryMatch,
    bubble_shooter: gameBubbleShooter,
    endless_runner: gameEndlessRunner,
    neon_tic_tac_toe: gameNeonTicTacToe,
    puzzle_2048: gamePuzzle2048,
    arrow_direction: gameArrowDirection,
    sliding_puzzle: gameSlidingPuzzle,
    quiz_battle: gameQuizBattle,
    tetris_blocks: gameTetrisBlocks,
    flappy_brain: gameFlappyBrain,
    snake_game: gameSnake
};

function showFatal(message) {
    area.innerHTML = "";

    const box = el("div", "game-result-panel");
    const h = el("h3");
    const p = el("p");

    h.textContent = "Game could not start";
    p.textContent = message;

    box.append(h, p, makeButton("🔄 Reload", () => window.location.reload()));
    area.append(box);
}

let limitShown = false;

function showLimitReached() {
    resetGame();
    limitShown = true;

    const panel = el("div", "game-result-panel");

    panel.innerHTML = `
        <div style="font-size:64px;font-weight:900;color:#dc2626;line-height:1">✕</div>
        <h3>Enough playing for today!</h3>
        <p>You have finished ${DailyLimit.limit} of ${DailyLimit.limit} game rounds today.
           Watch a lesson or ask the AI Tutor, then come back tomorrow.</p>`;

    area.append(panel);
}

function boot() {
    limitShown = false;

    if (!Levels.gameId) Levels.load();

    if (DailyLimit.reached()) {
        showLimitReached();
        return;
    }

    const key = Levels.gameId;
    const gameFunction = GAME_REGISTRY[key];

    if (!gameFunction) {
        console.error("Unknown EduVision game:", key);
        showFatal(key
            ? `Game "${key}" is not registered in game.js.`
            : "Game ID is missing. Check build_payload() in game_data.py or add data-game-key to <body>.");
        return;
    }

    try {
        gameFunction();

        // bring the game into view once, so the player does not have to scroll to find it
        try { area.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (e) { /* ignore */ }

        area.setAttribute("tabindex", "-1");
        area.style.outline = "none";
        try { area.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
        window.focus();
    } catch (error) {
        console.error("Game failed to start:", error);
        showFatal("Something went wrong while starting the game. Please refresh and try again.");
    }
}

/* =========================================================
   RESTART LEVEL
   ========================================================= */

function restartLevel() {
    try {
        document.getElementById("eduRewardPopup")?.remove();
        document.getElementById("eduFailPopup")?.remove();

        if (Levels.allowReplay) Levels.allowReplay();

        boot();
    } catch (error) {
        console.error("Restart failed, reloading page:", error);
        window.location.reload();
    }
}

document.addEventListener("click", event => {
    const button = event.target.closest && event.target.closest("button, a, [role='button']");

    if (!button || area.contains(button)) return;

    // the popups have their own buttons
    if (button.closest("#eduFailPopup, #eduRewardPopup")) return;

    const label = `${button.id} ${button.className} ${button.dataset.action || ""} ${button.textContent}`.toLowerCase();

    if (/restart|replay|retry level|reset level/.test(label)) {
        event.preventDefault();
        restartLevel();
    }
});

document.addEventListener("keydown", event => {
    if (event.code !== "KeyR" || event.ctrlKey || event.metaKey || event.altKey) return;

    const t = event.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;

    // do not restart behind an open popup
    if (document.getElementById("eduRewardPopup")) return;

    restartLevel();
});

window.EduVisionGame = {
    boot,
    restart: restartLevel,
    restartLevel,
    reset: restartLevel,
    registry: GAME_REGISTRY
};

/* The game starts immediately (it never waits for the network).
   Then the real unlocked level is read from the database. If the server
   is ahead of this browser and the player has not started yet, the game
   restarts quietly on the correct level. */
async function syncLevelFromServer() {
    if (!Levels.gameId) return false;

    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), 5000) : 0;

    try {
        const response = await fetch(
            `/api/game-progress/${encodeURIComponent(Levels.gameId)}`,
            {
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
                signal: controller ? controller.signal : undefined
            }
        );

        if (!response.ok) return false;

        const data = await response.json();

        if (data && data.ok) {
            return Levels.setLevel(data.unlocked_level, data.completed_levels);
        }
    } catch (error) {
        console.warn("Could not sync level from server:", error);
    } finally {
        if (timer) clearTimeout(timer);
    }

    return false;
}

/* Ask the server how many rounds were used today (the database is the real counter). */
async function syncDailyFromServer() {
    try {
        const response = await fetch("/api/game-daily-status", {
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });

        if (!response.ok) return;

        const data = await response.json();

        if (!data || !data.ok) return;

        DailyLimit.set(Number(data.used) || 0, Number(data.limit) || 10);
        refreshDailyStrip();

        const notStarted = score === 0 && moveCount === 0 && !over;

        if (DailyLimit.reached() && notStarted) showLimitReached();
        else if (!DailyLimit.reached() && limitShown) boot();
    } catch (error) {
        console.warn("Could not sync daily limit:", error);
    }
}

boot();
syncDailyFromServer();

syncLevelFromServer().then(levelChanged => {
    const notStarted = score === 0 && moveCount === 0 && !over;
    if (levelChanged && notStarted) boot();
});
});