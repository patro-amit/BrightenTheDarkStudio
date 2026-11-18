@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m src.start_dashboard --refresh
) else if exist "%SystemRoot%\py.exe" (
    py -3 -m src.start_dashboard --refresh
) else (
    python -m src.start_dashboard --refresh
)

if errorlevel 1 (
    echo.
    echo Could not open the dashboard. Install Python 3.10 or later and requirements.txt.
    pause
)
