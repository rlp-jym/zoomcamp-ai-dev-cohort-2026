@echo off
cd /d "%~dp0"

echo WARNING: This will truncate non-baseline app data.
echo Preserved: personas, rules, scenarios (including baseline_run), baseline runs/publications, and baseline fixture rows.
set /p CONFIRM=Type YES to continue: 
if /I not "%CONFIRM%"=="YES" (
    echo Aborted.
    pause
    exit /b 1
)

call stop_app.bat

.venv\Scripts\python.exe -c "import os; from dotenv import load_dotenv; load_dotenv(); import psycopg; c=psycopg.connect(os.getenv('DATABASE_URL')); cur=c.cursor(); cur.execute(\"TRUNCATE TABLE validations, reconciliations, exceptions, quarantines, approvals, alerts, agent_actions, otel_spans, otel_logs, otel_metrics, dashboard_cache CASCADE; DELETE FROM messages WHERE discussion_id NOT IN (SELECT discussion_id FROM discussions d JOIN runs r ON r.run_id::text=d.anchor_id WHERE d.anchor_type='run' AND r.scenario_name='baseline_run'); DELETE FROM discussions WHERE anchor_type='run' AND anchor_id NOT IN (SELECT run_id::text FROM runs WHERE scenario_name='baseline_run'); DELETE FROM runs WHERE scenario_name <> 'baseline_run'; DELETE FROM publications WHERE run_id NOT IN (SELECT run_id FROM runs WHERE scenario_name='baseline_run');\"); c.commit(); cur.close(); c.close(); print('Reset complete (baseline preserved).')"
if errorlevel 1 (
    echo DB reset failed.
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
echo Reset complete. App is running.
pause