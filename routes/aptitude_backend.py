# ============================================================
# EDUVISION - APTITUDE ARENA BACKEND
# File: routes/aptitude_backend.py
# Flask + MySQL
# ============================================================

from datetime import datetime
from functools import wraps
import random
import time
import uuid

from flask import (
    Blueprint, current_app, flash, redirect,
    render_template, render_template_string,
    request, session, url_for
)

from jinja2 import TemplateNotFound
from mysql.connector import Error
from werkzeug.routing import BuildError


aptitude_bp = Blueprint("aptitude", __name__, url_prefix="/aptitude")

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

HOME_TEMPLATE = "aptitude_arena.html"   # optional custom template

QUESTION_COUNTS = [10, 20, 30]
DEFAULT_COUNT = 30
# Time allowed depends on the number of questions.
TEST_DURATIONS = {10: 15 * 60, 20: 25 * 60, 30: 30 * 60}
DEFAULT_DURATION = 30 * 60


def _duration_for(count):
    return TEST_DURATIONS.get(count, DEFAULT_DURATION)

CATEGORY_NAMES = {
    "quantitative": "Quantitative Aptitude",
    "logical": "Logical Reasoning",
    "verbal": "Verbal Ability",
}

# Session keys your login might use. The first one found is used.
LOGIN_SESSION_KEYS = (
    "user_id", "id", "uid", "student_id",
    "user", "email", "username", "user_name",
)


def _q(question, options, answer, explanation):
    return {"q": question, "options": options, "answer": answer, "why": explanation}


# ------------------------------------------------------------
# QUESTION BANK (30 per category)
# ------------------------------------------------------------

