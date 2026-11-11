import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the same folder as app.py (not the terminal's current folder).
# utf-8-sig also handles .env files saved with a BOM by Windows Notepad.
_ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_FILE, override=True, encoding="utf-8-sig")  # Load before importing routes/services

from datetime import date, datetime, timedelta
import inspect
import json
import re
import secrets
import smtplib
import threading
import time
from email.message import EmailMessage
from functools import wraps
import uuid

from flask import (
    Flask, abort, current_app, flash, jsonify, redirect, render_template,
    render_template_string, request, send_from_directory, session, url_for,
)
import mysql.connector
from mysql.connector import Error
from werkzeug.routing import BuildError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from services.video_generator import extract_text, generate_video_package, ai_status

try:
    # Same limit as the generator (default 7 minutes, change with MAX_VIDEO_MINUTES in .env).
    from services.video_generator import MAX_VIDEO_MINUTES as GEN_MAX_VIDEO_MINUTES
except ImportError:
    GEN_MAX_VIDEO_MINUTES = 7

try:
    from game_data import GAMES as DATA_GAMES, build_payload as data_build_payload
except ImportError:
    DATA_GAMES = {}

    def data_build_payload(game_key, game):
        return dict(game or {}, key=game_key, game_id=game_key)

try:
    from learning import learning_bp
except ImportError:
    from routes.learning import learning_bp  # if learning.py lives in routes/

app = Flask(__name__)

# Always pick up edited templates and never let the browser keep an old copy of a page.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def _no_cache_for_pages(response):
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
if not os.getenv("FLASK_SECRET_KEY"):
    app.logger.warning("FLASK_SECRET_KEY is not set. Set it in .env for stable sessions.")
app.register_blueprint(learning_bp)

VIDEO_COST = max(1, int(os.getenv("VIDEO_COST", "10")))
DAILY_CREDIT_CAP = max(0, int(os.getenv("DAILY_CREDIT_CAP", "40")))

# Cartoon movies ALWAYS cost credits (free-mode animation still uses your server).
# Total cost = number of scenes x CARTOON_CREDITS_PER_SCENE.
CARTOON_CREDITS_PER_SCENE = max(1, int(os.getenv("CARTOON_CREDITS_PER_SCENE", "5")))

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "ai_visual_learning"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "connection_timeout": 10,
    "autocommit": False,
}

MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "").strip()
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "").replace(" ", "")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USERNAME).strip()
OTP_EXPIRY_MINUTES = max(2, int(os.getenv("OTP_EXPIRY_MINUTES", "5")))
OTP_MAX_ATTEMPTS = max(3, int(os.getenv("OTP_MAX_ATTEMPTS", "5")))
INITIAL_CREDITS = max(0, int(os.getenv("INITIAL_CREDITS", "50")))

MAX_UPLOAD_MB = 10

GENERATED_DIR = Path(app.root_path) / "static" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# TEMPLATE HELPERS
# ============================================================
@app.context_processor
def inject_aptitude_link():
    """Use `{{ aptitude_url }}` in templates for the Aptitude Arena link."""
    try:
        url = url_for("aptitude.aptitude_home")  # -> /aptitude/
    except BuildError:
        url = "/aptitude/"
    return {"aptitude_url": url}


def tutor_url_for_video(video_id):
    """URL of the AI Doubt Tutor opened for one specific video.

    The tutor is no longer in the main menu or quick actions; it is reached only
    from a generated video card. Templates can call `{{ tutor_url_for_video(video.id) }}`.
    """
    if not video_id:
        return "/ai-tutor/"
    try:
        return url_for("ai_tutor.tutor_page", video_id=video_id)
    except BuildError:
        return f"/ai-tutor/?video_id={int(video_id)}"


app.jinja_env.globals["tutor_url_for_video"] = tutor_url_for_video

# Some templates (e.g. cartoon_studio.html) use `current_app.view_functions`.
# Flask does not give templates `current_app` by default, so expose it here.
app.jinja_env.globals["current_app"] = current_app


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_db_connection():
    """Return a connected MySQL connection, or None if unavailable."""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
        connection.close()
    except Error as exc:
        app.logger.error("Database connection failed: %s", exc)
    return None
def save_game_result(user_id, game_name, score, credits_earned):
    """Save completed game results in MySQL."""

    connection = get_db_connection()

    if connection is None:
        app.logger.error("Cannot save game result: database unavailable.")
        return False

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO game_results
                (user_id, game_name, score, credits_earned)
            VALUES (%s, %s, %s, %s)
        """, (
            int(user_id),
            str(game_name),
            int(score),
            int(credits_earned)
        ))

        connection.commit()
        app.logger.info("Game result saved successfully.")
        return True

    except (Error, ValueError, TypeError) as exc:
        connection.rollback()
        app.logger.error("Game result could not be saved: %s", exc)
        return False

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


# Blueprints (e.g. aptitude_backend, video_quiz) use this instead of importing from app.py
app.config["GET_DB_CONNECTION"] = get_db_connection

from routes.aptitude_backend import aptitude_bp  # noqa: E402
from routes.video_quiz import video_quiz_bp  # noqa: E402

if aptitude_bp.name not in app.blueprints:
    app.register_blueprint(aptitude_bp)
if video_quiz_bp.name not in app.blueprints:
    app.register_blueprint(video_quiz_bp)

# AI Doubt-Solving Tutor (routes/ai_tutor.py). Registered once, with the same guard as above.
# It is opened from a video card: /ai-tutor/?video_id=<id>
from routes.ai_tutor import ai_tutor_bp  # noqa: E402

if ai_tutor_bp.name not in app.blueprints:
    app.register_blueprint(ai_tutor_bp)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            # Game scripts call /api/... with fetch(); an HTML login redirect
            # would break their JSON parsing and show "check your connection".
            if request.path.startswith("/api/") or request.path.startswith("/generate_video/"):
                return jsonify(
                    ok=False,
                    success=False,
                    error="Your session expired. Please log in again.",
                    message="Your session expired. Please log in again.",
                ), 401
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def get_user_credits(user_id):
    connection = get_db_connection()
    if connection is None:
        return 0
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return int(row["credits"] or 0) if row else 0
    except Error as exc:
        app.logger.error("Could not load credits: %s", exc)
        return 0
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def charge_credits(user_id, amount):
    """Atomically deduct credits if the user has enough."""
    if amount <= 0:
        return False
    connection = get_db_connection()
    if connection is None:
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE users SET credits = credits - %s "
            "WHERE id = %s AND credits >= %s",
            (amount, user_id, amount),
        )
        success = cursor.rowcount == 1
        connection.commit()
        return success
    except Error as exc:
        connection.rollback()
        app.logger.error("Credit charge failed: %s", exc)
        return False
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def refund_credits(user_id, amount):
    if amount <= 0:
        return
    connection = get_db_connection()
    if connection is None:
        app.logger.error("Unable to connect to refund credits for user %s", user_id)
        return
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE users SET credits = credits + %s WHERE id = %s",
            (amount, user_id),
        )
        connection.commit()
    except Error as exc:
        connection.rollback()
        app.logger.error("Credit refund failed: %s", exc)
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def log_activity(user_id, activity_type):
    connection = get_db_connection()
    if connection is None:
        return
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT IGNORE INTO user_activity "
            "(user_id, activity_date, activity_type) "
            "VALUES (%s, CURDATE(), %s)",
            (user_id, activity_type),
        )
        connection.commit()
    except Error as exc:
        connection.rollback()
        app.logger.warning("Activity could not be saved: %s", exc)
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def bump_video_progress(user_id):
    connection = get_db_connection()
    if connection is None:
        return
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE learning_progress "
            "SET videos_generated = videos_generated + 1 WHERE user_id = %s",
            (user_id,),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                "INSERT INTO learning_progress "
                "(user_id, videos_generated, quizzes_completed, games_played, total_score) "
                "VALUES (%s, 1, 0, 0, 0)",
                (user_id,),
            )
        connection.commit()
    except Error as exc:
        connection.rollback()
        app.logger.warning("Video progress could not be saved: %s", exc)
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def save_video_record(user_id, title, style, language, filename):
    """Save a generated video (basic version). Returns the new video id or None."""
    connection = get_db_connection()
    if connection is None:
        return None
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO generated_videos
                (user_id, title, description, video_style, language, filename)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                title,
                "AI-generated educational video",
                style,
                language,
                filename,
            ),
        )
        video_id = cursor.lastrowid
        connection.commit()
        return video_id
    except Exception:
        connection.rollback()
        app.logger.exception("Could not save generated video.")
        return None
    finally:
        cursor.close()
        connection.close()


def save_video_record_v2(user_id, meta):
    """Save a generated video with all its settings. Returns the new video id or None.

    Missing keys fall back to defaults, so cartoon movies can use it too.
    """
    meta = meta or {}
    connection = get_db_connection()
    if connection is None:
        return None
    cursor = None
    try:
        style = meta.get("style") or "Cartoon"
        language = meta.get("language") or "English"
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO generated_videos "
            "(user_id, title, description, video_style, language, difficulty, audience, "
            " aspect_ratio, filename, duration_seconds, subtitles, highlights, music, script_text) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                user_id,
                (meta.get("title") or "Educational Lesson")[:150],
                f"{style} lesson in {language}",
                style,
                language,
                meta.get("difficulty") or "Beginner",
                meta.get("audience") or "School Students",
                meta.get("aspect_ratio") or "16:9",
                meta.get("filename"),
                int(float(meta.get("duration_seconds") or 0)),
                1 if meta.get("subtitles") else 0,
                1 if meta.get("highlights") else 0,
                1 if meta.get("music") else 0,
                meta.get("script_text") or "",
            ),
        )
        connection.commit()
        return cursor.lastrowid
    except (Error, ValueError, TypeError) as exc:
        connection.rollback()
        app.logger.error("Video record could not be saved: %s", exc)
        return None
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def get_video_for_user(video_id, user_id):
    """Return the video row only if it belongs to this user."""
    connection = get_db_connection()
    if connection is None:
        return None
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM generated_videos WHERE id = %s AND user_id = %s",
            (video_id, user_id),
        )
        return cursor.fetchone()
    except Error as exc:
        app.logger.error("Could not load video: %s", exc)
        return None
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def get_video_context_for_tutor(video_id, user_id=None):
    """Return the video details the AI Tutor needs, or None.

    Only the logged-in user's own video is returned. Used by routes/ai_tutor.py
    through app.config["GET_VIDEO_CONTEXT"] when /ai-tutor/?video_id=<id> is opened.
    Keys: id, title, topic, script, language, style, difficulty, audience.
    """
    if not video_id:
        return None
    if user_id is None:
        user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        video = get_video_for_user(int(video_id), user_id)
    except (TypeError, ValueError):
        return None
    if not video:
        return None
    title = video.get("title") or "Educational Lesson"
    return {
        "id": video.get("id"),
        "title": title,
        "topic": title,
        "script": video.get("script_text") or "",
        "language": video.get("language") or "English",
        "style": video.get("video_style") or "Educational",
        "difficulty": video.get("difficulty") or "Beginner",
        "audience": video.get("audience") or "School Students",
    }


# ============================================================
# CARTOON STUDIO: credit hooks + blueprint + page
# ============================================================
# routes/cartoon_studio.py never imports app.py. It calls these functions through
# app.config, so every cartoon movie is charged, refunded and saved with the SAME
# credit logic as the educational videos. Cost = scenes x CARTOON_CREDITS_PER_SCENE.
app.config["CHARGE_CREDITS"] = charge_credits
app.config["REFUND_CREDITS"] = refund_credits
app.config["GET_USER_CREDITS"] = get_user_credits
app.config["SAVE_VIDEO_RECORD"] = save_video_record_v2
app.config["LOG_ACTIVITY"] = log_activity
app.config["BUMP_VIDEO_PROGRESS"] = bump_video_progress
app.config["GET_VIDEO_FOR_USER"] = get_video_for_user
app.config["GET_VIDEO_CONTEXT"] = get_video_context_for_tutor  # used by the AI Tutor
app.config["CARTOON_CREDITS_PER_SCENE"] = CARTOON_CREDITS_PER_SCENE
app.config["CARTOON_COST"] = lambda scenes: max(1, int(scenes)) * CARTOON_CREDITS_PER_SCENE

try:
    from routes.cartoon_studio import cartoon_bp  # noqa: E402
except ImportError:
    cartoon_bp = None
    app.logger.warning("routes/cartoon_studio.py not found; using the built-in studio page.")

if cartoon_bp is not None and cartoon_bp.name not in app.blueprints:
    app.register_blueprint(cartoon_bp)


@app.context_processor
def inject_cartoon_helpers():
    """Use `{{ cartoon_url }}` and `{{ cartoon_cost_per_scene }}` in templates."""
    try:
        url = url_for("cartoon.cartoon_studio")
    except BuildError:
        url = "/cartoon-studio"
    return {"cartoon_url": url, "cartoon_cost_per_scene": CARTOON_CREDITS_PER_SCENE}


CARTOON_SCENES_BY_DURATION = {"Short": 3, "Medium": 5, "Long": 8}
# These must match the styles in services/cartoon_generator.py (STYLES). The dashboard
# uses this list to tell cartoon movies apart from educational lessons.
CARTOON_STYLES = ["2D", "3D", "Anime", "Storybook", "Kids Cartoon", "Fantasy"]


def _cartoon_ready():
    """True when animation is configured (CARTOON_MODE=free or a FAL_KEY exists)."""
    return (os.getenv("CARTOON_MODE", "").strip().lower() == "free"
            or bool(os.getenv("FAL_KEY", "").strip()))


# Only used when the blueprint does not already provide the studio page.
if "cartoon.cartoon_studio" not in app.view_functions:
    @app.route("/cartoon-studio")
    @login_required
    def cartoon_studio_page():
        return render_template(
            "cartoon_studio.html",
            credits=get_user_credits(session["user_id"]),
            cost_per_scene=CARTOON_CREDITS_PER_SCENE,
            cost_by_duration={"Short": 5, "Medium": 10, "Long": 15},
            scenes_by_duration=CARTOON_SCENES_BY_DURATION,
            styles=CARTOON_STYLES,
            presets={},
            fal_ready=_cartoon_ready(),
        )


@app.route("/api/credits")
@login_required
def api_credits():
    """Live credit balance (the studio page can call this to refresh the badge)."""
    balance = get_user_credits(session["user_id"])
    session["credits"] = balance
    return jsonify(ok=True, credits=balance, video_cost=VIDEO_COST,
                   cartoon_cost_per_scene=CARTOON_CREDITS_PER_SCENE)


def calculate_streak(active_days):
    today = date.today()
    if today not in active_days:
        today -= timedelta(days=1)
    streak = 0
    while today in active_days:
        streak += 1
        today -= timedelta(days=1)
    return streak


def get_game_days(user_id):
    """Dates on which the user played at least one game (used for the daily streak).

    Only games count: game plays, game levels, game activity rows and Aptitude Arena tests.
    Logging in or generating a video does NOT extend the streak.
    """
    days = set()
    connection = get_db_connection()
    if connection is None:
        return days
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        for sql in (
            "SELECT DISTINCT DATE(played_at) AS d FROM game_plays WHERE user_id = %s",
            "SELECT DISTINCT DATE(created_at) AS d FROM game_level_rewards WHERE user_id = %s",
            "SELECT DISTINCT activity_date AS d FROM user_activity "
            "WHERE user_id = %s AND activity_type = 'game'",
        ):
            for row in _pp_query(cursor, sql, (user_id,)):
                if row.get("d") is not None:
                    days.add(row["d"])
        for attempt in _pp_aptitude_attempts(cursor, user_id):
            if attempt.get("at"):
                try:
                    days.add(datetime.fromisoformat(attempt["at"]).date())
                except ValueError:
                    pass
    except Error as exc:
        app.logger.warning("Game days query failed: %s", exc)
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()
    return days


def load_dashboard_data(user_id):
    data = {"credits": 0, "videos": [], "streak": 0, "quizzes_completed": 0}
    connection = get_db_connection()
    if connection is None:
        return data
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        data["credits"] = int(row["credits"] or 0) if row else 0

        cursor.execute(
            "SELECT * FROM generated_videos WHERE user_id = %s "
            "ORDER BY created_at DESC LIMIT 24",
            (user_id,),
        )
        for video in cursor.fetchall():
            data["videos"].append({
                "id": video.get("id"),
                "title": video.get("title") or "Educational Lesson",
                "description": video.get("description") or "Your generated learning video",
                "style": video.get("video_style") or video.get("style") or "AI Lesson",
                "language": video.get("language") or "English",
                "filename": video.get("filename") or video.get("video_filename"),
                "video_url": video.get("video_url"),
                "thumbnail": video.get("thumbnail"),
                "created_at": video.get("created_at"),
            })

        try:
            cursor.execute(
                "SELECT quizzes_completed FROM learning_progress WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            data["quizzes_completed"] = int(row["quizzes_completed"] or 0) if row else 0
        except Error as exc:
            app.logger.warning("Quiz progress query failed: %s", exc)

        try:
            cursor.execute(
                "SELECT DATE(created_at) AS d FROM generated_videos WHERE user_id = %s "
                "UNION SELECT activity_date AS d FROM user_activity WHERE user_id = %s",
                (user_id, user_id),
            )
            data["streak"] = calculate_streak({
                row["d"] for row in cursor.fetchall() if row.get("d") is not None
            })
        except Error as exc:
            app.logger.warning("Streak query failed: %s", exc)
    except Error as exc:
        app.logger.error("Dashboard data query failed: %s", exc)
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()
    return data


# ============================================================
# MY GENERATED VIDEOS
# ============================================================

@app.route("/my-videos")
@login_required
def my_generated_videos():
    # The video library lives on the dashboard ("My Generated Videos" section),
    # so this URL simply sends people there.
    return redirect(url_for("dashboard") + "#my-videos")


# Serve a generated video belonging to the logged-in user
@app.route("/my-videos/watch/<int:video_id>")
@login_required
def watch_generated_video(video_id):
    user_id = session.get("user_id")

    connection = get_db_connection()
    if connection is None:
        abort(503)

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT filename FROM generated_videos WHERE id = %s AND user_id = %s",
            (video_id, user_id),
        )
        video = cursor.fetchone()

        if not video or not video.get("filename"):
            abort(404)

        return redirect(url_for("generated_video_file", filename=video["filename"]))
    finally:
        if cursor:
            cursor.close()
        connection.close()


# Serve only generated files that belong to the logged-in user
@app.route("/generated-videos/<path:filename>")
@login_required
def generated_video_file(filename):
    user_id = session.get("user_id")

    connection = get_db_connection()
    if connection is None:
        abort(503)

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT id FROM generated_videos WHERE user_id = %s AND filename = %s LIMIT 1",
            (user_id, filename),
        )
        record = cursor.fetchone()
        if not record:
            abort(404)
    finally:
        if cursor:
            cursor.close()
        connection.close()

    # Videos are saved by services.video_generator into static/generated
    return send_from_directory(str(GENERATED_DIR), filename, as_attachment=False)


# Download a generated video (owner only) with a meaningful file name
@app.route("/my-videos/download/<int:video_id>")
@login_required
def download_generated_video(video_id):
    video = get_video_for_user(video_id, session["user_id"])
    if not video:
        abort(404)
    filename = Path(video.get("filename") or "").name
    if not filename or not (GENERATED_DIR / filename).is_file():
        flash("This video file is no longer available.", "error")
        return redirect(url_for("dashboard") + "#my-videos")
    nice_name = secure_filename(video.get("title") or "lesson")[:60] or "lesson"
    return send_from_directory(
        str(GENERATED_DIR), filename, as_attachment=True, download_name=nice_name + ".mp4"
    )


# ---- Open one saved cartoon movie (used by "Open in Studio" on the dashboard) ----
CARTOON_MOVIE_PAGE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} | EduVision Cartoon Studio</title>
<style>
body{margin:0;font-family:'Segoe UI',Arial,sans-serif;background:#fbfaff;color:#1f1b3d}
.top{display:flex;align-items:center;gap:16px;padding:12px 28px;background:#1f1b3d;color:#fff}
.top a{color:#d9d5ff;text-decoration:none;font-weight:600}
.brand{margin-right:auto;font-weight:800;font-size:1.2rem;color:#fff!important}
main{max-width:900px;margin:0 auto;padding:28px 20px 60px}
video{width:100%;max-height:70vh;background:#000;border-radius:14px}
h1{margin:20px 0 4px}.meta{color:#645f82}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.btn{padding:12px 22px;border-radius:11px;font-weight:800;text-decoration:none}
.primary{background:#5546e8;color:#fff}.ghost{background:#f0eeff;color:#4335cb}
</style></head><body>
<header class="top">
  <a class="brand" href="{{ dashboard_url }}">EduVision Cartoon Studio</a>
  <a href="{{ dashboard_url }}#my-videos">My videos</a>
</header>
<main>
  <video controls preload="metadata" src="{{ video_url }}"></video>
  <h1>{{ title }}</h1>
  <p class="meta">{{ style }} &middot; {{ language }}{% if created %} &middot; {{ created }}{% endif %}</p>
  <div class="row">
    <a class="btn primary" href="{{ download_url }}">Download movie</a>
    <a class="btn ghost" href="{{ studio_url }}">Make another cartoon</a>
    <a class="btn ghost" href="{{ dashboard_url }}#my-videos">Back to my videos</a>
  </div>
</main></body></html>
"""


