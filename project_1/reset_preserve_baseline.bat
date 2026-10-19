@echo off
cd /d "%~dp0"
set PYTHONPATH=%cd%
.venv\Scripts\python.exe -m backend.db.reset
pause