
import json
import secrets
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, abort
)

aptitude_bp = Blueprint("aptitude", __name__)

TEST_DURATION_MINUTES = 30
ALLOWED_COUNTS = {10, 20, 30}

CATEGORY_NAMES = {
    "quantitative": "Quantitative Aptitude",
}

# Answers stay on the server.
# Each answer is the zero-based index of the correct option.
QUESTION_BANK = {
    "quantitative": [
        {
            "question": "What is 25% of 240?",
            "options": ["40", "50", "60", "80"],
            "answer": 2,
            "explanation": "25% is one-fourth. 240 / 4 = 60."
        },
        {
            "question": "A number increases from 80 to 100. Find the percentage increase.",
            "options": ["20%", "25%", "30%", "40%"],
            "answer": 1,
            "explanation": "Increase = 20. Percentage = 20 / 80 * 100 = 25%."
        },
        {
            "question": "Find the average of 12, 18, 20 and 30.",
            "options": ["18", "19", "20", "22"],
            "answer": 2,
            "explanation": "The sum is 80. Average = 80 / 4 = 20."
        },
        {
            "question": "Five pens cost Rs. 60. What do eight pens cost?",
            "options": ["Rs. 84", "Rs. 90", "Rs. 96", "Rs. 100"],
            "answer": 2,
            "explanation": "One pen costs Rs. 12. Eight cost Rs. 96."
        },
        {
            "question": "A train travels 150 km in 3 hours. Find its average speed.",
            "options": ["40 km/h", "45 km/h", "50 km/h", "60 km/h"],
            "answer": 2,
            "explanation": "Speed = distance / time = 150 / 3 = 50 km/h."
        },
        {
            "question": "Simplify the ratio 24:36.",
            "options": ["2:3", "3:4", "4:5", "1:3"],
            "answer": 0,
            "explanation": "Divide both terms by 12 to get 2:3."
        },
        {
            "question": "Find the simple interest on Rs. 2,000 at 5% for 2 years.",
            "options": ["Rs. 100", "Rs. 150", "Rs. 200", "Rs. 250"],
            "answer": 2,
            "explanation": "SI = 2000 * 5 * 2 / 100 = Rs. 200."
        },
        {
            "question": "If x + 15 = 42, find x.",
            "options": ["25", "27", "28", "30"],
            "answer": 1,
            "explanation": "x = 42 - 15 = 27."
        },
        {
            "question": "An item costs Rs. 800 and sells for Rs. 920. Find the profit percentage.",
            "options": ["10%", "12%", "15%", "20%"],
            "answer": 2,
            "explanation": "Profit = 120. Profit percentage = 120 / 800 * 100 = 15%."
        },
        {
            "question": "Find the next number: 3, 6, 12, 24, __.",
            "options": ["36", "42", "48", "54"],
            "answer": 2,
            "explanation": "Each number is multiplied by 2. The answer is 48."
        },
        {
            "question": "What is 3/5 of 250?",
            "options": ["100", "125", "150", "175"],
            "answer": 2,
            "explanation": "250 * 3 / 5 = 150."
        },
        {
            "question": "A finishes a job in 10 days. What fraction does A complete daily?",
            "options": ["1/5", "1/10", "1/15", "1/20"],
            "answer": 1,
            "explanation": "Daily work = 1 / 10 of the job."
        },
        {
            "question": "Find the HCF of 18 and 30.",
            "options": ["3", "6", "9", "12"],
            "answer": 1,
            "explanation": "The highest common factor is 6."
        },
        {
            "question": "Find the LCM of 6 and 8.",
            "options": ["12", "18", "24", "48"],
            "answer": 2,
            "explanation": "The smallest common multiple is 24."
        },
        {
            "question": "A 120 m train crosses a pole in 6 seconds. Find its speed.",
            "options": ["20 m/s", "18 m/s", "15 m/s", "12 m/s"],
            "answer": 0,
            "explanation": "Speed = 120 / 6 = 20 m/s."
        },
        {
            "question": "Find the compound amount on Rs. 1,000 at 10% annually for 2 years.",
            "options": ["Rs. 1,100", "Rs. 1,200", "Rs. 1,210", "Rs. 1,220"],
            "answer": 2,
            "explanation": "Amount = 1000 * 1.1 * 1.1 = Rs. 1,210."
        },
        {
            "question": "If 40% of a number is 72, find the number.",
            "options": ["160", "170", "180", "200"],
            "answer": 2,
            "explanation": "Number = 72 / 0.4 = 180."
        },
        {
            "question": "An item bought for Rs. 500 sells for Rs. 450. Find the loss percentage.",
            "options": ["5%", "10%", "15%", "20%"],
            "answer": 1,
            "explanation": "Loss = 50. Loss percentage = 50 / 500 * 100 = 10%."
        },
        {
            "question": "What is the square root of 1444?",
            "options": ["36", "37", "38", "39"],
            "answer": 2,
            "explanation": "38 * 38 = 1444."
        },
        {
            "question": "Seven workers finish a job in 12 days. How many worker-days are required?",
            "options": ["19", "42", "72", "84"],
            "answer": 3,
            "explanation": "Worker-days = 7 * 12 = 84."
        },
        {
            "question": "A bag has 3 red and 2 blue balls. Find the probability of picking blue.",
            "options": ["1/5", "2/5", "3/5", "1/2"],
            "answer": 1,
            "explanation": "There are 2 blue balls among 5 balls. Probability = 2/5."
        },
        {
            "question": "Find the median of 4, 7, 9, 12, 15.",
            "options": ["7", "9", "10", "12"],
            "answer": 1,
            "explanation": "The middle value is 9."
        },
        {
            "question": "If 2x = 46, find x.",
            "options": ["21", "22", "23", "24"],
            "answer": 2,
            "explanation": "x = 46 / 2 = 23."
        },
        {
            "question": "A car travels 240 km in 4 hours. How far does it travel in 7 hours at the same speed?",
            "options": ["360 km", "400 km", "420 km", "480 km"],
            "answer": 2,
            "explanation": "Speed = 60 km/h. Distance = 60 * 7 = 420 km."
        },
        {
            "question": "Find the perimeter of a square with side 9 cm.",
            "options": ["18 cm", "27 cm", "36 cm", "81 cm"],
            "answer": 2,
            "explanation": "Perimeter = 4 * 9 = 36 cm."
        },
        {
            "question": "Find the area of a rectangle 12 cm long and 7 cm wide.",
            "options": ["19 cm2", "38 cm2", "84 cm2", "96 cm2"],
            "answer": 2,
            "explanation": "Area = 12 * 7 = 84 square cm."
        },
        {
            "question": "An item marked Rs. 1,500 has a 20% discount. Find the selling price.",
            "options": ["Rs. 1,000", "Rs. 1,100", "Rs. 1,200", "Rs. 1,300"],
            "answer": 2,
            "explanation": "Discount = Rs. 300. Selling price = Rs. 1,200."
        },
        {
            "question": "Two ages are in the ratio 2:3 and total 40 years. Find the younger age.",
            "options": ["12 years", "16 years", "20 years", "24 years"],
            "answer": 1,
            "explanation": "One part = 40 / 5 = 8. Younger age = 2 * 8 = 16."
        },
        {
            "question": "What is 15% of 360?",
            "options": ["45", "50", "54", "60"],
            "answer": 2,
            "explanation": "360 * 15 / 100 = 54."
        },
        {
            "question": "A number divided by 8 gives quotient 9 and remainder 3. Find the number.",
            "options": ["69", "72", "75", "81"],
            "answer": 2,
            "explanation": "Number = 8 * 9 + 3 = 75."
        },
    ]
}


def get_connection():
    """Reuse the MySQL connection function from app.py."""
    from app import get_db_connection
    return get_db_connection()


def get_attempt_owner():
    """Identify a logged-in user or the current guest session."""
    user_id = session.get("user_id")

    if user_id is not None:
        return user_id, None

    if not session.get("aptitude_guest_id"):
        session["aptitude_guest_id"] = secrets.token_urlsafe(32)

    return None, session["aptitude_guest_id"]


def ensure_aptitude_tables():
    """Create tables and migrate an older aptitude schema if needed."""
    connection = get_connection()

    if connection is None:
        raise RuntimeError("Unable to connect to EduVision MySQL.")

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS aptitude_questions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                category VARCHAR(30) NOT NULL,
                question_text TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_option TINYINT NOT NULL,
                explanation TEXT,
                active TINYINT(1) NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_aptitude_question
                    (category, question_text(180))
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS aptitude_attempts (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                guest_token VARCHAR(100) NULL,
                category VARCHAR(30) NOT NULL,
                question_count INT NOT NULL,
                started_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                submitted_at DATETIME NULL,
                score INT NOT NULL DEFAULT 0,
                percentage DECIMAL(5,2) NOT NULL DEFAULT 0,
                time_taken_seconds INT NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_aptitude_user (user_id, created_at),
                INDEX idx_aptitude_guest (guest_token)
            )
        """)

        # Add columns to tables created by an earlier version.
        cursor.execute("SHOW COLUMNS FROM aptitude_attempts")
        existing_columns = {
            row[0] for row in cursor.fetchall()
        }

        if "guest_token" not in existing_columns:
            cursor.execute("""
                ALTER TABLE aptitude_attempts
                ADD COLUMN guest_token VARCHAR(100) NULL
            """)

        if "user_id" in existing_columns:
            user_column = next(
                row for row in cursor.fetchall()
            ) if False else None

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS aptitude_attempt_answers (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                attempt_id BIGINT NOT NULL,
                question_id INT NOT NULL,
                selected_option TINYINT NULL,
                is_correct TINYINT(1) NOT NULL DEFAULT 0,
                CONSTRAINT fk_aptitude_attempt
                    FOREIGN KEY (attempt_id)
                    REFERENCES aptitude_attempts(id) ON DELETE CASCADE,
                CONSTRAINT fk_aptitude_question
                    FOREIGN KEY (question_id)
                    REFERENCES aptitude_questions(id),
                UNIQUE KEY unique_attempt_question
                    (attempt_id, question_id)
            )
        """)

        # Seed all available quantitative questions.
        for question in QUESTION_BANK["quantitative"]:
            cursor.execute("""
                INSERT IGNORE INTO aptitude_questions
                    (category, question_text, options_json,
                     correct_option, explanation)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                "quantitative",
                question["question"],
                json.dumps(question["options"]),
                question["answer"],
                question["explanation"],
            ))

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def find_owned_attempt(cursor, test_id, owner_user_id, guest_token,
                       lock=False):
    """Return an attempt only if it belongs to this user or guest."""
    sql = """
        SELECT *
        FROM aptitude_attempts
        WHERE id=%s
          AND (
              (user_id=%s AND %s IS NOT NULL)
              OR (user_id IS NULL AND guest_token=%s)
          )
    """

    if lock:
        sql += " FOR UPDATE"

    cursor.execute(
        sql,
        (test_id, owner_user_id, owner_user_id, guest_token)
    )
    return cursor.fetchone()


@aptitude_bp.route("/aptitude")
def aptitude_arena():
    try:
        ensure_aptitude_tables()
        return render_template("aptitude_arena.html")
    except Exception as exc:
        print("APTITUDE DATABASE ERROR:", exc)
        flash("Aptitude Arena could not connect to the database.")
        return render_template("aptitude_arena.html")


@aptitude_bp.route("/aptitude/start", methods=["POST"])
def aptitude_start():
    category = request.form.get(
        "category", "quantitative"
    ).strip().lower()

    try:
        count = int(request.form.get("question_count", "30"))
    except (TypeError, ValueError):
        count = 30

    if category not in CATEGORY_NAMES:
        flash("Please select a supported aptitude category.")
        return redirect(url_for("aptitude.aptitude_arena"))

    if count not in ALLOWED_COUNTS:
        flash("Choose 10, 20, or 30 questions.")
        return redirect(url_for("aptitude.aptitude_arena"))

    connection = None
    cursor = None

    try:
        ensure_aptitude_tables()
        connection = get_connection()

        if connection is None:
            raise RuntimeError("MySQL connection failed.")

        owner_user_id, guest_token = get_attempt_owner()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, question_text, options_json
            FROM aptitude_questions
            WHERE category=%s AND active=1
            ORDER BY RAND()
            LIMIT %s
        """, (category, count))

        questions = cursor.fetchall()

        if len(questions) < count:
            flash(
                f"Only {len(questions)} questions are available. "
                f"This test needs {count} questions."
            )
            return redirect(url_for("aptitude.aptitude_arena"))

        now = datetime.now()
        expiry = now + timedelta(minutes=TEST_DURATION_MINUTES)

        cursor.execute("""
            INSERT INTO aptitude_attempts
                (user_id, guest_token, category, question_count,
                 started_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            owner_user_id, guest_token, category,
            count, now, expiry
        ))

        test_id = cursor.lastrowid

        for question in questions:
            cursor.execute("""
                INSERT INTO aptitude_attempt_answers
                    (attempt_id, question_id)
                VALUES (%s, %s)
            """, (test_id, question["id"]))

        connection.commit()

        return redirect(
            url_for("aptitude.aptitude_test", test_id=test_id)
        )

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        print("APTITUDE START ERROR:", exc)
        flash("Could not start the test. Check the Flask terminal.")

        return redirect(url_for("aptitude.aptitude_arena"))

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@aptitude_bp.route("/aptitude/test/<int:test_id>")
def aptitude_test(test_id):
    connection = None
    cursor = None

    try:
        owner_user_id, guest_token = get_attempt_owner()
        connection = get_connection()

        if connection is None:
            raise RuntimeError("MySQL connection failed.")

        cursor = connection.cursor(dictionary=True)
        attempt = find_owned_attempt(
            cursor, test_id, owner_user_id, guest_token
        )

        if not attempt:
            abort(404)

        if attempt["status"] != "in_progress":
            return redirect(
                url_for("aptitude.aptitude_result", test_id=test_id)
            )

        if datetime.now() >= attempt["expires_at"]:
            return redirect(
                url_for("aptitude.aptitude_submit", test_id=test_id)
            )

        cursor.execute("""
            SELECT q.id, q.question_text, q.options_json
            FROM aptitude_attempt_answers aa
            JOIN aptitude_questions q ON q.id=aa.question_id
            WHERE aa.attempt_id=%s
            ORDER BY aa.id
        """, (test_id,))

        questions = [
            {
                "id": row["id"],
                "question_text": row["question_text"],
                "options": json.loads(row["options_json"]),
            }
            for row in cursor.fetchall()
        ]

        seconds_left = max(
            0,
            int((attempt["expires_at"] - datetime.now()).total_seconds())
        )

        return render_template(
            "aptitude_test.html",
            test_id=test_id,
            category_name=CATEGORY_NAMES[attempt["category"]],
            questions=questions,
            duration_seconds=seconds_left,
        )

    except Exception as exc:
        if getattr(exc, "code", None) == 404:
            raise

        print("APTITUDE TEST ERROR:", exc)
        flash("Unable to open the test. Please try again.")
        return redirect(url_for("aptitude.aptitude_arena"))

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@aptitude_bp.route(
    "/aptitude/submit/<int:test_id>",
    methods=["POST", "GET"]
)
def aptitude_submit(test_id):
    connection = None
    cursor = None

    try:
        owner_user_id, guest_token = get_attempt_owner()
        connection = get_connection()

        if connection is None:
            raise RuntimeError("MySQL connection failed.")

        cursor = connection.cursor(dictionary=True)

        attempt = find_owned_attempt(
            cursor, test_id, owner_user_id, guest_token, lock=True
        )

        if not attempt:
            abort(404)

        if attempt["status"] != "in_progress":
            connection.commit()
            return redirect(
                url_for("aptitude.aptitude_result", test_id=test_id)
            )

        now = datetime.now()
        expired = now >= attempt["expires_at"]

        # GET requests only submit automatically when the timer expires.
        if request.method == "GET" and not expired:
            return redirect(
                url_for("aptitude.aptitude_test", test_id=test_id)
            )

        cursor.execute("""
            SELECT aa.id AS answer_row_id,
                   aa.question_id, q.correct_option
            FROM aptitude_attempt_answers aa
            JOIN aptitude_questions q ON q.id=aa.question_id
            WHERE aa.attempt_id=%s
        """, (test_id,))

        answers = cursor.fetchall()
        score = 0

        for answer in answers:
            selected = None

            if request.method == "POST" and not expired:
                raw = request.form.get(
                    f"answer_{answer['question_id']}"
                )

                if raw is not None:
                    try:
                        candidate = int(raw)
                        if candidate in range(4):
                            selected = candidate
                    except (TypeError, ValueError):
                        selected = None

            correct = (
                selected is not None
                and selected == answer["correct_option"]
            )

            if correct:
                score += 1

            cursor.execute("""
                UPDATE aptitude_attempt_answers
                SET selected_option=%s, is_correct=%s
                WHERE id=%s
            """, (
                selected, int(correct), answer["answer_row_id"]
            ))

        total = attempt["question_count"]
        percentage = round(score * 100 / total, 2) if total else 0

        elapsed = int(
            (now - attempt["started_at"]).total_seconds()
        )
        elapsed = max(0, min(elapsed, TEST_DURATION_MINUTES * 60))

        cursor.execute("""
            UPDATE aptitude_attempts
            SET score=%s, percentage=%s, submitted_at=%s,
                time_taken_seconds=%s, status='submitted'
            WHERE id=%s AND status='in_progress'
        """, (score, percentage, now, elapsed, test_id))

        connection.commit()

        return redirect(
            url_for("aptitude.aptitude_result", test_id=test_id)
        )

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        if getattr(exc, "code", None) == 404:
            raise

        print("APTITUDE SUBMIT ERROR:", exc)
        flash("Could not save your test. Please try again.")
        return redirect(url_for("aptitude.aptitude_arena"))

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@aptitude_bp.route("/aptitude/result/<int:test_id>")
def aptitude_result(test_id):
    connection = None
    cursor = None

    try:
        owner_user_id, guest_token = get_attempt_owner()
        connection = get_connection()

        if connection is None:
            raise RuntimeError("MySQL connection failed.")

        cursor = connection.cursor(dictionary=True)
        attempt = find_owned_attempt(
            cursor, test_id, owner_user_id, guest_token
        )

        if not attempt:
            abort(404)

        if attempt["status"] == "in_progress":
            return redirect(
                url_for("aptitude.aptitude_test", test_id=test_id)
            )

        cursor.execute("""
            SELECT q.question_text, q.options_json,
                   q.correct_option, q.explanation,
                   aa.selected_option, aa.is_correct
            FROM aptitude_attempt_answers aa
            JOIN aptitude_questions q ON q.id=aa.question_id
            WHERE aa.attempt_id=%s
            ORDER BY aa.id
        """, (test_id,))

        review = []
        correct_answers = 0

        for row in cursor.fetchall():
            options = json.loads(row["options_json"])
            selected = row["selected_option"]
            correct = row["correct_option"]
            is_correct = bool(row["is_correct"])

            if is_correct:
                correct_answers += 1

            review.append({
                "question_text": row["question_text"],
                "selected_answer": (
                    options[selected]
                    if selected is not None
                    and 0 <= selected < len(options)
                    else None
                ),
                "correct_answer": options[correct],
                "explanation": row["explanation"],
                "is_correct": is_correct,
            })

        total = attempt["question_count"]
        incorrect_answers = total - correct_answers

        minutes, seconds = divmod(
            attempt["time_taken_seconds"], 60
        )

        return render_template(
            "aptitude_result.html",
            score=attempt["score"],
            total_questions=total,
            percentage=float(attempt["percentage"]),
            correct_answers=correct_answers,
            incorrect_answers=incorrect_answers,
            time_taken_display=f"{minutes:02d}:{seconds:02d}",
            review=review,
        )

    except Exception as exc:
        if getattr(exc, "code", None) == 404:
            raise

        print("APTITUDE RESULT ERROR:", exc)
        flash("Could not load your result. Please try again.")
        return redirect(url_for("aptitude.aptitude_arena"))

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
