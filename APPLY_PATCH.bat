@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py apply_daily_limit_patch.py) || (python apply_daily_limit_patch.py)
echo.
pause
