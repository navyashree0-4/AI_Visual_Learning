EduVision update: learning-first dashboard + daily game limit with X marks
=========================================================================

STEP 1  Copy the files from this folder into your PROJECT FOLDER (the one with app.py):
          templates\dashboard.html   -> replaces your dashboard.html
          apply_daily_limit_patch.py
          APPLY_PATCH.bat

STEP 2  Double-click APPLY_PATCH.bat (or run: python apply_daily_limit_patch.py)
        It updates app.py and static\js\game.js, and saves backups (app.py.bak, game.js.bak).
        If any edit spot is not found it changes NOTHING and tells you which one.

STEP 3  Optional in .env:   DAILY_GAME_LIMIT=10
STEP 4  Restart Flask, then hard refresh the browser (Ctrl+F5).

What you get
- Dashboard leads with learning (AI Lesson Video, Cartoon Movie, AI Tutor, Aptitude Arena);
  games sit under "Brain Break" with a daily usage meter.
- One daily limit shared by all 14 games (default 10 completed rounds), counted in MySQL.
- Reward popup shows X marks and "Enough playing for today!"; games are blocked after the limit.
