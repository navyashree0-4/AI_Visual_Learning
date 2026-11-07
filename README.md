# EduVision – AI-Based Multimodal Visual Learning System

## 1. Project Description

EduVision is an AI-based visual learning platform designed to make education easier and more interactive.

It allows students and teachers to generate educational video lessons using topics, PDF documents and images. The system simplifies learning content and creates narrated videos with visual explanations.

## 2. Main Features

- User registration and login
- AI-based educational video generation
- PDF and image text extraction
- Text-to-speech narration
- Video creation using FFmpeg
- Multiple learning languages
- AI-based quizzes
- Learning progress tracking
- Credit and reward system
- Educational games
- Aptitude Arena

## 3. Technologies Used

- Python
- Flask
- MySQL
- HTML, CSS and JavaScript
- Bootstrap (where used)
- Pillow
- PyMuPDF
- gTTS
- FFmpeg
- Python-dotenv

## 4. Project Structure

```text
AI_Visual_Learning/
│
├── app.py
├── README.md
├── requirements.txt
├── .env
├── venv/
├── ai/
├── database/
├── games/
├── generated/
├── models/
├── routes/
├── services/
├── static/
├── templates/
├── tests/
└── uploads/
```

## 5. Requirements

- Python 3.11
- MySQL Server 8.0
- FFmpeg
- Required Python packages listed in requirements.txt

## 6. Installation

Open the project folder in the terminal.

Create a virtual environment:

```bash
python -m venv venv
```

Activate it on Windows:

```cmd
venv\Scripts\activate
```

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Make sure MySQL Server is running and the database configuration is correct in the local `.env` file.

Make sure FFmpeg is installed and available in Windows PATH.

## 7. Run the Application

```bash
python app.py
```

Open the local address displayed in the terminal, usually:

```text
http://127.0.0.1:5000/
```

## 8. Important Notes

- Do not upload `.env` because it contains private configuration and credentials.
- Do not upload the `venv` folder to GitHub.
- Keep generated videos and uploaded files in their configured project folders.
- Ensure MySQL Server and FFmpeg are available before using video generation.

