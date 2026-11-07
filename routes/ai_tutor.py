"""
routes/ai_tutor.py

AI Doubt-Solving Tutor blueprint.

  GET  /ai-tutor/           the chat page
  POST /ai-tutor/api/chat   {"question": "...", "history": [...]}  ->  {"ok": true, "answer": "..."}

Works on its own: it needs no video, no script and no database table.
Like routes/video_quiz.py, it does its own login check so it never imports app.py.
"""

import threading
from functools import wraps

from flask import (
    Blueprint, current_app, jsonify, redirect, render_template, request,
    session, url_for,
)

from services.ai_tutor_service import MAX_QUESTION_CHARS, TutorError, ask_tutor

ai_tutor_bp = Blueprint("ai_tutor", __name__, url_prefix="/ai-tutor")

# One answer at a time per student (a local Ollama model works on one request at a time).
_BUSY_USERS = set()
_BUSY_LOCK = threading.Lock()


def tutor_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/ai-tutor/api/"):
                return jsonify(ok=False, error="Your session expired. Please log in again."), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@ai_tutor_bp.route("/")
@tutor_login_required
def tutor_page():
    return render_template(
        "ai_doubt_tutor.html",
        user_name=session.get("user_name", "Student"),
    )


@ai_tutor_bp.route("/api/chat", methods=["POST"])
@tutor_login_required
def chat_api():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error="Invalid request. Please refresh the page and try again."), 400

    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify(ok=False, error="Please type a question first."), 400
    question = question.strip()
    if len(question) > MAX_QUESTION_CHARS:
        return jsonify(
            ok=False,
            error=f"Your question is too long. Please keep it under {MAX_QUESTION_CHARS} characters.",
        ), 400

    history = data.get("history")
    user_id = session["user_id"]

    with _BUSY_LOCK:
        if user_id in _BUSY_USERS:
            return jsonify(ok=False, error="Please wait for the previous answer to finish."), 429
        _BUSY_USERS.add(user_id)

    try:
        answer = ask_tutor(question, history)
        return jsonify(ok=True, answer=answer)
    except TutorError as exc:
        return jsonify(ok=False, error=str(exc)), 503
    except Exception:
        current_app.logger.exception("AI tutor failed unexpectedly")
        return jsonify(ok=False, error="Something went wrong. Please try again."), 500
    finally:
        with _BUSY_LOCK:
            _BUSY_USERS.discard(user_id)