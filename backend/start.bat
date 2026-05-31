@echo off
cd /d E:\projects\knowclaw_v2_mvp_refactor\backend
echo Starting backend...
start /B python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend_console.log 2>&1
echo Backend started with PID: %PROCESS_ID%
timeout /t 3 /nobreak > nul
curl -s http://localhost:8000/health && echo Backend is running || echo Backend may still be starting...