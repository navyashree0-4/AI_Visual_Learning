"""
add_accuracy.py - adds the Accuracy Report to your app.py

HOW TO USE
    1. Put this file in the same folder as app.py
    2. Run:   python add_accuracy.py
    3. Restart your app and open  http://127.0.0.1:5000/accuracy

A backup of your original file is saved as app_backup.py.
Running it twice is safe (it detects that the block is already there).
"""
from pathlib import Path
import shutil
import sys

APP = Path(__file__).resolve().parent / "app.py"
BACKUP = APP.with_name("app_backup.py")

MARKER = ("# ============================================================\n"
          "# ERROR HANDLERS\n")

BLOCK = r'''# ============================================================
# ACCURACY REPORT (measured from real data in MySQL)
# ============================================================

def compute_accuracy(user_id=None):
    """Accuracy numbers from stored results.

    user_id given -> that student only (quiz, games, aptitude).
    user_id None  -> whole platform (quiz and games, all students).
    """
    where = "WHERE user_id = %s" if user_id else ""
    params = (user_id,) if user_id else ()
    out = {
        "quiz": {"attempts": 0, "correct": 0, "questions": 0, "accuracy": None},
        "games": {"plays": 0, "accuracy": None},
        "aptitude": {"attempts": 0, "accuracy": None},
        "overall": None,
    }
    connection = get_db_connection()
    if connection is None:
        return None
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        # Quiz accuracy = correct answers / total questions
        q = _pp_query(
            cursor,
            f"SELECT COUNT(*) AS n, COALESCE(SUM(score),0) AS c, "
            f"COALESCE(SUM(total_questions),0) AS t FROM video_quiz_attempts {where}",
            params, one=True)
        n, c, t = int(q.get("n") or 0), int(q.get("c") or 0), int(q.get("t") or 0)
        out["quiz"] = {"attempts": n, "correct": c, "questions": t,
                       "accuracy": round(c * 100 / t, 1) if t else None}

        # Game accuracy = average score percentage
        g = _pp_query(
            cursor,
            f"SELECT COUNT(*) AS n, AVG(score_pct) AS a FROM game_plays {where}",
            params, one=True)
        if int(g.get("n") or 0):
            out["games"] = {"plays": int(g["n"]), "accuracy": round(float(g["a"] or 0), 1)}

        # Aptitude accuracy (per student only)
        if user_id:
            pcts = [a["pct"] for a in _pp_aptitude_attempts(cursor, user_id) if a["pct"] is not None]
            if pcts:
                out["aptitude"] = {"attempts": len(pcts),
                                   "accuracy": round(sum(pcts) / len(pcts), 1)}

        # Overall = average of the parts that have data
        parts = [x["accuracy"] for x in (out["quiz"], out["games"], out["aptitude"])
                 if x["accuracy"] is not None]
        out["overall"] = round(sum(parts) / len(parts), 1) if parts else None
        return out
    except Exception:
        app.logger.exception("Accuracy calculation failed")
        return None
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


@app.route("/api/accuracy")
@login_required
def api_accuracy():
    """JSON accuracy. ?scope=all gives the whole platform, default is the logged-in student."""
    scope_all = request.args.get("scope") == "all"
    data = compute_accuracy(None if scope_all else session["user_id"])
    if data is None:
        return jsonify(ok=False, error="Could not calculate accuracy."), 503
    return jsonify(ok=True, scope="all" if scope_all else "me", accuracy=data)


@app.route("/accuracy")
@login_required
def accuracy_page():
    """Simple report page: my accuracy and platform accuracy."""
    mine = compute_accuracy(session["user_id"])
    everyone = compute_accuracy(None)
    if mine is None or everyone is None:
        return "Could not calculate accuracy right now.", 503

    def fmt(v):
        return "No data yet" if v is None else f"{v}%"

    return render_template_string("""
    <!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>Accuracy | EduVision</title>
    <style>
    body{font-family:Arial,sans-serif;background:#f4f6fb;margin:0;padding:30px;color:#182033}
    .wrap{max-width:760px;margin:auto}.card{background:#fff;border-radius:16px;padding:24px;
    box-shadow:0 10px 30px #1820331a;margin-bottom:20px}
    table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #e3e6f0;text-align:left}
    .big{font-size:42px;font-weight:700;color:#5546e8}small{color:#6b7385}
    </style></head><body><div class="wrap">
    <div class="card"><h2>My accuracy</h2><div class="big">{{ fmt(mine.overall) }}</div>
    <table>
    <tr><th>Quiz answers</th><td>{{ fmt(mine.quiz.accuracy) }}</td>
        <td><small>{{ mine.quiz.correct }} / {{ mine.quiz.questions }} correct</small></td></tr>
    <tr><th>Games</th><td>{{ fmt(mine.games.accuracy) }}</td>
        <td><small>{{ mine.games.plays }} plays</small></td></tr>
    <tr><th>Aptitude</th><td>{{ fmt(mine.aptitude.accuracy) }}</td>
        <td><small>{{ mine.aptitude.attempts }} tests</small></td></tr>
    </table></div>
    <div class="card"><h2>Platform accuracy (all students)</h2><div class="big">{{ fmt(everyone.overall) }}</div>
    <table>
    <tr><th>Quiz answers</th><td>{{ fmt(everyone.quiz.accuracy) }}</td>
        <td><small>{{ everyone.quiz.correct }} / {{ everyone.quiz.questions }} correct</small></td></tr>
    <tr><th>Games</th><td>{{ fmt(everyone.games.accuracy) }}</td>
        <td><small>{{ everyone.games.plays }} plays</small></td></tr>
    </table></div>
    <p><a href="{{ url_for('dashboard') }}">Back to dashboard</a></p>
    </div></body></html>
    """, mine=mine, everyone=everyone, fmt=fmt)


'''


def main():
    if not APP.is_file():
        sys.exit(f"app.py not found next to this script: {APP}")
    text = APP.read_text(encoding="utf-8")
    if "def compute_accuracy" in text:
        print("Accuracy report is already in app.py. Nothing to do.")
        return
    if text.count(MARKER) != 1:
        sys.exit("Could not find the '# ERROR HANDLERS' section exactly once. "
                 "Paste the block manually above that section.")
    shutil.copyfile(APP, BACKUP)
    APP.write_text(text.replace(MARKER, BLOCK + MARKER, 1), encoding="utf-8")
    print(f"Done. Backup saved as {BACKUP.name}.")
    print("Restart your app and open http://127.0.0.1:5000/accuracy")


if __name__ == "__main__":
    main()