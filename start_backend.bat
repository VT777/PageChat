@echo off
cd /d E:\projects\knowclaw_v2_mvp_refactor\backend
start /B python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1
echo Backend started on port 8000
timeout /t 5 > nul
curl -s http://localhost:8000/health 2>nul || echo "Service may still be starting..."