CATEGORIES = {

    "quantitative": {
        "title": "Quantitative Aptitude",
        "questions": [
            _q("What is 20% of 250?", ["40", "50", "60", "25"], 1, "20/100 × 250 = 50."),
            _q("A train travels at 60 km/h for 2.5 hours. Find the distance.", ["120 km", "150 km", "180 km", "135 km"], 1, "Distance = Speed × Time = 60 × 2.5 = 150 km."),
            _q("Two numbers are in the ratio 3:5. Their sum is 64. Find the larger number.", ["24", "32", "40", "44"], 2, "The larger number is 5/8 × 64 = 40."),
            _q("Find the next number: 2, 6, 12, 20, 30, ?", ["38", "40", "42", "44"], 2, "The differences are 4, 6, 8, 10 and 12. Answer = 42."),
            _q("Find the simple interest on ₹5000 at 8% for 2 years.", ["₹600", "₹800", "₹900", "₹1000"], 1, "SI = P × R × T / 100 = ₹800."),
            _q("What is 15% of 400?", ["40", "50", "60", "70"], 2, "15/100 × 400 = 60."),
            _q("A product costs ₹800. Its price increases by 10%. Find the new price.", ["₹840", "₹860", "₹880", "₹900"], 2, "10% of 800 = 80. New price = ₹880."),
            _q("Find the average of 10, 20, 30, 40 and 50.", ["25", "30", "35", "40"], 1, "Average = 150/5 = 30."),
            _q("If 5 pens cost ₹50, what is the cost of 8 pens?", ["₹60", "₹70", "₹80", "₹90"], 2, "One pen costs ₹10. Eight pens cost ₹80."),
            _q("What is the square root of 144?", ["10", "11", "12", "14"], 2, "12 × 12 = 144."),
            _q("A person buys an item for ₹500 and sells it for ₹600. Find the profit percentage.", ["10%", "15%", "20%", "25%"], 2, "Profit = 100. Profit percentage = 100/500 × 100 = 20%."),
            _q("Find the LCM of 12 and 18.", ["24", "30", "36", "48"], 2, "The smallest common multiple is 36."),
            _q("Find the HCF of 24 and 36.", ["6", "8", "12", "18"], 2, "The greatest common divisor of 24 and 36 is 12."),
            _q("A car covers 180 km in 3 hours. Find its speed.", ["50 km/h", "60 km/h", "70 km/h", "80 km/h"], 1, "Speed = 180/3 = 60 km/h."),
            _q("What is 3/4 of 200?", ["100", "125", "150", "175"], 2, "3/4 × 200 = 150."),
            _q("If x + 15 = 35, find x.", ["15", "20", "25", "30"], 1, "x = 35 - 15 = 20."),
            _q("Find the compound interest on ₹1000 at 10% annually for 2 years.", ["₹200", "₹210", "₹220", "₹250"], 1, "Amount = 1000 × 1.1 × 1.1 = 1210. CI = ₹210."),
            _q("A number is increased from 80 to 100. Find the percentage increase.", ["20%", "25%", "30%", "35%"], 1, "Increase = 20. Percentage = 20/80 × 100 = 25%."),
            _q("What is the value of 7 × 8 + 12?", ["56", "62", "68", "72"], 2, "7 × 8 + 12 = 56 + 12 = 68."),
            _q("A can complete a job in 10 days. How much work does A complete in one day?", ["1/5", "1/10", "1/15", "1/20"], 1, "One day's work = 1/10."),
            _q("Find the next number: 5, 10, 20, 40, ?", ["60", "70", "80", "100"], 2, "Each number is multiplied by 2. Answer = 80."),
            _q("Convert 0.75 into a percentage.", ["25%", "50%", "75%", "80%"], 2, "0.75 × 100 = 75%."),
            _q("What is the perimeter of a square with side 8 cm?", ["16 cm", "24 cm", "32 cm", "64 cm"], 2, "Perimeter = 4 × side = 32 cm."),
            _q("Find the area of a rectangle with length 12 cm and width 5 cm.", ["50 cm²", "55 cm²", "60 cm²", "65 cm²"], 2, "Area = length × width = 12 × 5 = 60 cm²."),
            _q("A shopkeeper gives a 10% discount on ₹1000. Find the selling price.", ["₹800", "₹850", "₹900", "₹950"], 2, "Discount = ₹100. Selling price = ₹900."),
            _q("Find the median of 3, 5, 7, 9, 11.", ["5", "7", "9", "11"], 1, "The middle value of the ordered data is 7."),
            _q("If 12 workers complete a task in 10 days, how many days will 6 workers take at the same rate?", ["5", "10", "15", "20"], 3, "Workers × Days = constant. 12 × 10 / 6 = 20 days."),
            _q("What is 2 raised to the power 5?", ["16", "24", "32", "64"], 2, "2 × 2 × 2 × 2 × 2 = 32."),
            _q("A bag contains 3 red and 2 blue balls. What is the probability of selecting a red ball?", ["1/5", "2/5", "3/5", "4/5"], 2, "Probability = favourable outcomes / total outcomes = 3/5."),
            _q("Find the next number: 1, 4, 9, 16, 25, ?", ["30", "32", "36", "49"], 2, "These are squares of 1, 2, 3, 4, 5. Next is 6² = 36."),
        ],
    },

    "logical": {
        "title": "Logical Reasoning",
        "questions": [
            _q("Find the next letter: A, C, F, J, ?", ["N", "O", "P", "M"], 1, "The gaps increase by 1: +2, +3, +4, +5. Answer O."),
            _q("Which is the odd one out?", ["Apple", "Banana", "Carrot", "Mango"], 2, "Carrot is a vegetable; the others are fruits."),
            _q("If CAT = 24 using letter positions, what is DOG?", ["24", "25", "26", "27"], 2, "D(4) + O(15) + G(7) = 26."),
            _q("Ali is taller than Ben. Ben is taller than Chi. Who is shortest?", ["Ali", "Ben", "Chi", "Cannot determine"], 2, "Ali > Ben > Chi. Therefore Chi is shortest."),
            _q("What is the angle between clock hands at 3:00?", ["60°", "90°", "120°", "180°"], 1, "Three hour divisions × 30° = 90°."),
            _q("Find the next number: 2, 4, 8, 16, ?", ["20", "24", "30", "32"], 3, "Each number is doubled. Answer = 32."),
            _q("If MONDAY is coded as NPOEBZ by shifting every letter forward by one, how is SUNDAY coded?", ["TVOEBZ", "RTMCZX", "TVOEBA", "TVNEBZ"], 0, "Each letter moves forward by one: SUNDAY becomes TVOEBZ."),
            _q("Which number does not belong?", ["4", "9", "16", "20"], 3, "4, 9 and 16 are perfect squares. 20 is not."),
            _q("Complete the series: 3, 6, 9, 12, ?", ["13", "14", "15", "18"], 2, "The sequence increases by 3. Answer = 15."),
            _q("If NORTH is opposite to SOUTH, EAST is opposite to:", ["WEST", "NORTH", "SOUTH", "NORTHEAST"], 0, "East and West are opposite directions."),
            _q("Find the odd pair.", ["2-4", "3-9", "4-16", "5-20"], 3, "The first three pairs contain a number and its square. 5² = 25, not 20."),
            _q("A is the brother of B. B is the sister of C. How is A related to C?", ["Brother", "Sister", "Father", "Cannot determine"], 0, "A is male and is the sibling of C, so A is C's brother."),
            _q("Find the next letter: Z, X, V, T, ?", ["R", "S", "Q", "P"], 0, "Letters move backward by two positions. Answer = R."),
            _q("If today is Monday, what day will it be after 10 days?", ["Wednesday", "Thursday", "Friday", "Saturday"], 1, "10 days = 7 + 3 days. Monday + 3 = Thursday."),
            _q("Which is different from the others?", ["Circle", "Triangle", "Square", "Cube"], 3, "Cube is a three-dimensional shape; the others are two-dimensional."),
            _q("Find the missing number: 5, 10, 15, 20, ?", ["22", "24", "25", "30"], 2, "The sequence increases by 5. Answer = 25."),
            _q("If all roses are flowers and some flowers fade quickly, which statement is definitely true?", ["All roses fade quickly", "All flowers are roses", "All roses are flowers", "No roses fade"], 2, "The first statement directly establishes that all roses are flowers."),
            _q("Arrange alphabetically: Mango, Apple, Banana, Orange. Which comes first?", ["Mango", "Apple", "Banana", "Orange"], 1, "Apple comes first alphabetically."),
            _q("Find the next number: 1, 1, 2, 3, 5, 8, ?", ["11", "12", "13", "15"], 2, "Each term is the sum of the previous two. 5 + 8 = 13."),
            _q("A person walks 5 km north and then 5 km south. Where is the person relative to the starting point?", ["5 km north", "5 km south", "Starting point", "10 km north"], 2, "The two movements cancel each other."),
            _q("Which word cannot be formed from the letters of EDUCATION?", ["ACTION", "DONATE", "CATION", "TEACHER"], 3, "EDUCATION does not contain H or R, required for TEACHER."),
            _q("Find the next number: 100, 90, 80, 70, ?", ["50", "55", "60", "65"], 2, "The series decreases by 10. Answer = 60."),
            _q("If 1 = 3, 2 = 6, 3 = 9, then 5 = ?", ["10", "12", "15", "18"], 2, "Each number is multiplied by 3. 5 × 3 = 15."),
            _q("Which month has 28 days?", ["February only", "January", "All months", "June"], 2, "Every month has at least 28 days."),
            _q("Find the odd one out.", ["Dog", "Cat", "Lion", "Eagle"], 3, "Eagle is a bird; the others are mammals."),
            _q("Complete the analogy: Book : Reading :: Fork : ?", ["Writing", "Eating", "Drawing", "Walking"], 1, "A book is used for reading; a fork is used for eating."),
            _q("If yesterday was Friday, what day is tomorrow?", ["Saturday", "Sunday", "Monday", "Thursday"], 1, "Yesterday Friday means today Saturday and tomorrow Sunday."),
            _q("Find the next number: 7, 14, 28, 56, ?", ["84", "98", "112", "120"], 2, "Each number is multiplied by 2. Answer = 112."),
            _q("A is older than B, and C is older than A. Who is the oldest?", ["A", "B", "C", "Cannot determine"], 2, "C > A > B. Therefore C is oldest."),
            _q("How many sides does a hexagon have?", ["5", "6", "7", "8"], 1, "A hexagon has six sides."),
        ],
    },

    "verbal": {
        "title": "Verbal Ability",
        "questions": [
            _q("Choose the synonym of 'Abundant'.", ["Rare", "Plentiful", "Tiny", "Weak"], 1, "Abundant means existing in large quantities, or plentiful."),
            _q("Choose the antonym of 'Expand'.", ["Grow", "Stretch", "Contract", "Increase"], 2, "Contract means to become smaller, the opposite of expand."),
            _q("She ___ to school every day.", ["go", "goes", "going", "gone"], 1, "A singular third-person subject takes 'goes' in the present simple."),
            _q("Choose the correct spelling.", ["Accomodate", "Acommodate", "Accommodate", "Acomodate"], 2, "Accommodate has a double c and a double m."),
            _q("A person who studies stars and planets is called:", ["Astrologer", "Astronomer", "Archaeologist", "Meteorologist"], 1, "Astronomers scientifically study celestial objects."),
            _q("Choose the synonym of 'Brave'.", ["Cowardly", "Courageous", "Weak", "Afraid"], 1, "Brave means courageous."),
            _q("Choose the antonym of 'Ancient'.", ["Old", "Historic", "Modern", "Traditional"], 2, "Modern is the opposite of ancient."),
            _q("They ___ playing cricket now.", ["is", "are", "was", "be"], 1, "The plural subject 'they' takes 'are'."),
            _q("Choose the correct article: He is ___ honest man.", ["a", "an", "the", "no article"], 1, "Honest begins with a vowel sound, so 'an' is correct."),
            _q("Choose the synonym of 'Rapid'.", ["Slow", "Fast", "Late", "Weak"], 1, "Rapid means fast or quick."),
            _q("Choose the antonym of 'Victory'.", ["Success", "Achievement", "Defeat", "Win"], 2, "Defeat is the opposite of victory."),
            _q("Identify the correctly spelled word.", ["Seperate", "Separate", "Seprate", "Separete"], 1, "The correct spelling is Separate."),
            _q("Neither Ravi nor his friends ___ present.", ["is", "was", "are", "has"], 2, "With neither...nor, the verb agrees with the nearer plural subject 'friends'."),
            _q("Choose the synonym of 'Diligent'.", ["Lazy", "Hardworking", "Careless", "Weak"], 1, "Diligent means hardworking and careful."),
            _q("Choose the antonym of 'Generous'.", ["Kind", "Helpful", "Selfish", "Friendly"], 2, "Selfish is the opposite of generous."),
            _q("Change to passive voice: 'She writes a letter.'", ["A letter is written by her.", "A letter was written by her.", "She is written a letter.", "A letter has written."], 0, "Present simple passive uses is/am/are + past participle."),
            _q("Choose the correct plural of 'Child'.", ["Childs", "Childes", "Children", "Childrens"], 2, "The irregular plural of child is children."),
            _q("Fill in the blank: I have been waiting ___ two hours.", ["since", "for", "from", "by"], 1, "For is used with a duration of time."),
            _q("Choose the synonym of 'Fragile'.", ["Strong", "Delicate", "Hard", "Heavy"], 1, "Fragile means easily broken or delicate."),
            _q("Choose the antonym of 'Accept'.", ["Receive", "Agree", "Reject", "Approve"], 2, "Reject is the opposite of accept."),
            _q("Identify the noun in this sentence: 'Honesty is the best policy.'", ["Best", "Honesty", "Is", "The"], 1, "Honesty is an abstract noun."),
            _q("Choose the correct sentence.", ["He do not like tea.", "He does not like tea.", "He not likes tea.", "He don't likes tea."], 1, "The correct third-person negative form is 'does not like'."),
            _q("What is the meaning of the idiom 'A piece of cake'?", ["A difficult task", "An easy task", "A food item", "A costly task"], 1, "A piece of cake means something very easy to do."),
            _q("Choose the synonym of 'Assist'.", ["Hinder", "Help", "Stop", "Avoid"], 1, "Assist means to help."),
            _q("Choose the antonym of 'Optimistic'.", ["Hopeful", "Positive", "Pessimistic", "Confident"], 2, "Pessimistic means expecting negative outcomes."),
            _q("Fill in the blank: The book is ___ the table.", ["in", "on", "at", "by"], 1, "On is used to indicate that something rests on a surface."),
            _q("Choose the correct past tense of 'Go'.", ["Goed", "Gone", "Went", "Going"], 2, "Went is the simple past tense of go."),
            _q("Choose the synonym of 'Commence'.", ["Finish", "Begin", "Close", "Stop"], 1, "Commence means to begin."),
            _q("Choose the correct indirect speech: He said, 'I am tired.'", ["He said that he was tired.", "He said that I am tired.", "He says he tired.", "He said that he is tiring."], 0, "In reported speech, present simple 'am' changes to past 'was' in this context."),
            _q("What is the plural of 'Mouse'?", ["Mouses", "Mices", "Mice", "Mouse"], 2, "The irregular plural of mouse is mice."),
        ],
    },
}


