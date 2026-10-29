"""
learning.py
Video page + ask a question + video quiz with retake + credit reward.
Register it in app.py with:
    from learning import learning_bp
    app.register_blueprint(learning_bp)
All addresses start with /learn
"""

import os
import json
import random
from functools import wraps

from flask import (Blueprint, render_template, request, session,
                   redirect, flash, jsonify, send_from_directory)

from config import Config
from db import get_connection
import ai_service

VIDEO_FOLDER = Config.VIDEO_FOLDER

learning_bp = Blueprint("learning", __name__, url_prefix="/learn")

PASS_PERCENT = 60        # marks needed to pass the quiz
REWARD_CREDITS = 5       # credits for passing a video quiz for the first time
QUESTION_COUNT = 5


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return view(*args, **kwargs)
    return wrapper


def get_video(video_id, user_id):
    """Finds a video that belongs to the logged-in user."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM videos WHERE id = %s AND user_id = %s", (video_id, user_id))
    video = cursor.fetchone()
    conn.close()
    return video


def first_value(video, names):
    """Returns the first non-empty column from a list of possible column names.
    This lets the code work even if your column is named differently."""
    for name in names:
        if video.get(name):
            return str(video[name])
    return ""


def video_context(video):
    """The text the AI uses to understand what the video taught."""
    text = first_value(video, ["script", "summary", "explanation", "content", "extracted_text"])
    return text if text else first_value(video, ["title", "topic"])


def video_url(video):
    path = first_value(video, ["video_path", "video_file", "file_path", "filename", "video_url"])
    if not path:
        return ""
    if path.startswith(("http", "/")):
        return path
    return "/learn/media/" + os.path.basename(path)


def load_or_make_quiz(video):
    """Quiz questions are created once per video and saved, so they stay the same."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT questions FROM video_quizzes WHERE video_id = %s", (video["id"],))
    row = cursor.fetchone()

    if row:
        conn.close()
        return json.loads(row["questions"])

    questions = ai_service.make_quiz(video_context(video), QUESTION_COUNT)
    if questions:
        cursor.execute("INSERT INTO video_quizzes (video_id, questions) VALUES (%s, %s)",
                       (video["id"], json.dumps(questions)))
        conn.commit()
    conn.close()
    return questions


# ---------------------------------------------------------
# Pages
# ---------------------------------------------------------
@learning_bp.route("/media/<path:filename>")
@login_required
def media(filename):
    return send_from_directory(VIDEO_FOLDER, filename)


@learning_bp.route("/video/<int:video_id>")
@login_required
def watch(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        flash("Video not found.")
        return redirect("/dashboard")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT question, answer FROM video_questions "
                   "WHERE user_id = %s AND video_id = %s ORDER BY id DESC LIMIT 10",
                   (session["user_id"], video_id))
    history = list(reversed(cursor.fetchall()))

    cursor.execute("SELECT MAX(percent) AS best, MAX(passed) AS passed, COUNT(*) AS tries "
                   "FROM quiz_attempts WHERE user_id = %s AND video_id = %s",
                   (session["user_id"], video_id))
    stats = cursor.fetchone()
    conn.close()

    return render_template("learn_video.html",
                           video=video,
                           video_url=video_url(video),
                           about=video_context(video)[:500],
                           history=history,
                           stats=stats,
                           pass_percent=PASS_PERCENT)


