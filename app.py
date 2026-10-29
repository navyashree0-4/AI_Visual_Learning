from datetime import date, datetime, timedelta
import re
import secrets
import smtplib
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
import os
import uuid
try:
    from game_data import GAMES as DATA_GAMES, build_payload as data_build_payload
except ImportError:
    DATA_GAMES = {}

    def data_build_payload(game_key, game):
        return dict(game or {}, key=game_key, game_id=game_key)
from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, jsonify, redirect, render_template,
    render_template_string, request, send_from_directory, session, url_for,
)
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from routes.aptitude_backend import aptitude_bp     

from learning import learning_bp
from services.video_generator import (
    extract_text,
    generate_video as build_educational_video,
)

load_dotenv()

app = Flask(__name__)
app.register_blueprint(aptitude_bp)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
if not os.getenv("FLASK_SECRET_KEY"):
    app.logger.warning("FLASK_SECRET_KEY is not set. Set it in .env for stable sessions.")
app.register_blueprint(learning_bp)

VIDEO_COST = max(1, int(os.getenv("VIDEO_COST", "10")))
DAILY_CREDIT_CAP = max(0, int(os.getenv("DAILY_CREDIT_CAP", "40")))

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


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
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
    connection = get_db_connection()
    if connection is None:
        app.logger.error("Video was generated, but its record could not be saved.")
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO generated_videos "
            "(user_id, title, description, video_style, language, filename) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                user_id,
                (title or "Educational Lesson")[:150],
                f"{style} lesson in {language}",
                style,
                language,
                filename,
            ),
        )
        connection.commit()
        return True
    except Error as exc:
        connection.rollback()
        app.logger.error("Video record could not be saved: %s", exc)
        return False
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def calculate_streak(active_days):
    today = date.today()
    if today not in active_days:
        today -= timedelta(days=1)
    streak = 0
    while today in active_days:
        streak += 1
        today -= timedelta(days=1)
    return streak


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
                "title": video.get("title") or "Educational Lesson",
                "description": video.get("description") or "Your generated learning video",
                "style": video.get("video_style") or video.get("style") or "AI Lesson",
                "language": video.get("language") or "English",
                "filename": video.get("filename") or video.get("video_filename"),
                "video_url": video.get("video_url"),
                "thumbnail": video.get("thumbnail"),
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


# Each game key (including the keys used on the dashboard cards)
# maps to the game name used by static/games.html?g=...
GAME_SLUGS = {
    "snake_learner": "snake",
    "whack_a_concept": "whack", "whack_concept": "whack",
    "typing_racer": "typing",
    "simon_memory": "simon",
    "tech_2048": "2048",
    "flappy_bird_brain": "flappy", "flappy_brain": "flappy",
    "tetris_blocks": "tetris",
    "minesweeper_debug": "mines",
    "maze_runner": "maze",
    "tower_defense": "tower", "tower_firewall": "tower",
    "pacman_data_hunt": "pac", "pacman_data": "pac",
    "logic_gates_lab": "logic", "logic_gates": "logic",
    "robot_coder": "robot",
    "platform_adventure": "platform",
    "escape_room_2": "escape",
    "candy_match": "candy",
    "mind_match": "memory",
    "daily_brain_boost": "memory",
    "arrow_rush": "arrowrush",
    "space_dodge": "dodge",
    "arrow_memory": "arrowmem",
    "packet_crossing": "cross",
}

# For alias keys (e.g. "whack_concept"), find the real GAMES key
# so the score is saved against the right game.
CANONICAL_KEY = {}
for _key, _slug in GAME_SLUGS.items():
    if _key in GAMES:
        CANONICAL_KEY.setdefault(_slug, _key)


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
        game_title=game["name"],
        game_type=game["mode"],
        credits=session.get("credits", 0),
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
    request.get_json(silent=True)
    session["games_played"] = session.get("games_played", 0) + 1
    return jsonify(ok=True)


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
# VIDEO INSTRUCTIONS
# ============================================================

