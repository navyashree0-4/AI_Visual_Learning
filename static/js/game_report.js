/*
 * game_report.js - reports a finished game to EduVision so it shows in the Accuracy page.
 *
 * 1. Save this file as  static/game_report.js
 * 2. Add this line to templates/game.html, BEFORE your game.js script tag:
 *        <script src="{{ url_for('static', filename='game_report.js') }}"></script>
 * 3. In game.js, at the place where a game ENDS (win, lose or time up), call:
 *
 *        reportGameResult({ game: GAME_KEY, score: finalScore, maxScore: bestPossibleScore, startedAt: startTime });
 *
 *    GAME_KEY      the game id, e.g. "snake_game" (same ids as /game/<game_key>)
 *    score         points the player got
 *    maxScore      the highest possible score, so accuracy is a true percentage
 *                  (for a quiz: number of questions; for a puzzle: 100 if you already have a percent)
 *    startedAt     Date.now() taken when the game started (optional, used for seconds played)
 *
 * It is safe to call more than once; each call is stored as one play.
 */
(function () {
  "use strict";

  window.reportGameResult = function (info) {
    info = info || {};
    var key = info.game || info.gameKey || window.GAME_KEY || (window.GAME_PAYLOAD && window.GAME_PAYLOAD.key) || "";
    var seconds = info.seconds;
    if (seconds == null && info.startedAt) {
      seconds = Math.round((Date.now() - info.startedAt) / 1000);
    }
    var body = {
      game: key,
      score: Number(info.score) || 0,
      seconds: Math.max(0, Math.round(Number(seconds) || 0))
    };
    if (info.maxScore != null) { body.max_score = Number(info.maxScore); }
    if (info.scorePct != null) { body.score_pct = Number(info.scorePct); }

    return fetch("/api/game/finish", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok) { console.warn("Game result not saved:", data); }
        return data;
      })
      .catch(function (err) {
        console.warn("Game result could not be sent:", err);
      });
  };
})();