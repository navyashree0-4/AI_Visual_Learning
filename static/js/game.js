/* =========================================================
   EDUVISION GAME ENGINE  ->  static/js/game.js
   BIG SCREENS + ANIMATIONS + JELLY MATCH  (all 14 games)
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
            message.textContent = `Complete Level ${state.level} to unlock Level ${state.level + 1}.`;
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
        getDifficulty,
        get level() { return state.level; },
        get gameId() { return state.gameId; },
        get completedLevels() { return state.completedLevels; }
    };
})();

window.EduVisionLevels = EduVisionLevels;

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

// Canvas that is drawn at full size and scaled down on small screens.
const cv = (root, width, height, maxW) => {
    const canvas = el("canvas", "gcanvas");
    canvas.width = width;
    canvas.height = height;
    canvas.style.width = `min(100%, ${maxW || width}px)`;
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

// rounded rectangle path
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

// tiny particle system used by the canvas games
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

// restartable CSS shake
const shake = node => {
    node.classList.remove("ev-shake");
    void node.offsetWidth;
    node.classList.add("ev-shake");
};

/* =========================================================
   STYLES: animations + bigger boards for every game
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
@keyframes evRise{0%{opacity:1;transform:translate(-50%,0) scale(.8)}100%{opacity:0;transform:translate(-50%,-70px) scale(1.25)}}
@keyframes evFlash{0%,100%{filter:none}50%{filter:brightness(2) saturate(.4)}}

#playArea.ev-in{animation:evFade .4s ease}
.game-heading{animation:evDrop .5s cubic-bezier(.2,1.4,.4,1) both}
.game-status{transition:background .25s,color .25s}
.game-status.win{animation:evPulse .7s ease 2}
.game-status.lose{animation:evShake .45s}
.gcanvas{display:block;margin:14px auto;border-radius:22px;max-width:100%;box-shadow:0 14px 34px rgba(20,25,60,.35),0 0 0 5px rgba(255,255,255,.75);animation:evDrop .5s ease both}
.ev-shake{animation:evShake .45s !important}
.ev-board{display:grid;justify-content:center;margin:16px auto;gap:10px}
.ev-board button:disabled{opacity:1;cursor:default}

/* ---------- jelly match ---------- */
.jl-goal{display:flex;align-items:center;gap:12px;justify-content:center;margin:10px auto 0;max-width:640px;font-weight:800}
.jl-bar{flex:1;height:16px;background:#e9e3ff;border-radius:99px;overflow:hidden;box-shadow:inset 0 2px 4px rgba(0,0,0,.15)}
.jl-bar i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#ff4d6d,#ffd23f,#3ddc84);transition:width .5s cubic-bezier(.3,1.4,.5,1)}
.jl-wrap{--jcell:clamp(38px,9.4vw,68px);--jgap:6px;width:max-content;max-width:100%;margin:14px auto;padding:16px;border-radius:30px;background:linear-gradient(160deg,#8b5cf6,#ec4899 60%,#f97316);box-shadow:0 18px 40px rgba(124,58,237,.4),inset 0 0 0 4px rgba(255,255,255,.35)}
.jl-board{position:relative;display:grid;gap:var(--jgap)}
.jl-cell{width:var(--jcell);height:var(--jcell);display:grid;place-items:center;padding:0;border:0;border-radius:18px;background:rgba(255,255,255,.16);box-shadow:inset 0 2px 6px rgba(0,0,0,.18);cursor:pointer;position:relative;-webkit-tap-highlight-color:transparent}
.jl-cell.sel{background:rgba(255,255,255,.42);box-shadow:0 0 0 3px #fff,0 0 22px rgba(255,255,255,.95);z-index:2}
.jl-cell.nope{animation:evShake .35s}
.jelly{position:relative;width:86%;height:86%;border-radius:44% 56% 52% 48% / 52% 46% 54% 48%;transform-origin:50% 90%;
 background:radial-gradient(circle at 30% 24%,rgba(255,255,255,.95) 0 7%,rgba(255,255,255,0) 9%),radial-gradient(circle at 50% 58%,var(--c1) 0%,var(--c2) 100%);
 box-shadow:inset 0 -7px 12px rgba(0,0,0,.22),inset 0 7px 12px rgba(255,255,255,.38),0 7px 12px rgba(0,0,0,.3);
 animation:jlIdle 2.6s ease-in-out var(--d,0s) infinite}
.jelly::before,.jelly::after{content:"";position:absolute;top:44%;width:12%;height:16%;background:#2b1b3a;border-radius:50%;box-shadow:inset 2px 2px 0 rgba(255,255,255,.75)}
.jelly::before{left:29%}.jelly::after{right:29%}
.jelly.t0{--c1:#ff9db1;--c2:#e11d48}.jelly.t1{--c1:#ffc46b;--c2:#ea580c}.jelly.t2{--c1:#fff08a;--c2:#eab308}
.jelly.t3{--c1:#9af5b8;--c2:#16a34a}.jelly.t4{--c1:#8fd8ff;--c2:#0284c7}.jelly.t5{--c1:#dcb8ff;--c2:#7c3aed}
.jl-cell.sel .jelly{animation:jlBounce .55s ease-in-out infinite;filter:brightness(1.12) saturate(1.2)}
.jelly.pop{animation:jlPop .33s ease-in forwards}
.jelly.fall{animation:jlFall .42s cubic-bezier(.3,.9,.4,1) both}
.jelly.enter{animation:jlEnter .5s cubic-bezier(.2,1.5,.4,1) var(--e,0s) both}
@keyframes jlIdle{0%,100%{transform:scale(1,1)}25%{transform:scale(1.05,.95)}50%{transform:scale(.96,1.05)}75%{transform:scale(1.03,.97)}}
@keyframes jlBounce{0%,100%{transform:translateY(0) scale(1.08,.94)}50%{transform:translateY(-10%) scale(.96,1.08)}}
@keyframes jlPop{0%{transform:scale(1)}30%{transform:scale(1.35,.7)}60%{transform:scale(.85,1.3)}100%{transform:scale(0) rotate(30deg);opacity:0}}
@keyframes jlFall{0%{transform:translateY(calc(var(--fall) * -118%));opacity:.2}15%{opacity:1}70%{transform:translateY(0) scale(1.1,.88)}85%{transform:translateY(-4%) scale(.96,1.05)}100%{transform:none}}
@keyframes jlEnter{from{transform:scale(0) rotate(-40deg);opacity:0}to{transform:scale(1);opacity:1}}
.jl-spark{position:absolute;width:10px;height:10px;border-radius:50%;pointer-events:none;z-index:5;transform:translate(-50%,-50%);animation:jlSpark .6s ease-out forwards}
@keyframes jlSpark{to{transform:translate(calc(-50% + var(--dx)),calc(-50% + var(--dy))) scale(.2);opacity:0}}
.jl-float{position:absolute;z-index:6;pointer-events:none;font-weight:900;font-size:24px;color:#fff;white-space:nowrap;text-shadow:0 2px 0 #7c3aed,0 0 12px rgba(0,0,0,.4);animation:evRise .95s ease-out forwards}

/* ---------- memory cards ---------- */
.mem-board{--card:clamp(60px,12.5vw,104px);gap:12px;perspective:900px}
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
.holo-board{--holo:clamp(72px,17vw,128px);grid-template-columns:repeat(3,var(--holo));gap:14px;padding:18px;border-radius:28px;background:radial-gradient(circle at 30% 20%,#312e81,#0b1020);width:max-content;max-width:100%;box-shadow:0 0 40px rgba(99,102,241,.45)}
.holo-cell{width:var(--holo);height:var(--holo);border:2px solid rgba(165,180,252,.5);border-radius:24px;background:linear-gradient(145deg,#1e1b4b,#312e81);color:#a5b4fc;font-size:calc(var(--holo)*.4);cursor:pointer;transition:transform .15s,background .15s,box-shadow .15s;animation:evPop .4s backwards}
.holo-cell:hover:not(:disabled){transform:scale(1.06)}
.holo-cell.lit{background:linear-gradient(145deg,#c4b5fd,#7c3aed);color:#fff;transform:scale(1.12);box-shadow:0 0 30px #8b5cf6,0 0 70px rgba(139,92,246,.7)}
.holo-cell.good{background:linear-gradient(145deg,#86efac,#16a34a);color:#fff;box-shadow:0 0 26px #22c55e}
.holo-cell.bad{background:linear-gradient(145deg,#fca5a5,#dc2626);color:#fff;animation:evShake .4s}

/* ---------- tic tac toe ---------- */
.ttt-board{--ttt:clamp(84px,22vw,130px);grid-template-columns:repeat(3,var(--ttt));gap:12px;padding:16px;border-radius:26px;background:radial-gradient(circle at 30% 20%,#312e81,#0f172a);width:max-content;max-width:100%;box-shadow:0 0 40px rgba(99,102,241,.45)}
.ttt-cell{width:var(--ttt);height:var(--ttt);border:2px solid rgba(165,180,252,.35);border-radius:20px;background:rgba(15,23,42,.85);font-size:calc(var(--ttt)*.6);font-weight:900;cursor:pointer;transition:background .2s,transform .15s;color:#fff}
.ttt-cell:hover:not(.x):not(.o){background:rgba(99,102,241,.4);transform:scale(1.05)}
.ttt-cell span{display:block;animation:evPop .35s both}
.ttt-cell.x{color:#22d3ee;text-shadow:0 0 18px #22d3ee,0 0 36px #22d3ee}
.ttt-cell.o{color:#f472b6;text-shadow:0 0 18px #f472b6,0 0 36px #f472b6}
.ttt-cell.win{background:rgba(250,204,21,.28);border-color:#facc15;animation:tttWin .6s ease infinite}
@keyframes tttWin{50%{transform:scale(1.12)}}

/* ---------- 2048 ---------- */
.p48-board{--t:clamp(58px,15vw,104px);grid-template-columns:repeat(var(--n),var(--t));gap:10px;padding:12px;border-radius:18px;background:#bbada0;width:max-content;max-width:100%;touch-action:none;box-shadow:0 12px 30px rgba(0,0,0,.25)}
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
.arw-stage{display:grid;place-items:center;width:clamp(180px,40vw,280px);height:clamp(180px,40vw,280px);margin:16px auto;border-radius:50%;background:radial-gradient(circle,#fff,#e0e7ff);box-shadow:0 0 0 8px #c7d2fe,0 18px 40px rgba(99,102,241,.35);transition:background .2s,box-shadow .2s}
.arw-stage.ok{background:radial-gradient(circle,#dcfce7,#86efac);box-shadow:0 0 0 8px #4ade80,0 0 50px rgba(34,197,94,.6)}
.arw-stage.bad{background:radial-gradient(circle,#fee2e2,#fca5a5);box-shadow:0 0 0 8px #f87171;animation:evShake .4s}
.arw-sym{font-size:clamp(80px,18vw,140px);line-height:1;animation:evPop .35s cubic-bezier(.2,1.6,.4,1) both}
.arw-bar{max-width:420px;height:14px;margin:8px auto;border-radius:99px;background:#e0e7ff;overflow:hidden}
.arw-bar i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#6366f1,#ec4899);transition:width .4s}
.arw-round{text-align:center;font-weight:800}

/* ---------- sliding puzzle ---------- */
.sl-board{--cell:clamp(58px,17vw,104px);--gap:8px;position:relative;box-sizing:content-box;margin:16px auto;padding:12px;border-radius:22px;background:linear-gradient(145deg,#1e293b,#334155);width:calc(var(--n)*var(--cell) + (var(--n) - 1)*var(--gap));height:calc(var(--n)*var(--cell) + (var(--n) - 1)*var(--gap));max-width:100%;box-shadow:0 14px 34px rgba(15,23,42,.45)}
.sl-tile{position:absolute;left:12px;top:12px;width:var(--cell);height:var(--cell);border:0;border-radius:16px;color:#fff;font-size:calc(var(--cell)*.4);font-weight:900;cursor:pointer;text-shadow:0 2px 4px rgba(0,0,0,.3);box-shadow:inset 0 -5px 0 rgba(0,0,0,.2),0 6px 12px rgba(0,0,0,.3);transform:translate(calc(var(--c)*(var(--cell) + var(--gap))),calc(var(--r)*(var(--cell) + var(--gap))));transition:transform .2s cubic-bezier(.3,1.3,.5,1),filter .15s;animation:evFade .4s backwards}
.sl-tile:hover{filter:brightness(1.12)}

/* ---------- quiz battle ---------- */
.qb-arena{display:flex;align-items:center;justify-content:space-between;gap:12px;max-width:760px;margin:14px auto;padding:18px 24px;border-radius:24px;background:linear-gradient(135deg,#1e1b4b,#4c1d95);color:#fff;box-shadow:0 14px 34px rgba(76,29,149,.4)}
.qb-fighter{flex:1;text-align:center;font-weight:800}
.qb-sprite{font-size:clamp(56px,10vw,92px);line-height:1;display:inline-block;animation:evFloat 2.2s ease-in-out infinite}
.qb-sprite.hit{animation:evShake .4s,evFlash .4s}
.qb-hp{height:14px;border-radius:99px;background:rgba(255,255,255,.2);overflow:hidden;margin-top:8px}
.qb-hp i{display:block;height:100%;width:100%;border-radius:99px;transition:width .5s}
.qb-hp.me i{background:linear-gradient(90deg,#34d399,#10b981)}
.qb-hp.foe i{background:linear-gradient(90deg,#f87171,#ef4444)}
.qb-vs{font-weight:900;font-size:28px;color:#fcd34d}
.qb-q{max-width:760px;margin:14px auto;padding:18px 22px;border-radius:20px;background:#f5f3ff;text-align:center;animation:evDrop .35s both}
.qb-q h3{margin:0 0 6px;color:#6d28d9}
.qb-q p{margin:0;font-size:1.2rem;font-weight:700}
.qb-opts{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;max-width:760px;margin:0 auto}
.qb-opt{padding:18px;border:0;border-radius:16px;font-size:1.05rem;font-weight:700;cursor:pointer;background:#fff;box-shadow:0 4px 0 #c7d2fe,0 8px 16px rgba(0,0,0,.08);transition:transform .15s,box-shadow .15s;animation:evPop .35s backwards}
.qb-opt:hover:not(:disabled){transform:translateY(-3px)}
.qb-opt.ok{background:#bbf7d0;box-shadow:0 4px 0 #22c55e}
.qb-opt.bad{background:#fecaca;box-shadow:0 4px 0 #ef4444;animation:evShake .4s}
@media(max-width:560px){.qb-opts{grid-template-columns:1fr}}
`;

    document.head.append(style);
};

ensureGameStyle();

const currentLevel = () => Math.max(1, Number(Levels.level) || 1);

/* ---------- engine state ---------- */
let session = 0;
let score = 0;
let over = false;
let cleanups = [];

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

const resetGame = () => {
    session++;

    const fns = cleanups;
    cleanups = [];

    fns.forEach(fn => {
        try { fn(); } catch (e) { /* ignore */ }
    });

    over = false;
    score = 0;

    area.innerHTML = "";
    scoreEl.textContent = "0";

    area.classList.remove("ev-in");
    void area.offsetWidth;
    area.classList.add("ev-in");

    document.getElementById("eduRewardPopup")?.remove();
};

/* ---------- UI helpers ---------- */
const makeButton = (label, callback, className = "gbtn") => {
    const button = el("button", className);
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", callback);
    return button;
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

    area.append(wrapper);
    return wrapper;
};

// Returns a function:  status("text", "win" | "lose")
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
    !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);

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

    pad.style.display = "flex";
    pad.style.flexWrap = "wrap";
    pad.style.justifyContent = "center";
    pad.style.gap = "10px";
    pad.style.marginTop = "14px";

    [["up", "▲"], ["left", "◀"], ["down", "▼"], ["right", "▶"]]
        .forEach(([dir, label]) => {
            const button = el("button", "gbtn secondary", label);

            button.type = "button";
            button.setAttribute("aria-label", dir);
            button.style.minWidth = "64px";
            button.style.minHeight = "56px";
            button.style.fontSize = "22px";

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
        .edu-reward-card{width:min(400px,100%);padding:26px 22px;border-radius:22px;text-align:center;color:#1f2a44;background:#fff;box-shadow:0 20px 50px rgba(31,42,68,.3);animation:eduRewardPop .35s ease-out}
        .edu-reward-confetti{font-size:26px;margin-bottom:6px}
        .edu-reward-trophy{font-size:62px;margin:6px 0}
        .edu-reward-card h2{margin:8px 0;font-size:26px}
        .edu-reward-message{color:#6b7794;line-height:1.5;margin:0}
        .edu-reward-earned{margin:18px 0;padding:14px;border-radius:16px;background:#fff6dd}
        .edu-reward-earned span,.edu-reward-balance span{display:block;font-size:13px;color:#6b7794}
        .edu-reward-earned strong{display:block;margin-top:4px;color:#e8920a;font-size:36px}
        .edu-reward-balance{margin:12px 0 18px}
        .edu-reward-balance strong{display:inline-block;margin:6px;color:#22b573;font-size:28px}
        #eduRewardContinue{width:100%;padding:14px;border:0;border-bottom:4px solid #178a57;border-radius:12px;background:#22b573;color:#fff;font-size:16px;font-weight:700;cursor:pointer}
        #eduRewardContinue:hover{filter:brightness(1.08)}
        @keyframes eduRewardPop{from{opacity:0;transform:scale(.88) translateY(12px)}to{opacity:1;transform:none}}
    `;

    document.head.append(style);
};

const showRewardPopup = ({ level, earned, balance, duplicate = false }) => {
    ensureRewardStyle();

    document.getElementById("eduRewardPopup")?.remove();

    const overlay = el("div", "edu-reward-overlay");
    overlay.id = "eduRewardPopup";

    overlay.innerHTML = `
        <div class="edu-reward-card">
            <div class="edu-reward-confetti">🎉 ✨ 🎊</div>
            <div class="edu-reward-trophy">🏆</div>
            <h2>Level ${level} Completed!</h2>
            <p class="edu-reward-message">
                ${duplicate
                    ? "You have already received the reward for this level."
                    : "Amazing work! Keep learning and playing."}
            </p>
            <div class="edu-reward-earned">
                <span>Credits ${duplicate ? "already claimed" : "earned"}</span>
                <strong id="eduRewardEarned">${duplicate ? 0 : earned}</strong>
            </div>
            <div class="edu-reward-balance">
                <span>Your total balance</span>
                <strong id="eduRewardBalance">${balance}</strong>
                <span>⭐ Credits</span>
            </div>
            <button type="button" id="eduRewardContinue">
                Continue to Level ${level + 1} →
            </button>
        </div>
    `;

    document.body.append(overlay);

    if (!duplicate) countUp(document.getElementById("eduRewardEarned"), earned);
    countUp(document.getElementById("eduRewardBalance"), balance);

    document.getElementById("eduRewardContinue")
        .addEventListener("click", () => {
            overlay.remove();
            window.location.reload();
        });
};

const completeLevelAndAwardCredits = async (completedLevel, finalScore) => {
    if (over) return;

    over = true;

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
            throw new Error("Flask returned an invalid response.");
        }

        if (!response.ok || !result.success) {
            throw new Error(result.message || `Could not save reward (${response.status}).`);
        }

        const earned = Math.max(0, Number(result.earned) || 0);
        const balance = Math.max(0, Number(result.balance) || 0);

        showCredits(balance);

        // Advance only after the server confirms completion.
        Levels.complete(true, finalScore);

        if (earned > 0 && !result.duplicate) {
            playCreditRewardSound();

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

        status(
            `🎉 Level ${completedLevel} completed! ` +
            (result.duplicate ? "Reward already claimed." : `+${earned} credits!`),
            "win"
        );

        showRewardPopup({
            level: completedLevel,
            earned,
            balance,
            duplicate: Boolean(result.duplicate)
        });
    } catch (error) {
        console.error("EduVision reward error:", error);

        over = false;

        status("⚠️ Reward could not be saved. Check your connection and try again.", "lose");

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

    completeLevelAndAwardCredits(currentLevel(), Math.max(0, Number(finalScore) || 0));
};

const finishLose = (message = "Game over! Try again.") => {
    if (over) return;

    over = true;

    const panel = el("div", "game-result-panel");
    const heading = el("h3");
    const description = el("p");

    heading.textContent = "Game Over";
    description.textContent = message;

    panel.append(heading, description, makeButton("🔄 Try Again", () => boot()));
    area.append(panel);
};

// short celebration / crash moment before the result appears
const winLater = (finalScore, ms = 700) => later(ms, () => finishWin(finalScore));
const loseLater = (message, ms = 600) => later(ms, () => finishLose(message));

/* =========================================================
   GAME 1: ARROW MAZE
   ========================================================= */

function gameArrowMaze() {
    resetGame();

    addHeading("🏹 Arrow Finder: Arrow Maze", "Follow the path and reach the glowing goal.");

    const level = currentLevel();
    const size = Math.min(9 + Math.floor(level / 2) * 2, 31);
    const gridSize = size % 2 === 0 ? size + 1 : size;

    const cell = clamp(Math.floor(680 / gridSize), 20, 72);
    const W = gridSize * cell;

    const [canvas, ctx] = cv(area, W, W, 760);
    const status = makeStatus("Use arrow keys, WASD or swipe to find the exit.");
    const fx = makeFX();

    const maze = Array.from({ length: gridSize }, () => Array(gridSize).fill(1));
    const directions = [[0, -2], [2, 0], [0, 2], [-2, 0]];

    function carve(x, y) {
        maze[y][x] = 0;

        for (const [dx, dy] of shuffle(directions)) {
            const nx = x + dx;
            const ny = y + dy;

            if (nx > 0 && ny > 0 && nx < gridSize - 1 && ny < gridSize - 1 && maze[ny][nx] === 1) {
                maze[y + dy / 2][x + dx / 2] = 0;
                carve(nx, ny);
            }
        }
    }

    carve(1, 1);

    const player = { x: 1, y: 1 };
    const goal = { x: gridSize - 2, y: gridSize - 2 };
    const visited = new Set(["1,1"]);

    let px = 1, py = 1;       // smooth (animated) position
    let moves = 0, t = 0, won = false, squash = 0;

    function draw() {
        const bg = ctx.createLinearGradient(0, 0, W, W);
        bg.addColorStop(0, "#0f172a");
        bg.addColorStop(1, "#1e1b4b");
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, W, W);

        for (let y = 0; y < gridSize; y++) {
            for (let x = 0; x < gridSize; x++) {
                if (maze[y][x]) {
                    ctx.fillStyle = "#334155";
                    rr(ctx, x * cell + 1, y * cell + 1, cell - 2, cell - 2, cell * 0.22);
                    ctx.fill();
                    ctx.fillStyle = "rgba(255,255,255,.08)";
                    rr(ctx, x * cell + 3, y * cell + 3, cell - 6, (cell - 6) * 0.45, cell * 0.15);
                    ctx.fill();
                } else {
                    ctx.fillStyle = visited.has(x + "," + y) ? "#c7d7ff" : "#eef2ff";
                    ctx.fillRect(x * cell, y * cell, cell, cell);
                }
            }
        }

        // pulsing goal
        const pulse = 0.5 + Math.sin(t * 0.12) * 0.5;
        const gx = goal.x * cell + cell / 2;
        const gy = goal.y * cell + cell / 2;

        ctx.fillStyle = `rgba(34,197,94,${0.25 + pulse * 0.3})`;
        ctx.beginPath();
        ctx.arc(gx, gy, cell * (0.55 + pulse * 0.18), 0, Math.PI * 2);
        ctx.fill();

        ctx.textBaseline = "middle";
        txt(ctx, "🏁", gx, gy, `${Math.round(cell * 0.62)}px sans-serif`);

        // player ball
        const cx = px * cell + cell / 2;
        const cy = py * cell + cell / 2;
        const rad = cell * 0.34;

        ctx.fillStyle = "rgba(0,0,0,.25)";
        ctx.beginPath();
        ctx.ellipse(cx, cy + rad * 0.9, rad * 0.9, rad * 0.35, 0, 0, Math.PI * 2);
        ctx.fill();

        ctx.save();
        ctx.translate(cx, cy);
        ctx.scale(1 + squash * 0.25, 1 - squash * 0.25);

        const ball = ctx.createRadialGradient(-rad * 0.3, -rad * 0.3, rad * 0.1, 0, 0, rad);
        ball.addColorStop(0, "#fecaca");
        ball.addColorStop(1, "#dc2626");
        ctx.fillStyle = ball;
        ctx.beginPath();
        ctx.arc(0, 0, rad, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        fx.draw(ctx);
    }

    function move(direction) {
        if (over || won) return;

        const vectors = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
        const [dx, dy] = vectors[direction];
        const nx = player.x + dx;
        const ny = player.y + dy;

        if (nx < 0 || ny < 0 || nx >= gridSize || ny >= gridSize || maze[ny][nx] === 1) {
            squash = 1;
            return;
        }

        player.x = nx;
        player.y = ny;
        moves++;
        visited.add(nx + "," + ny);

        setScore(Math.max(0, 1000 - moves * 5));

        if (player.x === goal.x && player.y === goal.y) {
            won = true;

            const finalScore = Math.max(100, 1000 - moves * 5);

            setScore(finalScore);
            status("🎉 Maze completed! Saving your credits...", "win");

            for (let i = 0; i < 5; i++) {
                fx.burst(goal.x * cell + cell / 2, goal.y * cell + cell / 2,
                    pick(["#facc15", "#22c55e", "#38bdf8", "#f472b6"]), 14, 6);
            }

            winLater(finalScore, 900);
        }
    }

    keys(move);
    swipe(canvas, move);
    dpad(move);

    loop(dt => {
        t += dt;
        px = lerp(px, player.x, clamp(0.35 * dt, 0, 1));
        py = lerp(py, player.y, clamp(0.35 * dt, 0, 1));
        squash = Math.max(0, squash - 0.08 * dt);
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

        if (index !== sequence[position]) {
            accepting = false;
            cells[index].classList.add("bad");
            status("Wrong tile!", "lose");
            loseLater("Memory challenge failed. Try again.", 700);
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

    showSequence();
}

/* =========================================================
   GAME 3: JELLY MATCH (was Candy Match)
   ========================================================= */

function gameCandyMatch() {
    resetGame();

    addHeading("🍬 Jelly Match Puzzle", "Swap two neighbouring jellies to match three or more.");

    const level = currentLevel();
    const mySession = session;
    const rows = 8;
    const cols = 8;
    const TYPES = 6;
    const target = Math.min(500 + level * 100, 10000);
    const COLORS = ["#ff4d6d", "#ff9f1c", "#ffd23f", "#3ddc84", "#38b6ff", "#b57bff"];
    const PRAISE = ["Sweet!", "Tasty!", "Jelly-licious!", "Wobbly wow!", "Gooey genius!"];

    const goal = el("div", "jl-goal", `<span>🎯 Goal: ${target}</span><div class="jl-bar"><i></i></div>`);
    area.append(goal);
    const barFill = goal.querySelector("i");

    const wrap = el("div", "jl-wrap");
    const board = el("div", "jl-board");
    board.style.gridTemplateColumns = `repeat(${cols}, var(--jcell))`;
    wrap.append(board);
    area.append(wrap);

    const status = makeStatus("Tap a jelly, then tap a neighbour to swap.");

    const grid = new Array(rows * cols).fill(-1);
    const els = [];

    let selected = -1;
    let busy = false;

    const stale = () => over || session !== mySession;

    for (let i = 0; i < rows * cols; i++) {
        const b = el("button", "jl-cell");
        const j = el("div", "jelly");

        b.type = "button";
        b.setAttribute("aria-label", "jelly");
        j.style.setProperty("--d", `${(Math.random() * 2).toFixed(2)}s`);
        b.addEventListener("click", () => select(i));
        b.append(j);
        board.append(b);

        els.push({ b, j });
    }

    function fillGrid() {
        for (let i = 0; i < rows * cols; i++) {
            const r = Math.floor(i / cols);
            const c = i % cols;
            let v;

            do {
                v = rnd(TYPES);
            } while (
                (c >= 2 && grid[i - 1] === v && grid[i - 2] === v) ||
                (r >= 2 && grid[i - cols] === v && grid[i - 2 * cols] === v)
            );

            grid[i] = v;
        }
    }

    function paint(entrance = false, falls = null) {
        els.forEach(({ j }, i) => {
            j.className = `jelly t${grid[i]}`;

            if (falls && falls[i]) {
                void j.offsetWidth;
                j.style.setProperty("--fall", falls[i]);
                j.classList.add("fall");
            } else if (entrance) {
                j.style.setProperty("--e", `${((i % cols) + Math.floor(i / cols)) * 40}ms`);
                j.classList.add("enter");
            }
        });
    }

    const settle = () => els.forEach(({ j }) => j.classList.remove("fall", "enter"));

    function markSelected() {
        els.forEach(({ b }, i) => b.classList.toggle("sel", i === selected));
    }

    function findMatches() {
        const matches = new Set();

        for (let r = 0; r < rows; r++) {
            let start = 0;

            for (let c = 1; c <= cols; c++) {
                const same = c < cols && grid[r * cols + c] === grid[r * cols + start];
                if (same) continue;

                if (c - start >= 3) {
                    for (let k = start; k < c; k++) matches.add(r * cols + k);
                }

                start = c;
            }
        }

        for (let c = 0; c < cols; c++) {
            let start = 0;

            for (let r = 1; r <= rows; r++) {
                const same = r < rows && grid[r * cols + c] === grid[start * cols + c];
                if (same) continue;

                if (r - start >= 3) {
                    for (let k = start; k < r; k++) matches.add(k * cols + c);
                }

                start = r;
            }
        }

        return matches;
    }

    const swapData = (a, b) => { [grid[a], grid[b]] = [grid[b], grid[a]]; };

    function hasMoves() {
        for (let i = 0; i < rows * cols; i++) {
            const r = Math.floor(i / cols);
            const c = i % cols;
            const neighbours = [];

            if (c < cols - 1) neighbours.push(i + 1);
            if (r < rows - 1) neighbours.push(i + cols);

            for (const n of neighbours) {
                swapData(i, n);
                const ok = findMatches().size > 0;
                swapData(i, n);
                if (ok) return true;
            }
        }

        return false;
    }

    function newBoard() {
        do {
            fillGrid();
        } while (findMatches().size > 0 || !hasMoves());
    }

    function swapAnim(a, b) {
        return new Promise(resolve => {
            const A = els[a].b;
            const B = els[b].b;
            const ca = a % cols, ra = Math.floor(a / cols);
            const cb = b % cols, rb = Math.floor(b / cols);

            const move = (dc, dr) =>
                `translate(calc(${dc} * (100% + var(--jgap))), calc(${dr} * (100% + var(--jgap))))`;

            A.style.zIndex = "3";
            A.style.transition = B.style.transition = "transform .18s ease";
            A.style.transform = move(cb - ca, rb - ra);
            B.style.transform = move(ca - cb, ra - rb);

            later(200, () => {
                A.style.transition = B.style.transition = "";
                A.style.transform = B.style.transform = "";
                A.style.zIndex = "";
                resolve();
            });
        });
    }

    function sparks(index, type) {
        const r = Math.floor(index / cols);
        const c = index % cols;

        for (let k = 0; k < 7; k++) {
            const a = (k / 7) * Math.PI * 2 + Math.random();
            const s = el("i", "jl-spark");

            s.style.left = `${((c + 0.5) / cols) * 100}%`;
            s.style.top = `${((r + 0.5) / rows) * 100}%`;
            s.style.background = COLORS[type];
            s.style.setProperty("--dx", `${Math.cos(a) * 55}px`);
            s.style.setProperty("--dy", `${Math.sin(a) * 55}px`);

            board.append(s);
            later(650, () => s.remove());
        }
    }

    function floatText(index, text) {
        const r = Math.floor(index / cols);
        const c = index % cols;
        const f = el("span", "jl-float", text);

        f.style.left = `${((c + 0.5) / cols) * 100}%`;
        f.style.top = `${((r + 0.5) / rows) * 100}%`;

        board.append(f);
        later(1000, () => f.remove());
    }

    function gain(points) {
        addScore(points);
        barFill.style.width = `${Math.min(100, (score / target) * 100)}%`;
    }

    function applyGravity(removed) {
        const falls = new Array(rows * cols).fill(0);

        for (let c = 0; c < cols; c++) {
            const stack = [];

            for (let r = rows - 1; r >= 0; r--) {
                const i = r * cols + c;
                if (!removed.has(i)) stack.push({ v: grid[i], r });
            }

            const fresh = rows - stack.length;

            for (let n = 0; n < stack.length; n++) {
                const nr = rows - 1 - n;
                grid[nr * cols + c] = stack[n].v;
                falls[nr * cols + c] = nr - stack[n].r;
            }

            for (let nr = 0; nr < fresh; nr++) {
                grid[nr * cols + c] = rnd(TYPES);
                falls[nr * cols + c] = fresh;
            }
        }

        return falls;
    }

    async function resolveAll() {
        let combo = 0;

        while (true) {
            const matches = findMatches();
            if (matches.size === 0) break;

            combo++;

            const gained = matches.size * 50 * combo;
            const first = [...matches][0];

            matches.forEach(i => {
                els[i].j.classList.add("pop");
                sparks(i, grid[i]);
            });

            floatText(first, combo > 1 ? `${pick(PRAISE)} x${combo}` : `+${gained}`);
            gain(gained);

            await wait(340);
            if (stale()) return;

            const falls = applyGravity(matches);
            paint(false, falls);

            await wait(460);
            if (stale()) return;

            settle();

            if (score >= target) {
                status("🎉 Jelly goal reached! Saving your reward...", "win");
                await wait(500);
                if (!stale()) finishWin(score);
                return;
            }
        }

        if (!hasMoves()) {
            status("No more moves — shuffling the jellies!");
            await wait(600);
            if (stale()) return;

            newBoard();
            paint(true);
            await wait(700);
            settle();
            status("Fresh jellies! Keep matching.");
        }
    }

    async function select(index) {
        if (stale() || busy) return;

        if (selected === -1) {
            selected = index;
            markSelected();
            return;
        }

        if (selected === index) {
            selected = -1;
            markSelected();
            return;
        }

        const a = selected;
        const dist = Math.abs(Math.floor(a / cols) - Math.floor(index / cols)) +
                     Math.abs((a % cols) - (index % cols));

        if (dist !== 1) {
            selected = index;
            markSelected();
            return;
        }

        selected = -1;
        markSelected();
        busy = true;

        await swapAnim(a, index);
        if (stale()) return;

        swapData(a, index);
        paint();

        if (findMatches().size === 0) {
            await swapAnim(a, index);
            if (stale()) return;

            swapData(a, index);
            paint();

            [a, index].forEach(i => {
                els[i].b.classList.remove("nope");
                void els[i].b.offsetWidth;
                els[i].b.classList.add("nope");
            });

            busy = false;
            return;
        }

        status("Nice swap!");
        await resolveAll();
        busy = false;
    }

    newBoard();
    paint(true);
    later(900, settle);
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

    const movesLabel = el("p", "mem-moves");
    movesLabel.textContent = "Moves: 0";
    area.append(movesLabel);

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
        movesLabel.textContent = `Moves: ${moves}`;

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
}

/* =========================================================
   GAME 5: BUBBLE SHOOTER
   ========================================================= */

function gameBubbleShooter() {
    resetGame();

    addHeading("🫧 Bubble Shooter", "Aim with the mouse, then click or tap to shoot. Match 3 or more!");

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
    }

    on(canvas, "pointermove", setAim);
    on(canvas, "pointerdown", e => { setAim(e); shoot(); });

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

        // danger line
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

        // aim guide
        if (!proj && !won && !dead) {
            let x = sx, y = sy, vx = Math.cos(angle), vy = Math.sin(angle);

            for (let i = 0; i < 60; i++) {
                x += vx * 9;
                y += vy * 9;

                if (x < R) { x = R; vx = Math.abs(vx); }
                if (x > W - R) { x = W - R; vx = -Math.abs(vx); }
                if (y <= by(0) || hitsBubble(x, y)) break;

                if (i % 2 === 0) {
                    ctx.fillStyle = `rgba(255,255,255,${0.75 - i * 0.011})`;
                    ctx.beginPath();
                    ctx.arc(x, y, 3, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        }

        // cannon
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
        fx.burst(P.x + 17, GROUND, "#d6c59a", 6, 2);
    }

    on(window, "keydown", event => {
        if (event.code === "Space" || event.code === "ArrowUp" || event.code === "KeyW") {
            event.preventDefault();
            jump();
        }
    });

    on(canvas, "pointerdown", jump);
    area.append(makeButton("⬆ Jump", jump));

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
        ctx.ellipse(cx, GROUND + 4, 18 - (GROUND - feet) * 0.05, 5, 0, 0, Math.PI * 2);
        ctx.fill();

        ctx.save();
        ctx.translate(cx, feet);
        ctx.scale(1 + P.sq * 0.25 - (P.air ? 0.06 : 0), 1 - P.sq * 0.25 + (P.air ? 0.1 : 0));

        // legs
        const swing = P.air ? 0.5 : Math.sin(run) * 0.9;
        ctx.fillStyle = "#1d4ed8";
        rr(ctx, -12 + swing * 5, -14, 9, 14, 4); ctx.fill();
        rr(ctx, 3 - swing * 5, -14, 9, 14, 4); ctx.fill();

        // body
        const body = ctx.createLinearGradient(0, -P.h, 0, -10);
        body.addColorStop(0, "#93c5fd");
        body.addColorStop(1, "#2563eb");
        ctx.fillStyle = body;
        rr(ctx, -P.w / 2, -P.h, P.w, P.h - 10, 12);
        ctx.fill();

        // eye
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

        // hills (parallax)
        ctx.fillStyle = "#86efac";
        ctx.beginPath();
        ctx.moveTo(0, GROUND);
        for (let x = 0; x <= W; x += 20) {
            ctx.lineTo(x, GROUND - 40 - Math.sin((x + scroll * 0.25) / 70) * 22);
        }
        ctx.lineTo(W, GROUND);
        ctx.closePath();
        ctx.fill();

        // ground
        ctx.fillStyle = "#854d0e";
        ctx.fillRect(0, GROUND, W, H - GROUND);
        ctx.fillStyle = "#65a30d";
        ctx.fillRect(0, GROUND, W, 8);

        ctx.fillStyle = "rgba(0,0,0,.18)";
        for (let x = -((scroll) % 60); x < W; x += 60) ctx.fillRect(x, GROUND + 24, 28, 4);

        obstacles.forEach(drawCactus);
        drawPlayer();
        fx.draw(ctx);

        // HUD
        ctx.fillStyle = "rgba(15,23,42,.55)";
        rr(ctx, 14, 12, 250, 22, 11);
        ctx.fill();
        ctx.fillStyle = "#facc15";
        rr(ctx, 14, 12, 250 * clamp(score / target, 0, 1), 22, 11);
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
                loseLater(`Game over! You scored ${score}.`, 800);
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
   ========================================================= */

function gameNeonTicTacToe() {
    resetGame();

    addHeading("⭕ Neon Tic-Tac-Toe", "Get three marks in a row before the computer.");

    const board = el("div", "ev-board ttt-board");
    area.append(board);

    const status = makeStatus("Your turn: X");

    const cells = Array(9).fill("");
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

    function getWin() {
        for (const line of wins) {
            const [a, b, c] = line;
            if (cells[a] && cells[a] === cells[b] && cells[a] === cells[c]) {
                return { mark: cells[a], line };
            }
        }

        return null;
    }

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
                loseLater("The computer won. Try again.", 1100);
            }

            return true;
        }

        if (cells.every(Boolean)) {
            busy = true;
            status("It's a draw!", "lose");
            loseLater("It is a draw. Play another round.", 900);
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

    function move(index) {
        if (over || busy || !playerTurn || cells[index]) return;

        cells[index] = "X";
        draw(index);

        if (checkEnd()) return;

        playerTurn = false;
        busy = true;
        status("Computer is thinking...");

        later(550, () => {
            const empty = cells.map((v, i) => (v ? -1 : i)).filter(i => i !== -1);

            if (!empty.length) return;

            let choice = findWinningMove("O");
            if (choice === -1) choice = findWinningMove("X");
            if (choice === -1 && !cells[4]) choice = 4;
            if (choice === -1) choice = pick(empty);

            cells[choice] = "O";
            draw(choice);

            busy = false;
            playerTurn = true;

            if (!checkEnd()) status("Your turn: X");
        });
    }

    draw();
}

/* =========================================================
   GAME 8: 2048
   ========================================================= */

function gamePuzzle2048() {
    resetGame();

    addHeading("🔢 2048 Number Puzzle", "Slide tiles. Combine matching numbers to reach the target tile.");

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

        addScore(gained);
        merged = mergedNow;
        spawn();

        board.dataset.slide = direction;
        draw();

        if (grid.some(row => row.some(v => v >= target))) {
            status("🎉 Target tile reached! Saving reward...", "win");
            locked = true;   // block more moves during the celebration
            winLater(score, 800);
            return;
        }

        if (!emptyCells().length && !canMove()) {
            shake(board);
            loseLater("No moves remain. Try again.", 700);
        }
    }

    let locked = false;

    const safeMove = dir => { if (!locked) move(dir); };

    keys(safeMove);
    swipe(board, safeMove);
    dpad(safeMove);

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

    const status = makeStatus("Ready? Follow the arrows!");

    const roundLabel = el("p", "arw-round");
    area.append(roundLabel);

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

        status("Use the arrow keys or on-screen controls.");
    }

    function answer(direction) {
        if (over || !accepting || !current) return;

        accepting = false;

        if (direction === current.direction) {
            addScore(100);
            stage.classList.add("ok");
            bar.firstChild.style.width = `${(round / rounds) * 100}%`;
            status("Correct! ⭐", "win");
            later(420, nextRound);
        } else {
            stage.classList.add("bad");
            status("Wrong arrow!", "lose");
            loseLater("Incorrect arrow. Try again.", 700);
        }
    }

    keys(answer);
    dpad(answer);

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

        if (!neighbors(emptyIndex).includes(index)) return;

        [tiles[index], tiles[emptyIndex]] = [tiles[emptyIndex], tiles[index]];

        addScore(10);
        place();

        if (solved()) {
            status("🎉 Puzzle solved! Saving your reward...", "win");
            Object.values(nodes).forEach((n, i) => later(i * 40, () => { n.style.filter = "brightness(1.3)"; }));
            winLater(score + 500, 900);
        }
    }

    // keyboard: the arrow shows where the tile moves
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

    place();
}

/* =========================================================
   GAME 11: QUIZ BATTLE
   ========================================================= */

function gameQuizBattle() {
    resetGame();

    addHeading("⚔️ Quiz Battle Arena", "Answer correctly to damage the monster. Win at 60% or more!");

    const level = currentLevel();
    const questionCount = Math.min(5 + level, 20);

    const questions = [
        { q: "Which language is mainly used to style web pages?", options: ["HTML", "CSS", "SQL", "Python"], answer: 1 },
        { q: "Which data structure follows FIFO?", options: ["Stack", "Tree", "Queue", "Graph"], answer: 2 },
        { q: "What does CPU stand for?", options: ["Central Processing Unit", "Computer Primary Utility", "Central Program User", "Control Processing Utility"], answer: 0 },
        { q: "Which SQL command retrieves data?", options: ["GET", "SELECT", "PUSH", "FETCHALL"], answer: 1 },
        { q: "Which is a Python collection with key-value pairs?", options: ["List", "Tuple", "Dictionary", "String"], answer: 2 },
        { q: "Which protocol is commonly used for secure web browsing?", options: ["FTP", "HTTPS", "SMTP", "SSH only"], answer: 1 },
        { q: "Which number system uses only 0 and 1?", options: ["Decimal", "Octal", "Binary", "Hexadecimal"], answer: 2 },
        { q: "Which of these is a relational database?", options: ["MySQL", "HTML", "CSS", "React"], answer: 0 },
        { q: "Which keyword declares a constant in JavaScript?", options: ["let", "var", "const", "static"], answer: 2 },
        { q: "What is the full form of AI?", options: ["Automated Internet", "Artificial Intelligence", "Advanced Interface", "Applied Integration"], answer: 1 }
    ];

    const pool = shuffle(questions);
    const selected = Array.from({ length: questionCount }, (_, i) => pool[i % pool.length]);

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
                loseLater("Quiz battle lost. You need at least 60% correct.", 400);
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
            hit(meSprite);
            meHp.style.width = `${Math.max(0, 1 - wrong / (allowedWrong + 1)) * 100}%`;
            status(`Ouch! Correct answer: ${item.options[item.answer]}`, "lose");
        }

        later(1100, () => {
            position++;
            renderQuestion();
        });
    }

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
            loseLater("No space left! Game over.", 700);
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
            // ghost
            let gy = piece.y;
            while (!collides(piece.x, gy + 1, piece.shape)) gy++;

            piece.shape.forEach((row, y) => row.forEach((value, x) => {
                if (value) block((piece.x + x) * cell, (gy + y) * cell, piece.color, 0.22);
            }));

            piece.shape.forEach((row, y) => row.forEach((value, x) => {
                if (value) block((piece.x + x) * cell, (piece.y + y) * cell, piece.color);
            }));
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

    const controls = el("div", "tetris-controls");

    controls.style.display = "flex";
    controls.style.flexWrap = "wrap";
    controls.style.justifyContent = "center";
    controls.style.gap = "10px";
    controls.style.marginTop = "12px";

    [["◀", "left"], ["⟳", "rotate"], ["▼", "down"], ["▶", "right"]].forEach(([label, action]) => {
        const button = el("button", "gbtn secondary", label);

        button.type = "button";
        button.style.minWidth = "64px";
        button.style.minHeight = "56px";
        button.style.fontSize = "22px";
        button.addEventListener("pointerdown", e => {
            e.preventDefault();
            control(action);
        });

        controls.append(button);
    });

    if (isTouchDevice()) area.append(controls);

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
        fx.burst(BX - 12, birdY + 8, "#ffffff", 5, 2);
    }

    on(window, "keydown", event => {
        if (event.code === "Space" || event.code === "ArrowUp" || event.code === "KeyW") {
            event.preventDefault();
            flap();
        }
    });

    on(canvas, "pointerdown", flap);
    area.append(makeButton("⬆ Flap", flap));

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

        // hills
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

        // ground
        ctx.fillStyle = "#854d0e";
        ctx.fillRect(0, H - GROUND, W, GROUND);
        ctx.fillStyle = "#65a30d";
        ctx.fillRect(0, H - GROUND, W, 12);
        ctx.fillStyle = "rgba(0,0,0,.18)";
        for (let x = -(scroll % 40); x < W; x += 40) ctx.fillRect(x, H - GROUND + 30, 20, 5);

        // brain bird
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
                        loseLater("You hit an obstacle!", 900);
                        break;
                    }
                }

                obstacles = obstacles.filter(o => o.x > -PW - 20);

                if (!dead && birdY + BR > H - GROUND) {
                    dead = true;
                    birdY = H - GROUND - BR;
                    fx.burst(BX, birdY, "#f472b6", 22, 5);
                    shake(canvas);
                    loseLater("The brain hit the ground!", 900);
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
    const status = makeStatus(`Eat ${target} apples. Use arrow keys, WASD or swipe.`);
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

    function tick() {
        direction = nextDirection;
        old = snake.map(s => ({ ...s }));

        const head = { x: snake[0].x + direction.x, y: snake[0].y + direction.y };

        if (head.x < 0 || head.x >= cols || head.y < 0 || head.y >= rows) {
            dead = true;
            shake(canvas);
            fx.burst(snake[0].x * cell + cell / 2, snake[0].y * cell + cell / 2, "#22c55e", 20, 5);
            loseLater("The snake hit the wall!", 800);
            return;
        }

        const eating = head.x === food.x && head.y === food.y;
        const bodyToCheck = eating ? snake : snake.slice(0, -1);

        if (bodyToCheck.some(part => part.x === head.x && part.y === head.y)) {
            dead = true;
            shake(canvas);
            fx.burst(head.x * cell + cell / 2, head.y * cell + cell / 2, "#22c55e", 20, 5);
            loseLater("The snake collided with itself!", 800);
            return;
        }

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

        // apple
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

        // smooth body
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

        // head + eyes
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

function boot() {
    const key = Levels.gameId;
    const gameFunction = GAME_REGISTRY[key];

    if (!gameFunction) {
        area.innerHTML = "";

        const error = el("p");
        error.textContent = `Game "${key}" is not registered in game.js.`;
        area.append(error);

        console.error("Unknown EduVision game:", key);
        return;
    }

    try {
        gameFunction();

        area.setAttribute("tabindex", "-1");
        area.style.outline = "none";
        try { area.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
        window.focus();
    } catch (error) {
        console.error("Game failed to start:", error);

        area.innerHTML = "";

        const message = el("p");
        message.textContent = "The game could not start. Please refresh the page and try again.";
        area.append(message);
    }
}

window.EduVisionGame = { boot, registry: GAME_REGISTRY };

boot();
});