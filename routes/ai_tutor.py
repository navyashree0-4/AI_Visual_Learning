"""
routes/ai_tutor.py

AI Doubt-Solving Tutor blueprint. It is opened from a generated video card.

  GET  /ai-tutor/?video_id=<id>   the chat page (tied to that video; general tutor if no id)
  POST /ai-tutor/api/chat         {"question": "...", "history": [...], "video_id": 12}
                                  ->  {"ok": true, "answer": "..."}

If the student asks for an image/diagram, the answer contains a Markdown image
(added by services/ai_tutor_service.py).

The video is loaded through app.config["GET_VIDEO_CONTEXT"] (set in app.py), so this file
never imports app.py. Only the logged-in student's OWN video is ever used.
"""

import os
import re
import threading
from functools import wraps

from flask import (
    Blueprint, abort, current_app, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)

from services.ai_tutor_service import (
    MAX_QUESTION_CHARS, TutorError, ask_tutor, _diagram_folder,
)

ai_tutor_bp = Blueprint("ai_tutor", __name__, url_prefix="/ai-tutor")

# One answer at a time per student (a local Ollama model works on one request at a time).
_BUSY_USERS = set()
_BUSY_LOCK = threading.Lock()

# How much of the video script is given to the tutor.
MAX_SCRIPT_CHARS = 6000


def tutor_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/ai-tutor/api/"):
                return jsonify(ok=False, error="Your session expired. Please log in again."), 401
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def _load_video(video_id):
    """Return the video context dict for this student's own video, or None."""
    if not video_id:
        return None
    try:
        video_id = int(video_id)
    except (TypeError, ValueError):
        return None
    getter = current_app.config.get("GET_VIDEO_CONTEXT")
    if not callable(getter):
        return None
    try:
        return getter(video_id, session.get("user_id"))
    except Exception:
        current_app.logger.exception("Could not load video context for the tutor")
        return None


def _lesson_context_text(video):
    """Plain-text description of the video the student is asking about."""
    script = (video.get("script") or "").strip()[:MAX_SCRIPT_CHARS]
    parts = [
        "The student is watching the lesson video described below. "
        "If the question relates to this lesson, answer using the lesson first, "
        "in the same language and level as the lesson. "
        "If the question is about something else, answer it normally and clearly "
        "using your own knowledge. Never refuse a question just because it is "
        "not covered in the video.",
        f"Title: {video.get('title', '')}",
        f"Language: {video.get('language', 'English')}",
        f"Level: {video.get('difficulty', 'Beginner')}",
        f"Audience: {video.get('audience', 'School Students')}",
    ]
    if script:
        parts.append("Video script:\n" + script)
    return "\n".join(parts)



# Diagram pictures made by the tutor (SVG files). Served from here, so they display
# no matter how the Flask "static" folder is configured. File names are random,
# and only names like  neural-network-1a2b3c4d.svg  are accepted (no path tricks).
_DIAGRAM_NAME = re.compile(r"^[a-z0-9][a-z0-9\-]{0,60}\.svg$")


@ai_tutor_bp.route("/diagram/<name>")
def diagram_file(name):
    if not _DIAGRAM_NAME.fullmatch(name):
        abort(404)
    folder = _diagram_folder()
    if not os.path.isfile(os.path.join(folder, name)):
        abort(404)
    response = send_from_directory(folder, name, mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@ai_tutor_bp.route("/")
@tutor_login_required
def tutor_page():
    video = _load_video(request.args.get("video_id", type=int))
    return render_template(
        "ai_doubt_tutor.html",
        user_name=session.get("user_name", "Student"),
        video=video,
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

    # video_id is optional. A video that is not the student's own loads as None.
    raw_video_id = data.get("video_id")
    video = _load_video(raw_video_id)
    if raw_video_id and video is None:
        return jsonify(ok=False, error="This video was not found. Open the tutor from My Videos."), 404

    video_context = _lesson_context_text(video) if video else None
    topic_hint = (video.get("title") or "").strip() if video else None

    with _BUSY_LOCK:
        if user_id in _BUSY_USERS:
            return jsonify(ok=False, error="Please wait for the previous answer to finish."), 429
        _BUSY_USERS.add(user_id)

    try:
        answer = ask_tutor(
            question,
            history,
            video_context=video_context,
            topic_hint=topic_hint,
        )
        return jsonify(ok=True, answer=answer)
    except TutorError as exc:
        return jsonify(ok=False, error=str(exc)), 503
    except Exception:
        current_app.logger.exception("AI tutor failed unexpectedly")
        return jsonify(ok=False, error="Something went wrong. Please try again."), 500
    finally:
        with _BUSY_LOCK:
            _BUSY_USERS.discard(user_id)