# ------------------------------------------------------------
# STABLE QUESTION IDS
# ------------------------------------------------------------

QUESTION_INDEX = {}

for _key, _data in CATEGORIES.items():
    for _i, _question in enumerate(_data["questions"], start=1):
        _qid = f"{_key}-{_i}"
        _question["id"] = _qid
        QUESTION_INDEX[_qid] = _question


# ------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------

def _db():
    getter = current_app.config.get("GET_DB_CONNECTION")

    if not callable(getter):
        current_app.logger.error("GET_DB_CONNECTION is not configured in Flask.")
        return None

    try:
        return getter()
    except Exception:
        current_app.logger.exception("Could not open database connection.")
        return None


_tables_ready = False


def _ensure_tables():
    """
    Create/prepare Aptitude history using EduVision's existing users.id INT
    and the existing aptitude_attempts column names. Never convert user_id
    to VARCHAR: it is a foreign key to users.id.
    """
    global _tables_ready

    if _tables_ready:
        return

    connection = _db()
    if connection is None:
        return

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS aptitude_attempts (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                attempt_token VARCHAR(100) NOT NULL,
                user_id INT NULL,
                guest_token VARCHAR(100) NULL,
                category VARCHAR(30) NOT NULL,
                question_count INT NOT NULL,
                started_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                submitted_at DATETIME NULL,
                score INT NOT NULL DEFAULT 0,
                percentage DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                time_taken_seconds INT NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_aptitude_attempt_token (attempt_token),
                KEY idx_aptitude_user (user_id, created_at),
                KEY idx_aptitude_guest (guest_token),
                CONSTRAINT fk_aptitude_attempt_user
                    FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'aptitude_attempts'
        """)
        columns = {
            str(row[0]).lower(): str(row[1]).lower()
            for row in cursor.fetchall()
        }

        # user_id must match users.id (INT). Do not change it to VARCHAR.
        if columns.get("user_id") not in ("int", "integer"):
            raise RuntimeError(
                "aptitude_attempts.user_id must match users.id (INT). "
                "No automatic type conversion was attempted."
            )

        # Add the token to older tables without deleting existing attempts.
        if "attempt_token" not in columns:
            cursor.execute("""
                ALTER TABLE aptitude_attempts
                ADD COLUMN attempt_token VARCHAR(100) NULL
            """)
            cursor.execute("""
                UPDATE aptitude_attempts
                SET attempt_token = REPLACE(UUID(), '-', '')
                WHERE attempt_token IS NULL
            """)
            cursor.execute("""
                ALTER TABLE aptitude_attempts
                MODIFY attempt_token VARCHAR(100) NOT NULL
            """)
            cursor.execute("""
                ALTER TABLE aptitude_attempts
                ADD UNIQUE KEY uq_aptitude_attempt_token (attempt_token)
            """)
            columns["attempt_token"] = "varchar"

        required = {
            "question_count", "started_at", "expires_at", "submitted_at",
            "score", "percentage", "time_taken_seconds", "status",
            "created_at", "attempt_token", "user_id", "category"
        }
        missing = required.difference(columns.keys())
        if missing:
            raise RuntimeError(
                "aptitude_attempts is missing required columns: "
                + ", ".join(sorted(missing))
            )

        connection.commit()
        _tables_ready = True

    except Exception:
        connection.rollback()
        current_app.logger.exception(
            "Could not prepare aptitude_attempts table."
        )

    finally:
        if cursor:
            cursor.close()
        connection.close()


# ------------------------------------------------------------
# LOGIN (works with any common session key)
# ------------------------------------------------------------

def _current_user_id():
    """Return an identifier for the logged-in user, or None."""

    for key in LOGIN_SESSION_KEYS:
        value = session.get(key)

        if isinstance(value, dict):
            value = value.get("id") or value.get("email")

        if value not in (None, ""):
            return str(value)

    return None


def _safe_url(endpoints, fallback="/", **values):
    """First endpoint that exists, otherwise the fallback path."""

    for endpoint in endpoints:
        try:
            return url_for(endpoint, **values)
        except BuildError:
            continue

    return fallback


def _login_redirect():
    return redirect(
        _safe_url(("login", "auth.login", "index"), "/", next=request.path)
    )


def aptitude_login_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        if _current_user_id() is None:
            current_app.logger.warning(
                "Aptitude: no login found in session. Keys: %s",
                list(session.keys())
            )
            flash("Please log in to continue.", "warning")
            return _login_redirect()

        return view(*args, **kwargs)

    return wrapped


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def _category_title(category):
    if category == "all":
        return "All Categories"
    return CATEGORIES.get(category, {}).get("title", category)


def _render(template, **context):
    """Render a built-in template with shared values."""

    context.setdefault("css", BASE_CSS)
    context["dashboard_url"] = _safe_url(("dashboard",), "/")

    return render_template_string(template, **context)


def _get_csrf_token():
    token = session.get("aptitude_csrf")

    if not token:
        token = uuid.uuid4().hex
        session["aptitude_csrf"] = token

    return token


# ------------------------------------------------------------
# PROGRESS
# ------------------------------------------------------------

def _as_database_user_id(user_id):
    """Convert the logged-in session ID to the INT used by users.id."""
    try:
        value = int(user_id)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def _load_progress(user_id):
    stats = {"attempts": 0, "best": 0, "average": 0, "recent": []}
    db_user_id = _as_database_user_id(user_id)

    if db_user_id is None:
        return stats

    connection = _db()
    if connection is None:
        return stats

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                COUNT(*) AS attempts,
                COALESCE(MAX(percentage), 0) AS best,
                COALESCE(ROUND(AVG(percentage)), 0) AS average
            FROM aptitude_attempts
            WHERE user_id = %s AND status = 'completed'
        """, (db_user_id,))

        row = cursor.fetchone() or {}
        stats["attempts"] = int(row.get("attempts") or 0)
        stats["best"] = int(round(float(row.get("best") or 0)))
        stats["average"] = int(round(float(row.get("average") or 0)))

        cursor.execute("""
            SELECT
                category,
                score AS correct,
                question_count AS total,
                percentage AS score_pct,
                time_taken_seconds AS seconds,
                created_at
            FROM aptitude_attempts
            WHERE user_id = %s AND status = 'completed'
            ORDER BY created_at DESC
            LIMIT 20
        """, (db_user_id,))

        for row in cursor.fetchall():
            created_at = row["created_at"]
            stats["recent"].append({
                "category": _category_title(row["category"]),
                "correct": int(row["correct"] or 0),
                "total": int(row["total"] or 0),
                "score_pct": float(row["score_pct"] or 0),
                "seconds": int(row["seconds"] or 0),
                "date": (
                    created_at.strftime("%d %b %Y, %H:%M")
                    if created_at else ""
                ),
            })

    except Error:
        current_app.logger.exception("Could not load aptitude progress.")

    finally:
        if cursor:
            cursor.close()
        connection.close()

    return stats


