
# game_data.py
# EduVision - Game Data and Configuration

import random


# =====================================================
# 1. COMMON LEARNING TERMS
# =====================================================

TERMS = [
    {"term": "CPU", "definition": "The brain of a computer that processes instructions."},
    {"term": "RAM", "definition": "Temporary memory used by running programs."},
    {"term": "ROM", "definition": "Memory that stores permanent instructions."},
    {"term": "HTML", "definition": "A markup language used to structure web pages."},
    {"term": "CSS", "definition": "A language used to style web pages."},
    {"term": "Python", "definition": "A programming language known for readable syntax."},
    {"term": "Java", "definition": "An object-oriented programming language."},
    {"term": "MySQL", "definition": "A relational database management system."},
    {"term": "Flask", "definition": "A lightweight Python web framework."},
    {"term": "AI", "definition": "Artificial Intelligence."},
    {"term": "Machine Learning", "definition": "A field of AI that learns patterns from data."},
    {"term": "Algorithm", "definition": "A sequence of steps used to solve a problem."},
    {"term": "Variable", "definition": "A named location used to store a value."},
    {"term": "Function", "definition": "A reusable block of code that performs a task."},
    {"term": "Database", "definition": "An organized collection of information."},
    {"term": "Operating System", "definition": "Software that manages hardware and applications."},
    {"term": "Network", "definition": "Connected devices that communicate with each other."},
    {"term": "Internet", "definition": "A global network of interconnected computer networks."},
    {"term": "Input", "definition": "Data supplied to a computer or program."},
    {"term": "Output", "definition": "Information produced by a computer or program."},
]


# =====================================================
# 2. QUIZ QUESTIONS
# =====================================================

QUESTIONS = [
    {
        "question": "What is the brain of a computer?",
        "options": ["Monitor", "CPU", "Keyboard", "Mouse"],
        "answer": 1,
        "explanation": "The CPU processes instructions and controls computer operations."
    },
    {
        "question": "Which language structures web pages?",
        "options": ["HTML", "SQL", "Python", "C"],
        "answer": 0,
        "explanation": "HTML defines the structure and content of web pages."
    },
    {
        "question": "Which technology styles web pages?",
        "options": ["MySQL", "CSS", "Flask", "Java"],
        "answer": 1,
        "explanation": "CSS controls the appearance and layout of web pages."
    },
    {
        "question": "Which is a Python web framework?",
        "options": ["Flask", "HTML", "RAM", "CPU"],
        "answer": 0,
        "explanation": "Flask is a lightweight Python web framework."
    },
    {
        "question": "What does AI stand for?",
        "options": [
            "Automatic Internet",
            "Artificial Intelligence",
            "Advanced Input",
            "Applied Information"
        ],
        "answer": 1,
        "explanation": "AI stands for Artificial Intelligence."
    },
    {
        "question": "Which memory is temporary?",
        "options": ["ROM", "Hard disk", "RAM", "DVD"],
        "answer": 2,
        "explanation": "RAM temporarily stores data used by running programs."
    },
    {
        "question": "What is an algorithm?",
        "options": [
            "A computer screen",
            "A sequence of problem-solving steps",
            "A storage device",
            "A programming error"
        ],
        "answer": 1,
        "explanation": "An algorithm is a sequence of steps for solving a problem."
    },
    {
        "question": "Which is a relational database system?",
        "options": ["MySQL", "CSS", "HTML", "PowerPoint"],
        "answer": 0,
        "explanation": "MySQL is a relational database management system."
    },
    {
        "question": "What is a variable used for?",
        "options": [
            "Storing a value",
            "Printing paper",
            "Connecting a monitor",
            "Deleting an operating system"
        ],
        "answer": 0,
        "explanation": "Variables store values that programs can use."
    },
    {
        "question": "What manages computer hardware and applications?",
        "options": ["Browser", "Operating system", "Text file", "HTML"],
        "answer": 1,
        "explanation": "An operating system manages hardware and software resources."
    },
]


# =====================================================
# 3. MEMORY GAME ITEMS
# =====================================================

MEMORY_ITEMS = [
    {"term": "CPU", "definition": "Processes instructions"},
    {"term": "RAM", "definition": "Temporary memory"},
    {"term": "HTML", "definition": "Web page structure"},
    {"term": "CSS", "definition": "Web page styling"},
    {"term": "Python", "definition": "Programming language"},
    {"term": "MySQL", "definition": "Relational database"},
    {"term": "Flask", "definition": "Python web framework"},
    {"term": "AI", "definition": "Artificial Intelligence"},
]


# =====================================================
# 4. MATCHING GAME ITEMS
# =====================================================

