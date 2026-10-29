"""
db.py
One function that opens a connection to the MySQL database.
Use it like this:
    from db import get_connection
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ...
    conn.close()
"""

import mysql.connector
from config import Config


def get_connection():
    return mysql.connector.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE,
        port=Config.MYSQL_PORT,
    )