def build_video_instructions(topic, video_style, audience_level, language):
    audience_instructions = {
        "Kids": "Use very simple words, short sentences, colorful visuals, fun examples, and friendly narration.",
        "School Students": "Explain step by step with definitions, diagrams, school-level examples, key points, and revision questions.",
        "College Students": "Use detailed explanations, appropriate technical terms, practical examples, diagrams, and real-world applications.",
        "Teachers": "Include learning objectives, structured explanations, classroom examples, teaching tips, and assessment questions.",
    }
    style_instructions = {
        "Educational": "Use an introduction, learning objectives, explanation, examples, and summary.",
        "Animated": "Describe animated objects, characters, movements, visual effects, and transitions.",
        "Simple Explanation": "Use everyday examples, simple comparisons, and short sentences.",
        "Storytelling": "Explain through a story with characters, a problem, and a conclusion.",
    }
    return f"""
Create an accurate educational video script.
TOPIC: {topic}
TARGET AUDIENCE: {audience_level}
VIDEO STYLE: {video_style}
NARRATION LANGUAGE: {language}

AUDIENCE REQUIREMENTS:
{audience_instructions.get(audience_level, audience_instructions["School Students"])}

STYLE REQUIREMENTS:
{style_instructions.get(video_style, style_instructions["Educational"])}

Divide the topic into ordered scenes. Give each scene a title, narration, and matching visual description.
Use the selected narration language and vocabulary appropriate for the audience.
End with a summary and three review questions.
"""


# ============================================================
# HOME AND AUTHENTICATION
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


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
      <label>New password</label><input type="password" name="new_password" minlength="6" required>
      <label>Confirm new password</label><input type="password" name="confirm_password" minlength="6" required>
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
    # table_name is an internal constant, never supplied by the request.
    connection = get_db_connection()
    if connection is None:
        return False, "Database connection error."
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(f"SELECT otp_hash, expires_at, attempts FROM {table_name} WHERE email=%s", (email,))
        row = cursor.fetchone()
        if not row:
            return False, "No verification request was found. Request a new code."
        if int(row.get("attempts") or 0) >= OTP_MAX_ATTEMPTS:
            cursor.execute(f"DELETE FROM {table_name} WHERE email=%s", (email,))
            connection.commit()
            return False, "Too many attempts. Request a new code."
        expiry = row["expires_at"]
        if expiry is None or expiry < datetime.now():
            cursor.execute(f"DELETE FROM {table_name} WHERE email=%s", (email,))
            connection.commit()
            return False, "The code expired. Request a new one."
        if not check_password_hash(row["otp_hash"], otp):
            cursor.execute(f"UPDATE {table_name} SET attempts=attempts+1 WHERE email=%s", (email,))
            connection.commit()
            return False, "Incorrect verification code. Please try again."
        return True, "Verified."
    except Error:
        app.logger.exception("OTP verification database error")
        return False, "Unable to verify the code. Please try again."
    finally:
        if cursor:
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
        # FIX: use the real template (it needs `email`).
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


# FIX: this route was missing, but verify_otp.html calls url_for('resend_otp').
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
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
        session.clear()
        session["login_otp_email"] = email
        target = request.args.get("next", "")
        if target.startswith("/") and not target.startswith("//"):
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
        target = session.get("login_next", "")

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session["credits"] = int(user["credits"] or 0)

        log_activity(user["id"], "login")

        if target.startswith("/") and not target.startswith("//"):
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
        flash("If an account exists for that email, a password reset code has been sent.", "success")
        return redirect(url_for("login"))
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

GENERATED_DIR = Path(app.root_path) / "static" / "generated"


@app.route("/generated/<path:filename>")
@login_required
def generated_video(filename):
    """Serve generated videos (used by the dashboard video player)."""
    return send_from_directory(str(GENERATED_DIR), filename)


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

    # Latest video for the learning workspace player
    latest_video = ""
    latest_video_topic = ""
    latest_video_exists = False
    for video in data["videos"]:
        name = Path(video["filename"] or "").name
        if name and (GENERATED_DIR / name).exists():
            latest_video = name
            latest_video_topic = video["title"]
            latest_video_exists = True
            break

    recent_videos = [
        {
            "prompt": video["title"],
            "video_style": video["style"],
            "language": video["language"],
        }
        for video in data["videos"][:5]
    ]

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name", "Learner"),
        user_email=session.get("user_email", ""),
        credits=data["credits"],
        videos=data["videos"],
        recent_videos=recent_videos,
        latest_video=latest_video,
        latest_video_topic=latest_video_topic,
        latest_video_exists=latest_video_exists,
        videos_completed=videos_completed,
        quizzes_completed=quizzes_completed,
        games_played=games_played,
        learning_progress=learning_progress_value,
        learning_streak=data["streak"],
        streak=data["streak"],
        recent_activities=recent_activities,
        games=GAMES,
        progress={
            "videos_generated": videos_completed,
            "videos_completed": videos_completed,
            "quizzes_completed": quizzes_completed,
            "games_played": games_played,
        },
    )


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

