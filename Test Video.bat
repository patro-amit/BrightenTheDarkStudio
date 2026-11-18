@echo off
setlocal
cd /d "%~dp0"

set "CLIP=%~1"
if not defined CLIP (
    set /p "CLIP=Drag a video file here and press Enter, or paste its full path: "
)
if not defined CLIP exit /b 1

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m src.start_dashboard --video "%CLIP%"
) else if exist "%SystemRoot%\py.exe" (
    py -3 -m src.start_dashboard --video "%CLIP%"
) else (
    python -m src.start_dashboard --video "%CLIP%"
)

if errorlevel 1 (
    echo.
    echo Could not process the video.
    pause
)
