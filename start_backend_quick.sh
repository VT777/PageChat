#!/bin/bash
# Quick start script for backend

cd /e/projects/knowclaw_v2_mvp_refactor/backend
"C:\Users\TT_WT\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning
