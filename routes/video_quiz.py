"""
routes/video_quiz.py  -  "Take Quiz" for a generated video. ONE ATTEMPT ONLY.

Endpoints
  GET  /video-quiz/<video_id>               quiz page (endpoint: video_quiz.video_quiz_page)
                                            -> if already taken, shows a "Not allowed" page
                                               with the old score (the quiz is NOT shown)
  GET  /api/video-quiz/<video_id>           loads (or creates) the quiz; correct answers are NOT sent
                                            -> 403 if already taken
  POST /api/video-quiz/<video_id>/submit    grades answers, awards credits
                                            -> 409 if already taken

Uses the tables created by app.initialize_database():
  video_quizzes(video_id UNIQUE, user_id, questions LONGTEXT)
  video_quiz_attempts(user_id, video_id, quiz_id, answers, score, total_questions, percentage, credits_earned)

ONE-ATTEMPT RULE (enforced 3 ways)
  1. App code checks for an earlier attempt before showing / grading.
  2. The user row is locked (FOR UPDATE) so two quick submits cannot both pass.
  3. MySQL UNIQUE (user_id, video_id) on video_quiz_attempts, called
     `unique_user_video_attempt` (the same name app.initialize_database() uses).
     app.py only adds it when there are no duplicate rows. This file ALSO adds it,
     after removing old duplicates, the first time a quiz route is used
     (see _ensure_one_attempt_key). The same SQL is in video_quiz_one_attempt.sql.
"""
import json
import os
import threading
from functools import wraps

from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)
from mysql.connector import Error, IntegrityError

from services.video_generator import generate_quiz

video_quiz_bp = Blueprint("video_quiz", __name__)

QUIZ_CREDITS_PER_CORRECT = max(0, int(os.getenv("QUIZ_CREDITS_PER_CORRECT", "2")))
QUIZ_QUESTION_COUNT = max(3, min(10, int(os.getenv("QUIZ_QUESTION_COUNT", "5"))))

ALREADY_TAKEN_TEXT = "Not allowed. You have already taken this quiz once. It can only be attempted one time."

ONE_ATTEMPT_KEY = "unique_user_video_attempt"   # same name as app.py
OLD_DUPLICATE_KEY = "uq_user_video"              # from the first SQL file; dropped if redundant
_key_ready = False
_key_lock = threading.Lock()


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _conn():
    return current_app.config["GET_DB_CONNECTION"]()


def _ensure_one_attempt_key():
    """Make sure MySQL itself refuses a 2nd attempt (UNIQUE user_id + video_id).

    Runs once per process and does nothing if a matching unique key already exists
    (whatever it is called). If it is missing, old duplicate attempts are removed first
    (the first attempt is kept), because the ALTER TABLE would fail otherwise."""
    global _key_ready
    if _key_ready:
        return
    with _key_lock:
        if _key_ready:
            return
        connection = _conn()
        if connection is None:
            return
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'video_quiz_attempts' "
                "AND non_unique = 0 GROUP BY index_name"
            )
            matching = []
            for name, cols in cursor.fetchall():
                name = name.decode() if isinstance(name, (bytes, bytearray)) else name
                cols = cols.decode() if isinstance(cols, (bytes, bytearray)) else cols
                if set(str(cols).split(",")) == {"user_id", "video_id"}:
                    matching.append(name)

            if not matching:
                cursor.execute(
                    "DELETE a FROM video_quiz_attempts a "
                    "JOIN video_quiz_attempts b "
                    "  ON a.user_id = b.user_id AND a.video_id = b.video_id AND a.id > b.id"
                )
                connection.commit()
                cursor.execute(
                    f"ALTER TABLE video_quiz_attempts "
                    f"ADD UNIQUE KEY {ONE_ATTEMPT_KEY} (user_id, video_id)"
                )
                connection.commit()
                current_app.logger.info("Added unique key %s to video_quiz_attempts", ONE_ATTEMPT_KEY)
            elif len(matching) > 1 and OLD_DUPLICATE_KEY in matching:
                # two identical unique keys: drop the one from the first SQL file
                cursor.execute(f"ALTER TABLE video_quiz_attempts DROP INDEX {OLD_DUPLICATE_KEY}")
                connection.commit()
                current_app.logger.info("Dropped redundant key %s", OLD_DUPLICATE_KEY)
            _key_ready = True
        except Exception:
            # Do not block the quiz: the app-level checks still enforce one attempt.
            current_app.logger.exception("Could not add one-attempt unique key (will retry later)")
        finally:
            if cursor:
                cursor.close()
            connection.close()


