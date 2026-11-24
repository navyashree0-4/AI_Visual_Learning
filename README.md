# EduVision – AI-Based Multimodal Visual Learning System

EduVision is a web-based educational platform that combines visual learning, educational video generation, study assistance and interactive learning activities. It allows students to generate educational videos from topics and uploaded study materials while providing additional features such as study notes, an AI Doubt Tutor, quizzes, educational games, aptitude tests and learning progress tracking.

The application is developed using Python, Flask, MySQL, HTML, CSS and JavaScript.

## Project Information

| Category | Details |
|---|---|
| Project Name | EduVision |
| Project Title | AI-Based Multimodal Visual Learning and Educational Video Generation System |
| Project Type | Web-Based Educational Application |
| Backend | Python, Flask |
| Frontend | HTML5, CSS3, JavaScript |
| Database | MySQL 8.0 |
| Development Environment | Visual Studio Code |
| Version Control | Git and GitHub |

## Features

### 1. User Authentication
- Student registration and login.
- Email OTP verification.
- Password hashing using Werkzeug.
- Session management.
- Protected application routes.

### 2. Educational Video Generation
- Generate educational videos from topics.
- Upload PDF, TXT and image files.
- Extract text from supported input formats.
- Identify important concepts and keywords.
- Simplify educational content.
- Generate educational scripts and scenes.
- Add relevant images, captions and labels.
- Generate audio narration using text-to-speech.
- Render videos in MP4 format using FFmpeg.

**Video customization options:**
- Difficulty: Beginner, Intermediate and Advanced.
- Audience: Kids, School Students, College Students and Teachers.
- Language: English, Kannada and Hindi.
- Style: Educational, Animated, Simple Explanation and Storytelling.
- Duration: Short, Medium and Long.

### 3. Study Notes
Provides a facility to process educational materials and prepare study notes for revision and examination preparation.

### 4. AI Doubt Tutor
Provides educational explanations and answers to student questions. It also supports visual explanations where available.

### 5. Video Quiz
- Educational multiple-choice questions.
- Automatic answer evaluation.
- Score calculation.
- Quiz result display.
- Learning assessment.

### 6. Educational Games
EduVision includes 14 interactive games:

1. Arrow Maze
2. Hologram Memory
3. Candy Match
4. Memory Match
5. Bubble Shooter
6. Endless Runner
7. Neon Tic-Tac-Toe
8. Puzzle 2048
9. Arrow Direction
10. Sliding Puzzle
11. Quiz Battle
12. Tetris Blocks
13. Flappy Brain
14. Snake Game

The arcade module supports game levels, scores and progress tracking.

### 7. Aptitude Arena
Provides aptitude practice in three categories:
- Quantitative Aptitude
- Logical Reasoning
- Verbal Ability

Students can select the question count, attend timed tests and view their results.

### 8. Credit Management
- Initial credits for new users.
- Credit deduction for selected activities.
- Configurable video generation cost.
- Eligible activity-based credit rewards.
- Credit balance management.

### 9. Learning Progress
Maintains student learning activity information, including:
- Generated videos.
- Quiz scores.
- Game activities.
- Aptitude attempts.
- Learning performance.

## Technology Stack

| Technology | Description |
|---|---|
| Python 3.11 | Backend programming |
| Flask | Web framework |
| MySQL 8.0 | Relational database |
| HTML5 | Frontend structure |
| CSS3 | Styling and layouts |
| JavaScript | Client-side functionality |
| Jinja2 | Template rendering |
| Werkzeug | Password hashing and security utilities |
| PyMuPDF | PDF text extraction |
| Tesseract OCR | Optical character recognition |
| pytesseract | Python OCR integration |
| Pillow | Image processing |
| gTTS / Edge-TTS | Text-to-speech |
| FFmpeg | Audio and video processing |
| deep-translator | Language translation |

## System Architecture

EduVision follows a layered architecture consisting of:

1. **Presentation Layer:** Handles the user interface using HTML, CSS, JavaScript and Jinja2.
2. **Application Layer:** Manages application requests, authentication and modules using Flask.
3. **Processing Layer:** Handles content extraction, text processing, script preparation, narration and video generation.
4. **Database Layer:** Stores application information using MySQL.
5. **Output Layer:** Provides generated videos, study notes, quiz results, game scores and learning progress.