def _save_attempt(
    user_id, attempt_token, category, correct, total, score_pct, seconds,
    started_at, expires_at
):
    db_user_id = _as_database_user_id(user_id)
    if db_user_id is None:
        current_app.logger.error(
            "Aptitude result was not saved: session user ID is not a numeric users.id."
        )
        return False

    connection = _db()
    if connection is None:
        return False

    cursor = None
    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO aptitude_attempts (
                attempt_token,
                user_id,
                category,
                question_count,
                started_at,
                expires_at,
                submitted_at,
                score,
                percentage,
                time_taken_seconds,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'completed')
            ON DUPLICATE KEY UPDATE
                attempt_token = VALUES(attempt_token)
        """, (
            attempt_token,
            db_user_id,
            category,
            total,
            started_at,
            expires_at,
            datetime.now(),
            correct,
            score_pct,
            seconds,
        ))

        connection.commit()
        return True

    except Error:
        connection.rollback()
        current_app.logger.exception("Could not save aptitude attempt.")
        return False

    finally:
        if cursor:
            cursor.close()
        connection.close()


# ------------------------------------------------------------
# STYLING
# ------------------------------------------------------------

BASE_CSS = """
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, sans-serif; background: #f4f6fb; color: #182033; }
header { background: white; padding: 16px 5%; display: flex; justify-content: space-between;
         align-items: center; flex-wrap: wrap; gap: 12px; box-shadow: 0 2px 12px #18203314; }
.logo { color: #5546e8; font-size: 18px; font-weight: 800; }
nav a { color: #5546e8; text-decoration: none; margin-left: 16px; font-weight: 600; }
main { max-width: 900px; margin: 30px auto; padding: 0 18px; }
.card { background: white; padding: 24px; margin-bottom: 18px; border-radius: 16px;
        box-shadow: 0 8px 28px #1820330f; }
.btn { border: 0; border-radius: 10px; padding: 12px 20px; background: #5546e8; color: white;
       font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; }
.btn.alt { background: #eef0ff; color: #4435c7; }
.btn:disabled { opacity: .4; cursor: not-allowed; }
.sub { color: #687187; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.timer { font-size: 25px; font-weight: 800; color: #5546e8; }
.timer.danger { color: #df3434; }
.big { font-size: 44px; font-weight: 800; color: #5546e8; }
label.opt { display: block; padding: 13px; margin: 9px 0; border: 1px solid #dce0eb;
            border-radius: 10px; cursor: pointer; }
label.opt:hover { border-color: #5546e8; }
label.opt input { margin-right: 10px; }
.opt.right { background: #e7f8ee; border-color: #2e9e5b; }
.opt.wrong { background: #fdecec; border-color: #d64545; }
.why { background: #f5f5ff; padding: 12px; border-radius: 9px; margin-top: 12px; color: #505a70; }
.stats { display: flex; gap: 14px; flex-wrap: wrap; }
.stat { flex: 1; min-width: 120px; text-align: center; }
.stat b { display: block; font-size: 28px; color: #5546e8; }
.progress-track { height: 8px; background: #e7e8f1; border-radius: 20px; overflow: hidden; margin: 15px 0; }
.progress-fill { height: 100%; background: #5546e8; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 12px; border-bottom: 1px solid #eceff6; }
th { background: #f2f0ff; }
.flash { background: #f2f0ff; padding: 12px; border-radius: 8px; margin-bottom: 12px; }
@media (max-width: 600px) {
    .card { padding: 17px; }
    nav a { margin-left: 7px; font-size: 13px; }
    table { font-size: 12px; }
}
"""

_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} | EduVision</title>
<style>
{{ css|safe }}
header.site-header { background: #fff; padding: 0; display: block; box-shadow: 0 2px 14px #1820330f; }
.nav-inner { max-width: 1120px; margin: 0 auto; padding: 14px 18px; display: flex;
             align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 10px; font-size: 20px; font-weight: 800;
         color: #182033; text-decoration: none; }
.brand span.dim { color: #5546e8; }
.brand-mark { width: 36px; height: 36px; border-radius: 10px; background: #5546e8; color: #fff;
              display: grid; place-items: center; font-weight: 800; }
.menu { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.menu a { margin: 0; padding: 9px 16px; border-radius: 10px; color: #4a5268; font-weight: 600;
          text-decoration: none; font-size: 15px; }
.menu a:hover { background: #f1efff; color: #5546e8; }
.menu a.pill { background: #5546e8; color: #fff; }
.menu a.pill:hover { background: #4435c7; color: #fff; }
.site-footer { max-width: 1120px; margin: 50px auto 0; padding: 26px 18px; display: flex;
               justify-content: space-between; flex-wrap: wrap; gap: 8px; color: #687187;
               font-size: 14px; border-top: 1px solid #e3e6f0; }
</style>
</head>

<body>

<header class="site-header">
    <div class="nav-inner">
        <a class="brand" href="{{ dashboard_url }}">
            <span class="brand-mark">E</span>
            <span>Edu<span class="dim">Vision</span></span>
        </a>
        <nav class="menu">
            <a href="{{ url_for('aptitude.aptitude_home') }}">Aptitude Arena</a>
            <a href="{{ url_for('aptitude.aptitude_progress') }}">My Progress</a>
            <a class="pill" href="{{ dashboard_url }}">Dashboard</a>
        </nav>
    </div>
</header>

<main>

{% with messages = get_flashed_messages() %}
    {% for message in messages %}
        <div class="flash">{{ message }}</div>
    {% endfor %}
{% endwith %}
"""

_FOOT = """
</main>

<footer class="site-footer">
    <div>© 2026 EduVision · Aptitude Arena</div>
    <div>Practise daily. Perform better.</div>
</footer>

</body>
</html>
"""


# ------------------------------------------------------------
# HOME PAGE (built-in, used if templates/aptitude_arena.html is missing)
# ------------------------------------------------------------

CATEGORY_INFO = {
    "quantitative": {
        "icon": "🔢",
        "desc": "Percentages, profit and loss, time and work, number systems and maths problems.",
    },
    "logical": {
        "icon": "🧩",
        "desc": "Puzzles, series, coding-decoding, blood relations and patterns.",
    },
    "verbal": {
        "icon": "📖",
        "desc": "Grammar, vocabulary, synonyms, antonyms and sentence correction.",
    },
}

COUNT_LABELS = {10: "Quick Practice", 20: "Standard Practice", 30: "Full Test"}


HOME_HTML = _HEAD + """
<style>
main { max-width: 1120px; }
html { scroll-behavior: smooth; }

/* ---------- hero ---------- */
.hero { display: grid; grid-template-columns: 1.4fr 1fr; gap: 32px; align-items: center;
        background: linear-gradient(135deg, #4a3bdc 0%, #7c5cff 100%); color: #fff;
        border-radius: 24px; padding: 48px; margin-bottom: 36px; position: relative; overflow: hidden; }
.hero::after { content: ""; position: absolute; right: -80px; top: -80px; width: 280px; height: 280px;
               border-radius: 50%; background: #ffffff14; }
.eyebrow { display: inline-block; font-size: 12px; font-weight: 800; letter-spacing: 1.5px;
           background: #ffffff26; padding: 6px 14px; border-radius: 20px; }
.hero h1 { font-size: 44px; line-height: 1.15; margin: 18px 0 14px; }
.hero p { color: #e9e6ff; font-size: 17px; line-height: 1.7; margin: 0 0 26px; max-width: 520px; }
.hero-btns { display: flex; gap: 12px; flex-wrap: wrap; }
.cta { background: #fff; color: #4435c7; padding: 14px 26px; border-radius: 12px; font-size: 16px; }
.cta:hover { background: #f1efff; }
.ghost { background: #ffffff26; color: #fff; padding: 14px 26px; border-radius: 12px; font-size: 16px; }
.ghost:hover { background: #ffffff3d; }
.stat-card { background: #ffffff1f; border: 1px solid #ffffff33; border-radius: 20px; padding: 24px;
             position: relative; z-index: 1; }
.stat-card h3 { margin: 0 0 14px; font-size: 16px; color: #e9e6ff; }
.stat-line { display: flex; justify-content: space-between; align-items: center; padding: 12px 0;
             border-bottom: 1px solid #ffffff26; }
.stat-line:last-child { border-bottom: 0; }
.stat-line b { font-size: 26px; }
.stat-line span { color: #e9e6ff; }

/* ---------- sections ---------- */
.section-title { text-align: center; margin: 44px 0 8px; font-size: 30px; }
.section-sub { text-align: center; color: #687187; margin: 0 auto 26px; max-width: 560px; line-height: 1.6; }
.steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; }
.step { background: #fff; border-radius: 18px; padding: 26px; box-shadow: 0 8px 28px #1820330f; }
.step .n { width: 40px; height: 40px; border-radius: 12px; background: #efecff; color: #5546e8;
           display: grid; place-items: center; font-weight: 800; margin-bottom: 14px; }
.step h3 { margin: 0 0 6px; }
.step p { margin: 0; color: #687187; line-height: 1.6; font-size: 15px; }

.cat-grid, .cnt-grid { display: grid; gap: 18px; }
.cat-grid { grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
.cnt-grid { grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
.pick { position: relative; display: block; cursor: pointer; }
.pick input { position: absolute; opacity: 0; pointer-events: none; }
.pick-body { height: 100%; background: #fff; border: 2px solid #e3e6f0; border-radius: 18px;
             padding: 24px; transition: all .15s ease; }
.pick:hover .pick-body { border-color: #b9b1ff; transform: translateY(-3px); box-shadow: 0 12px 30px #5546e81a; }
.pick input:checked + .pick-body { border-color: #5546e8; background: #f6f4ff; box-shadow: 0 0 0 4px #5546e81f; }
.pick input:focus-visible + .pick-body { outline: 3px solid #5546e855; }
.icon { width: 56px; height: 56px; display: grid; place-items: center; font-size: 28px;
        background: #efecff; border-radius: 16px; margin-bottom: 16px; }
.pick h3 { margin: 0 0 8px; font-size: 19px; }
.pick p { margin: 0 0 16px; color: #687187; font-size: 14px; line-height: 1.6; }
.tick { font-weight: 800; font-size: 14px; }
.tick::before { content: "Select category →"; color: #8b86b8; }
.pick input:checked + .pick-body .tick::before { content: "✓ Selected"; color: #5546e8; }
.cnt-body { text-align: center; }
.cnt-body .num { font-size: 40px; font-weight: 800; color: #5546e8; line-height: 1; }
.cnt-body .lbl { color: #687187; font-size: 14px; margin: 6px 0 12px; }
.cnt-body .mins { display: inline-block; background: #eef0ff; color: #4435c7; font-size: 13px;
                  font-weight: 700; padding: 5px 14px; border-radius: 20px; }

/* ---------- time table ---------- */
.table-card { padding: 0; overflow: hidden; margin-top: 22px; }
.table-card h3 { margin: 0; padding: 20px 24px 6px; }
.table-card .sub { margin: 0; padding: 0 24px 14px; font-size: 14px; }
.time-table th { background: #5546e8; color: #fff; font-size: 14px; padding: 14px 24px; }
.time-table td { padding: 16px 24px; font-size: 16px; }
.time-table tbody tr { transition: background .15s; }
.time-table tbody tr.on { background: #f3f1ff; }
.time-table tbody tr.on td { font-weight: 700; color: #4435c7; }

/* ---------- summary ---------- */
.info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-top: 18px; }
.info { background: #f6f4ff; border-radius: 14px; padding: 16px 18px; }
.info b { display: block; margin-bottom: 4px; }
.info span { color: #505a70; font-size: 14px; }
.rules { margin: 18px 0 0; padding-left: 20px; color: #505a70; line-height: 1.9; font-size: 14px; }
.start-btn { width: 100%; margin-top: 24px; padding: 18px; font-size: 18px; border-radius: 14px; }
.start-btn:hover { background: #4435c7; }

.features { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 18px; margin-top: 8px; }
.feature { text-align: center; padding: 10px; }
.feature .fi { font-size: 34px; }
.feature h4 { margin: 8px 0 4px; }
.feature p { margin: 0; color: #687187; font-size: 14px; line-height: 1.6; }

@media (max-width: 820px) {
    .hero { grid-template-columns: 1fr; padding: 30px 24px; }
    .hero h1 { font-size: 32px; }
}
</style>

<section class="hero">
    <div style="position:relative;z-index:1">
        <span class="eyebrow">PLACEMENT PREPARATION</span>
        <h1>Practise. Test.<br>Improve every day.</h1>
        <p>Welcome back, {{ user_name }}! Take timed aptitude tests in a real exam-style
           environment and learn from a clear explanation for every answer.</p>
        <div class="hero-btns">
            <a class="btn cta" href="#start">Start a test →</a>
            <a class="btn ghost" href="{{ url_for('aptitude.aptitude_progress') }}">My progress</a>
        </div>
    </div>

    <div class="stat-card">
        <h3>YOUR PROGRESS</h3>
        <div class="stat-line"><span>Tests taken</span><b>{{ stats.attempts }}</b></div>
        <div class="stat-line"><span>Best score</span><b>{{ stats.best }}%</b></div>
        <div class="stat-line"><span>Average score</span><b>{{ stats.average }}%</b></div>
    </div>
</section>

<h2 class="section-title">How it works</h2>
<p class="section-sub">Three simple steps to build speed and accuracy for your placement rounds.</p>

<div class="steps">
    <div class="step"><div class="n">1</div><h3>Choose a subject</h3>
        <p>Pick Quantitative, Logical or Verbal, or take a mixed test of everything.</p></div>
    <div class="step"><div class="n">2</div><h3>Take a timed test</h3>
        <p>Answer multiple-choice questions against the clock, just like the real exam.</p></div>
    <div class="step"><div class="n">3</div><h3>Review and improve</h3>
        <p>See every correct answer with an explanation and track your scores over time.</p></div>
</div>

<form method="POST" action="{{ url_for('aptitude.aptitude_start') }}" id="start">

    <h2 class="section-title">Choose Your Category</h2>
    <p class="section-sub">Select a subject to begin your aptitude practice.</p>

    <div class="cat-grid">

        {% for key, name in categories.items() %}
        <label class="pick">
            <input type="radio" name="category" value="{{ key }}" {% if loop.first %}checked{% endif %}>
            <div class="pick-body">
                <div class="icon">{{ category_info[key].icon }}</div>
                <h3>{{ name }}</h3>
                <p>{{ category_info[key].desc }}</p>
                <span class="tick"></span>
            </div>
        </label>
        {% endfor %}

        <label class="pick">
            <input type="radio" name="category" value="all">
            <div class="pick-body">
                <div class="icon">🎯</div>
                <h3>All Categories</h3>
                <p>A mixed test with questions from every subject, like a real placement exam.</p>
                <span class="tick"></span>
            </div>
        </label>

    </div>

    <h2 class="section-title">Configure Your Test</h2>
    <p class="section-sub">Choose the number of questions. The time limit is set automatically.</p>

    <div class="cnt-grid">
        {% for count in question_counts %}
        <label class="pick">
            <input type="radio" name="question_count" value="{{ count }}"
                   data-min="{{ durations[count] // 60 }}"
                   {% if count == default_count %}checked{% endif %}>
            <div class="pick-body cnt-body">
                <div class="num">{{ count }}</div>
                <div class="lbl">{{ count_labels[count] }}</div>
                <span class="mins">⏱ {{ durations[count] // 60 }} minutes</span>
            </div>
        </label>
        {% endfor %}
    </div>

    <div class="card table-card">
        <h3>⏱ Time allowed</h3>
        <p class="sub">The more questions you choose, the more time you get.</p>

        <table class="time-table">
            <thead>
                <tr><th>Questions</th><th>Time</th><th>Test type</th></tr>
            </thead>
            <tbody>
                {% for count in question_counts %}
                <tr data-count="{{ count }}">
                    <td>{{ count }}</td>
                    <td>{{ durations[count] // 60 }} minutes</td>
                    <td>{{ count_labels[count] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="card" style="margin-top:22px;padding:28px">
        <h3 style="margin:0;font-size:20px">Test Summary</h3>

        <div class="info-grid">
            <div class="info"><b>⏱ Test Duration</b><span id="durText">30 minutes</span></div>
            <div class="info"><b>📝 Test Type</b><span id="qText">30 multiple-choice questions</span></div>
            <div class="info"><b>🎯 Marking</b><span>1 mark each, no negative marking</span></div>
        </div>

        <ul class="rules">
            <li>Move between questions freely using the question palette.</li>
            <li>Use <b>Mark for Review</b> for questions you want to revisit.</li>
            <li>The test is submitted automatically when the timer reaches zero.</li>
            <li>Do not refresh or close the page during the test.</li>
        </ul>

        <button class="btn start-btn" type="submit">Start Test →</button>
    </div>

</form>

<h2 class="section-title">Why practise here?</h2>
<div class="features">
    <div class="feature"><div class="fi">🧠</div><h4>90 curated questions</h4>
        <p>Core placement topics across three sections.</p></div>
    <div class="feature"><div class="fi">💡</div><h4>Instant explanations</h4>
        <p>Learn the method behind every answer.</p></div>
    <div class="feature"><div class="fi">📈</div><h4>Track your growth</h4>
        <p>Your scores are saved so you can see improvement.</p></div>
    <div class="feature"><div class="fi">⏱</div><h4>Real exam feel</h4>
        <p>Timer, question palette and review marking.</p></div>
</div>

<script>
(function () {
    var radios = document.querySelectorAll('input[name="question_count"]');
    var rows = document.querySelectorAll(".time-table tbody tr");

    function update() {
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].checked) {
                document.getElementById("durText").textContent =
                    radios[i].getAttribute("data-min") + " minutes";
                document.getElementById("qText").textContent =
                    radios[i].value + " multiple-choice questions";
                for (var r = 0; r < rows.length; r++) {
                    rows[r].classList.toggle("on", rows[r].getAttribute("data-count") === radios[i].value);
                }
            }
        }
    }

    for (var i = 0; i < radios.length; i++) {
        radios[i].addEventListener("change", update);
    }

    update();
})();
</script>
""" + _FOOT


# ------------------------------------------------------------
# TEST PAGE (exam style)
# GET /aptitude/test
# ------------------------------------------------------------

TEST_HTML = _HEAD + """
<style>
main { max-width: 1150px; }
.exam-top { position: sticky; top: 0; z-index: 20; }
.timer-box { text-align: right; }
.timer { font-variant-numeric: tabular-nums; }
.timer.warn { color: #e08a00; }
.layout { display: grid; grid-template-columns: 1fr 300px; gap: 18px; align-items: start; }
.qhead { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.qnum { font-weight: 800; color: #5546e8; }
.flag { display: none; background: #fff4de; color: #b86e00; font-size: 12px; font-weight: 700;
        padding: 4px 10px; border-radius: 20px; }
.qbox.is-marked .flag { display: inline-block; }
.qtext { font-size: 20px; line-height: 1.5; margin: 8px 0 18px; }
.choice { display: flex; align-items: center; gap: 14px; padding: 14px; margin: 10px 0;
          border: 2px solid #e3e6f0; border-radius: 12px; cursor: pointer; transition: all .12s ease; }
.choice:hover { border-color: #b9b1ff; background: #faf9ff; }
.choice input { display: none; }
.choice .letter { width: 32px; height: 32px; flex: none; display: grid; place-items: center;
                  border-radius: 50%; background: #eef0ff; color: #4435c7; font-weight: 800; }
.choice.sel { border-color: #5546e8; background: #f3f1ff; }
.choice.sel .letter { background: #5546e8; color: #fff; }
.actions .group { display: flex; gap: 10px; flex-wrap: wrap; }
.btn.warn { background: #fff4de; color: #a86200; }
.btn.danger { background: #d64545; }
.btn.full { width: 100%; margin-top: 14px; }
.palette { position: sticky; top: 96px; }
.palette h3 { margin: 0 0 12px; }
.pgrid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
.pbtn { height: 42px; border: 2px solid transparent; border-radius: 10px; background: #e7e8f1;
        color: #3a4258; font-weight: 700; cursor: pointer; position: relative; }
.pbtn.visited { background: #fde8e8; color: #b42d2d; }
.pbtn.answered { background: #e1f5e9; color: #1f7a45; }
.pbtn.marked::after { content: ""; position: absolute; top: 4px; right: 4px; width: 9px; height: 9px;
                      border-radius: 50%; background: #f59e0b; }
.pbtn.current { border-color: #5546e8; box-shadow: 0 0 0 3px #5546e826; }
.legend { margin-top: 16px; display: grid; gap: 8px; font-size: 13px; color: #505a70; }
.legend div { display: flex; align-items: center; gap: 8px; }
.dot { width: 14px; height: 14px; border-radius: 4px; display: inline-block; }
.modal { position: fixed; inset: 0; background: #11182766; display: none; place-items: center;
         z-index: 50; padding: 18px; }
.modal.open { display: grid; }
.modal-card { background: #fff; border-radius: 18px; padding: 28px; width: 100%; max-width: 440px; }
.modal-card h2 { margin-top: 0; }
.sum-row { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #eceff6; }
@media (max-width: 860px) {
    .layout { grid-template-columns: 1fr; }
    .palette { position: static; }
    .qtext { font-size: 18px; }
}
</style>

<div class="card row exam-top">
    <div>
        <h2 style="margin:0">{{ title_text }}</h2>
        <div class="sub">{{ questions|length }} questions · {{ minutes }} minutes</div>
    </div>
    <div class="timer-box">
        <small class="sub">Time remaining</small>
        <div class="timer" id="timer">--:--</div>
    </div>
</div>

<form id="testForm" method="POST" action="{{ url_for('aptitude.aptitude_submit') }}">

    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">

    <div class="layout">

        <div>
            {% for q in questions %}
            <div class="card qbox" data-index="{{ loop.index0 }}" {% if not loop.first %}style="display:none"{% endif %}>

                <div class="qhead">
                    <span class="qnum">Question {{ loop.index }} of {{ questions|length }}</span>
                    <span class="flag">⚑ Marked for review</span>
                </div>

                <h3 class="qtext">{{ q.q }}</h3>

                {% for option in q.options %}
                <label class="choice">
                    <input type="radio" name="{{ q.id }}" value="{{ loop.index0 }}">
                    <span class="letter">{{ 'ABCD'[loop.index0] }}</span>
                    <span>{{ option }}</span>
                </label>
                {% endfor %}

            </div>
            {% endfor %}

            <div class="card row actions">
                <div class="group">
                    <button type="button" class="btn alt" id="prev">← Previous</button>
                    <button type="button" class="btn alt" id="clear">Clear Response</button>
                </div>
                <div class="group">
                    <button type="button" class="btn warn" id="mark">⚑ Mark for Review</button>
                    <button type="button" class="btn" id="next">Save &amp; Next →</button>
                </div>
            </div>
        </div>

        <aside class="card palette">
            <h3>Question Palette</h3>

            <div class="pgrid">
                {% for q in questions %}
                <button type="button" class="pbtn" data-i="{{ loop.index0 }}">{{ loop.index }}</button>
                {% endfor %}
            </div>

            <div class="legend">
                <div><span class="dot" style="background:#e1f5e9"></span> Answered: <b id="cAns">0</b></div>
                <div><span class="dot" style="background:#fde8e8"></span> Not answered: <b id="cNot">0</b></div>
                <div><span class="dot" style="background:#e7e8f1"></span> Not visited: <b id="cUnv">0</b></div>
                <div><span class="dot" style="background:#f59e0b;border-radius:50%"></span> Marked for review: <b id="cMark">0</b></div>
            </div>

            <button type="button" class="btn full" id="openSubmit">Submit Test</button>
        </aside>

    </div>

    <div class="modal" id="modal">
        <div class="modal-card">
            <h2>Submit your test?</h2>
            <div class="sum-row"><span>Answered</span><b id="mAns">0</b></div>
            <div class="sum-row"><span>Not answered</span><b id="mNot">0</b></div>
            <div class="sum-row"><span>Marked for review</span><b id="mMark">0</b></div>
            <p class="sub">You cannot change your answers after submitting.</p>
            <div class="row">
                <button type="button" class="btn alt" id="cancelSubmit">Go back</button>
                <button type="button" class="btn danger" id="confirmSubmit">Yes, submit</button>
            </div>
        </div>
    </div>

</form>

<script>
(function () {
    var boxes = Array.prototype.slice.call(document.querySelectorAll(".qbox"));
    var pbtns = Array.prototype.slice.call(document.querySelectorAll(".pbtn"));
    var form = document.getElementById("testForm");
    var prev = document.getElementById("prev");
    var next = document.getElementById("next");
    var clearBtn = document.getElementById("clear");
    var markBtn = document.getElementById("mark");
    var modal = document.getElementById("modal");
    var timerEl = document.getElementById("timer");

    var marked = {};
    var visited = {};
    var current = 0;
    var submitted = false;

    function isAnswered(i) {
        return !!boxes[i].querySelector("input:checked");
    }

    function counts() {
        var a = 0, m = 0, n = 0, u = 0;
        for (var i = 0; i < boxes.length; i++) {
            if (marked[i]) m++;
            if (isAnswered(i)) a++;
            else if (visited[i]) n++;
            else u++;
        }
        return { ans: a, not: n, unv: u, mark: m };
    }

    function refresh() {
        for (var i = 0; i < pbtns.length; i++) {
            var cls = "pbtn";
            if (isAnswered(i)) cls += " answered";
            else if (visited[i]) cls += " visited";
            if (marked[i]) cls += " marked";
            if (i === current) cls += " current";
            pbtns[i].className = cls;
            boxes[i].classList.toggle("is-marked", !!marked[i]);
        }
        var c = counts();
        document.getElementById("cAns").textContent = c.ans;
        document.getElementById("cNot").textContent = c.not;
        document.getElementById("cUnv").textContent = c.unv;
        document.getElementById("cMark").textContent = c.mark;
        markBtn.textContent = marked[current] ? "⚑ Unmark Review" : "⚑ Mark for Review";
    }

    function show(index) {
        current = index;
        visited[index] = true;
        for (var i = 0; i < boxes.length; i++) {
            boxes[i].style.display = (i === index) ? "block" : "none";
        }
        prev.disabled = (index === 0);
        next.textContent = (index === boxes.length - 1) ? "Save & Finish" : "Save & Next →";
        refresh();
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function openModal() {
        var c = counts();
        document.getElementById("mAns").textContent = c.ans + " / " + boxes.length;
        document.getElementById("mNot").textContent = boxes.length - c.ans;
        document.getElementById("mMark").textContent = c.mark;
        modal.classList.add("open");
    }

    function submitNow() {
        if (submitted) return;
        submitted = true;
        form.submit();
    }

    // Highlight the chosen option.
    for (var b = 0; b < boxes.length; b++) {
        (function (box) {
            var inputs = box.querySelectorAll("input[type=radio]");
            for (var k = 0; k < inputs.length; k++) {
                inputs[k].addEventListener("change", function () {
                    var labels = box.querySelectorAll(".choice");
                    for (var l = 0; l < labels.length; l++) {
                        labels[l].classList.toggle("sel", labels[l].querySelector("input").checked);
                    }
                    refresh();
                });
            }
        })(boxes[b]);
    }

    for (var p = 0; p < pbtns.length; p++) {
        pbtns[p].addEventListener("click", function () {
            show(parseInt(this.getAttribute("data-i"), 10));
        });
    }

    prev.addEventListener("click", function () { if (current > 0) show(current - 1); });

    next.addEventListener("click", function () {
        if (current < boxes.length - 1) show(current + 1);
        else openModal();
    });

    clearBtn.addEventListener("click", function () {
        var inputs = boxes[current].querySelectorAll("input[type=radio]");
        for (var i = 0; i < inputs.length; i++) inputs[i].checked = false;
        var labels = boxes[current].querySelectorAll(".choice");
        for (var j = 0; j < labels.length; j++) labels[j].classList.remove("sel");
        refresh();
    });

    markBtn.addEventListener("click", function () {
        marked[current] = !marked[current];
        refresh();
        if (marked[current] && current < boxes.length - 1) show(current + 1);
    });

    document.getElementById("openSubmit").addEventListener("click", openModal);
    document.getElementById("cancelSubmit").addEventListener("click", function () {
        modal.classList.remove("open");
    });
    document.getElementById("confirmSubmit").addEventListener("click", submitNow);

    // TIMER (based on the real clock so it stays accurate)
    var endAt = Date.now() + {{ remaining }} * 1000;

    function tick() {
        var left = Math.max(0, Math.round((endAt - Date.now()) / 1000));
        var m = Math.floor(left / 60);
        var s = left % 60;
        timerEl.textContent = (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;

        timerEl.classList.toggle("warn", left <= 300 && left > 60);
        timerEl.classList.toggle("danger", left <= 60);

        if (left <= 0) {
            submitNow();
            return;
        }
        setTimeout(tick, 250);
    }

    window.addEventListener("beforeunload", function (event) {
        if (!submitted) {
            event.preventDefault();
            event.returnValue = "";
        }
    });

    show(0);
    tick();
})();
</script>
""" + _FOOT


# ------------------------------------------------------------
# RESULT PAGE
# ------------------------------------------------------------

RESULT_HTML = _HEAD + """
<div class="card" style="text-align:center">
    <h2>{{ result.title }}</h2>
    <div class="big">{{ result.correct }}/{{ result.total }}</div>
    <h2>{{ result.score_pct }}%</h2>

    {% if result.timed_out %}
        <p style="color:#df3434">Time expired. Unsubmitted answers were not counted.</p>
    {% endif %}

    <p class="sub">Time taken: {{ result.minutes }} minutes {{ result.secs }} seconds</p>

    <div class="progress-track">
        <div class="progress-fill" style="width:{{ result.score_pct }}%"></div>
    </div>

    <div class="stats">
        <div class="stat"><b>{{ result.correct }}</b>Correct</div>
        <div class="stat"><b>{{ result.total - result.correct }}</b>Incorrect / Unanswered</div>
        <div class="stat"><b>{{ result.score_pct }}%</b>Score</div>
    </div>

    {% if result.saved %}
        <p style="color:green">✓ Result saved to your progress.</p>
    {% endif %}
</div>

<h2>Answer Review</h2>

{% for item in result.review %}
<div class="card">
    <h3>{{ loop.index }}. {{ item.q }}</h3>

    {% for option in item.options %}
        {% set state = 'right' if loop.index0 == item.answer else ('wrong' if loop.index0 == item.chosen else '') %}
        <label class="opt {{ state }}">
            {{ option }}
            {% if loop.index0 == item.answer %} ✓ Correct answer
            {% elif loop.index0 == item.chosen %} ✗ Your answer
            {% endif %}
        </label>
    {% endfor %}

    <div class="why"><b>Explanation:</b> {{ item.why }}</div>

    {% if item.chosen is none %}
        <p class="sub">You did not answer this question.</p>
    {% endif %}
</div>
{% endfor %}

<div class="row">
    <a class="btn" href="{{ url_for('aptitude.aptitude_home') }}">Take Another Test</a>
    <a class="btn alt" href="{{ url_for('aptitude.aptitude_progress') }}">View My Progress</a>
</div>
""" + _FOOT


# ------------------------------------------------------------
# PROGRESS PAGE
# ------------------------------------------------------------

PROGRESS_HTML = _HEAD + """
<div class="card">
    <h1>My Aptitude Progress</h1>
    <p class="sub">Track your placement preparation and improvement.</p>

    <div class="stats">
        <div class="stat"><b>{{ stats.attempts }}</b>Total Tests</div>
        <div class="stat"><b>{{ stats.best }}%</b>Best Score</div>
        <div class="stat"><b>{{ stats.average }}%</b>Average Score</div>
    </div>
</div>

<div class="card">
    <h2>Recent Attempts</h2>

    {% if stats.recent %}
    <table>
        <tr>
            <th>Category</th><th>Score</th><th>Correct</th><th>Time</th><th>Date</th>
        </tr>
        {% for item in stats.recent %}
        <tr>
            <td>{{ item.category }}</td>
            <td>{{ item.score_pct }}%</td>
            <td>{{ item.correct }}/{{ item.total }}</td>
            <td>{{ item.seconds // 60 }}m {{ item.seconds % 60 }}s</td>
            <td>{{ item.date }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
        <p class="sub">No aptitude tests completed yet. Start your first test!</p>
    {% endif %}
</div>

<a class="btn" href="{{ url_for('aptitude.aptitude_home') }}">Start Aptitude Test</a>
""" + _FOOT


# ------------------------------------------------------------
# BLUEPRINT HOOK
# ------------------------------------------------------------

@aptitude_bp.before_request
def _prepare():
    _ensure_tables()


# ------------------------------------------------------------
# 1. HOME   GET /aptitude/
# ------------------------------------------------------------

@aptitude_bp.route("/")
@aptitude_login_required
def aptitude_home():

    context = {
        "question_counts": QUESTION_COUNTS,
        "default_count": DEFAULT_COUNT,
        "durations": TEST_DURATIONS,
        "count_labels": COUNT_LABELS,
        "categories": CATEGORY_NAMES,
        "category_info": CATEGORY_INFO,
        "user_name": session.get("user_name", session.get("username", "Student")),
        "stats": _load_progress(_current_user_id()),
    }

    return _render(HOME_HTML, title="Aptitude Arena", **context)


# ------------------------------------------------------------
# 2. START   POST /aptitude/start
# ------------------------------------------------------------

@aptitude_bp.route("/start", methods=["POST"])
@aptitude_login_required
def aptitude_start():

    category = request.form.get("category", "quantitative").strip().lower()

    if category not in CATEGORIES and category != "all":
        flash("Please select a valid category.", "warning")
        return redirect(url_for("aptitude.aptitude_home"))

    try:
        count = int(request.form.get("question_count", DEFAULT_COUNT))
    except (ValueError, TypeError):
        count = DEFAULT_COUNT

    if count not in QUESTION_COUNTS:
        flash("Please select 10, 20 or 30 questions.", "warning")
        return redirect(url_for("aptitude.aptitude_home"))

    if category == "all":
        pool = list(QUESTION_INDEX.keys())
    else:
        pool = [q["id"] for q in CATEGORIES[category]["questions"]]

    if len(pool) < count:
        flash("Not enough questions are available for this test.", "warning")
        return redirect(url_for("aptitude.aptitude_home"))

    session["apt_test"] = {
        "category": category,
        "ids": random.sample(pool, count),
        "started": int(time.time()),
        "token": uuid.uuid4().hex,
        "duration": _duration_for(count),
    }

    session.pop("apt_result", None)

    return redirect(url_for("aptitude.aptitude_test"))


# ------------------------------------------------------------
# 3. TEST   GET /aptitude/test
# ------------------------------------------------------------

@aptitude_bp.route("/test")
@aptitude_login_required
def aptitude_test():

    test = session.get("apt_test")

    if not test:
        flash("Please start a new test first.", "warning")
        return redirect(url_for("aptitude.aptitude_home"))

    elapsed = max(0, int(time.time()) - int(test["started"]))
    duration = int(test.get("duration", DEFAULT_DURATION))
    remaining = max(0, duration - elapsed)

    questions = []

    for question_id in test["ids"]:
        question = QUESTION_INDEX.get(question_id)

        if question is None:
            continue

        # Never send answers or explanations to the browser.
        questions.append({
            "id": question_id,
            "q": question["q"],
            "options": question["options"],
        })

    return _render(
        TEST_HTML,
        title="Aptitude Test",
        title_text=_category_title(test["category"]),
        questions=questions,
        remaining=remaining,
        minutes=duration // 60,
        csrf_token=_get_csrf_token(),
    )


# ------------------------------------------------------------
# 4. SUBMIT   POST /aptitude/submit
# ------------------------------------------------------------

@aptitude_bp.route("/submit", methods=["POST"])
@aptitude_login_required
def aptitude_submit():

    test = session.get("apt_test")

    if not test:
        if session.get("apt_result"):
            return redirect(url_for("aptitude.aptitude_result"))

        flash("No active test found.", "warning")
        return redirect(url_for("aptitude.aptitude_home"))

    submitted_token = request.form.get("csrf_token", "")
    expected_token = session.get("aptitude_csrf", "")

    if not submitted_token or submitted_token != expected_token:
        flash("Invalid test submission. Please try again.", "danger")
        return redirect(url_for("aptitude.aptitude_test"))

    elapsed = max(0, int(time.time()) - int(test["started"]))

    # Small grace period so the auto-submit at 00:00 is not rejected.
    duration = int(test.get("duration", DEFAULT_DURATION))
    timed_out = elapsed > duration + 10

    correct = 0
    chosen_map = {}

    for question_id in test["ids"]:
        question = QUESTION_INDEX[question_id]
        raw = request.form.get(question_id)

        try:
            chosen = int(raw) if raw is not None else None
        except (ValueError, TypeError):
            chosen = None

        if chosen is not None and not 0 <= chosen < len(question["options"]):
            chosen = None

        if timed_out:
            chosen = None

        if chosen == question["answer"]:
            correct += 1

        chosen_map[question_id] = chosen

    total = len(test["ids"])
    score_pct = round(correct * 100 / total) if total else 0
    seconds = min(elapsed, duration)

    saved = _save_attempt(
        user_id=_current_user_id(),
        attempt_token=test["token"],
        category=test["category"],
        correct=correct,
        total=total,
        score_pct=score_pct,
        seconds=seconds,
        started_at=datetime.fromtimestamp(int(test["started"])),
        expires_at=datetime.fromtimestamp(
            int(test["started"]) + int(test.get("duration", DEFAULT_DURATION))
        ),
    )

    session["apt_result"] = {
        "category": test["category"],
        "ids": test["ids"],
        "chosen": chosen_map,
        "seconds": seconds,
        "saved": saved,
        "timed_out": timed_out,
    }

    session.pop("apt_test", None)

    return redirect(url_for("aptitude.aptitude_result"))


# ------------------------------------------------------------
# 5. RESULT   GET /aptitude/result
# ------------------------------------------------------------

@aptitude_bp.route("/result")
@aptitude_login_required
def aptitude_result():

    stored = session.get("apt_result")

    if not stored:
        flash("No test result found.", "warning")
        return redirect(url_for("aptitude.aptitude_home"))

    review = []
    correct = 0

    for question_id in stored["ids"]:
        question = QUESTION_INDEX[question_id]
        chosen = stored["chosen"].get(question_id)

        if chosen == question["answer"]:
            correct += 1

        review.append({
            "q": question["q"],
            "options": question["options"],
            "answer": question["answer"],
            "chosen": chosen,
            "why": question["why"],
        })

    total = len(stored["ids"])
    seconds = stored["seconds"]

    result = {
        "title": _category_title(stored["category"]),
        "correct": correct,
        "total": total,
        "score_pct": round(correct * 100 / total) if total else 0,
        "minutes": seconds // 60,
        "secs": seconds % 60,
        "saved": stored["saved"],
        "timed_out": stored.get("timed_out", False),
        "review": review,
    }

    return _render(RESULT_HTML, title="Aptitude Result", result=result)


# ------------------------------------------------------------
# 6. PROGRESS   GET /aptitude/progress
# ------------------------------------------------------------

@aptitude_bp.route("/progress")
@aptitude_login_required
def aptitude_progress():

    stats = _load_progress(_current_user_id())

    return _render(PROGRESS_HTML, title="My Aptitude Progress", stats=stats)