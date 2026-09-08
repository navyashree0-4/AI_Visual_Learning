from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
import sqlite3
import os

app = Flask(__name__)

app.secret_key = "eduvision_secret_key"

# --------------------------------------------------
# DATABASE
# --------------------------------------------------

DATABASE = "eduvision.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/")
def home():

    return render_template("index.html")


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        # Basic validation

        if not name or not email or not password:
            flash("Please fill all the fields.")
            return redirect(url_for("register"))

        if len(name.strip()) < 3:
            flash("Name must contain at least 3 characters.")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must contain at least 6 characters.")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("register"))

        # Save user

        try:

            conn = get_db()

            conn.execute(
                """
                INSERT INTO users (name, email, password)
                VALUES (?, ?, ?)
                """,
                (name, email, password)
            )

            conn.commit()
            conn.close()

            flash("Account created successfully! Please login.")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            flash("This email is already registered.")

            return redirect(url_for("register"))

    return render_template("register.html")


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:

            flash("Please enter email and password.")

            return redirect(url_for("login"))


        conn = get_db()

        user = conn.execute(
            """
            SELECT * FROM users
            WHERE email = ? AND password = ?
            """,
            (email, password)
        ).fetchone()

        conn.close()


        if user:

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            flash("Login successful!")

            return redirect(url_for("home"))

        else:

            flash("Invalid email or password.")

            return redirect(url_for("login"))


    return render_template("login.html")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out.")

    return redirect(url_for("home"))


# --------------------------------------------------
# VIDEO
# --------------------------------------------------

# Put your video inside:
# static/video/

VIDEO_FOLDER = os.path.join(
    app.root_path,
    "static",
    "video"
)


@app.route("/video/<filename>")
def video(filename):

    return send_from_directory(
        VIDEO_FOLDER,
        filename
    )


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    create_database()

    app.run(
        debug=True
    )