@video_quiz_bp.before_request
def _before_quiz_request():
    _ensure_one_attempt_key()


def quiz_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Your session expired. Please log in again."), 401
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _load_video(video_id, user_id):
    connection = _conn()
    if connection is None:
        raise RuntimeError("Database connection failed.")
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, title, language, difficulty, script_text FROM generated_videos "
            "WHERE id = %s AND user_id = %s",
            (video_id, user_id),
        )
        video = cursor.fetchone()
        quiz = None
        if video:
            cursor.execute(
                "SELECT id, questions FROM video_quizzes WHERE video_id = %s", (video_id,)
            )
            quiz = cursor.fetchone()
        return video, quiz
    finally:
        if cursor:
            cursor.close()
        connection.close()


def _store_quiz(video_id, user_id, questions):
    """Insert the quiz (a concurrent request may have inserted it first) and return its row."""
    connection = _conn()
    if connection is None:
        raise RuntimeError("Database connection failed.")
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "INSERT IGNORE INTO video_quizzes (video_id, user_id, questions) VALUES (%s, %s, %s)",
            (video_id, user_id, json.dumps(questions, ensure_ascii=False)),
        )
        connection.commit()
        cursor.execute(
            "SELECT id, questions FROM video_quizzes WHERE video_id = %s", (video_id,)
        )
        return cursor.fetchone()
    except Error:
        connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        connection.close()


def _existing_attempt(video_id, user_id):
    """Return this student's attempt for this video (score, total, percentage) or None.
    Raises on database problems so that a failure never lets a second attempt through."""
    connection = _conn()
    if connection is None:
        raise RuntimeError("Database connection failed.")
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT score, total_questions, percentage FROM video_quiz_attempts "
            "WHERE video_id = %s AND user_id = %s ORDER BY id ASC LIMIT 1",
            (video_id, user_id),
        )
        return cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        connection.close()


def _already_taken_payload(attempt):
    return dict(
        ok=False,
        already_attempted=True,
        error=ALREADY_TAKEN_TEXT,
        score=attempt["score"],
        total=attempt["total_questions"],
        percentage=attempt["percentage"],
    )


# ------------------------------------------------------------------
# page
# ------------------------------------------------------------------
@video_quiz_bp.route("/video-quiz/<int:video_id>")
@quiz_login_required
def video_quiz_page(video_id):
    user_id = session["user_id"]
    try:
        video, _ = _load_video(video_id, user_id)
        attempt = _existing_attempt(video_id, user_id) if video else None
    except Exception:
        current_app.logger.exception("Quiz page: could not load video")
        flash("Could not open the quiz. Please try again.", "error")
        return redirect(url_for("dashboard"))
    if not video:
        flash("Video not found.", "error")
        return redirect(url_for("my_generated_videos"))

    # if `attempt` is set, the template shows the "Not allowed" page (no quiz, no retake)
    return render_template(
        "video_quiz.html",
        video_id=video_id,
        video_title=video.get("title") or "Your lesson",
        language=video.get("language") or "English",
        credits_per_correct=QUIZ_CREDITS_PER_CORRECT,
        user_name=session.get("user_name", "Student"),
        already_taken=attempt,
        already_taken_text=ALREADY_TAKEN_TEXT,
    )


# ------------------------------------------------------------------
# API: load or create quiz
# ------------------------------------------------------------------
@video_quiz_bp.route("/api/video-quiz/<int:video_id>")
@quiz_login_required
def api_get_quiz(video_id):
    user_id = session["user_id"]
    try:
        video, quiz = _load_video(video_id, user_id)
        if not video:
            return jsonify(ok=False, error="Video not found."), 404

        # one attempt only: do not even send the questions again
        attempt = _existing_attempt(video_id, user_id)
        if attempt:
            return jsonify(**_already_taken_payload(attempt)), 403

        if not quiz:
            script = (video.get("script_text") or "").strip()
            if not script:
                return jsonify(
                    ok=False,
                    error="This video has no saved lesson text, so a quiz cannot be made for it.",
                ), 422
            questions = generate_quiz(
                script,
                language=video.get("language") or "English",
                difficulty=video.get("difficulty") or "Beginner",
                count=QUIZ_QUESTION_COUNT,
            )
            quiz = _store_quiz(video_id, user_id, questions)

        questions = json.loads(quiz["questions"])
        public = [{"question": q["question"], "options": q["options"]} for q in questions]
        return jsonify(ok=True, questions=public,
                       credits_per_correct=QUIZ_CREDITS_PER_CORRECT)

    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 422
    except Exception as exc:
        current_app.logger.exception("Quiz load failed")
        return jsonify(
            ok=False,
            error=f"The quiz could not be created ({type(exc).__name__}). "
                  "Make sure Ollama is running, then try again.",
        ), 500


