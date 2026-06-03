@echo off
echo ==========================================
echo   PageChat - Starting All Services
echo ==========================================
echo.

cd /d D:\projects\page_chat

echo [1/2] Starting Backend Server...
call start-backend.bat

timeout /t 3 /nobreak > nul

echo.
echo [2/2] Starting Frontend Server...
call start-frontend.bat

echo.
echo ==========================================
echo   All services started!
echo ==========================================
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo ==========================================
pause
