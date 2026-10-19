@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Create the virtual environment first.
    pause
    exit /b 1
)
start "RDRP App" .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:8000"
pause