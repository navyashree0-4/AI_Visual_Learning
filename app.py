from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash

import os
from dotenv import load_dotenv


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "eduvision-secret-key"
)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

# MySQL settings are read from the .env file.
DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "ai_visual_learning"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "connection_timeout": 10,
    "autocommit": False
}


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():
    """Connect to MySQL and return a connection, or None on failure."""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)

        if connection.is_connected():
            print("DATABASE CONNECTED SUCCESSFULLY")
            return connection

        print("DATABASE CONNECTION ERROR: MySQL connection is not active.")

    except mysql.connector.Error as e:
        print("DATABASE CONNECTION ERROR:", e)

    except Exception as e:
        print("UNEXPECTED DATABASE ERROR:", e)

    return None


# ============================================================
# GET USER CREDITS
# ============================================================

def get_user_credits(user_id):

    connection = get_db_connection()

    if connection is None:
        return 0

    try:

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT credits
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        cursor.close()
        connection.close()

        if user:
            return user["credits"]

        return 0

    except Error as e:

        print(
            "CREDITS ERROR:",
            e
        )

        try:
            connection.close()
        except Exception:
            pass

        return 0


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )


        # ----------------------------
        # BASIC VALIDATION
        # ----------------------------

        if not name:

            flash(
                "Please enter your name."
            )

            return redirect(
                url_for("register")
            )


        if not email:

            flash(
                "Please enter your email address."
            )

            return redirect(
                url_for("register")
            )


        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters."
            )

            return redirect(
                url_for("register")
            )


        if password != confirm_password:

            flash(
                "Passwords do not match."
            )

            return redirect(
                url_for("register")
            )


        # ----------------------------
        # DATABASE
        # ----------------------------

        connection = get_db_connection()

        if connection is None:

            flash(
                "Database connection error."
            )

            return redirect(
                url_for("register")
            )


        try:

            cursor = connection.cursor(
                dictionary=True
            )


            # Check existing email

            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            existing_user = cursor.fetchone()


            if existing_user:

                cursor.close()
                connection.close()

                flash(
                    "An account with this email already exists."
                )

                return redirect(
                    url_for("login")
                )


            # Hash password

            hashed_password = (
                generate_password_hash(password)
            )


            # Create user

            cursor.execute(
                """
                INSERT INTO users
                (
                    name,
                    email,
                    password,
                    credits
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    name,
                    email,
                    hashed_password,
                    50
                )
            )


            connection.commit()

            cursor.close()
            connection.close()


            flash(
                "Account created successfully. Please login."
            )

            return redirect(
                url_for("login")
            )


        except Error as e:

            print(
                "REGISTER ERROR:",
                e
            )

            try:
                connection.rollback()
                connection.close()
            except Exception:
                pass

            flash(
                "Unable to create your account."
            )

            return redirect(
                url_for("register")
            )


    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )


        # ----------------------------
        # VALIDATION
        # ----------------------------

        if not email:

            flash(
                "Please enter your email address."
            )

            return redirect(
                url_for("login")
            )


        if not password:

            flash(
                "Please enter your password."
            )

            return redirect(
                url_for("login")
            )


        # ----------------------------
        # DATABASE
        # ----------------------------

        connection = get_db_connection()

        if connection is None:

            flash(
                "Database connection error."
            )

            return redirect(
                url_for("login")
            )


        try:

            cursor = connection.cursor(
                dictionary=True
            )


            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    email,
                    password,
                    credits
                FROM users
                WHERE email = %s
                """,
                (email,)
            )


            user = cursor.fetchone()


            cursor.close()
            connection.close()


            # ----------------------------
            # CHECK USER
            # ----------------------------

            if user is None:

                flash(
                    "Invalid email or password."
                )

                return redirect(
                    url_for("login")
                )


            # ----------------------------
            # CHECK PASSWORD
            # ----------------------------

            password_valid = check_password_hash(
                user["password"],
                password
            )


            if not password_valid:

                flash(
                    "Invalid email or password."
                )

                return redirect(
                    url_for("login")
                )


            # ----------------------------
            # CREATE SESSION
            # ----------------------------

            session.clear()

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]

            session["credits"] = user["credits"]


            return redirect(
                url_for("dashboard")
            )


        except Error as e:

            print(
                "LOGIN ERROR:",
                e
            )

            try:
                connection.close()
            except Exception:
                pass

            flash(
                "Unable to login. Please try again."
            )

            return redirect(
                url_for("login")
            )


    return render_template(
        "login.html"
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        flash(
            "Please login to continue."
        )

        return redirect(
            url_for("login")
        )


    user_id = session["user_id"]


    credits = get_user_credits(
        user_id
    )


    session["credits"] = credits


    return render_template(
        "dashboard.html",
        user_name=session.get(
            "user_name",
            "Student"
        ),
        user_email=session.get(
            "user_email",
            ""
        ),
        credits=credits
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out successfully."
    )

    return redirect(
        url_for("login")
    )


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404


@app.errorhandler(500)
def internal_server_error(error):

    return render_template(
        "500.html"
    ), 500


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("EDUVISION")
    print("AI-Based Multimodal Visual Learning")
    print("=" * 60)
    print()

    app.run(
        debug=True
    )