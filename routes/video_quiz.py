"""
routes/video_quiz.py  -  "Take Quiz" for a generated video.

Endpoints
  GET  /video-quiz/<video_id>               quiz page (endpoint: video_quiz.video_quiz_page)
  GET  /api/video-quiz/<video_id>           loads (or creates) the quiz; correct answers are NOT sent
  POST /api/video-quiz/<video_id>/submit    grades answers, awards credits (first attempt only)

Uses the tables created by app.initialize_database():
  video_quizzes(video_id UNIQUE, user_id, questions LONGTEXT)
  video_quiz_attempts(user_id, video_id, quiz_id, answers, score, total_questions, percentage, credits_earned)
"""
import json
import os
from functools import wraps

from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)
from mysql.connector import Error

from services.video_generator import generate_quiz

video_quiz_bp = Blueprint("video_quiz", __name__)

QUIZ_CREDITS_PER_CORRECT = max(0, int(os.getenv("QUIZ_CREDITS_PER_CORRECT", "2")))
QUIZ_QUESTION_COUNT = max(3, min(10, int(os.getenv("QUIZ_QUESTION_COUNT", "5"))))


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _conn():
    return current_app.config["GET_DB_CONNECTION"]()


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


def _best_attempt(quiz_id, user_id):
    connection = _conn()
    if connection is None:
        return None
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT score, total_questions, percentage FROM video_quiz_attempts "
            "WHERE quiz_id = %s AND user_id = %s ORDER BY percentage DESC, id DESC LIMIT 1",
            (quiz_id, user_id),
        )
        return cursor.fetchone()
    except Error:
        return None
    finally:
        if cursor:
            cursor.close()
        connection.close()


# ------------------------------------------------------------------
# page
# ------------------------------------------------------------------
@video_quiz_bp.route("/video-quiz/<int:video_id>")
@quiz_login_required
def video_quiz_page(video_id):
    try:
        video, _ = _load_video(video_id, session["user_id"])
    except Exception:
        current_app.logger.exception("Quiz page: could not load video")
        flash("Could not open the quiz. Please try again.", "error")
        return redirect(url_for("dashboard"))
    if not video:
        flash("Video not found.", "error")
        return redirect(url_for("my_generated_videos"))
    return render_template(
        "video_quiz.html",
        video_id=video_id,
        video_title=video.get("title") or "Your lesson",
        language=video.get("language") or "English",
        credits_per_correct=QUIZ_CREDITS_PER_CORRECT,
        user_name=session.get("user_name", "Student"),
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
        best = _best_attempt(quiz["id"], user_id)
        return jsonify(ok=True, questions=public, best=best,
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
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        # lock the user row so two quick submits cannot both be "first attempt"
        cursor.execute("SELECT credits FROM users WHERE id = %s FOR UPDATE", (user_id,))
        if not cursor.fetchone():
            connection.rollback()
            return jsonify(ok=False, error="Account not found."), 404

        cursor.execute(
            "SELECT COUNT(*) AS c FROM video_quiz_attempts WHERE user_id = %s AND quiz_id = %s",
            (user_id, quiz["id"]),
        )
        first_attempt = int((cursor.fetchone() or {}).get("c") or 0) == 0
        earned = score * QUIZ_CREDITS_PER_CORRECT if first_attempt else 0

        cursor.execute(
            "INSERT INTO video_quiz_attempts "
            "(user_id, video_id, quiz_id, answers, score, total_questions, percentage, credits_earned) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (user_id, video_id, quiz["id"], json.dumps(clean), score, total, percentage, earned),
        )
        if earned:
            cursor.execute("UPDATE users SET credits = credits + %s WHERE id = %s", (earned, user_id))
        if first_attempt:
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
    except Error:
        connection.rollback()
        current_app.logger.exception("Quiz submit failed")
        return jsonify(ok=False, error="Your result could not be saved. Please try again."), 500
    finally:
        if cursor:
            cursor.close()
        connection.close()

    return jsonify(
        ok=True, score=score, total=total, percentage=percentage,
        credits_earned=earned, first_attempt=first_attempt, balance=balance,
        results=results,
    )