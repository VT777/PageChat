chcp 65001 > nul
@echo off
echo ==========================================
echo   PageChat Backend (with cache clean)
echo ==========================================
echo.

cd /d D:\projects\page_chat\backend

echo [1/3] Clearing memory cache...
venv\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from app.services.cache_service import cache_service; cache_service.clear_all(); print('      OK Memory cache cleared')" 2>nul
echo.

echo [2/3] Checking virtual environment...
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at venv\Scripts\python.exe
    pause
    exit /b 1
)
echo       OK Virtual environment ready

echo.
echo [3/3] Starting backend server...
echo       URL: http://localhost:8000
echo       API Docs: http://localhost:8000/docs
echo       Press Ctrl+C to stop
echo.

start "PageChat Backend" cmd /k "cd /d D:\projects\page_chat\backend && venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo       OK Backend window opened
echo.
pause
