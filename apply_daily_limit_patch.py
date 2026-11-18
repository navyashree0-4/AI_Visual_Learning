"""
EduVision: daily game limit + X marks patch.

Usage (run from your project folder, next to app.py):
    python apply_daily_limit_patch.py
    python apply_daily_limit_patch.py --game static/js/game.js --app app.py

What it does
  game.js : shared daily limit, X-mark reward popup, blocked start screen,
            server sync (/api/game-daily-status), 429 handling.
  app.py  : DAILY_GAME_LIMIT (.env, default 10), server-side check inside
            /api/game-level/complete, /api/game-daily-status route,
            dashboard passes daily_used / daily_limit.

Safe: makes .bak backups, checks every anchor first and writes NOTHING
if any anchor is missing. Running it twice is harmless.
"""
import argparse
import shutil
import sys
from pathlib import Path

# ----------------------------------------------------------------------------
# game.js pieces
# ----------------------------------------------------------------------------

JS_DAILY_LIMIT = r'''window.EduVisionLevels = EduVisionLevels;

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

window.EduVisionDaily = DailyLimit;'''

JS_POPUP_START = "const showRewardPopup = ({"
JS_POPUP_END = "const completeLevelAndAwardCredits = async"

JS_POPUP = r'''const showRewardPopup = ({ level, earned, balance, duplicate = false, time = "", moves = 0, blocked = false, capped = false }) => {
    ensureRewardStyle();

    document.getElementById("eduRewardPopup")?.remove();

    const overlay = el("div", "edu-reward-overlay");
    overlay.id = "eduRewardPopup";

    const used = Math.min(DailyLimit.used(), DailyLimit.limit);
    const marks = Array.from({ length: DailyLimit.limit }, (_, i) =>
        i < used ? '<b class="edu-mark on">✕</b>' : '<b class="edu-mark">·</b>').join("");

    const limitBox = (blocked || capped) ? `
        <div class="edu-limit-box">
            <div class="edu-limit-x">✕</div>
            <strong>Enough playing for today!</strong>
            <p>You have used all ${DailyLimit.limit} game rounds. Time to learn something new 📚</p>
            <div class="edu-marks">${marks}</div>
        </div>` : "";

    const rewardBlock = blocked ? "" : `
        <div class="edu-reward-stats"><span>⏱ ${time}</span><span>👣 ${moves}</span></div>
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
        <div class="edu-reward-card">
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
            ${limitBox}
            <button type="button" id="eduRewardContinue">
                ${(blocked || capped) ? "Back to Dashboard →" : `Continue to Level ${level + 1} →`}
            </button>
        </div>
    `;

    document.body.append(overlay);

    if (!blocked) {
        if (!duplicate) countUp(document.getElementById("eduRewardEarned"), earned);
        countUp(document.getElementById("eduRewardBalance"), balance);
    }

    document.getElementById("eduRewardContinue")
        .addEventListener("click", () => {
            overlay.remove();
            if (blocked || capped) window.location.href = "/dashboard";
            else window.location.reload();
        });
};

'''

JS_CSS_ANCHOR = "@keyframes eduRewardPop{from{opacity:0;transform:scale(.88) translateY(12px)}to{opacity:1;transform:none}}"
JS_CSS_NEW = JS_CSS_ANCHOR + r'''
        .edu-limit-box{margin:14px 0;padding:14px;border-radius:16px;background:#fee2e2;color:#991b1b}
        .edu-limit-box p{margin:6px 0;font-size:.9rem}
        .edu-limit-x{font-size:44px;font-weight:900;line-height:1;color:#dc2626}
        .edu-marks{display:flex;justify-content:center;gap:4px;flex-wrap:wrap;margin-top:8px}
        .edu-mark{width:22px;height:22px;display:grid;place-items:center;border-radius:6px;background:#fff;color:#fca5a5;font-size:.8rem}
        .edu-mark.on{background:#dc2626;color:#fff}'''

JS_STILLHERE = "    const stillHere = () => session === mySession;\n"
JS_STILLHERE_NEW = JS_STILLHERE + r'''
    // daily limit already used up: no credits, show the X screen
    if (DailyLimit.reached()) {
        showRewardPopup({ level: completedLevel, earned: 0, balance: 0, blocked: true });
        return;
    }
'''

JS_LOG = 'console.log("Reward API status:", response.status, result);'
JS_LOG_NEW = JS_LOG + r'''

        // server says the daily limit is used up
        if (response.status === 429 || result.limit_reached) {
            if (Number.isFinite(Number(result.daily_used))) {
                DailyLimit.set(Number(result.daily_used), Number(result.daily_limit));
            } else {
                DailyLimit.fill();
            }

            if (stillHere()) {
                showRewardPopup({ level: completedLevel, earned: 0, balance: 0, blocked: true });
            }

            return;
        }'''