@app.route("/cartoon-movie/<int:video_id>")
@login_required
def cartoon_movie_page(video_id):
    """Open one saved cartoon movie (owner only). Cartoon movies have no quiz."""
    video = get_video_for_user(video_id, session["user_id"])
    if not video:
        abort(404)
    filename = Path(video.get("filename") or "").name
    if not filename or not (GENERATED_DIR / filename).is_file():
        flash("This movie file is no longer available.", "error")
        return redirect(url_for("dashboard") + "#my-videos")

    try:
        studio_url = url_for("cartoon.cartoon_studio")
    except BuildError:
        studio_url = "/cartoon-studio"

    created = video.get("created_at")
    return render_template_string(
        CARTOON_MOVIE_PAGE,
        title=video.get("title") or "Cartoon Movie",
        style=(video.get("video_style") or "Cartoon").replace("_", " ").title(),
        language=(video.get("language") or "English").title(),
        created=created.strftime("%d %b %Y") if hasattr(created, "strftime") else "",
        video_url=url_for("generated_video_file", filename=filename),
        download_url=url_for("download_generated_video", video_id=video_id),
        studio_url=studio_url,
        dashboard_url=url_for("dashboard"),
    )


# Delete a generated video belonging to the logged-in user
@app.route("/my-videos/delete/<int:video_id>", methods=["POST"])
@login_required
def delete_generated_video(video_id):
    user_id = session.get("user_id")

    connection = get_db_connection()
    if connection is None:
        flash("Database connection failed.", "error")
        return redirect(url_for("dashboard") + "#my-videos")

    cursor = None
    filename = None

    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT filename FROM generated_videos WHERE id = %s AND user_id = %s",
            (video_id, user_id),
        )
        record = cursor.fetchone()

        if not record:
            flash("Video not found.", "error")
            return redirect(url_for("dashboard") + "#my-videos")

        filename = record[0]

        cursor.execute(
            "DELETE FROM generated_videos WHERE id = %s AND user_id = %s",
            (video_id, user_id),
        )
        connection.commit()

        if filename:
            video_path = GENERATED_DIR / os.path.basename(filename)
            if video_path.is_file():
                video_path.unlink()

        flash("Video deleted successfully.", "success")

    except Error as exc:
        connection.rollback()
        app.logger.error("Video deletion failed: %s", exc)
        flash("Could not delete the video.", "error")

    finally:
        if cursor:
            cursor.close()
        connection.close()

    return redirect(url_for("dashboard") + "#my-videos")


# ============================================================
# GAME CATALOG - EDUVISION
# ============================================================

def _game(name, mode, reward=10, min_seconds=10, once_a_day=False):
    return {
        "name": name,
        "title": name,
        "mode": mode,
        "reward": reward,
        "min_seconds": min_seconds,
        "once_a_day": once_a_day,
    }


APP_GAMES = {
    "arrow_maze": _game("Arrow Finder: Arrow Maze", "arrow_maze"),
    "hologram_memory": _game("Hologram Memory Challenge", "hologram_memory"),
    "candy_match": _game("Candy Match Puzzle", "candy_match"),
    "memory_match": _game("Memory Card Matching", "memory_match"),
    "bubble_shooter": _game("Bubble Shooter", "bubble_shooter"),
    "endless_runner": _game("Endless Runner", "endless_runner"),
    "neon_tic_tac_toe": _game("Neon Tic-Tac-Toe", "neon_tic_tac_toe"),
    "puzzle_2048": _game("2048 Number Puzzle", "puzzle_2048"),
    "arrow_direction": _game("Arrow Direction Puzzle", "arrow_direction"),
    "sliding_puzzle": _game("Sliding Puzzle", "sliding_puzzle"),
    "quiz_battle": _game("Quiz Battle Arena", "quiz_battle"),
    "tetris_blocks": _game("Tetris Blocks", "tetris_blocks"),
    "flappy_brain": _game("Flappy Brain", "flappy_brain"),
    "snake_game": _game("Snake Game", "snake_game"),
}

# The current app/game.js IDs are the canonical catalog. game_data.py is used
# only as a content provider for overlapping IDs; app-only IDs get fallback payloads.
GAMES = APP_GAMES

_FALLBACK_TERMS = [
    {"term": "Input", "definition": "Data given to a system."},
    {"term": "Process", "definition": "Work performed on the input."},
    {"term": "Output", "definition": "The result produced by a system."},
    {"term": "Algorithm", "definition": "A step-by-step method to solve a problem."},
    {"term": "Variable", "definition": "A named place to store a value."},
    {"term": "Database", "definition": "An organized collection of information."},
]


def build_payload(game_key, game=None):
    """Use game_data.py payloads where available; provide safe fallback data for app-only IDs."""
    game = game or GAMES.get(game_key, {})
    if game_key in DATA_GAMES:
        try:
            payload = data_build_payload(game_key, DATA_GAMES[game_key])
            if isinstance(payload, dict):
                payload.setdefault("key", game_key)
                payload.setdefault("game_id", game_key)
                payload.setdefault("name", game.get("name", game_key.replace("_", " ").title()))
                payload.setdefault("title", payload.get("name"))
                payload.setdefault("mode", game.get("mode", "quiz"))
                payload.setdefault("terms", _FALLBACK_TERMS)
                payload.setdefault("items", payload.get("terms", _FALLBACK_TERMS))
                payload.setdefault("questions", [])
                return payload
        except Exception:
            app.logger.exception("game_data.build_payload failed for %s; using fallback", game_key)
    return {
        **game,
        "key": game_key,
        "game_id": game_key,
        "id": game_key,
        "name": game.get("name", game_key.replace("_", " ").title()),
        "title": game.get("title", game.get("name", game_key.replace("_", " ").title())),
        "mode": game.get("mode", game_key),
        "terms": _FALLBACK_TERMS,
        "items": _FALLBACK_TERMS,
        "match_items": _FALLBACK_TERMS,
        "questions": [],
    }


# ============================================================
# GAME PAGES
# ============================================================

@app.route("/game")
@login_required
def games():
    return render_template(
        "arcade.html",
        user_name=session.get("user_name", "Student"),
        credits=get_user_credits(session["user_id"]),
        games=GAMES,
    )


@app.route("/learn/arcade")
@login_required
def arcade():
    return render_template(
        "arcade.html",
        user_name=session.get("user_name", "Student"),
        credits=get_user_credits(session["user_id"]),
        games=GAMES,
    )


@app.route("/game/<game_key>")
@login_required
def eduvision_game(game_key):
    game = GAMES.get(game_key)

    if game is None:
        abort(404)

    payload = build_payload(game_key, game)

    return render_template(
        "game.html",
        payload=payload,
        game_key=game_key,
        game_title=game["name"],
        game_type=game["mode"],
        credits=get_user_credits(session["user_id"]),
        daily_cap=DAILY_CREDIT_CAP,
        video_cost=VIDEO_COST,
    )


@app.route("/arcade/<game_key>")
@login_required
def play_game(game_key):
    if game_key not in GAMES:
        abort(404)
    return redirect(url_for("eduvision_game", game_key=game_key))


@app.route("/play/<game_key>")
@login_required
def play_game_redirect(game_key):
    if game_key not in GAMES:
        abort(404)
    return redirect(url_for("eduvision_game", game_key=game_key))


