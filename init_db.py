"""
init_db.py
Creates the database and tables by running database/schema.sql.
Run it once with:   python init_db.py
It uses the settings in your .env file (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME).
"""

import os
import mysql.connector
from dotenv import load_dotenv

# 1. Read the settings from the .env file
load_dotenv()

host = os.getenv("MYSQL_HOST") or os.getenv("DB_HOST", "localhost")
user = os.getenv("MYSQL_USER") or os.getenv("DB_USER", "root")
password = os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD", "")
db_name = os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME", "ai_visual_learning")
port = int(os.getenv("MYSQL_PORT") or 3306)

# 2. Read the SQL file
sql_path = os.path.join("database", "schema.sql")

if not os.path.exists(sql_path):
    print("Could not find", sql_path)
    print("Check that the file is inside the 'database' folder.")
    raise SystemExit

with open(sql_path, "r", encoding="utf-8") as f:
    sql_text = f.read()

# 3. Connect to MySQL (without choosing a database yet)
connection = mysql.connector.connect(host=host, user=user, password=password, port=port)
cursor = connection.cursor()

# 4. Create the database if it is missing, then use it
cursor.execute("CREATE DATABASE IF NOT EXISTS `" + db_name + "`")
cursor.execute("USE `" + db_name + "`")
print("Using database:", db_name)

# 5. Run every command in schema.sql, one by one
for command in sql_text.split(";"):
    command = command.strip()

    if command == "":
        continue

    # Skip these two because we already did them above
    first_word = command.upper()
    if first_word.startswith("CREATE DATABASE") or first_word.startswith("USE "):
        continue

    try:
        cursor.execute(command)
    except mysql.connector.Error as error:
        print("Problem with this command:")
        print(command[:80], "...")
        print("Error:", error)

connection.commit()

# 6. Show the tables that now exist
cursor.execute("SHOW TABLES")
tables = cursor.fetchall()

print()
print("Tables in", db_name, ":")
for table in tables:
    print(" -", table[0])

cursor.close()
connection.close()