@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Create the virtual environment first.
    pause
    exit /b 1
)
start "RDRP App" .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

set /a attempts=0
:wait
set /a attempts+=1
if %attempts% gtr 60 (
    echo Timed out waiting for the app to start.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
curl -s --max-time 1 http://127.0.0.1:8000/health >nul 2>&1
if errorlevel 1 goto wait

start "" "http://127.0.0.1:8000"
#pause