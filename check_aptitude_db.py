
"""
EduVision Aptitude Arena - Database Diagnostic
Run: python check_aptitude_db.py
"""

import os
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv
import mysql.connector

load_dotenv()

config = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "ai_visual_learning"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
}

print("Connecting to", config["host"],
      "database:", config["database"])

try:
    conn = mysql.connector.connect(**config)
    cur = conn.cursor()

    print("\nSTEP 1 OK - MySQL connected.")

    cur.execute("DESCRIBE aptitude_attempts")
    columns = {row[0]: str(row[1]).lower()
               for row in cur.fetchall()}

    print("\nSTEP 2 OK - Table structure:")

    for name, kind in columns.items():
        print(f"  {name}: {kind}")

    required = [
        "id", "user_id", "guest_token", "attempt_token",
        "category", "question_count", "started_at",
        "expires_at", "submitted_at", "score",
        "percentage", "time_taken_seconds", "status"
    ]

    missing = [name for name in required if name not in columns]

    if missing:
        print("\nFAILED - Missing columns:", missing)
        raise SystemExit(1)

    if columns["user_id"] not in ("int", "integer"):
        print("\nFAILED - user_id must be INT.")
        raise SystemExit(1)

    print("\nSTEP 2 PASSED - Database schema is compatible.")

    # Test using a guest record so no real user is affected.
    token = uuid.uuid4().hex
    now = datetime.now()
    expires = now + timedelta(minutes=30)

    try:
        cur.execute("""
            INSERT INTO aptitude_attempts (
                attempt_token,
                user_id,
                guest_token,
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
            VALUES (
                %s, NULL, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
        """, (
            token,
            "diagnostic_" + token,
            "quantitative",
            10,
            now,
            expires,
            now,
            8,
            80.00,
            120,
            "completed"
        ))

        conn.commit()

        print("\nSTEP 3 PASSED - Test record inserted.")

        cur.execute("""
            DELETE FROM aptitude_attempts
            WHERE attempt_token = %s
        """, (token,))

        conn.commit()

        print("STEP 4 PASSED - Diagnostic record deleted.")
        print("\nSUCCESS: Aptitude database is ready.")

    except mysql.connector.Error as exc:
        conn.rollback()
        print("\nSTEP 3 FAILED:")
        print(exc)

finally:
    if 'cur' in locals():
        cur.close()

    if 'conn' in locals() and conn.is_connected():
        conn.close()