JS_CREDITS = "        showCredits(balance);\n\n        Levels.complete(true, finalScore);"
JS_CREDITS_NEW = r'''        showCredits(balance);

        // keep the local counter in step with the server
        if (Number.isFinite(Number(result.daily_used))) {
            DailyLimit.set(Number(result.daily_used), Number(result.daily_limit));
        } else if (!result.duplicate) {
            DailyLimit.record();
        }

        Levels.complete(true, finalScore);'''

JS_DUP = "            duplicate: Boolean(result.duplicate),\n"
JS_DUP_NEW = JS_DUP + "            capped: DailyLimit.reached(),\n"

JS_BOOT = "function boot() {\n    if (!Levels.gameId) Levels.load();\n"
JS_BOOT_NEW = r'''let limitShown = false;

function showLimitReached() {
    resetGame();
    limitShown = true;

    const panel = el("div", "game-result-panel");

    panel.innerHTML = `
        <div style="font-size:64px;font-weight:900;color:#dc2626;line-height:1">✕</div>
        <h3>Enough playing for today!</h3>
        <p>You have finished ${DailyLimit.limit} of ${DailyLimit.limit} game rounds today.
           Watch a lesson or ask the AI Tutor, then come back tomorrow.</p>`;

    panel.append(makeButton("📚 Back to Dashboard", () => { window.location.href = "/dashboard"; }));
    area.append(panel);
}

function boot() {
    limitShown = false;

    if (!Levels.gameId) Levels.load();

    if (DailyLimit.reached()) {
        showLimitReached();
        return;
    }
'''

JS_TAIL = "\nboot();\n\nsyncLevelFromServer().then("
JS_TAIL_NEW = r'''
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

        const notStarted = score === 0 && moveCount === 0 && !over;

        if (DailyLimit.reached() && notStarted) showLimitReached();
        else if (!DailyLimit.reached() && limitShown) boot();
    } catch (error) {
        console.warn("Could not sync daily limit:", error);
    }
}

boot();
syncDailyFromServer();

syncLevelFromServer().then('''

# ----------------------------------------------------------------------------
# app.py pieces
# ----------------------------------------------------------------------------

PY_CONST = "GAME_LEVEL_REWARD = 10\nMAX_GAME_LEVEL = 1000\n"
PY_CONST_NEW = PY_CONST + r'''
# Maximum completed game rounds per user per day, shared by ALL games.
# Change with DAILY_GAME_LIMIT in .env (default 10).
DAILY_GAME_LIMIT = max(1, int(os.getenv("DAILY_GAME_LIMIT", "10")))


def get_daily_game_count(user_id):
    """How many game rounds this user completed today (rewards saved today)."""
    connection = get_db_connection()
    if connection is None:
        return 0
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) AS n FROM game_level_rewards "
            "WHERE user_id = %s AND DATE(created_at) = CURDATE()",
            (user_id,),
        )
        return int((cursor.fetchone() or {}).get("n") or 0)
    except Error as exc:
        app.logger.warning("Daily game count failed: %s", exc)
        return 0
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()
'''

PY_CHECK = '''        cursor.execute(
            "INSERT IGNORE INTO game_progress "
            "(user_id, game_key, unlocked_level, completed_levels, best_score) "
'''
PY_CHECK_NEW = '''        # Daily limit shared by all games (the user row is locked above, so this is race-safe).
        cursor.execute(
            "SELECT COUNT(*) AS n FROM game_level_rewards "
            "WHERE user_id = %s AND DATE(created_at) = CURDATE()",
            (user_id,),
        )
        used_today = int((cursor.fetchone() or {}).get("n") or 0)
        if used_today >= DAILY_GAME_LIMIT:
            connection.rollback()
            msg = "Enough playing for today! Come back tomorrow."
            return jsonify(
                ok=False, success=False, limit_reached=True,
                daily_used=used_today, daily_limit=DAILY_GAME_LIMIT,
                error=msg, message=msg,
            ), 429

''' + PY_CHECK

PY_DUP = "            duplicate=not newly_completed,\n"
PY_DUP_NEW = (PY_DUP +
              "            daily_used=used_today + (1 if newly_completed else 0),\n"
              "            daily_limit=DAILY_GAME_LIMIT,\n")

