@echo off
cd /d "%~dp0"
uv run --project data python run_generator.py
pause