@learning_bp.route("/video/<int:video_id>/quiz")
@login_required
def quiz_page(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return redirect("/dashboard")
    return render_template("learn_quiz.html", video=video)


# ---------------------------------------------------------
# Ask a question about the video
# ---------------------------------------------------------
@learning_bp.route("/api/video/<int:video_id>/ask", methods=["POST"])
@login_required
def ask(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return jsonify(error="Video not found."), 404

    question = (request.get_json(silent=True) or {}).get("question", "").strip()
    if len(question) < 3:
        return jsonify(error="Please type your question."), 400
    question = question[:300]

    try:
        answer = ai_service.answer_question(video_context(video), question)
    except Exception as error:
        print("Ask AI problem:", error)
        return jsonify(error="The AI is busy right now. Please try again in a moment."), 503

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO video_questions (user_id, video_id, question, answer) "
                   "VALUES (%s, %s, %s, %s)", (session["user_id"], video_id, question, answer))
    conn.commit()
    conn.close()

    return jsonify(answer=answer)


# ---------------------------------------------------------
# Quiz: questions, instant check, final result
# ---------------------------------------------------------
@learning_bp.route("/api/video/<int:video_id>/quiz-data")
@login_required
def quiz_data(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return jsonify(error="Video not found."), 404

    questions = load_or_make_quiz(video)
    if not questions:
        return jsonify(error="Could not create the quiz right now. Please try again."), 503

    # Every time the quiz opens (also on retake) the order is shuffled.
    # The correct answers are NOT sent to the browser.
    order = list(range(len(questions)))
    random.shuffle(order)

    payload = []
    for qid in order:
        options = questions[qid]["options"][:]
        random.shuffle(options)
        payload.append({"id": qid, "question": questions[qid]["q"], "options": options})

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM quiz_attempts WHERE user_id = %s AND video_id = %s",
                   (session["user_id"], video_id))
    tries = cursor.fetchone()[0]
    conn.close()

    return jsonify(questions=payload, attempt=tries + 1, pass_percent=PASS_PERCENT,
                   title=first_value(video, ["title", "topic"]))


@learning_bp.route("/api/video/<int:video_id>/quiz-check", methods=["POST"])
@login_required
def quiz_check(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return jsonify(error="Video not found."), 404

    data = request.get_json(silent=True) or {}
    questions = load_or_make_quiz(video)

    try:
        question = questions[int(data.get("id"))]
    except (TypeError, ValueError, IndexError):
        return jsonify(error="Bad question."), 400

    return jsonify(correct=(data.get("choice") == question["answer"]),
                   answer=question["answer"],
                   explanation=question.get("explanation", ""))


@learning_bp.route("/api/video/<int:video_id>/quiz-submit", methods=["POST"])
@login_required
def quiz_submit(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return jsonify(error="Video not found."), 404

    questions = load_or_make_quiz(video)
    answers = (request.get_json(silent=True) or {}).get("answers", [])

    # Count the score on the server (each question counted once)
    score = 0
    seen = set()
    for item in answers:
        try:
            qid = int(item["id"])
            if qid in seen:
                continue
            seen.add(qid)
            if item["choice"] == questions[qid]["answer"]:
                score += 1
        except (KeyError, TypeError, ValueError, IndexError):
            continue

    total = len(questions)
    percent = round(score / total * 100)
    passed = percent >= PASS_PERCENT
    user_id = session["user_id"]

    conn = get_connection()
    cursor = conn.cursor()

    # Credits are given only the first time the quiz is passed
    cursor.execute("SELECT COUNT(*) FROM quiz_attempts WHERE user_id = %s AND video_id = %s AND passed = 1",
                   (user_id, video_id))
    passed_before = cursor.fetchone()[0] > 0
    reward = REWARD_CREDITS if (passed and not passed_before) else 0

    cursor.execute("INSERT INTO quiz_attempts (user_id, video_id, score, total, percent, passed, reward) "
                   "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (user_id, video_id, score, total, percent, int(passed), reward))

    if reward:
        cursor.execute("UPDATE users SET credits = credits + %s WHERE id = %s", (reward, user_id))

    cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    credits = row[0] if row else 0
    cursor.execute("SELECT COUNT(*) FROM quiz_attempts WHERE user_id = %s AND video_id = %s",
                   (user_id, video_id))
    tries = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    return jsonify(score=score, total=total, percent=percent, passed=passed,
                   reward=reward, credits=credits, attempt=tries, pass_percent=PASS_PERCENT)


# ---------------------------------------------------------
# Saving a video (call this from your video generation code)
# ---------------------------------------------------------
def save_video(user_id, title, script, video_path):
    """Adds one row to the videos table and returns the new video id.
    Call it right after a video is generated:
        video_id = save_video(session["user_id"], "OSI Model", script_text, "osi_model.mp4")
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO videos (user_id, title, script, video_path) VALUES (%s, %s, %s, %s)",
                   (user_id, title, script, video_path))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


# ---------------------------------------------------------
# TEST ONLY: creates a sample video row so you can try
# "ask a question" and the quiz without generating a real video.
# Open  http://127.0.0.1:5000/learn/demo  while logged in.
# Delete this route when your real video generation is connected.
# ---------------------------------------------------------
@learning_bp.route("/demo")
@login_required
def demo():
    script = (
        "The OSI model explains how data travels across a network using seven layers. "
        "The layers are Physical, Data Link, Network, Transport, Session, Presentation and Application. "
        "Each layer does one job. The Physical layer sends raw bits over cables. "
        "The Network layer decides the path using IP addresses. "
        "The Transport layer makes sure data arrives correctly, using TCP or UDP. "
        "The Application layer is what users see, such as a web browser or email. "
        "Think of sending a parcel by post: each step adds a label, and each office does one small task."
    )
    video_id = save_video(session["user_id"], "OSI Model in Simple Words", script, "")
    return redirect("/learn/video/" + str(video_id))


# ---------------------------------------------------------
# GAMES
# ---------------------------------------------------------
GAMES = ["memory", "tf", "scramble", "match", "challenge"]
REWARD_GAME = 2          # credits for scoring 60% or more in a game for the first time


def load_or_make_pack(video):
    """The game content is created once per video and saved."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT pack FROM game_packs WHERE video_id = %s", (video["id"],))
    row = cursor.fetchone()

    if row:
        conn.close()
        return json.loads(row["pack"])

    pack = ai_service.make_game_pack(video_context(video))
    if pack:
        cursor.execute("INSERT INTO game_packs (video_id, pack) VALUES (%s, %s)",
                       (video["id"], json.dumps(pack)))
        conn.commit()
    conn.close()
    return pack


@learning_bp.route("/games")
@login_required
def games_shortcut():
    """Opens the games of the user's newest video (used by the dashboard)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM videos WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                   (session["user_id"],))
    row = cursor.fetchone()
    conn.close()

    if row:
        return redirect("/learn/video/" + str(row[0]) + "/games")

    flash("Create a video first to unlock the games.")
    return redirect("/dashboard")


@learning_bp.route("/video/<int:video_id>/games")
@login_required
def games_page(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return redirect("/dashboard")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT game FROM game_plays "
                   "WHERE user_id = %s AND video_id = %s AND percent >= 60",
                   (session["user_id"], video_id))
    done = [row[0] for row in cursor.fetchall()]
    conn.close()

    return render_template("learn_games.html", video=video, done=done, reward=REWARD_GAME)


@learning_bp.route("/api/video/<int:video_id>/game-pack")
@login_required
def game_pack(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return jsonify(error="Video not found."), 404

    pack = load_or_make_pack(video)
    if not pack:
        return jsonify(error="Could not create the games right now. Please try again."), 503
    return jsonify(pack)


@learning_bp.route("/api/video/<int:video_id>/game-complete", methods=["POST"])
@login_required
def game_complete(video_id):
    video = get_video(video_id, session["user_id"])
    if not video:
        return jsonify(error="Video not found."), 404

    data = request.get_json(silent=True) or {}
    game = data.get("game")

    try:
        score, total = int(data.get("score")), int(data.get("total"))
    except (TypeError, ValueError):
        return jsonify(error="Bad result."), 400

    if game not in GAMES or total < 1 or score < 0 or score > total:
        return jsonify(error="Bad result."), 400

    percent = round(score / total * 100)
    user_id = session["user_id"]

    conn = get_connection()
    cursor = conn.cursor()

    # Credits are given only the first time each game is passed for a video
    cursor.execute("SELECT COUNT(*) FROM game_plays "
                   "WHERE user_id = %s AND video_id = %s AND game = %s AND percent >= 60",
                   (user_id, video_id, game))
    passed_before = cursor.fetchone()[0] > 0
    reward = REWARD_GAME if (percent >= 60 and not passed_before) else 0

    cursor.execute("INSERT INTO game_plays (user_id, video_id, game, score, total, percent, reward) "
                   "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (user_id, video_id, game, score, total, percent, reward))

    if reward:
        cursor.execute("UPDATE users SET credits = credits + %s WHERE id = %s", (reward, user_id))

    cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()

    return jsonify(reward=reward, credits=row[0] if row else 0, percent=percent)


# ---------------------------------------------------------
# GAME ARCADE (games on the dashboard: Gem Match, Pop Blast, Merge 2048)
# ---------------------------------------------------------
ARCADE_RULES = {"match3": 500, "pop": 400, "merge": 256}   # score needed to earn credits
ARCADE_REWARD = 2                                          # credits, once per game per day


@learning_bp.route("/api/arcade/complete", methods=["POST"])
@login_required
def arcade_complete():
    data = request.get_json(silent=True) or {}
    game = data.get("game")

    try:
        score = int(data.get("score"))
    except (TypeError, ValueError):
        return jsonify(error="Bad result."), 400

    if game not in ARCADE_RULES or score < 0 or score > 10000000:
        return jsonify(error="Bad result."), 400

    user_id = session["user_id"]
    reward = 0

    conn = get_connection()
    cursor = conn.cursor()

    if score >= ARCADE_RULES[game]:
        cursor.execute("SELECT COUNT(*) FROM arcade_plays WHERE user_id = %s AND game = %s "
                       "AND reward > 0 AND DATE(created_at) = CURDATE()", (user_id, game))
        if cursor.fetchone()[0] == 0:
            reward = ARCADE_REWARD

    cursor.execute("INSERT INTO arcade_plays (user_id, game, score, reward) VALUES (%s, %s, %s, %s)",
                   (user_id, game, score, reward))

    if reward:
        cursor.execute("UPDATE users SET credits = credits + %s WHERE id = %s", (reward, user_id))

    cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()

    return jsonify(reward=reward, credits=row[0] if row else 0)


# ---------------------------------------------------------
# GAMES PAGE (Coding Logic Challenge): 7 games, endless levels
# Credits earned here are used to create videos.
# ---------------------------------------------------------
ARCADE_GAMES = ["candy", "bubble", "color", "order", "spot", "flash", "quiz"]
VIDEO_COST = 5           # credits needed for one video (change it to your own rule)


def level_reward(level):
    """Levels 1-3 give 1 credit, 4-6 give 2, 7-9 give 3, 10-12 give 4, and 13 or higher give 5."""
    return min(5, 1 + (level - 1) // 3)


@learning_bp.route("/arcade")
@login_required
def arcade_page():
    return render_template("arcade.html")


@learning_bp.route("/api/arcade/progress")
@login_required
def arcade_progress():
    user_id = session["user_id"]
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT game, MAX(level) FROM arcade_levels WHERE user_id = %s GROUP BY game", (user_id,))
    progress = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()

    return jsonify(progress=progress, credits=row[0] if row else 0, video_cost=VIDEO_COST)


@learning_bp.route("/api/arcade/level-complete", methods=["POST"])
@login_required
def arcade_level_complete():
    data = request.get_json(silent=True) or {}
    game = data.get("game")

    try:
        level = int(data.get("level"))
    except (TypeError, ValueError):
        return jsonify(error="Bad level."), 400

    if game not in ARCADE_GAMES or level < 1 or level > 100000:
        return jsonify(error="Bad level."), 400

    user_id = session["user_id"]
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(level) FROM arcade_levels WHERE user_id = %s AND game = %s", (user_id, game))
    highest = cursor.fetchone()[0] or 0

    # Levels must be cleared in order
    if level > highest + 1:
        conn.close()
        return jsonify(error="Clear the earlier levels first."), 400

    cursor.execute("SELECT COUNT(*) FROM arcade_levels WHERE user_id = %s AND game = %s AND level = %s",
                   (user_id, game, level))
    reward = 0
    if cursor.fetchone()[0] == 0:
        reward = level_reward(level)
        cursor.execute("INSERT IGNORE INTO arcade_levels (user_id, game, level) VALUES (%s, %s, %s)",
                       (user_id, game, level))
        cursor.execute("UPDATE users SET credits = credits + %s WHERE id = %s", (reward, user_id))

    cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()

    return jsonify(reward=reward, credits=row[0] if row else 0, highest=max(highest, level),
                   video_cost=VIDEO_COST)


# ---------------------------------------------------------
# QUICK ACTIONS (dashboard) and LEADERBOARD
# ---------------------------------------------------------
def latest_video_id(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM videos WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


@learning_bp.route("/ask")
@login_required
def ask_shortcut():
    """Dashboard 'Ask a question': opens the newest video with the question box ready."""
    video_id = latest_video_id(session["user_id"])
    if video_id:
        return redirect("/learn/video/" + str(video_id) + "#ask")
    flash("Create a video first. Then you can ask questions about it.")
    return redirect("/dashboard")


@learning_bp.route("/quiz")
@login_required
def quiz_shortcut():
    """Dashboard 'Video quiz': opens the quiz of the newest video."""
    video_id = latest_video_id(session["user_id"])
    if video_id:
        return redirect("/learn/video/" + str(video_id) + "/quiz")
    flash("Create a video first. Then you can take its quiz.")
    return redirect("/dashboard")


POINTS_VIDEO = 10     # for every video created
POINTS_QUIZ = 20      # for every video quiz passed
POINTS_LEVEL = 5      # for every game level cleared


@learning_bp.route("/leaderboard")
@login_required
def leaderboard():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()

    def counts(sql):
        cursor.execute(sql)
        return {row["user_id"]: row["n"] for row in cursor.fetchall()}

    videos = counts("SELECT user_id, COUNT(*) AS n FROM videos GROUP BY user_id")
    quizzes = counts("SELECT user_id, COUNT(DISTINCT video_id) AS n FROM quiz_attempts "
                     "WHERE passed = 1 GROUP BY user_id")
    levels = counts("SELECT user_id, COUNT(*) AS n FROM arcade_levels GROUP BY user_id")
    conn.close()

    board = []
    for user in users:
        uid = user["id"]
        name = (user.get("full_name") or user.get("name") or user.get("username")
                or (user.get("email") or "Learner").split("@")[0])
        v, qz, lv = videos.get(uid, 0), quizzes.get(uid, 0), levels.get(uid, 0)
        board.append({"id": uid, "name": name, "videos": v, "quizzes": qz, "levels": lv,
                      "points": v * POINTS_VIDEO + qz * POINTS_QUIZ + lv * POINTS_LEVEL})

    board.sort(key=lambda row: row["points"], reverse=True)
    for rank, row in enumerate(board, start=1):
        row["rank"] = rank

    me = next((row for row in board if row["id"] == session["user_id"]), None)
    top = [row for row in board if row["points"] > 0][:10]

    return render_template("learn_leaderboard.html", rows=top, me=me, my_id=session["user_id"],
                           p_video=POINTS_VIDEO, p_quiz=POINTS_QUIZ, p_level=POINTS_LEVEL)