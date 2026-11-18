@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m src.studio
) else if exist "%SystemRoot%\py.exe" (
    py -3 -m src.studio
) else (
    python -m src.studio
)

if errorlevel 1 (
    echo.
    echo Could not start Brighten Studio. Install Python 3.10 or later and requirements.txt.
    pause
)
