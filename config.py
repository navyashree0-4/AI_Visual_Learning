"""
config.py
All settings of the project are kept here.
The values come from your .env file (MYSQL_HOST, MYSQL_USER, ...).
"""

import os
from dotenv import load_dotenv

# Read the .env file
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def find_video_folder():
    """Uses the first video folder that exists in your project."""
    for folder in ["generated/video", "generated/videos", "generated_videos", "static/videos"]:
        if os.path.isdir(os.path.join(BASE_DIR, folder)):
            return os.path.join(BASE_DIR, folder)
    return os.path.join(BASE_DIR, "generated", "video")


class Config:
    # Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "eduvision-secret-key")

    # MySQL
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ai_visual_learning")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT") or 3306)

    # Folders for uploaded files and generated videos
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    VIDEO_FOLDER = find_video_folder()
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024      # 16 MB upload limit