MATCH_ITEMS = [
    {"left": "CPU", "right": "Processes instructions"},
    {"left": "RAM", "right": "Temporary memory"},
    {"left": "HTML", "right": "Web page structure"},
    {"left": "CSS", "right": "Web page styling"},
    {"left": "Python", "right": "Programming language"},
    {"left": "MySQL", "right": "Database management"},
    {"left": "Flask", "right": "Python web framework"},
    {"left": "Algorithm", "right": "Problem-solving steps"},
]


# =====================================================
# 5. WORD WIZARD ITEMS
# =====================================================

WORD_ITEMS = [
    {"word": "PYTHON", "hint": "A popular programming language"},
    {"word": "DATABASE", "hint": "An organized collection of information"},
    {"word": "ALGORITHM", "hint": "Steps used to solve a problem"},
    {"word": "NETWORK", "hint": "Connected computers that communicate"},
    {"word": "VARIABLE", "hint": "Stores a value in a program"},
    {"word": "FUNCTION", "hint": "A reusable block of code"},
]


# =====================================================
# 6. NEW GAMES - OLD GAME CONFIGURATIONS REMOVED
# =====================================================

GAMES = {
    "arrow_maze": {
        "name": "🏹 Arrow Finder: Arrow Maze",
        "title": "Arrow Finder: Arrow Maze",
        "mode": "arrow_maze",
        "category": "Puzzle",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "hologram_memory": {
        "name": "✨ Hologram Memory Challenge",
        "title": "Hologram Memory Challenge",
        "mode": "hologram_memory",
        "category": "Memory",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": MEMORY_ITEMS,
    },

    "candy_match": {
        "name": "🍬 Candy Match Puzzle",
        "title": "Candy Match Puzzle",
        "mode": "candy_match",
        "category": "Puzzle",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": MATCH_ITEMS,
    },

    "memory_match": {
        "name": "🃏 Memory Card Matching",
        "title": "Memory Card Matching",
        "mode": "memory_match",
        "category": "Memory",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": MEMORY_ITEMS,
    },

    "bubble_shooter": {
        "name": "🫧 Bubble Shooter",
        "title": "Bubble Shooter",
        "mode": "bubble_shooter",
        "category": "Puzzle",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "endless_runner": {
        "name": "🏃 Endless Runner",
        "title": "Endless Runner",
        "mode": "endless_runner",
        "category": "Arcade",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "neon_tic_tac_toe": {
        "name": "❌ Neon Tic-Tac-Toe",
        "title": "Neon Tic-Tac-Toe",
        "mode": "neon_tic_tac_toe",
        "category": "Strategy",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": QUESTIONS,
    },

    "puzzle_2048": {
        "name": "🔢 2048 Number Puzzle",
        "title": "2048 Number Puzzle",
        "mode": "puzzle_2048",
        "category": "Puzzle",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "arrow_direction": {
        "name": "➡️ Arrow Direction Puzzle",
        "title": "Arrow Direction Puzzle",
        "mode": "arrow_direction",
        "category": "Brain Training",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "sliding_puzzle": {
        "name": "🧩 Sliding Puzzle",
        "title": "Sliding Puzzle",
        "mode": "sliding_puzzle",
        "category": "Puzzle",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "quiz_battle": {
        "name": "⚔️ Quiz Battle Arena",
        "title": "Quiz Battle Arena",
        "mode": "quiz_battle",
        "category": "Quiz",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": QUESTIONS,
    },

    "tetris_blocks": {
        "name": "🧱 Tetris Blocks",
        "title": "Tetris Blocks",
        "mode": "tetris_blocks",
        "category": "Arcade",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "flappy_brain": {
        "name": "🧠 Flappy Brain",
        "title": "Flappy Brain",
        "mode": "flappy_brain",
        "category": "Arcade",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },

    "snake_game": {
        "name": "🐍 Snake Game",
        "title": "Snake Game",
        "mode": "snake_game",
        "category": "Arcade",
        "reward": 10,
        "terms": TERMS,
        "questions": QUESTIONS,
        "items": TERMS,
    },
}


# =====================================================
# 7. BUILD PAYLOAD FOR game.html
# =====================================================

def build_payload(game_key, game):
    return {
        **game,
        "id": game_key,
        "key": game_key,
        "name": game.get("name", game_key),
        "title": game.get("title", game.get("name", game_key)),
        "mode": game.get("mode", game_key),
        "reward": game.get("reward", 10),
        "terms": game.get("terms", TERMS),
        "questions": game.get("questions", QUESTIONS),
        "items": game.get("items", []),
    }


# =====================================================
# 8. RANDOM QUIZ HELPER
# =====================================================

def get_random_questions(count=5):
    questions = QUESTIONS.copy()
    random.shuffle(questions)
    return questions[:max(0, min(count, len(questions)))]