@app.route("/generate_video", methods=["GET", "POST"])
@login_required
def generate_video():
    user_id = session["user_id"]
    if request.method == "GET":
        return render_template(
            "generate_video.html",
            user_name=session.get("user_name", "Student"),
            video_url=None,
        )

    temporary_path = None
    charged = False
    try:
        topic = (request.form.get("topic") or request.form.get("prompt") or "").strip()[:1000]
        style = request.form.get("video_style", "Educational")
        language = request.form.get("language", "English")
        audience = request.form.get("audience_level", "School Students")
        difficulty = request.form.get("difficulty", "Beginner")

        allowed_styles = {"Educational", "Animated", "Simple Explanation", "Storytelling"}
        allowed_languages = {"English", "Kannada", "Hindi", "Spanish", "French", "German"}
        allowed_difficulties = {"Beginner", "Intermediate", "Advanced"}
        allowed_audiences = {"Kids", "School Students", "College Students", "Teachers"}

        if style not in allowed_styles:
            raise ValueError("Please select a valid video style.")
        if language not in allowed_languages:
            raise ValueError("Please select a valid narration language.")
        if difficulty not in allowed_difficulties:
            raise ValueError("Please select a valid difficulty level.")
        if audience not in allowed_audiences:
            raise ValueError("Please select a valid target audience.")

        instructions = build_video_instructions(topic, style, audience, language)
        source_text = topic
        uploaded = request.files.get("file")

        if uploaded and uploaded.filename:
            filename = secure_filename(uploaded.filename)
            if not filename:
                raise ValueError("Please choose a valid filename.")
            extension = Path(filename).suffix.lower()
            if extension not in {".pdf", ".txt", ".png", ".jpg", ".jpeg"}:
                raise ValueError("Supported uploads: PDF, TXT, PNG, JPG and JPEG.")

            upload_dir = Path(app.root_path) / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = upload_dir / f"{uuid.uuid4().hex}{extension}"
            uploaded.save(str(temporary_path))
            extracted = extract_text(temporary_path).strip()
            if extracted:
                source_text = (
                    source_text + "\n\nAdditional uploaded material:\n" + extracted
                ).strip()
            elif not source_text:
                raise ValueError("No readable text was found in the uploaded file.")

        if not source_text.strip():
            raise ValueError("Enter a topic or upload readable material.")
        if not charge_credits(user_id, VIDEO_COST):
            raise ValueError(
                f"You need {VIDEO_COST} credits to generate a video. "
                "Play a learning game to earn more."
            )
        charged = True

        output_name = build_educational_video(
            source_text=instructions + "\n\nEDUCATIONAL SOURCE MATERIAL:\n" + source_text,
            style=style,
            difficulty=difficulty,
            language=language,
        )
        saved = save_video_record(
            user_id, topic or "Lesson from upload", style, language, Path(output_name).name
        )
        if not saved:
            raise RuntimeError("The video was generated, but its database record could not be saved. Please try again.")
        # Keep the charge only after both video generation and its record succeed.
        charged = False
        log_activity(user_id, "video")
        bump_video_progress(user_id)
        session["credits"] = get_user_credits(user_id)

        video_url = url_for("static", filename="generated/" + Path(output_name).name)
        return render_template(
            "generate_video.html",
            user_name=session.get("user_name", "Student"),
            video_url=video_url,
        )
    except (ValueError, RuntimeError) as exc:
        if charged:
            refund_credits(user_id, VIDEO_COST)
        flash(str(exc), "error")
    except Exception:
        if charged:
            refund_credits(user_id, VIDEO_COST)
        app.logger.exception("Educational video generation failed")
        flash("Video generation failed. Check the Flask terminal for details.", "error")
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return render_template(
        "generate_video.html",
        user_name=session.get("user_name", "Student"),
        video_url=None,
    )


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

@app.route("/api/game/finish", methods=["POST"])
@login_required
def api_game_finish():
    data = request.get_json(silent=True) or {}
    game_key = data.get("game")

    if not isinstance(game_key, str) or game_key not in GAMES:
        return jsonify(ok=False, error="Unknown game."), 400

    try:
        score_pct = int(data.get("score", 0))
        seconds = int(data.get("seconds", 0))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Invalid score or time."), 400

    score_pct = max(0, min(100, score_pct))
    seconds = max(0, min(86400, seconds))

    result = award_game_credits(session["user_id"], game_key, score_pct, seconds)

    # A missing balance means the result could not be saved
    if result["balance"] is None:
        return jsonify(ok=False, error=result["message"]), 503

    session["credits"] = result["balance"]

    return jsonify(
        ok=True,
        earned=result["earned"],
        balance=result["balance"],
        message=result["message"],
    ), 200


# ============================================================
# OTHER PAGES
# ============================================================

@app.route("/qa")
@login_required
def qa():
    return render_template("qa.html", user_name=session.get("user_name", "Student"))