@app.route("/api/game-result", methods=["POST"])
@login_required
def game_result():
    data = request.get_json(silent=True) or {}

    # Get game information from the frontend
    game_name = str(
        data.get("game_name") or data.get("game_key") or ""
    ).strip()

    try:
        score = int(data.get("score", 0))
    except (ValueError, TypeError):
        return jsonify(
            ok=False,
            error="Invalid game score."
        ), 400

    if not game_name or len(game_name) > 100:
        return jsonify(
            ok=False,
            error="Invalid game name."
        ), 400

    if score < 0:
        return jsonify(
            ok=False,
            error="Score cannot be negative."
        ), 400

    user_id = session["user_id"]

    # Save the completed game in MySQL.
    # Credits remain zero until the server-side reward
    # calculation is connected.
    saved = save_game_result(
        user_id=user_id,
        game_name=game_name,
        score=score,
        credits_earned=0
    )

    if not saved:
        return jsonify(
            ok=False,
            error="Game result could not be saved."
        ), 500

    session["games_played"] = session.get("games_played", 0) + 1

    return jsonify(
        ok=True,
        message="Game result saved successfully.",
        games_played=session["games_played"]
    )



def _game_alias(game_key):
    def open_alias():
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return redirect(url_for("eduvision_game", game_key=game_key))
    return open_alias


# Legacy URLs that still point to active games.
_GAME_ROUTE_ALIASES = {
    "legacy_candy_match": ("candy_match", "/games/candy_match"),
    "legacy_mind_match": ("memory_match", "/games/mind_match"),
}

for _endpoint, (_alias_key, _legacy_url) in _GAME_ROUTE_ALIASES.items():
    app.add_url_rule(
        _legacy_url,
        endpoint=_endpoint,
        view_func=_game_alias(_alias_key),
        methods=["GET"],
    )


# ============================================================
# HOME AND AUTHENTICATION
# ============================================================

@app.route("/")
def index():
    return render_template("index.html", game_count=len(GAMES))


def send_otp_email(email, otp, purpose):
    """Send a time-limited one-time code. Configure Gmail app password in .env."""
    if not MAIL_USERNAME or not MAIL_PASSWORD or not MAIL_FROM:
        raise RuntimeError("Email is not configured. Set MAIL_USERNAME, MAIL_PASSWORD and MAIL_FROM in .env.")
    message = EmailMessage()
    message["Subject"] = f"EduVision {purpose} verification code"
    message["From"] = MAIL_FROM
    message["To"] = email
    message.set_content(
        f"Your EduVision verification code is: {otp}\n\n"
        f"This code expires in {OTP_EXPIRY_MINUTES} minutes. Do not share it with anyone.\n"
        "If you did not request this code, you can ignore this email."
    )
    if MAIL_PORT == 465:
        with smtplib.SMTP_SSL(MAIL_SERVER, MAIL_PORT, timeout=20) as server:
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(message)


def otp_page(title, action, message, include_password=False, include_email=False):
    password_fields = """
      <label>New password</label><input type="password" name="new_password" minlength="8" required>
      <label>Confirm new password</label><input type="password" name="confirm_password" minlength="8" required>
    """ if include_password else ""
    email_field = '<label>Email address</label><input type="email" name="email" required>' if include_email else ""
    return render_template_string("""
    <!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{{ title }} | EduVision</title><style>
    body{font-family:Arial,sans-serif;background:#f4f6fb;display:grid;place-items:center;min-height:100vh;margin:0;color:#182033}
    .card{width:min(420px,90vw);background:#fff;padding:30px;border-radius:18px;box-shadow:0 12px 40px #18203318}
    h1{font-size:25px;margin-top:0}p{color:#5c6475;line-height:1.5}label{display:block;margin:16px 0 6px;font-weight:600}
    input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #d7dce7;border-radius:9px;font-size:16px}
    button{margin-top:20px;width:100%;border:0;border-radius:9px;padding:13px;background:#5546e8;color:white;font-size:16px;font-weight:700;cursor:pointer}
    a{color:#5546e8;text-decoration:none}.message{background:#f2f0ff;padding:10px;border-radius:8px}</style></head><body>
    <main class="card"><h1>{{ title }}</h1><p>{{ message }}</p>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for category, flash_message in messages %}<p class="message">{{ flash_message }}</p>{% endfor %}
    {% endwith %}
    <form method="post" action="{{ action }}">{{ email_field|safe }}
    <label>6-digit verification code</label><input name="otp" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" minlength="6" maxlength="6" required>
    {{ password_fields|safe }}<button type="submit">Verify and continue</button></form><p><a href="{{ url_for('login') }}">Back to login</a></p></main></body></html>
    """, title=title, action=action, message=message, password_fields=password_fields,
       email_field=email_field)


def _verify_otp(table_name, email, otp):
    # Only internal table names are allowed.
    allowed_tables = {
        "registration_otp_pending",
        "login_otp_pending",
        "password_reset_pending",
    }

    if table_name not in allowed_tables:
        app.logger.error("Invalid OTP table name.")
        return False, "Unable to verify the code."

    connection = get_db_connection()
    if connection is None:
        return False, "Database connection error."

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            f"SELECT otp_hash, expires_at, attempts FROM {table_name} WHERE email = %s FOR UPDATE",
            (email,),
        )

        row = cursor.fetchone()

        if not row:
            connection.rollback()
            return False, "No verification request was found. Request a new code."

        if int(row.get("attempts") or 0) >= OTP_MAX_ATTEMPTS:
            cursor.execute(f"DELETE FROM {table_name} WHERE email = %s", (email,))
            connection.commit()
            return False, "Too many attempts. Request a new code."

        expiry = row["expires_at"]

        if expiry is None or expiry < datetime.now():
            cursor.execute(f"DELETE FROM {table_name} WHERE email = %s", (email,))
            connection.commit()
            return False, "The code expired. Request a new one."

        if not check_password_hash(row["otp_hash"], otp):
            cursor.execute(
                f"UPDATE {table_name} SET attempts = attempts + 1 WHERE email = %s",
                (email,),
            )
            connection.commit()
            return False, "Incorrect verification code. Please try again."

        connection.commit()
        return True, "Verified."

    except Error:
        connection.rollback()
        app.logger.exception("OTP verification database error")
        return False, "Unable to verify the code. Please try again."

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()[:100]
    email = request.form.get("email", "").strip().lower()[:150]
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not name or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        flash("Enter your name and a valid email address.", "error")
        return redirect(url_for("register"))

    if len(password) < 8:
        flash("Password must contain at least 8 characters.", "error")
        return redirect(url_for("register"))

    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect(url_for("register"))

    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("register"))

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT id FROM users WHERE email = %s LIMIT 1", (email,))
        if cursor.fetchone():
            flash("This email is already registered. Please log in instead.", "error")
            return redirect(url_for("login"))

        otp = f"{secrets.randbelow(1000000):06d}"
        password_hash = generate_password_hash(password)
        otp_hash = generate_password_hash(otp)
        expiry_time = datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

        cursor.execute(
            """
            INSERT INTO registration_otp_pending
                (email, name, password_hash, otp_hash,
                 expires_at, attempts, created_at)
            VALUES (%s, %s, %s, %s, %s, 0, NOW())
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                password_hash = VALUES(password_hash),
                otp_hash = VALUES(otp_hash),
                expires_at = VALUES(expires_at),
                attempts = 0,
                created_at = NOW()
            """,
            (email, name, password_hash, otp_hash, expiry_time),
        )
        connection.commit()

        # Send the OTP after saving the pending registration
        send_otp_email(email, otp, "registration")

        session["registration_otp_email"] = email
        flash("A verification code has been sent to your email.", "success")
        return redirect(url_for("verify_otp"))

    except (Error, RuntimeError, OSError, smtplib.SMTPException):
        connection.rollback()
        app.logger.exception("Registration OTP could not be sent")
        flash("Unable to complete registration. Please check your email settings and try again.", "error")
        return redirect(url_for("register"))

    finally:
        if cursor:
            cursor.close()
        connection.close()


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    email = session.get("registration_otp_email", "")
    if not email:
        flash("Please register first to request a verification code.", "warning")
        return redirect(url_for("register"))

    if request.method == "GET":
        return render_template("verify_otp.html", email=email)

    otp = request.form.get("otp", "").strip()
    if not re.fullmatch(r"\d{6}", otp):
        flash("Enter the six-digit code.", "error")
        return redirect(url_for("verify_otp"))

    ok, message = _verify_otp("registration_otp_pending", email, otp)
    if not ok:
        flash(message, "error")
        return redirect(url_for("verify_otp"))

    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("verify_otp"))

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT name,password_hash FROM registration_otp_pending WHERE email=%s", (email,))
        pending = cursor.fetchone()
        if not pending:
            flash("Registration request expired. Please register again.", "error")
            return redirect(url_for("register"))

        cursor.execute(
            "INSERT INTO users (name,email,password,credits) VALUES (%s,%s,%s,%s)",
            (pending["name"], email, pending["password_hash"], INITIAL_CREDITS),
        )
        user_id = cursor.lastrowid
        cursor.execute(
            "INSERT IGNORE INTO learning_progress (user_id,videos_generated,quizzes_completed,games_played,total_score) "
            "VALUES (%s,0,0,0,0)",
            (user_id,),
        )
        cursor.execute("DELETE FROM registration_otp_pending WHERE email=%s", (email,))
        connection.commit()

        session.pop("registration_otp_email", None)
        flash("Your account is verified and created. Please log in.", "success")
        return redirect(url_for("login"))

    except Error:
        connection.rollback()
        app.logger.exception("Account creation after OTP failed")
        flash("Unable to finish registration. Please try again.", "error")
        return redirect(url_for("verify_otp"))
    finally:
        if cursor:
            cursor.close()
        connection.close()


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    email = session.get("registration_otp_email", "")
    if not email:
        flash("Please register first to request a verification code.", "warning")
        return redirect(url_for("register"))

    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("verify_otp"))

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT created_at FROM registration_otp_pending WHERE email = %s",
            (email,),
        )
        row = cursor.fetchone()
        if not row:
            flash("Registration request expired. Please register again.", "error")
            return redirect(url_for("register"))

        # Server-side cooldown so the button cannot be spammed.
        if row.get("created_at"):
            age = (datetime.now() - row["created_at"]).total_seconds()
            if age < 30:
                flash("Please wait a few seconds before requesting another code.", "warning")
                return redirect(url_for("verify_otp"))

        otp = f"{secrets.randbelow(1000000):06d}"
        cursor.execute(
            "UPDATE registration_otp_pending "
            "SET otp_hash = %s, expires_at = %s, attempts = 0, created_at = NOW() "
            "WHERE email = %s",
            (
                generate_password_hash(otp),
                datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES),
                email,
            ),
        )
        connection.commit()
        send_otp_email(email, otp, "registration")
        flash("A new verification code has been sent to your email.", "success")
    except (Error, RuntimeError, OSError, smtplib.SMTPException):
        connection.rollback()
        app.logger.exception("Registration OTP could not be re-sent")
        flash("Unable to send a new code. Please try again.", "error")
    finally:
        if cursor:
            cursor.close()
        connection.close()

    return redirect(url_for("verify_otp"))


def _safe_next(target):
    """Only allow local paths as post-login destinations."""
    target = target or ""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return ""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        # Remember where the user wanted to go, even if the login form
        # does not send ?next=... back to the server.
        next_url = _safe_next(request.args.get("next"))
        if next_url:
            session["login_next_hint"] = next_url
        return render_template("login.html", next_url=next_url)

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not email or not password:
        flash("Enter both your email and password.", "error")
        return redirect(url_for("login"))
    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("login"))
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id,name,email,password,credits FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        if not user or not check_password_hash(user["password"], password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))
        otp = f"{secrets.randbelow(1000000):06d}"
        cursor.execute(
            "INSERT INTO login_otp_pending (email,otp_hash,expires_at,attempts,created_at) VALUES (%s,%s,%s,0,NOW()) "
            "ON DUPLICATE KEY UPDATE otp_hash=VALUES(otp_hash),expires_at=VALUES(expires_at),attempts=0,created_at=NOW()",
            (email, generate_password_hash(otp), datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)),
        )
        connection.commit()
        send_otp_email(email, otp, "login")

        # Read the destination BEFORE clearing the session, then restore it.
        target = _safe_next(
            request.args.get("next")
            or request.form.get("next")
            or session.get("login_next_hint")
        )
        session.clear()
        session["login_otp_email"] = email
        if target:
            session["login_next"] = target

        flash("A login verification code has been sent to your email.", "success")
        return redirect(url_for("verify_login_otp"))
    except (Error, RuntimeError, OSError, smtplib.SMTPException):
        connection.rollback()
        app.logger.exception("Login OTP could not be sent")
        flash("Unable to send login code. Check email settings and try again.", "error")
        return redirect(url_for("login"))
    finally:
        if cursor:
            cursor.close()
        connection.close()