# ------------------------------------------------------------------
# API: submit answers
# ------------------------------------------------------------------
@video_quiz_bp.route("/api/video-quiz/<int:video_id>/submit", methods=["POST"])
@quiz_login_required
def api_submit_quiz(video_id):
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    answers = data.get("answers")
    if not isinstance(answers, list):
        return jsonify(ok=False, error="No answers were received."), 400

    try:
        video, quiz = _load_video(video_id, user_id)
    except Exception:
        current_app.logger.exception("Quiz submit: load failed")
        return jsonify(ok=False, error="Database error. Please try again."), 500
    if not video or not quiz:
        return jsonify(ok=False, error="Quiz not found."), 404

    questions = json.loads(quiz["questions"])
    total = len(questions)
    if len(answers) != total:
        return jsonify(ok=False, error="Please answer every question."), 400

    clean = []
    for a in answers:
        try:
            a = int(a)
        except (TypeError, ValueError):
            a = -1
        clean.append(a if 0 <= a <= 3 else -1)
    if -1 in clean:
        return jsonify(ok=False, error="Please answer every question."), 400

    results, score = [], 0
    for q, chosen in zip(questions, clean):
        ok = chosen == q["correct_index"]
        score += 1 if ok else 0
        results.append({
            "chosen": chosen,
            "correct_index": q["correct_index"],
            "is_correct": ok,
            "explanation": q.get("explanation", ""),
        })
    percentage = round(score * 100 / total) if total else 0

    connection = _conn()
    if connection is None:
        return jsonify(ok=False, error="Database connection failed."), 503

    already_taken = False
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        # lock the user row so two quick submits cannot both pass the "already taken" check
        cursor.execute("SELECT credits FROM users WHERE id = %s FOR UPDATE", (user_id,))
        if not cursor.fetchone():
            connection.rollback()
            return jsonify(ok=False, error="Account not found."), 404

        cursor.execute(
            "SELECT score, total_questions, percentage FROM video_quiz_attempts "
            "WHERE user_id = %s AND video_id = %s ORDER BY id ASC LIMIT 1",
            (user_id, video_id),
        )
        previous = cursor.fetchone()
        if previous:
            connection.rollback()
            return jsonify(**_already_taken_payload(previous)), 409

        earned = score * QUIZ_CREDITS_PER_CORRECT

        cursor.execute(
            "INSERT INTO video_quiz_attempts "
            "(user_id, video_id, quiz_id, answers, score, total_questions, percentage, credits_earned) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (user_id, video_id, quiz["id"], json.dumps(clean), score, total, percentage, earned),
        )
        if earned:
            cursor.execute("UPDATE users SET credits = credits + %s WHERE id = %s", (earned, user_id))

        cursor.execute(
            "UPDATE learning_progress SET quizzes_completed = quizzes_completed + 1 WHERE user_id = %s",
            (user_id,),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                "INSERT INTO learning_progress "
                "(user_id, videos_generated, quizzes_completed, games_played, total_score) "
                "VALUES (%s, 0, 1, 0, 0)",
                (user_id,),
            )
        cursor.execute(
            "INSERT IGNORE INTO user_activity (user_id, activity_date, activity_type) "
            "VALUES (%s, CURDATE(), 'quiz')",
            (user_id,),
        )
        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        balance = int((cursor.fetchone() or {}).get("credits") or 0)
        connection.commit()
        session["credits"] = balance

    except IntegrityError:
        # The UNIQUE (user_id, video_id) key was hit: another submit saved an attempt first.
        # IntegrityError must be caught BEFORE Error (it is a subclass of Error).
        connection.rollback()
        already_taken = True
    except Error:
        connection.rollback()
        current_app.logger.exception("Quiz submit failed")
        return jsonify(ok=False, error="Your result could not be saved. Please try again."), 500
    finally:
        if cursor:
            cursor.close()
        connection.close()

    # Handled after the connection is closed so we never reuse a closed connection.
    if already_taken:
        try:
            prev = _existing_attempt(video_id, user_id)
        except Exception:
            current_app.logger.exception("Quiz submit: could not read previous attempt")
            prev = None
        if prev:
            return jsonify(**_already_taken_payload(prev)), 409
        return jsonify(ok=False, error="Your result could not be saved. Please try again."), 500

    return jsonify(
        ok=True, score=score, total=total, percentage=percentage,
        credits_earned=earned, first_attempt=True, balance=balance,
        results=results,
    )