## Video Generation Workflow

```text
Student Login
      |
      v
Topic / PDF / Image Input
      |
      v
Input Validation
      |
      v
Content Extraction
      |
      v
Content Understanding
      |
      v
Important Concept Identification
      |
      v
Educational Content Simplification
      |
      v
Script Generation
      |
      v
Scene Generation
      |
      v
Visual Generation
      |
      v
Text-to-Speech
      |
      v
Captions and Labels
      |
      v
FFmpeg Video Rendering
      |
      v
Educational MP4 Video
      |
      v
Quiz and Learning Progress
```

## Database

EduVision uses MySQL 8.0 for storing and managing application data.

The database manages records related to:

- Users and authentication.
- Generated videos.
- Quizzes and quiz attempts.
- Learning progress.
- User activities.
- Game plays.
- Game progress.
- Game level rewards.
- Game results.
- Aptitude attempts.
- Credit management.

## Installation and Setup

### Prerequisites

Install the following:

- Python 3.11
- MySQL 8.0
- FFmpeg
- Tesseract OCR
- Visual Studio Code
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/navyashree0-4/AI_Visual_Learning.git
```

### 2. Navigate to the Project Directory

```bash
cd AI_Visual_Learning
```

### 3. Create a Virtual Environment

```bash
python -m venv venv
```

### 4. Activate the Virtual Environment

Windows:

```bash
venv\Scripts\activate
```

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

### 6. Configure MySQL Database

Start the MySQL server and create the database:

```sql
CREATE DATABASE ai_visual_learning;
```

Configure the database connection using the project's `.env` configuration.

Ensure that all required database tables are initialized using the application's database setup process.

### 7. Configure Environment Variables

Create a `.env` file in the application directory and provide the required configuration values, such as:

- Database host.
- Database username.
- Database password.
- Database name.
- Flask secret key.
- Optional external service API keys.

Use the actual variable names expected by the application. Do not commit private credentials to GitHub.

### 8. Run the Application

```bash
python app.py
```

### 9. Access the Application

Open the following address in your browser:

```text
http://127.0.0.1:5000/
```

Register or log in to access the available features.

## Project Structure

The application is organised into different directories for backend processing, frontend resources, templates and generated content.

```text
AI_Visual_Learning/
│
├── app.py
├── requirements.txt
├── .env
│
├── routes/
│
├── services/
│
├── templates/
│
├── static/
│   ├── css/
│   ├── js/
│   ├── images/
│   └── generated/
│
├── database/
│
└── README.md
```

*Note: This is a high-level directory representation. Refer to the repository for the complete project structure.*

## Security

- Password hashing.
- User authentication.
- Session management.
- Protected routes.
- File format validation.
- Input validation.
- Database access through the backend.
- Error handling.

## Testing

The application uses different testing approaches:

- Unit Testing
- Integration Testing
- System Testing
- Functional Testing
- Validation Testing

These tests are used to verify individual modules, communication between components and the overall application workflow.

## Limitations

- Video generation time depends on content length and system performance.
- Output quality depends on the supplied educational material and processing services.
- Some features require internet connectivity.
- Supported file formats depend on the implemented extraction methods.
- The project does not train a separate machine-learning model using a custom dataset.

## Future Enhancements

- Advanced educational animations.
- Additional regional language support.
- Improved visual storytelling.
- Personalised learning recommendations.
- Advanced performance analytics.
- Additional educational games.
- Cloud deployment.
- Improved mobile accessibility.

## Repository

**GitHub:** https://github.com/navyashree0-4/AI_Visual_Learning

## Developer

**Name:** Navyashree

**Department:** Master of Computer Applications (MCA)

**Institution:** A.J. Institute of Engineering & Technology, Mangaluru

**University:** Visvesvaraya Technological University (VTU)

**Project:** Semester III Main Project

---

## License

This project is developed for academic purposes. Add an appropriate open-source license if you intend to distribute the source code under specific reuse terms.