@app.route("/verify-login-otp", methods=["GET", "POST"])
def verify_login_otp():
    email = session.get("login_otp_email", "")

    if not email:
        flash("Please log in again to request a code.", "warning")
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Verify Login | EduVision</title>
            <style>
                * { box-sizing: border-box; }
                body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 20px;
                    font-family: Arial, sans-serif; background: linear-gradient(135deg, #eef2ff, #f8fafc); color: #172033; }
                .card { width: 100%; max-width: 420px; padding: 32px; background: white; border-radius: 20px;
                    box-shadow: 0 15px 45px rgba(30, 41, 59, .12); }
                .logo { color: #5546e8; font-size: 15px; font-weight: bold; letter-spacing: 1px; }
                h1 { margin-bottom: 10px; font-size: 28px; }
                p { color: #647084; line-height: 1.6; }
                .email { overflow-wrap: anywhere; color: #5546e8; font-weight: bold; }
                label { display: block; margin: 20px 0 8px; font-weight: bold; }
                input { width: 100%; padding: 14px; border: 1px solid #d7ddec; border-radius: 10px;
                    font-size: 20px; letter-spacing: 6px; text-align: center; }
                button { width: 100%; padding: 14px; margin-top: 18px; border: 0; border-radius: 10px;
                    background: #5546e8; color: white; font-size: 16px; font-weight: bold; cursor: pointer; }
                button:hover { background: #4335cb; }
                .secondary { margin-top: 10px; background: #eef0ff; color: #4435c7; }
                .secondary:hover { background: #e0e4ff; }
                .messages { margin: 15px 0; padding: 10px; border-radius: 8px; background: #f3f4f6; }
                .back { display: block; margin-top: 20px; text-align: center; color: #5546e8; text-decoration: none; }
            </style>
        </head>
        <body>
            <main class="card">
                <div class="logo">EDUVISION</div>
                <h1>Verify your login</h1>
                <p>Enter the six-digit verification code sent to:</p>
                <p class="email">{{ email }}</p>

                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% if messages %}
                        {% for category, message in messages %}
                            <div class="messages">{{ message }}</div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}

                <form method="post" action="{{ url_for('verify_login_otp') }}">
                    <label for="otp">Verification code</label>
                    <input id="otp" type="text" name="otp" inputmode="numeric" autocomplete="one-time-code"
                        pattern="[0-9]{6}" minlength="6" maxlength="6" placeholder="000000" required>
                    <button type="submit">Verify and continue</button>
                </form>

                <form method="post" action="{{ url_for('resend_login_otp') }}">
                    <button class="secondary" type="submit">Resend verification code</button>
                </form>

                <a class="back" href="{{ url_for('login') }}">Back to login</a>
            </main>
        </body>
        </html>
        """, email=email)

    otp = request.form.get("otp", "").strip()
    if not re.fullmatch(r"\d{6}", otp):
        flash("Enter the six-digit code.", "error")
        return redirect(url_for("verify_login_otp"))

    ok, message = _verify_otp("login_otp_pending", email, otp)
    if not ok:
        flash(message, "error")
        return redirect(url_for("verify_login_otp"))

    connection = get_db_connection()
    if connection is None:
        flash("Database connection error. Please try again.", "error")
        return redirect(url_for("login"))

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, name, email, credits FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if not user:
            flash("Account not found. Please log in again.", "error")
            return redirect(url_for("login"))

        cursor.execute("DELETE FROM login_otp_pending WHERE email = %s", (email,))
        connection.commit()

        # Preserve the intended destination before clearing the session.
        target = _safe_next(session.get("login_next", ""))

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session["credits"] = int(user["credits"] or 0)

        # Aliases so other modules written with different key names still
        # recognise the logged-in user.
        session["logged_in"] = True
        session["id"] = user["id"]
        session["name"] = user["name"]
        session["user"] = user["name"]
        session["username"] = user["name"]
        session["email"] = user["email"]

        log_activity(user["id"], "login")

        if target:
            return redirect(target)

        return redirect(url_for("dashboard"))

    except Error:
        connection.rollback()
        app.logger.exception("Login OTP completion failed")
        flash("Unable to complete login. Please try again.", "error")
        return redirect(url_for("login"))
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


@app.route("/resend-login-otp", methods=["POST"])
def resend_login_otp():
    email = session.get("login_otp_email", "")

    if not email:
        flash("Please log in again to request a code.", "warning")
        return redirect(url_for("login"))

    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("verify_login_otp"))

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        # Server-side cooldown so the button cannot be spammed.
        cursor.execute("SELECT created_at FROM login_otp_pending WHERE email = %s", (email,))
        row = cursor.fetchone()

        if row and row.get("created_at"):
            age = (datetime.now() - row["created_at"]).total_seconds()
            if age < 30:
                flash("Please wait a few seconds before requesting another code.", "warning")
                return redirect(url_for("verify_login_otp"))

        otp = f"{secrets.randbelow(1000000):06d}"

        cursor.execute(
            "INSERT INTO login_otp_pending (email, otp_hash, expires_at, attempts, created_at) "
            "VALUES (%s, %s, %s, 0, NOW()) "
            "ON DUPLICATE KEY UPDATE otp_hash = VALUES(otp_hash), "
            "expires_at = VALUES(expires_at), attempts = 0, created_at = NOW()",
            (email, generate_password_hash(otp), datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)),
        )
        connection.commit()

        send_otp_email(email, otp, "login")
        flash("A new verification code has been sent to your email.", "success")

    except (Error, RuntimeError, OSError, smtplib.SMTPException):
        connection.rollback()
        app.logger.exception("Login OTP could not be re-sent")
        flash("Unable to send a new code. Please try again.", "error")

    finally:
        if cursor:
            cursor.close()
        connection.close()

    return redirect(url_for("verify_login_otp"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        # Email-only form so the user's email ownership is verified before a new password is set.
        return render_template_string("""
        <!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Forgot password | EduVision</title><style>
        body{font-family:Arial,sans-serif;background:#f4f6fb;display:grid;place-items:center;min-height:100vh;margin:0;color:#182033}
        .card{width:min(420px,90vw);background:#fff;padding:30px;border-radius:18px;box-shadow:0 12px 40px #18203318}
        h1{font-size:25px}p{color:#5c6475;line-height:1.5}label{display:block;margin:16px 0 6px;font-weight:600}
        input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #d7dce7;border-radius:9px;font-size:16px}
        button{margin-top:20px;width:100%;border:0;border-radius:9px;padding:13px;background:#5546e8;color:white;font-size:16px;font-weight:700;cursor:pointer}
        a{color:#5546e8;text-decoration:none}</style></head><body><main class="card"><h1>Reset your password</h1>
        <p>Enter your account email. We will send a verification code if an account is registered.</p>
        <form method="post"><label>Email address</label><input type="email" name="email" autocomplete="email" required>
        <button type="submit">Send verification code</button></form><p><a href="{{ url_for('login') }}">Back to login</a></p></main></body></html>
        """)
    email = request.form.get("email", "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("forgot_password"))
    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("forgot_password"))
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        exists = cursor.fetchone() is not None
        # Generic response to avoid revealing whether an account exists.
        if exists:
            otp = f"{secrets.randbelow(1000000):06d}"
            cursor.execute(
                "INSERT INTO password_reset_pending (email,otp_hash,expires_at,attempts,created_at) VALUES (%s,%s,%s,0,NOW()) "
                "ON DUPLICATE KEY UPDATE otp_hash=VALUES(otp_hash),expires_at=VALUES(expires_at),attempts=0,created_at=NOW()",
                (email, generate_password_hash(otp), datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)),
            )
            connection.commit()
            send_otp_email(email, otp, "password reset")
            session["password_reset_email"] = email
            flash("If an account exists for that email, a password reset code has been sent.", "success")
            return redirect(url_for("reset_password"))
        session["password_reset_email"] = email
        flash("If an account exists for that email, a password reset code has been sent.", "success")
        return redirect(url_for("reset_password"))
    except (Error, RuntimeError, OSError, smtplib.SMTPException):
        connection.rollback()
        app.logger.exception("Password reset code could not be sent")
        flash("Unable to send reset code. Check email settings and try again.", "error")
        return redirect(url_for("forgot_password"))
    finally:
        if cursor:
            cursor.close()
        connection.close()


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("password_reset_email", "")
    if not email:
        flash("Request a password reset code first.", "warning")
        return redirect(url_for("forgot_password"))
    if request.method == "GET":
        return otp_page("Reset password", url_for("reset_password"),
                        f"Enter the code sent to {email} and choose a new password.", include_password=True)
    otp = request.form.get("otp", "").strip()
    password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not re.fullmatch(r"\d{6}", otp):
        flash("Enter the six-digit verification code.", "error")
        return redirect(url_for("reset_password"))
    if len(password) < 8:
        flash("Use a password with at least 8 characters.", "error")
        return redirect(url_for("reset_password"))
    if password != confirm:
        flash("Passwords do not match.", "error")
        return redirect(url_for("reset_password"))
    ok, message = _verify_otp("password_reset_pending", email, otp)
    if not ok:
        flash(message, "error")
        return redirect(url_for("reset_password"))
    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("reset_password"))
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET password=%s WHERE email=%s", (generate_password_hash(password), email))
        if cursor.rowcount != 1:
            connection.rollback()
            flash("Unable to reset password. Request a new code.", "error")
            return redirect(url_for("forgot_password"))
        cursor.execute("DELETE FROM password_reset_pending WHERE email=%s", (email,))
        connection.commit()
        session.pop("password_reset_email", None)
        flash("Password updated successfully. Please log in.", "success")
        return redirect(url_for("login"))
    except Error:
        connection.rollback()
        app.logger.exception("Password reset failed")
        flash("Unable to update your password.", "error")
        return redirect(url_for("reset_password"))
    finally:
        if cursor:
            cursor.close()
        connection.close()


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("login"))


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/generated/<path:filename>")
@login_required
def generated_video(filename):
    """Serve generated videos (owner only; same check as /generated-videos/)."""
    return generated_video_file(filename)


# The dashboard template no longer contains the video form, cartoon promo or game hub.
# This safety net removes any leftover <section> that still contains these headings,
# using proper open/close tag counting (works with nested sections).
_DASHBOARD_REMOVE_PHRASES = [
    "BRING YOUR IDEAS TO LIFE",
    "Create something amazing",
    "STORIES THAT MOVE",
    "AI Cartoon & Animation Studio",
    "AI Cartoon &amp; Animation Studio",
]
_SECTION_TAG = re.compile(r"<(/?)section\b", re.I)


def _strip_sections_with_text(html, phrases):
    for phrase in phrases:
        search_from = 0
        while True:
            idx = html.lower().find(phrase.lower(), search_from)
            if idx == -1:
                break
            start = html.rfind("<section", 0, idx)
            if start == -1:
                search_from = idx + len(phrase)
                continue
            depth, end = 0, None
            for m in _SECTION_TAG.finditer(html, start):
                depth += -1 if m.group(1) else 1
                if depth == 0:
                    end = html.find(">", m.end()) + 1
                    break
            # Only remove if the section really wraps the phrase.
            if end is None or end <= idx:
                search_from = idx + len(phrase)
                continue
            html = html[:start] + html[end:]
            search_from = start
    return html


def _clean_dashboard_html(html):
    """Keep the dashboard clean: no video form, cartoon promo or game hub on the main page.

    Generate Educational Video and Create Cartoon Movie stay in the sidebar.
    """
    return _strip_sections_with_text(html, _DASHBOARD_REMOVE_PHRASES)


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    data = load_dashboard_data(user_id)
    videos_completed = len(data["videos"])
    quizzes_completed = data["quizzes_completed"]
    games_played = 0
    learning_progress_value = 0
    recent_activities = []

    connection = get_db_connection()
    if connection is not None:
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM game_plays WHERE user_id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
                games_played = int((row or {}).get("total") or 0)
            except Error as exc:
                app.logger.warning("Game count query failed: %s", exc)

            cursor.execute(
                "SELECT videos_generated, quizzes_completed, games_played, total_score "
                "FROM learning_progress WHERE user_id = %s",
                (user_id,),
            )
            progress = cursor.fetchone()
            if progress:
                videos_completed = int(progress["videos_generated"] or 0)
                quizzes_completed = int(progress["quizzes_completed"] or 0)
                games_played = int(progress["games_played"] or 0)
                learning_progress_value = max(0, min(100, int(progress["total_score"] or 0)))

            cursor.execute(
                "SELECT title AS activity, created_at AS activity_date "
                "FROM generated_videos WHERE user_id = %s "
                "ORDER BY created_at DESC LIMIT 5",
                (user_id,),
            )
            recent_activities = [
                {"activity": row["activity"] or "Learning video", "date": row["activity_date"]}
                for row in cursor.fetchall()
            ]
        except Error:
            app.logger.exception("Could not load dashboard statistics")
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

    session["credits"] = data["credits"]

    # Daily streak: counts only days with a played game. Missing a day breaks it.
    game_days = get_game_days(user_id)
    today = date.today()
    streak_value = calculate_streak(game_days)
    played_today = today in game_days
    week_days = [(today - timedelta(days=6 - i)) in game_days for i in range(7)]

    # Build the "My Generated Videos" library
    generated_videos = []

    for video in data["videos"][:12]:
        filename = Path(video.get("filename") or "").name

        # Skip records whose video file does not exist
        if not filename or not (GENERATED_DIR / filename).is_file():
            continue

        # Cartoon movies are saved with a cartoon style (3D, 2D, Anime, ...).
        style_name = str(video.get("style") or "Educational")
        is_cartoon = (
            style_name.strip().lower() in {c.lower() for c in CARTOON_STYLES}
            or "cartoon" in style_name.lower()
        )

        generated_videos.append({
            "id": video.get("id"),
            "title": video.get("title") or ("Cartoon Movie" if is_cartoon else "Untitled Lesson"),
            "video_type": "cartoon" if is_cartoon else "educational",
            "cartoon_style": style_name if is_cartoon else "",
            "download_url": url_for("download_generated_video", video_id=video.get("id")),
            "video_style": style_name,
            "language": video.get("language") or "English",
            "filename": filename,
            "url": url_for("generated_video", filename=filename),
            "quiz_url": url_for("video_quiz.video_quiz_page", video_id=video.get("id")),
            # AI Doubt Tutor opens with THIS video's context (/ai-tutor/?video_id=<id>)
            "tutor_url": tutor_url_for_video(video.get("id")),
            "created_at": video.get("created_at") or "",
        })

    # Latest available video for the learning workspace
    latest_video = ""
    latest_video_topic = ""
    latest_video_exists = False
    latest_video_id = None

    if generated_videos:
        latest_video = generated_videos[0]["filename"]
        latest_video_topic = generated_videos[0]["title"]
        latest_video_id = generated_videos[0]["id"]
        latest_video_exists = True

    # Recent videos for other dashboard sections
    recent_videos = [
        {
            "prompt": video["title"],
            "video_style": video["video_style"],
            "language": video["language"],
        }
        for video in generated_videos[:5]
    ]

    page_html = render_template(
        "dashboard.html",
        user_name=session.get("user_name", "Learner"),
        user_email=session.get("user_email", ""),
        credits=data["credits"],
        videos=data["videos"],
        generated_videos=generated_videos,
        recent_videos=recent_videos,
        latest_video=latest_video,
        latest_video_topic=latest_video_topic,
        latest_video_exists=latest_video_exists,
        latest_video_id=latest_video_id,
        latest_quiz_url=(url_for("video_quiz.video_quiz_page", video_id=latest_video_id)
                         if latest_video_id else ""),
        latest_tutor_url=(tutor_url_for_video(latest_video_id) if latest_video_id else ""),
        videos_completed=videos_completed,
        quizzes_completed=quizzes_completed,
        games_played=games_played,
        learning_progress=learning_progress_value,
        learning_streak=streak_value,
        streak=streak_value,
        daily_done=played_today,
        week_days=week_days,
        recent_activities=recent_activities,
        games=GAMES,
        progress={
            "videos_generated": videos_completed,
            "videos_completed": videos_completed,
            "quizzes_completed": quizzes_completed,
            "games_played": games_played,
        },
    )
    return _clean_dashboard_html(page_html)


@app.route("/ask_question", methods=["POST"])
@login_required
def ask_question():
    """Used by the dashboard 'Ask EduAI' box. Connect your AI/Q&A service here."""
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify(error="Please enter a question."), 400
    return jsonify(
        answer="EduAI Q&A is not connected yet. Open the Q&A page from the menu "
               "to ask your question."
    )


# ============================================================
# VIDEO GENERATION
# ============================================================
# Two ways in:
#   POST /generate_video/start          (AJAX) charges the credits, starts a background job -> {job_id, credits}
#   GET  /generate_video/status/<id>    (AJAX) live percent, message, credits, result or error
#   GET  /generate_video/active         (AJAX) the user's running job, if any (page refresh)
#   POST /generate_video/cancel         (AJAX) stops the job and refunds the credits
#   POST /generate_video                (plain form) waits and redirects
#
# CREDITS: the cost is deducted the moment generation starts (inside /start), and the
# live balance is returned with every status poll. It is refunded automatically when the
# video fails or is cancelled. A video that finishes keeps the charge.

ALLOWED_UPLOADS = {".pdf", ".txt", ".png", ".jpg", ".jpeg"}
IMAGE_UPLOADS = {".png", ".jpg", ".jpeg"}
MAX_UPLOAD_FILES = 5
VALID_STYLES = {"Educational", "Animated", "Simple Explanation", "Storytelling"}
VALID_LANGUAGES = {"English", "Kannada", "Hindi"}
VALID_DIFFICULTIES = {"Beginner", "Intermediate", "Advanced"}
VALID_AUDIENCES = {"Kids", "School Students", "College Students", "Teachers"}
VALID_ASPECTS = {"16:9", "9:16"}
VALID_DURATIONS = {"Short", "Medium", "Long"}
VALID_VOICES = {"Female", "Male"}
# Longest video a user can ask for (type any number of minutes from 1 up to this).
MAX_VIDEO_MINUTES = max(1, int(os.getenv("MAX_VIDEO_MINUTES", str(GEN_MAX_VIDEO_MINUTES))))


def _is_on(value):
    """Checkbox helper: unchecked boxes are missing; checked ones send 'on' (or true/1/yes)."""
    return str(value or "").strip().lower() in ("on", "true", "1", "yes")


def _normalize_language(value):
    """Accept the button label too: 'ಕನ್ನಡ Kannada' -> 'Kannada', 'हिन्दी Hindi' -> 'Hindi'.

    An empty value means English. Anything unrecognised is returned unchanged,
    so the validation below can still reject it.
    """
    text = str(value or "").strip()
    low = text.lower()
    if not text:
        return "English"
    if "kannada" in low or "ಕನ್ನಡ" in text:
        return "Kannada"
    if "hindi" in low or "हिन्दी" in text or "हिंदी" in text:
        return "Hindi"
    if "english" in low:
        return "English"
    return text


class JobCancelled(BaseException):
    """Raised inside a video job when the user pressed Cancel.

    It derives from BaseException on purpose: the generator only swallows Exception
    in its progress reporting, so this passes straight through and stops the job.
    """


VIDEO_JOBS = {}
VIDEO_JOBS_LOCK = threading.RLock()
JOB_STALE_SECONDS = 600   # a job with no progress for 10 minutes is treated as dead


def _cleanup_files(paths):
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            app.logger.warning("Could not delete temporary upload %s", p)


def _parse_video_form(form, files):
    """Validate the form, save uploads to temp files and return (params, temp_paths).

    Every look/sound choice is optional: an empty or missing value falls back to a default.
    Raises ValueError with a user-friendly message.
    """
    topic = (form.get("topic") or form.get("prompt") or "").strip()[:1000]
    style = form.get("video_style") or "Educational"
    language = _normalize_language(form.get("language"))
    audience = form.get("audience_level") or form.get("audience") or "School Students"
    difficulty = form.get("difficulty") or "Beginner"
    aspect_ratio = form.get("aspect_ratio") or "16:9"
    duration = form.get("duration") or "Short"           # Short = 1 minute (fastest)
    voice = form.get("voice") or "Female"
    minutes_raw = (form.get("duration_minutes") or "").strip()
    duration_minutes = None
    if minutes_raw:
        try:
            duration_minutes = int(float(minutes_raw))
        except ValueError:
            raise ValueError("Video length must be a whole number of minutes.")
        if not 1 <= duration_minutes <= MAX_VIDEO_MINUTES:
            raise ValueError(f"Video length must be between 1 and {MAX_VIDEO_MINUTES} minutes.")

    app.logger.info("Video request: style %r, %s min, language %r, %s voice",
                    style, duration_minutes or duration, language, voice)

    if style not in VALID_STYLES:
        raise ValueError("Please select a valid video style.")
    if language not in VALID_LANGUAGES:
        raise ValueError("Please select a valid narration language.")
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError("Please select a valid difficulty level.")
    if audience not in VALID_AUDIENCES:
        raise ValueError("Please select a valid target audience.")
    if aspect_ratio not in VALID_ASPECTS:
        raise ValueError("Please select a valid aspect ratio.")
    if duration not in VALID_DURATIONS:
        raise ValueError("Please select a valid video length.")
    if voice not in VALID_VOICES:
        raise ValueError("Please select Female or Male voice.")

    uploads = [f for f in (files.getlist("files") + files.getlist("file")) if f and f.filename]
    if len(uploads) > MAX_UPLOAD_FILES:
        raise ValueError(f"Please upload at most {MAX_UPLOAD_FILES} files.")

    temp_paths = []
    texts = [topic] if topic else []
    image_path = None
    image_without_text = False

    try:
        upload_dir = Path(app.root_path) / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        for uploaded in uploads:
            filename = secure_filename(uploaded.filename)
            extension = Path(filename).suffix.lower()
            if not filename or extension not in ALLOWED_UPLOADS:
                raise ValueError("Supported uploads: PDF, TXT, PNG, JPG and JPEG.")

            uploaded.stream.seek(0, os.SEEK_END)
            size_bytes = uploaded.stream.tell()
            uploaded.stream.seek(0)
            if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
                raise ValueError(f"{filename} is larger than {MAX_UPLOAD_MB} MB.")

            path = upload_dir / f"{uuid.uuid4().hex}{extension}"
            uploaded.save(str(path))
            temp_paths.append(path)

            if extension in IMAGE_UPLOADS:
                if image_path is None:
                    image_path = str(path)
                try:
                    text = extract_text(path).strip()  # OCR; may fail if Tesseract is missing
                except Exception:
                    text = ""
                if text:
                    texts.append(text)
                else:
                    image_without_text = True
            else:
                try:
                    text = extract_text(path).strip()
                except ValueError as exc:
                    raise ValueError(f"{filename}: {exc}") from exc
                except ImportError as exc:
                    raise ValueError(f"{filename}: {exc}") from exc
                if text:
                    texts.append(text)

        source_text = "\n\n".join(texts).strip()

        if not source_text and not image_path:
            raise ValueError("Enter a topic or upload a PDF or image first.")
        if not source_text and image_path and image_without_text and not os.getenv("OLLAMA_VISION_MODEL", "").strip():
            raise ValueError(
                "No readable text was found in the image. Add a topic as well, "
                "or set OLLAMA_VISION_MODEL=llava in .env so EduVision can describe pictures."
            )
    except Exception:
        _cleanup_files(temp_paths)
        raise

    params = {
        "source_text": source_text,
        "style": style,
        "language": language,
        "audience": audience,
        "difficulty": difficulty,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "duration_minutes": duration_minutes,
        "voice": voice,
        "subtitles": _is_on(form.get("subtitles")),
        "highlights": _is_on(form.get("highlight_concepts")),
        "music": _is_on(form.get("background_music")),
        "image_path": image_path,
    }
    return params, temp_paths


def _call_generator(**kwargs):
    """Call generate_video_package with only the arguments the installed version supports."""
    accepted = inspect.signature(generate_video_package).parameters
    return generate_video_package(**{k: v for k, v in kwargs.items() if k in accepted})


def _release_job_charge(job_id):
    """Clear the 'credits are held for this job' flag.

    Returns True only the first time it is called for a job that still held credits, so the
    refund (or the final keep) can never happen twice.
    """
    with VIDEO_JOBS_LOCK:
        job = VIDEO_JOBS.get(job_id)
        if job and job.get("charged"):
            job["charged"] = False
            return True
    return False


def _execute_video_job(user_id, params, temp_paths, progress=None, job_id=None):
    """Build the video and save it. Refunds and cleans up on any failure.

    job_id given  -> the credits were ALREADY deducted in /generate_video/start.
    job_id None   -> (plain form) the credits are deducted here.
    Runs in a worker thread or the request thread, so it must not touch `session`.
    """
    pre_charged = job_id is not None
    charged_here = False
    created_file = None
    try:
        if not pre_charged:
            if not charge_credits(user_id, VIDEO_COST):
                raise ValueError(
                    f"You need {VIDEO_COST} credits to generate a video. "
                    "Play a learning game to earn more."
                )
            charged_here = True

        result = _call_generator(
            source_text=params["source_text"],
            style=params["style"],
            difficulty=params["difficulty"],
            language=params["language"],
            audience=params["audience"],
            aspect_ratio=params["aspect_ratio"],
            subtitles=params["subtitles"],
            highlights=params["highlights"],
            music=params["music"],
            image_path=params["image_path"],
            duration=params["duration"],
            duration_minutes=params.get("duration_minutes"),
            voice=params.get("voice", "Female"),
            progress=progress,
        )
        created_file = Path(result["path"])

        video_id = save_video_record_v2(user_id, {
            "title": result["title"], "style": params["style"], "language": params["language"],
            "difficulty": params["difficulty"], "audience": params["audience"],
            "aspect_ratio": params["aspect_ratio"], "filename": result["filename"],
            "duration_seconds": result["duration_seconds"],
            "subtitles": params["subtitles"], "highlights": params["highlights"],
            "music": params["music"], "script_text": result["script_text"],
        })
        if not video_id:
            raise RuntimeError("The video was generated, but its database record could not be saved.")

        # Saved successfully: keep the charge and keep the file.
        if pre_charged:
            _release_job_charge(job_id)
        else:
            charged_here = False
        created_file = None
        log_activity(user_id, "video")
        bump_video_progress(user_id)

        minutes, seconds = divmod(int(result["duration_seconds"]), 60)
        return {
            "video_id": video_id,
            "filename": result["filename"],
            "title": result["title"],
            "language": params["language"],
            "style": params["style"],
            "difficulty": params["difficulty"],
            "aspect_ratio": params["aspect_ratio"],
            "duration": f"{minutes}m {seconds:02d}s",
        }
    finally:
        if pre_charged:
            if _release_job_charge(job_id):          # still held -> it failed or was cancelled
                refund_credits(user_id, VIDEO_COST)
        elif charged_here:
            refund_credits(user_id, VIDEO_COST)
        if created_file is not None:
            try:
                created_file.unlink(missing_ok=True)
            except OSError:
                pass
        _cleanup_files(temp_paths)


def _friendly_error(exc):
    if isinstance(exc, ValueError):
        return str(exc)
    text = f"{type(exc).__name__}: {str(exc)[:300]}"
    return f"Video generation failed. Your credits were refunded. ({text})"


def _active_job_id(user_id):
    """Return the id of this user's live job (call with VIDEO_JOBS_LOCK held).

    A job that made no progress for JOB_STALE_SECONDS is closed and its credits refunded.
    """
    now = time.time()
    for jid, job in list(VIDEO_JOBS.items()):
        if job["user_id"] != user_id or job["status"] not in ("queued", "running"):
            continue
        if now - job.get("updated", job["created"]) > JOB_STALE_SECONDS:
            job.update(status="failed", cancelled=True, finished=now,
                       error="The previous video stopped responding. Your credits were refunded.")
            if _release_job_charge(jid):
                refund_credits(user_id, VIDEO_COST)
            continue
        return jid
    return None


def _video_job_worker(job_id, user_id, params, temp_paths):
    def progress(percent, message):
        with VIDEO_JOBS_LOCK:
            job = VIDEO_JOBS.get(job_id)
            if job is None or job.get("cancelled"):
                cancelled = True
            else:
                cancelled = False
                job["status"] = "running"
                job["percent"] = max(job["percent"], min(99, int(percent)))
                job["message"] = str(message)
                job["updated"] = time.time()
        if cancelled:
            raise JobCancelled()

    try:
        info = _execute_video_job(user_id, params, temp_paths, progress, job_id=job_id)
        with VIDEO_JOBS_LOCK:
            job = VIDEO_JOBS.get(job_id)
            if job and not job.get("cancelled"):
                job.update(status="done", percent=100, message="Your video is ready!", result=info,
                           finished=time.time(), updated=time.time())
    except JobCancelled:
        app.logger.info("Video job %s was cancelled by the user.", job_id)
    except BaseException as exc:
        app.logger.exception("Educational video generation failed")
        with VIDEO_JOBS_LOCK:
            job = VIDEO_JOBS.get(job_id)
            if job and not job.get("cancelled"):
                job.update(status="failed", error=_friendly_error(exc), finished=time.time())
    finally:
        # Whatever happened, the job must never stay "running" forever.
        with VIDEO_JOBS_LOCK:
            job = VIDEO_JOBS.get(job_id)
            if job and job["status"] in ("queued", "running"):
                job.update(status="failed", error="The video job ended unexpectedly. "
                                                  "Your credits were refunded.", finished=time.time())


def _prune_jobs():
    cutoff = time.time() - 3600
    with VIDEO_JOBS_LOCK:
        for job_id in [k for k, v in VIDEO_JOBS.items()
                       if v["status"] in ("done", "failed")
                       and v.get("finished", v["created"]) < cutoff]:
            VIDEO_JOBS.pop(job_id, None)


def _render_generate_page(video_url=None, video_info=None, quiz_url=None, download_url=None,
                          tutor_url=None):
    user_id = session["user_id"]
    return render_template(
        "generate_video.html",
        user_name=session.get("user_name", "Student"),
        credits=get_user_credits(user_id),
        video_cost=VIDEO_COST,
        video_url=video_url,
        video_info=video_info,
        quiz_url=quiz_url,
        download_url=download_url,
        tutor_url=tutor_url,
        max_minutes=MAX_VIDEO_MINUTES,
    )


@app.route("/generate_video/start", methods=["POST"])
@login_required
def generate_video_start():
    user_id = session["user_id"]
    _prune_jobs()

    # Already running? Re-attach to it instead of showing an error.
    with VIDEO_JOBS_LOCK:
        existing = _active_job_id(user_id)
    if existing:
        return jsonify(ok=True, job_id=existing, resumed=True,
                       credits=get_user_credits(user_id))

    if get_user_credits(user_id) < VIDEO_COST:
        return jsonify(ok=False, error=f"You need {VIDEO_COST} credits to generate a video. "
                                       "Play a learning game to earn more.",
                       credits=get_user_credits(user_id)), 402
    try:
        params, temp_paths = _parse_video_form(request.form, request.files)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except Exception as exc:
        app.logger.exception("Could not read the upload")
        return jsonify(ok=False, error=f"Could not read your upload: {type(exc).__name__}"), 400

    # Deduct the credits NOW, so the balance drops as soon as generation starts.
    if not charge_credits(user_id, VIDEO_COST):
        _cleanup_files(temp_paths)
        return jsonify(ok=False, error=f"You need {VIDEO_COST} credits to generate a video. "
                                       "Play a learning game to earn more.",
                       credits=get_user_credits(user_id)), 402

    job_id = uuid.uuid4().hex
    now = time.time()
    with VIDEO_JOBS_LOCK:
        existing = _active_job_id(user_id)          # check again: double-click safe
        if existing:
            duplicate = True
        else:
            duplicate = False
            VIDEO_JOBS[job_id] = {
                "user_id": user_id, "status": "queued", "percent": 1, "message": "Starting",
                "error": "", "result": None, "created": now, "updated": now,
                "cancelled": False, "charged": True,
            }
    if duplicate:
        refund_credits(user_id, VIDEO_COST)         # the second click paid twice: give it back
        _cleanup_files(temp_paths)
        balance = get_user_credits(user_id)
        session["credits"] = balance
        return jsonify(ok=True, job_id=existing, resumed=True, credits=balance)

    try:
        threading.Thread(target=_video_job_worker, args=(job_id, user_id, params, temp_paths),
                         daemon=True).start()
    except Exception:
        app.logger.exception("Could not start the video worker thread")
        with VIDEO_JOBS_LOCK:
            VIDEO_JOBS.pop(job_id, None)
        refund_credits(user_id, VIDEO_COST)
        _cleanup_files(temp_paths)
        return jsonify(ok=False, error="Could not start the video. Your credits were refunded.",
                       credits=get_user_credits(user_id)), 500

    balance = get_user_credits(user_id)
    session["credits"] = balance
    return jsonify(ok=True, job_id=job_id, credits=balance)


@app.route("/generate_video/active")
@login_required
def generate_video_active():
    with VIDEO_JOBS_LOCK:
        jid = _active_job_id(session["user_id"])
    return jsonify(ok=True, job_id=jid, credits=get_user_credits(session["user_id"]))


@app.route("/generate_video/cancel", methods=["POST"])
@login_required
def generate_video_cancel():
    """Stops the running job and refunds its credits immediately."""
    user_id = session["user_id"]
    with VIDEO_JOBS_LOCK:
        ids = [jid for jid, job in VIDEO_JOBS.items()
               if job["user_id"] == user_id and job["status"] in ("queued", "running")]
        for jid in ids:
            VIDEO_JOBS[jid].update(status="failed", cancelled=True, error="Cancelled.",
                                   finished=time.time())
    for jid in ids:
        if _release_job_charge(jid):                # refund exactly once
            refund_credits(user_id, VIDEO_COST)
    balance = get_user_credits(user_id)
    session["credits"] = balance
    return jsonify(ok=True, credits=balance)


@app.route("/generate_video/status/<job_id>")
@login_required
def generate_video_status(job_id):
    with VIDEO_JOBS_LOCK:
        job = VIDEO_JOBS.get(job_id)
        job = dict(job) if job else None

    if not job or job["user_id"] != session["user_id"]:
        return jsonify(ok=False, error="This video job was not found. Check My Videos."), 404

    balance = get_user_credits(session["user_id"])
    session["credits"] = balance
    payload = {"ok": True, "status": job["status"], "percent": job["percent"],
               "message": job["message"], "error": job["error"], "credits": balance}
    if job["status"] == "done" and job["result"]:
        info = job["result"]
        payload["result"] = {
            "video_url": url_for("generated_video_file", filename=info["filename"]),
            "download_url": url_for("download_generated_video", video_id=info["video_id"]),
            "quiz_url": url_for("video_quiz.video_quiz_page", video_id=info["video_id"]),
            "tutor_url": tutor_url_for_video(info["video_id"]),
            "credits": balance,
            "info": {k: info[k] for k in ("title", "language", "style", "difficulty",
                                          "aspect_ratio", "duration")},
        }
    return jsonify(payload)


@app.route("/generate_video", methods=["GET", "POST"])
@login_required
def generate_video():
    user_id = session["user_id"]

    if request.method == "GET":
        return _render_generate_page()

    return_to = request.form.get("return_to", "generate_page")
    temp_paths = []
    try:
        params, temp_paths = _parse_video_form(request.form, request.files)
        info = _execute_video_job(user_id, params, temp_paths)
        session["credits"] = get_user_credits(user_id)

        if return_to == "dashboard":
            flash("Your educational video was generated successfully!", "success")
            return redirect(url_for("dashboard"))

        return _render_generate_page(
            video_url=url_for("generated_video_file", filename=info["filename"]),
            download_url=url_for("download_generated_video", video_id=info["video_id"]),
            quiz_url=url_for("video_quiz.video_quiz_page", video_id=info["video_id"]),
            tutor_url=tutor_url_for_video(info["video_id"]),
            video_info={
                "title": info["title"], "language": info["language"], "style": info["style"],
                "difficulty": info["difficulty"], "aspect_ratio": info["aspect_ratio"],
                "duration": info["duration"],
                "created_at": datetime.now().strftime("%d %b %Y"),
            },
        )
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception as exc:
        app.logger.exception("Educational video generation failed")
        flash(_friendly_error(exc), "error")
    finally:
        session["credits"] = get_user_credits(user_id)

    if return_to == "dashboard":
        return redirect(url_for("dashboard"))
    return _render_generate_page()


@app.route("/generate-video", methods=["GET"])
@login_required
def generate_video_page():
    return _render_generate_page()


# ============================================================
# GAME SCORING AND CREDIT REWARDS
# ============================================================

def award_game_credits(user_id, game_key, score_pct, seconds):
    game = GAMES[game_key]
    score_pct = max(0, min(100, int(score_pct)))
    seconds = max(0, int(seconds))
    result = {"earned": 0, "message": "", "balance": None}

    if seconds < game.get("min_seconds", 10):
        result["message"] = "That finished too quickly to count. Please play the game properly."
        result["balance"] = get_user_credits(user_id)
        return result

    connection = get_db_connection()
    if connection is None:
        result["message"] = "Database connection error. Your score was not saved."
        return result

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT credits FROM users WHERE id = %s FOR UPDATE", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            connection.rollback()
            result["message"] = "User account was not found."
            return result

        cursor.execute(
            "SELECT COALESCE(SUM(credits_earned), 0) AS total FROM game_plays "
            "WHERE user_id = %s AND DATE(played_at) = CURDATE()",
            (user_id,),
        )
        earned_today = int((cursor.fetchone() or {}).get("total") or 0)

        cursor.execute(
            "SELECT COUNT(*) AS c FROM game_plays "
            "WHERE user_id = %s AND game_key = %s AND DATE(played_at) = CURDATE()",
            (user_id, game_key),
        )
        played_today = int((cursor.fetchone() or {}).get("c") or 0)

        earned = round(game["reward"] * score_pct / 100)
        if game.get("once_a_day", False) and played_today > 0:
            earned = 0
            result["message"] = "You have already played today's bonus challenge."
        elif earned > 0 and earned_today >= DAILY_CREDIT_CAP:
            earned = 0
            result["message"] = f"You reached today's {DAILY_CREDIT_CAP}-credit game limit."
        elif earned > DAILY_CREDIT_CAP - earned_today:
            earned = max(0, DAILY_CREDIT_CAP - earned_today)
            result["message"] = f"Daily game-credit limit: {DAILY_CREDIT_CAP} credits."

        cursor.execute(
            "INSERT INTO game_plays "
            "(user_id, game_key, score_pct, seconds, credits_earned) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, game_key, score_pct, seconds, earned),
        )
        if earned:
            cursor.execute(
                "UPDATE users SET credits = credits + %s WHERE id = %s",
                (earned, user_id),
            )

        cursor.execute(
            "UPDATE learning_progress SET games_played = games_played + 1, "
            "total_score = total_score + %s WHERE user_id = %s",
            (score_pct, user_id),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                "INSERT INTO learning_progress "
                "(user_id, videos_generated, quizzes_completed, games_played, total_score) "
                "VALUES (%s, 0, 0, 1, %s)",
                (user_id, score_pct),
            )

        cursor.execute(
            "INSERT IGNORE INTO user_activity (user_id, activity_date, activity_type) "
            "VALUES (%s, CURDATE(), 'game')",
            (user_id,),
        )
        connection.commit()

        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        balance_row = cursor.fetchone()
        result["balance"] = int(balance_row["credits"] or 0) if balance_row else 0
        result["earned"] = earned
        if earned and not result["message"]:
            result["message"] = f"You earned {earned} credits!"
        elif not result["message"]:
            result["message"] = "Score saved. No credits earned for this score."
        return result
    except Error as exc:
        connection.rollback()
        app.logger.exception("Game credit award failed: %s", exc)
        result["message"] = "Something went wrong while saving your score."
        return result
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


# ============================================================
# GAME FINISH API
# ============================================================

_GAME_KEY_ALIASES = {
    "snake": "snake_game", "tetris": "tetris_blocks", "flappy": "flappy_brain",
    "flappy_bird": "flappy_brain", "2048": "puzzle_2048", "candy": "candy_match",
    "memory": "memory_match", "mind_match": "memory_match", "tictactoe": "neon_tic_tac_toe",
    "tic_tac_toe": "neon_tic_tac_toe", "bubble": "bubble_shooter", "runner": "endless_runner",
    "sliding": "sliding_puzzle", "quiz": "quiz_battle", "arrow": "arrow_maze",
    "hologram": "hologram_memory",
}


def _normalize_game_key(raw):
    """Map whatever id game.js sends to a catalog key, or return None."""
    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in GAMES:
        return key
    key = _GAME_KEY_ALIASES.get(key, key)
    return key if key in GAMES else None


def _read_game_request():
    """Accept JSON, form posts and sendBeacon bodies."""
    data = request.get_json(silent=True, force=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict() if request.form else {}


def _num(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _game_key_from(data):
    return _normalize_game_key(
        data.get("game") or data.get("game_key") or data.get("game_id")
        or data.get("key") or data.get("gameKey") or data.get("id")
    )


@app.route("/api/game/finish", methods=["POST"])
@login_required
def api_game_finish():
    data = _read_game_request()
    game_key = _game_key_from(data)
    if game_key is None:
        msg = "Unknown game."
        return jsonify(ok=False, success=False, error=msg, message=msg), 400

    score_pct = max(0, min(100, _num(data.get("score", data.get("score_pct", 0)))))
    seconds = max(0, min(86400, _num(data.get("seconds", data.get("time", 0)))))

    result = award_game_credits(session["user_id"], game_key, score_pct, seconds)

    # A missing balance means the result could not be saved
    if result["balance"] is None:
        return jsonify(ok=False, success=False, error=result["message"],
                       message=result["message"]), 503

    session["credits"] = result["balance"]
    return jsonify(
        ok=True, success=True,
        earned=result["earned"], balance=result["balance"],
        credits=result["balance"], message=result["message"],
    ), 200


# ============================================================
# OTHER PAGES
# ============================================================

@app.route("/qa")
@login_required
def qa():
    return render_template("qa.html", user_name=session.get("user_name", "Student"))


@app.template_filter("pp_date")
def pp_date_filter(value):
    """Friendly date for the My Progress page."""
    if not value:
        return ""
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)[:10]
    diff = (datetime.now() - when).total_seconds()
    if 0 <= diff < 60:
        return "Just now"
    if 0 <= diff < 3600:
        return f"{int(diff // 60)} min ago"
    if 0 <= diff < 86400:
        return f"{int(diff // 3600)} hr ago"
    return when.strftime("%d %b %Y")


def _pp_empty_payload(credits=0):
    return {
        "overview": {"videos": 0, "games": 0, "quizzes": 0, "aptitude": 0},
        "videos": {"total": 0, "recent": []},
        "games": {"played": 0, "levels": 0, "highest": 0, "list": []},
        "quizzes": {"attempted": 0, "average": 0, "highest": 0, "recent": []},
        "aptitude": {"attempted": 0, "average": 0, "highest": 0, "recent": []},
        "credits": {"balance": credits, "from_games": 0, "from_quizzes": 0, "total_earned": 0},
        "achievements": [], "activity": [],
    }


@app.route("/learning-progress")
@login_required
def learning_progress():
    """My Progress page. All numbers are rendered on the server (no JavaScript needed)."""
    data = build_progress_payload(session["user_id"])
    load_failed = data is None
    if load_failed:
        data = _pp_empty_payload(get_user_credits(session["user_id"]))
    return render_template(
        "learning_progress.html",
        user_name=session.get("user_name", "Student"),
        credits=data["credits"]["balance"],
        data=data,
        load_failed=load_failed,
    )


def _pp_iso(value):
    if value is None or value == "":
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _pp_query(cursor, sql, params=(), one=False):
    """Run a read-only query; a failure in one section never breaks the page."""
    try:
        cursor.execute(sql, params)
        return (cursor.fetchone() or {}) if one else cursor.fetchall()
    except Error as exc:
        app.logger.warning("My Progress query skipped: %s", exc)
        return {} if one else []


def _pp_columns(cursor, table):
    rows = _pp_query(
        cursor,
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (DB_CONFIG["database"], table),
    )
    names = set()
    for row in rows:
        value = list(row.values())[0]
        names.add(value.decode() if isinstance(value, (bytes, bytearray)) else value)
    return names


def _pp_aptitude_attempts(cursor, user_id):
    """Read aptitude_attempts using whichever columns really exist in your table."""
    cols = _pp_columns(cursor, "aptitude_attempts")
    if "user_id" not in cols:
        return []

    def pick(options):
        return next((c for c in options if c in cols), None)

    pct = pick(["percentage", "score_pct", "accuracy", "percent"])
    score = pick(["score", "correct_answers", "correct"])
    total = pick(["total_questions", "total", "total_marks"])
    when = pick(["completed_at", "created_at", "attempted_at", "submitted_at", "finished_at", "started_at"])
    label = pick(["category", "topic", "test_name", "title", "section", "level", "difficulty"])

    select = [
        f"`{pct}` AS pct" if pct else "NULL AS pct",
        f"`{score}` AS score" if score else "NULL AS score",
        f"`{total}` AS total" if total else "NULL AS total",
        f"`{when}` AS at" if when else "NULL AS at",
        f"`{label}` AS label" if label else "NULL AS label",
    ]
    order = f"ORDER BY `{when}` DESC" if when else ("ORDER BY id DESC" if "id" in cols else "")
    rows = _pp_query(
        cursor,
        f"SELECT {', '.join(select)} FROM aptitude_attempts WHERE user_id = %s {order} LIMIT 500",
        (user_id,),
    )
    attempts = []
    for r in rows:
        try:
            if r["pct"] is not None:
                value = float(r["pct"])
            elif r["score"] is not None and r["total"]:
                value = float(r["score"]) / float(r["total"]) * 100
            else:
                value = None
        except (TypeError, ValueError, ZeroDivisionError):
            value = None
        attempts.append({
            "pct": None if value is None else round(max(0, min(100, value))),
            "at": _pp_iso(r["at"]),
            "label": str(r["label"]) if r["label"] else "Aptitude test",
        })
    return attempts


def build_progress_payload(user_id):
    connection = get_db_connection()
    if connection is None:
        return None
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        user = _pp_query(cursor, "SELECT name, credits FROM users WHERE id = %s", (user_id,), one=True)
        lp = _pp_query(cursor, "SELECT videos_generated, quizzes_completed, games_played "
                               "FROM learning_progress WHERE user_id = %s", (user_id,), one=True)

        # ---- Videos
        vcount = _pp_query(cursor, "SELECT COUNT(*) AS n FROM generated_videos WHERE user_id = %s",
                           (user_id,), one=True)
        total_videos = max(int(lp.get("videos_generated") or 0), int(vcount.get("n") or 0))
        videos = [
            {"title": v["title"] or "Educational Lesson", "style": v["video_style"] or "Lesson",
             "language": v["language"] or "English", "at": _pp_iso(v["created_at"])}
            for v in _pp_query(cursor, "SELECT title, video_style, language, created_at FROM generated_videos "
                                       "WHERE user_id = %s ORDER BY created_at DESC LIMIT 6", (user_id,))
        ]

        # ---- Games
        plays = {r["game_key"]: r for r in _pp_query(
            cursor, "SELECT game_key, COUNT(*) AS plays, MAX(score_pct) AS best FROM game_plays "
                    "WHERE user_id = %s GROUP BY game_key", (user_id,))}
        levels = {r["game_key"]: r for r in _pp_query(
            cursor, "SELECT game_key, completed_levels, best_score FROM game_progress WHERE user_id = %s",
            (user_id,))}
        game_rows = []
        for key in set(plays) | set(levels):
            p, l = plays.get(key, {}), levels.get(key, {})
            game_rows.append({
                "name": GAMES.get(key, {}).get("name") or key.replace("_", " ").title(),
                "plays": int(p.get("plays") or 0),
                "levels": int(l.get("completed_levels") or 0),
                "best": max(int(p.get("best") or 0), int(l.get("best_score") or 0)),
            })
        game_rows.sort(key=lambda g: (g["plays"], g["levels"]), reverse=True)
        games_played = max(
            sum(g["plays"] for g in game_rows),
            int(lp.get("games_played") or 0),
            len([g for g in game_rows if g["levels"] > 0]),  # games where levels were completed
        )
        games = {
            "played": games_played,
            "levels": sum(g["levels"] for g in game_rows),
            "highest": max([g["best"] for g in game_rows] or [0]),
            "list": game_rows[:6],
        }

        # ---- Video quizzes
        q = _pp_query(cursor, "SELECT COUNT(*) AS n, AVG(percentage) AS avg, MAX(percentage) AS mx "
                              "FROM video_quiz_attempts WHERE user_id = %s", (user_id,), one=True)
        quiz_recent = [
            {"title": r["title"] or "Video quiz", "score": int(r["score"] or 0),
             "total": int(r["total_questions"] or 0), "pct": int(r["percentage"] or 0),
             "at": _pp_iso(r["completed_at"])}
            for r in _pp_query(
                cursor, "SELECT a.score, a.total_questions, a.percentage, a.completed_at, v.title "
                        "FROM video_quiz_attempts a LEFT JOIN generated_videos v ON v.id = a.video_id "
                        "WHERE a.user_id = %s ORDER BY a.completed_at DESC LIMIT 5", (user_id,))
        ]
        quiz_count = int(q.get("n") or 0) or int(lp.get("quizzes_completed") or 0)
        quizzes = {"attempted": quiz_count, "average": round(float(q.get("avg") or 0)),
                   "highest": int(q.get("mx") or 0), "recent": quiz_recent}

        # ---- Aptitude Arena
        attempts = _pp_aptitude_attempts(cursor, user_id)
        scored = [a["pct"] for a in attempts if a["pct"] is not None]
        aptitude = {"attempted": len(attempts),
                    "average": round(sum(scored) / len(scored)) if scored else 0,
                    "highest": max(scored) if scored else 0,
                    "recent": attempts[:5]}

        # ---- Credits (reads the existing users.credits and existing reward tables only)
        lvl = _pp_query(cursor, "SELECT COALESCE(SUM(credits_earned),0) AS s FROM game_level_rewards "
                                "WHERE user_id = %s", (user_id,), one=True)
        gp = _pp_query(cursor, "SELECT COALESCE(SUM(credits_earned),0) AS s FROM game_plays "
                               "WHERE user_id = %s", (user_id,), one=True)
        vq = _pp_query(cursor, "SELECT COALESCE(SUM(credits_earned),0) AS s FROM video_quiz_attempts "
                               "WHERE user_id = %s", (user_id,), one=True)
        from_games = int(lvl.get("s") or 0) + int(gp.get("s") or 0)
        from_quizzes = int(vq.get("s") or 0)
        credits = {"balance": int(user.get("credits") or 0), "from_games": from_games,
                   "from_quizzes": from_quizzes, "total_earned": from_games + from_quizzes}

        # ---- Achievements: calculated from the real numbers above (no new table)
        goals = [
            ("First Video", "Generate your first video", "bi-camera-video", total_videos, 1),
            ("Video Creator", "Generate 5 videos", "bi-collection-play", total_videos, 5),
            ("Game Starter", "Play your first game", "bi-controller", games["played"], 1),
            ("Level Climber", "Complete 10 game levels", "bi-graph-up-arrow", games["levels"], 10),
            ("Quiz Taker", "Attempt a video quiz", "bi-patch-question", quizzes["attempted"], 1),
            ("Quiz Ace", "Score 90% or more in a quiz", "bi-trophy", quizzes["highest"], 90),
            ("Aptitude Challenger", "Attempt an Aptitude Arena test", "bi-lightning-charge", aptitude["attempted"], 1),
            ("Credit Collector", "Earn 100 credits", "bi-coin", credits["total_earned"], 100),
        ]
        achievements = [{"name": n, "desc": d, "icon": i, "current": min(c, t), "target": t,
                         "unlocked": c >= t} for n, d, i, c, t in goals]

        # ---- Recent activity (merged, newest first)
        activity = [{"type": "video", "title": v["title"], "detail": f'{v["style"]} video generated', "at": v["at"]}
                    for v in videos]
        for r in _pp_query(cursor, "SELECT game_key, score_pct, credits_earned, played_at FROM game_plays "
                                   "WHERE user_id = %s ORDER BY played_at DESC LIMIT 6", (user_id,)):
            activity.append({
                "type": "game",
                "title": GAMES.get(r["game_key"], {}).get("name") or r["game_key"].replace("_", " ").title(),
                "detail": f'Score {int(r["score_pct"] or 0)}%' +
                          (f' · +{int(r["credits_earned"])} credits' if r["credits_earned"] else ""),
                "at": _pp_iso(r["played_at"])})
        activity += [{"type": "quiz", "title": r["title"], "detail": f'{r["score"]}/{r["total"]} correct · {r["pct"]}%',
                      "at": r["at"]} for r in quiz_recent]
        activity += [{"type": "aptitude", "title": a["label"],
                      "detail": "Test attempted" if a["pct"] is None else f'Score {a["pct"]}%', "at": a["at"]}
                     for a in attempts[:5]]
        activity.sort(key=lambda a: a["at"] or "", reverse=True)

        return {"name": user.get("name") or session.get("user_name", "Student"),
                "overview": {"videos": total_videos, "games": games["played"],
                             "quizzes": quizzes["attempted"], "aptitude": aptitude["attempted"]},
                "videos": {"total": total_videos, "recent": videos},
                "games": games, "quizzes": quizzes, "aptitude": aptitude,
                "credits": credits, "achievements": achievements, "activity": activity[:10]}
    except Exception:
        app.logger.exception("My Progress data failed")
        return None
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


@app.route("/api/learning-progress")
@login_required
def api_learning_progress():
    """JSON for the My Progress page. Always uses the logged-in user's id."""
    payload = build_progress_payload(session["user_id"])
    if payload is None:
        return jsonify(ok=False, error="Could not load your progress right now."), 503
    return jsonify(ok=True, data=payload)


@app.route("/videos")
@login_required
def videos():
    # There is no separate videos.html page. The video library lives on the dashboard
    # ("My Generated Videos"), so this URL sends people there (same as /my-videos).
    return redirect(url_for("dashboard") + "#my-videos")


@app.route("/materials")
@login_required
def materials():
    return render_template("materials.html", user_name=session.get("user_name", "Student"))


@app.route("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    connection = get_db_connection()

    if connection is None:
        return "Database connection failed", 503

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, email, credits FROM users WHERE id = %s",
            (user_id,),
        )
        user = cursor.fetchone()

        if not user:
            return "User not found", 404

        return render_template("profile.html", user=user)
    finally:
        if cursor:
            cursor.close()
        connection.close()


@app.route("/quiz")
@login_required
def quiz():
    return render_template("quiz.html", user_name=session.get("user_name", "Student"))


@app.route("/mcq")
@login_required
def mcq():
    return render_template("mcq.html", user_name=session.get("user_name", "Student"))


def render_game(template_name):
    return render_template(
        template_name,
        user_name=session.get("user_name", "Student"),
        credits=get_user_credits(session["user_id"]),
    )


@app.route("/true-false")
@login_required
def true_false():
    return render_game("true_false.html")


@app.route("/match-game")
@login_required
def match_game():
    return render_game("match_game.html")


@app.route("/word-scramble")
@login_required
def word_scramble():
    return render_game("word_scramble.html")


@app.route("/memory-game")
@login_required
def memory_game():
    return render_game("memory_game.html")


# ============================================================
# GAME LEVEL PROGRESS AND REWARDS
# ============================================================
# game.js sends one request per level reached while playing:
#   POST /api/game-level/complete  {game_key, level, score}
# and one request when the game ends (see /api/game/finish above).
# Each level pays GAME_LEVEL_REWARD credits ONCE per user and game.
# MAX_GAME_LEVEL limits the total payout per game.

# Always in sync with the game catalog above.
ALLOWED_GAME_KEYS = set(GAMES)

GAME_LEVEL_REWARD = 10
MAX_GAME_LEVEL = 1000


def get_or_create_game_progress(user_id, game_key):
    """Return the saved progress for one user and one game."""
    connection = get_db_connection()
    if connection is None:
        raise RuntimeError("Unable to connect to MySQL.")

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            INSERT IGNORE INTO game_progress
                (user_id, game_key, unlocked_level, completed_levels)
            VALUES (%s, %s, 1, 0)
            """,
            (user_id, game_key),
        )
        connection.commit()

        cursor.execute(
            """
            SELECT unlocked_level, completed_levels, best_score
            FROM game_progress
            WHERE user_id = %s AND game_key = %s
            """,
            (user_id, game_key),
        )
        progress = cursor.fetchone()
        if progress is None:
            raise RuntimeError("Unable to load game progress.")
        return progress
    except Exception:
        connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        connection.close()


@app.route("/api/game-level/complete", methods=["POST"])
@login_required
def complete_game_level():
    user_id = session["user_id"]
    data = _read_game_request()

    def fail(message, status):
        return jsonify(ok=False, success=False, error=message, message=message), status

    game_key = _game_key_from(data)
    level = _num(data.get("level"), None)
    score = _num(data.get("score", 0), 0)

    if game_key is None:
        return fail("Unknown game.", 400)
    if level is None or level < 1 or level > MAX_GAME_LEVEL:
        return fail("Invalid game level.", 400)
    score = max(0, score)

    connection = get_db_connection()
    if connection is None:
        return fail("Database connection failed.", 503)

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        # Lock the user's row so two requests cannot pay the same level twice.
        cursor.execute("SELECT credits FROM users WHERE id = %s FOR UPDATE", (user_id,))
        if not cursor.fetchone():
            connection.rollback()
            return fail("User account not found.", 404)

        cursor.execute(
            "INSERT IGNORE INTO game_progress "
            "(user_id, game_key, unlocked_level, completed_levels, best_score) "
            "VALUES (%s, %s, 1, 0, 0)",
            (user_id, game_key),
        )

        # Anti-cheat: a level can only be completed if the player has unlocked it.
        cursor.execute(
            "SELECT unlocked_level FROM game_progress WHERE user_id = %s AND game_key = %s",
            (user_id, game_key),
        )
        prog = cursor.fetchone() or {}
        if level > int(prog.get("unlocked_level") or 1):
            connection.rollback()
            return fail("That level is not unlocked yet.", 400)

        # One reward per user + game + level (UNIQUE key blocks duplicates).
        cursor.execute(
            "INSERT IGNORE INTO game_level_rewards "
            "(user_id, game_key, level_number, score, credits_earned) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, game_key, level, score, GAME_LEVEL_REWARD),
        )
        newly_completed = cursor.rowcount == 1
        earned = 0

        if newly_completed:
            earned = GAME_LEVEL_REWARD
            cursor.execute(
                "UPDATE users SET credits = COALESCE(credits, 0) + %s WHERE id = %s",
                (earned, user_id),
            )
            cursor.execute(
                "UPDATE game_progress "
                "SET completed_levels = completed_levels + 1, "
                "    unlocked_level = GREATEST(unlocked_level, %s), "
                "    best_score = GREATEST(COALESCE(best_score, 0), %s) "
                "WHERE user_id = %s AND game_key = %s",
                (level + 1, score, user_id, game_key),
            )
            cursor.execute(
                "INSERT IGNORE INTO user_activity (user_id, activity_date, activity_type) "
                "VALUES (%s, CURDATE(), 'game')",
                (user_id,),
            )

        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        balance = int((cursor.fetchone() or {}).get("credits") or 0)
        connection.commit()
        session["credits"] = balance

        return jsonify(
            ok=True, success=True,
            earned=earned, balance=balance, credits=balance,
            level=level, game_key=game_key,
            duplicate=not newly_completed,
            message=(f"You earned {earned} credits!" if earned > 0
                     else "This level has already been completed."),
        ), 200

    except Error:
        connection.rollback()
        app.logger.exception("Game level reward database error")
        return fail("Database error while saving game reward.", 500)
    except Exception:
        connection.rollback()
        app.logger.exception("Unexpected game level completion error")
        return fail("Unexpected error while saving game reward.", 500)
    finally:
        if cursor:
            cursor.close()
        connection.close()


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_server_error(error):
    import traceback
    from markupsafe import escape

    original = getattr(error, "original_exception", None) or error
    details = "".join(
        traceback.format_exception(type(original), original, original.__traceback__)
    )
    app.logger.error("HTTP 500 error:\n%s", details)

    # Show the real error in the browser when developing (debug mode or localhost).
    if os.getenv("FLASK_DEBUG", "0") == "1":
        return (
            "<h2>EduVision error (development view)</h2>"
            f"<p>URL: {escape(request.path)}</p>"
            f"<pre style='white-space:pre-wrap;font-size:14px'>{escape(details)}</pre>",
            500,
        )
    return "EduVision encountered an error. Please try again later.", 500


# ============================================================
# DATABASE INITIALIZATION: create required tables if missing
# ============================================================

def _relax_legacy_columns(cursor, database_name, table, known_columns):
    """Make leftover NOT NULL columns (from older table versions) optional so INSERTs don't fail."""
    cursor.execute(
        "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND IS_NULLABLE = 'NO' "
        "AND COLUMN_DEFAULT IS NULL AND EXTRA NOT LIKE %s",
        (database_name, table, "%auto_increment%"),
    )
    for name, col_type in cursor.fetchall():
        name = name.decode() if isinstance(name, (bytes, bytearray)) else name
        col_type = col_type.decode() if isinstance(col_type, (bytes, bytearray)) else col_type
        if name in known_columns:
            continue
        cursor.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{name}` {col_type} NULL")
        app.logger.info("Made %s.%s optional", table, name)


def initialize_database():
    """Create the configured database and all tables used by this app.

    Existing tables/data are preserved. CREATE TABLE IF NOT EXISTS does not
    alter old schemas, so missing columns are added by the migration below.
    (The aptitude_attempts table is also upgraded automatically by
    routes/aptitude_backend.py if an older version exists.)
    """
    connection = None
    cursor = None
    database_name = DB_CONFIG["database"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise RuntimeError("MYSQL_DATABASE may contain only letters, numbers and underscores.")
    try:
        connection = mysql.connector.connect(
            host=DB_CONFIG["host"], user=DB_CONFIG["user"], password=DB_CONFIG["password"],
            port=DB_CONFIG["port"], connection_timeout=DB_CONFIG["connection_timeout"]
        )
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        connection.commit()
    except Error as exc:
        app.logger.error("Could not create/check database: %s", exc)
        return False
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    connection = get_db_connection()
    if connection is None:
        app.logger.error("Database unavailable. Check MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD and MYSQL_DATABASE in .env.")
        return False
    cursor = None
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE, password VARCHAR(255) NOT NULL,
            credits INT NOT NULL DEFAULT 50, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS learning_progress (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL UNIQUE,
            videos_generated INT NOT NULL DEFAULT 0, quizzes_completed INT NOT NULL DEFAULT 0,
            games_played INT NOT NULL DEFAULT 0, total_score INT NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_learning_progress_user (user_id)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS generated_videos (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL,
            title VARCHAR(150) NOT NULL DEFAULT 'Educational Lesson', description TEXT,
            video_style VARCHAR(80) DEFAULT 'Educational', language VARCHAR(40) DEFAULT 'English',
            filename VARCHAR(255), video_url VARCHAR(500), thumbnail VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_generated_videos_user_created (user_id, created_at)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS user_activity (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL,
            activity_date DATE NOT NULL, activity_type VARCHAR(60) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_user_activity_day_type (user_id, activity_date, activity_type),
            INDEX idx_user_activity_user_date (user_id, activity_date)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS game_plays (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, game_key VARCHAR(100) NOT NULL,
            score_pct INT NOT NULL DEFAULT 0, seconds INT NOT NULL DEFAULT 0,
            credits_earned INT NOT NULL DEFAULT 0, played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_game_plays_user_day (user_id, played_at),
            INDEX idx_game_plays_user_game_day (user_id, game_key, played_at)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS game_progress (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, game_key VARCHAR(100) NOT NULL,
            unlocked_level INT NOT NULL DEFAULT 1, completed_levels INT NOT NULL DEFAULT 0,
            best_score INT NOT NULL DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY unique_user_game_progress (user_id, game_key)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS game_level_rewards (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, game_key VARCHAR(100) NOT NULL,
            level_number INT NOT NULL, score INT NOT NULL DEFAULT 0, credits_earned INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_user_game_level (user_id, game_key, level_number),
            INDEX idx_level_rewards_user (user_id)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS registration_otp_pending (
            email VARCHAR(150) PRIMARY KEY, name VARCHAR(100) NOT NULL, password_hash VARCHAR(255) NOT NULL,
            otp_hash VARCHAR(255) NOT NULL, expires_at DATETIME NOT NULL,
            attempts INT NOT NULL DEFAULT 0, created_at DATETIME NOT NULL
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS login_otp_pending (
            email VARCHAR(150) PRIMARY KEY, otp_hash VARCHAR(255) NOT NULL,
            expires_at DATETIME NOT NULL, attempts INT NOT NULL DEFAULT 0, created_at DATETIME NOT NULL
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS password_reset_pending (
            email VARCHAR(150) PRIMARY KEY, otp_hash VARCHAR(255) NOT NULL,
            expires_at DATETIME NOT NULL, attempts INT NOT NULL DEFAULT 0, created_at DATETIME NOT NULL
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS video_quizzes (
            id INT AUTO_INCREMENT PRIMARY KEY, video_id INT NOT NULL, user_id INT NOT NULL,
            questions LONGTEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_video_quiz (video_id), INDEX idx_video_quizzes_user (user_id),
            CONSTRAINT fk_video_quizzes_video FOREIGN KEY (video_id)
                REFERENCES generated_videos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS video_quiz_attempts (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, video_id INT NOT NULL,
            quiz_id INT NOT NULL, answers TEXT NOT NULL, score INT NOT NULL DEFAULT 0,
            total_questions INT NOT NULL DEFAULT 0, percentage INT NOT NULL DEFAULT 0,
            credits_earned INT NOT NULL DEFAULT 0, completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_vqa_user_quiz (user_id, quiz_id),
            CONSTRAINT fk_vqa_video FOREIGN KEY (video_id)
                REFERENCES generated_videos(id) ON DELETE CASCADE,
            CONSTRAINT fk_vqa_quiz FOREIGN KEY (quiz_id)
                REFERENCES video_quizzes(id) ON DELETE CASCADE
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS game_results (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, game_name VARCHAR(100) NOT NULL,
            score INT NOT NULL DEFAULT 0, credits_earned INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_game_results_user (user_id)
        ) ENGINE=InnoDB""",
    ]
    try:
        cursor = connection.cursor()

        # Older versions of generated_videos may be missing columns the app uses.
        # Add those first, then create the tables that depend on generated_videos.
        for statement in statements[:10]:
            cursor.execute(statement)

        wanted_columns = [
            ("game_progress", "unlocked_level", "INT NOT NULL DEFAULT 1"),
            ("game_progress", "completed_levels", "INT NOT NULL DEFAULT 0"),
            ("game_progress", "best_score", "INT NOT NULL DEFAULT 0"),
            ("game_level_rewards", "level_number", "INT NOT NULL DEFAULT 1"),
            ("game_level_rewards", "score", "INT NOT NULL DEFAULT 0"),
            ("game_level_rewards", "credits_earned", "INT NOT NULL DEFAULT 0"),
            ("game_plays", "score_pct", "INT NOT NULL DEFAULT 0"),
            ("game_plays", "seconds", "INT NOT NULL DEFAULT 0"),
            ("game_plays", "credits_earned", "INT NOT NULL DEFAULT 0"),
            ("generated_videos", "title", "VARCHAR(150) NOT NULL DEFAULT 'Educational Lesson'"),
            ("generated_videos", "description", "TEXT NULL"),
            ("generated_videos", "video_style", "VARCHAR(80) NULL DEFAULT 'Educational'"),
            ("generated_videos", "language", "VARCHAR(40) NULL DEFAULT 'English'"),
            ("generated_videos", "filename", "VARCHAR(255) NULL"),
            ("generated_videos", "video_url", "VARCHAR(500) NULL"),
            ("generated_videos", "thumbnail", "VARCHAR(500) NULL"),
            ("generated_videos", "difficulty", "VARCHAR(30) NULL"),
            ("generated_videos", "audience", "VARCHAR(40) NULL"),
            ("generated_videos", "aspect_ratio", "VARCHAR(10) NULL DEFAULT '16:9'"),
            ("generated_videos", "duration_seconds", "INT NOT NULL DEFAULT 0"),
            ("generated_videos", "subtitles", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("generated_videos", "highlights", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("generated_videos", "music", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("generated_videos", "script_text", "LONGTEXT NULL"),
        ]
        for table, column, definition in wanted_columns:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                (database_name, table, column),
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"
                )
                app.logger.info("Added missing column %s.%s", table, column)

        # Old game tables may contain leftover NOT NULL columns that make INSERTs fail.
        _relax_legacy_columns(cursor, database_name, "game_level_rewards",
                              {"id", "user_id", "game_key", "level_number", "score",
                               "credits_earned", "created_at"})
        _relax_legacy_columns(cursor, database_name, "game_progress",
                              {"id", "user_id", "game_key", "unlocked_level",
                               "completed_levels", "best_score", "updated_at"})
        _relax_legacy_columns(cursor, database_name, "game_plays",
                              {"id", "user_id", "game_key", "score_pct", "seconds",
                               "credits_earned", "played_at"})

        # Make sure the "one reward per level" unique key exists on old tables.
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'game_level_rewards' "
            "AND INDEX_NAME = 'unique_user_game_level'",
            (database_name,),
        )
        if cursor.fetchone()[0] == 0:
            try:
                cursor.execute(
                    "ALTER TABLE game_level_rewards ADD UNIQUE KEY unique_user_game_level "
                    "(user_id, game_key, level_number)"
                )
            except Error as exc:
                app.logger.warning("Could not add unique level-reward key: %s", exc)

        # Older versions of generated_videos used prompt / difficulty / file_name.
        # Make those optional and copy old data into title / filename.
        def _text(value):
            return value.decode() if isinstance(value, (bytes, bytearray)) else value

        cursor.execute(
            "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'generated_videos'",
            (database_name,),
        )
        video_columns = {
            _text(row[0]): (_text(row[1]), _text(row[2]))
            for row in cursor.fetchall()
        }

        for legacy in ("prompt", "difficulty", "file_name"):
            info = video_columns.get(legacy)
            if info and info[1] == "NO":
                cursor.execute(
                    f"ALTER TABLE generated_videos MODIFY COLUMN `{legacy}` {info[0]} NULL"
                )
                app.logger.info("Made generated_videos.%s optional", legacy)

        if "prompt" in video_columns:
            cursor.execute(
                "UPDATE generated_videos SET title = LEFT(prompt, 150) "
                "WHERE prompt IS NOT NULL AND prompt <> '' "
                "AND (title IS NULL OR title = 'Educational Lesson')"
            )
        if "file_name" in video_columns:
            cursor.execute(
                "UPDATE generated_videos SET filename = file_name "
                "WHERE file_name IS NOT NULL AND file_name <> '' "
                "AND (filename IS NULL OR filename = '')"
            )

        # Quiz tables reference generated_videos(id), so they are created last.
        for statement in statements[10:]:
            cursor.execute(statement)

        # Quiz tables created by an older version may lack columns the quiz code needs.
        quiz_columns = [
            ("video_quizzes", "user_id", "INT NOT NULL DEFAULT 0"),
            ("video_quizzes", "questions", "LONGTEXT NULL"),
            ("video_quizzes", "created_at", "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"),
            ("video_quiz_attempts", "user_id", "INT NOT NULL DEFAULT 0"),
            ("video_quiz_attempts", "video_id", "INT NOT NULL DEFAULT 0"),
            ("video_quiz_attempts", "quiz_id", "INT NOT NULL DEFAULT 0"),
            ("video_quiz_attempts", "answers", "TEXT NULL"),
            ("video_quiz_attempts", "score", "INT NOT NULL DEFAULT 0"),
            ("video_quiz_attempts", "total_questions", "INT NOT NULL DEFAULT 0"),
            ("video_quiz_attempts", "percentage", "INT NOT NULL DEFAULT 0"),
            ("video_quiz_attempts", "credits_earned", "INT NOT NULL DEFAULT 0"),
            ("video_quiz_attempts", "completed_at", "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"),
        ]
        for table, column, definition in quiz_columns:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                (database_name, table, column),
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")
                app.logger.info("Added missing column %s.%s", table, column)

        # Ensure every existing account has a progress row.
        cursor.execute(
            "INSERT IGNORE INTO learning_progress (user_id, videos_generated, quizzes_completed, games_played, total_score) "
            "SELECT id,0,0,0,0 FROM users"
        )
        connection.commit()
        app.logger.info("EduVision database tables are ready.")
        return True
    except Error as exc:
        connection.rollback()
        app.logger.exception("Database table initialization failed: %s", exc)
        return False
    finally:
        if cursor:
            cursor.close()
        connection.close()


# ============================================================
# APPLICATION STARTUP
# ============================================================

if __name__ == "__main__":
    print(f".env file: {_ENV_FILE}")
    print(ai_status())
    print(f".env exists: {_ENV_FILE.exists()}")
    # Shows exactly which generate_video.html Flask uses, and which routes serve the page.
    try:
        _src = app.jinja_env.loader.get_source(app.jinja_env, "generate_video.html")[1]
        print(f"generate_video.html is loaded from: {_src}")
        print(f"  last changed: {datetime.fromtimestamp(os.path.getmtime(_src)):%Y-%m-%d %H:%M:%S}")
    except Exception as _exc:
        print(f"generate_video.html could not be found: {_exc}")
    for _rule in app.url_map.iter_rules():
        if "generate" in _rule.rule:
            print(f"  route {_rule.rule} -> {_rule.endpoint}")
    if initialize_database():
        print("Database initialization successful.")
    else:
        print("WARNING: Database initialization failed.")

    # use_reloader=False is REQUIRED: video rendering uses worker processes and a
    # background thread, and Flask's reloader would restart them mid-job on Windows.
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        use_reloader=False,
        threaded=True,
    )