@app.route("/learning-progress")
@login_required
def learning_progress():
    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("dashboard"))
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        user_id = session["user_id"]
        cursor.execute(
            "SELECT videos_generated, quizzes_completed, games_played, total_score "
            "FROM learning_progress WHERE user_id = %s",
            (user_id,),
        )
        progress = cursor.fetchone() or {
            "videos_generated": 0, "quizzes_completed": 0,
            "games_played": 0, "total_score": 0,
        }
        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        return render_template(
            "learning_progress.html",
            user_name=session.get("user_name", "Student"),
            credits=int(user["credits"] or 0) if user else 0,
            progress=progress,
        )
    except Error:
        app.logger.exception("Learning progress page failed")
        flash("Unable to load learning progress.", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


@app.route("/videos")
@login_required
def videos():
    connection = get_db_connection()
    if connection is None:
        flash("Database connection error.", "error")
        return redirect(url_for("dashboard"))
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM generated_videos WHERE user_id = %s ORDER BY created_at DESC",
            (session["user_id"],),
        )
        return render_template(
            "videos.html",
            videos=cursor.fetchall(),
            user_name=session.get("user_name", "Student"),
        )
    except Error:
        app.logger.exception("Videos page failed")
        flash("Unable to load videos.", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


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

MAX_GAME_LEVEL = 10
GAME_LEVEL_REWARD = 5

ALLOWED_GAME_KEYS = set(GAMES.keys())


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
    data = request.get_json(silent=True) or {}

    game_key = str(data.get("game_key", "")).strip()

    try:
        level = int(data.get("level", 0))
        score = max(0, int(data.get("score", 0)))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid level or score."}), 400

    if game_key not in GAMES or level < 1:
        return jsonify({"success": False, "message": "Invalid game or level."}), 400

    connection = get_db_connection()
    if connection is None:
        return jsonify({"success": False, "message": "Unable to connect to the database."}), 503

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()

        cursor.execute("SELECT credits FROM users WHERE id = %s FOR UPDATE", (user_id,))
        user = cursor.fetchone()

        if not user:
            connection.rollback()
            return jsonify({"success": False, "message": "User account not found."}), 404

        cursor.execute(
            "INSERT IGNORE INTO game_progress (user_id, game_key, unlocked_level, completed_levels, best_score) "
            "VALUES (%s, %s, 1, 0, 0)",
            (user_id, game_key),
        )

        reward = GAME_LEVEL_REWARD

        # The unique database index prevents duplicate rewards.
        cursor.execute(
            """
            INSERT IGNORE INTO game_level_rewards
                (user_id, game_key, level_number, score, credits_earned)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, game_key, level, score, reward),
        )

        newly_completed = cursor.rowcount == 1

        if newly_completed:
            cursor.execute(
                "UPDATE users SET credits = COALESCE(credits, 0) + %s WHERE id = %s",
                (reward, user_id),
            )
            cursor.execute(
                """UPDATE game_progress
                   SET completed_levels = completed_levels + 1,
                       unlocked_level = GREATEST(unlocked_level, %s),
                       best_score = GREATEST(COALESCE(best_score, 0), %s)
                   WHERE user_id = %s AND game_key = %s""",
                (level + 1, score, user_id, game_key),
            )
            earned = reward
        else:
            earned = 0

        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        updated_user = cursor.fetchone()
        balance = int(updated_user["credits"] or 0)

        connection.commit()
        session["credits"] = balance

        return jsonify({
            "success": True,
            "earned": earned,
            "balance": balance,
            "level": level,
            "game_key": game_key,
            "duplicate": not newly_completed,
            "message": (
                f"+{earned} credits earned!"
                if earned > 0
                else "You already earned credits for this level."
            ),
        })

    except Error:
        connection.rollback()
        app.logger.exception("Game level reward failed")
        return jsonify({"success": False, "message": "Unable to save credits. Please try again."}), 500

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
    app.logger.error("HTTP 500 error: %s", error)
    return (
        "EduVision encountered an error. "
        "Check the VS Code terminal for the traceback.",
        500,
    )


# ============================================================
# DATABASE INITIALIZATION: create required tables if missing
# ============================================================

def initialize_database():
    """Create the configured database and all tables used by this app.

    Existing tables/data are preserved. CREATE TABLE IF NOT EXISTS does not
    alter old schemas, so existing tables must already match these columns.
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
    ]
    try:
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
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


# Run schema checks for both `python app.py` and `flask run`.
initialize_database()

if __name__ == "__main__":
    print("=" * 60)
    print("EDUVISION - AI-Based Multimodal Visual Learning")
    print("=" * 60)
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")