PY_ERR = "# ============================================================\n# ERROR HANDLERS\n"
PY_ERR_NEW = '''# ============================================================
# DAILY GAME LIMIT STATUS
# ============================================================

@app.route("/api/game-daily-status")
@login_required
def game_daily_status():
    """Used by game.js to show the X marks and block games when the limit is used up."""
    used = get_daily_game_count(session["user_id"])
    return jsonify(
        ok=True, used=used, limit=DAILY_GAME_LIMIT,
        remaining=max(0, DAILY_GAME_LIMIT - used),
        reached=used >= DAILY_GAME_LIMIT,
    )


''' + PY_ERR

PY_DASH = "        daily_done=played_today,\n"
PY_DASH_NEW = (PY_DASH +
               "        daily_used=get_daily_game_count(user_id),\n"
               "        daily_limit=DAILY_GAME_LIMIT,\n")


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def load(path):
    raw = Path(path).read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def save(path, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    Path(path).write_bytes(text.encode("utf-8"))


def replace_once(text, old, new, label, problems):
    n = text.count(old)
    if n != 1:
        problems.append(f"  - {label}: expected 1 match, found {n}")
        return text
    return text.replace(old, new)


def patch_game(path):
    text, crlf = load(path)
    if "const DailyLimit" in text:
        print(f"{path}: already patched, skipped.")
        return None
    problems = []
    t = text

    t = replace_once(t, "window.EduVisionLevels = EduVisionLevels;", JS_DAILY_LIMIT, "game.js: DailyLimit module", problems)

    if t.count(JS_POPUP_START) == 1 and t.count(JS_POPUP_END) == 1:
        i, j = t.index(JS_POPUP_START), t.index(JS_POPUP_END)
        if i < j:
            t = t[:i] + JS_POPUP + t[j:]
        else:
            problems.append("  - game.js: showRewardPopup markers in wrong order")
    else:
        problems.append("  - game.js: showRewardPopup markers not found exactly once")

    t = replace_once(t, JS_CSS_ANCHOR, JS_CSS_NEW, "game.js: popup CSS", problems)
    t = replace_once(t, JS_STILLHERE, JS_STILLHERE_NEW, "game.js: limit check in completeLevelAndAwardCredits", problems)
    t = replace_once(t, JS_LOG, JS_LOG_NEW, "game.js: 429 handling", problems)
    t = replace_once(t, JS_CREDITS, JS_CREDITS_NEW, "game.js: record play", problems)
    t = replace_once(t, JS_DUP, JS_DUP_NEW, "game.js: capped flag", problems)
    t = replace_once(t, JS_BOOT, JS_BOOT_NEW, "game.js: boot / limit screen", problems)
    t = replace_once(t, JS_TAIL, JS_TAIL_NEW, "game.js: server sync", problems)
    return t, crlf, problems


def patch_app(path):
    text, crlf = load(path)
    if "DAILY_GAME_LIMIT" in text:
        print(f"{path}: already patched, skipped.")
        return None
    problems = []
    t = text
    t = replace_once(t, PY_CONST, PY_CONST_NEW, "app.py: constants + helper", problems)
    t = replace_once(t, PY_CHECK, PY_CHECK_NEW, "app.py: limit check in complete_game_level", problems)
    t = replace_once(t, PY_DUP, PY_DUP_NEW, "app.py: response fields", problems)
    t = replace_once(t, PY_ERR, PY_ERR_NEW, "app.py: status route", problems)
    t = replace_once(t, PY_DASH, PY_DASH_NEW, "app.py: dashboard values", problems)
    return t, crlf, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="static/js/game.js")
    ap.add_argument("--app", default="app.py")
    args = ap.parse_args()

    jobs = []
    for label, path, fn in (("game.js", args.game, patch_game), ("app.py", args.app, patch_app)):
        if not Path(path).is_file():
            print(f"ERROR: {label} not found at {path}. Use --{'game' if label == 'game.js' else 'app'} PATH")
            sys.exit(1)
        result = fn(path)
        if result is not None:
            jobs.append((path, result))

    bad = [p for _, (_, _, probs) in jobs for p in probs]
    if bad:
        print("Nothing was changed. These spots were not found (file differs from the one I saw):")
        print("\n".join(bad))
        sys.exit(1)

    for path, (text, crlf, _) in jobs:
        shutil.copyfile(path, str(path) + ".bak")
        save(path, text, crlf)
        print(f"Patched {path} (backup: {path}.bak)")

    print("\nDone. Optional .env line:  DAILY_GAME_LIMIT=2")
    print("Restart Flask, then hard-refresh the browser (Ctrl+F5).")


if __name__ == "__main__":
    main()
