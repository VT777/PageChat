@echo off
chcp 65001 >nul
setlocal

title PageChat Frontend

set "PROJECT_DIR=D:\projects\page_chat"
set "FRONTEND_DIR=%PROJECT_DIR%\frontend"
set "HOST=0.0.0.0"
set "PORT=5173"

echo ==========================================
echo   PageChat Frontend
echo ==========================================
echo.

if not exist "%FRONTEND_DIR%" (
    echo [ERROR] Frontend directory not found:
    echo         %FRONTEND_DIR%
    echo.
    pause
    exit /b 1
)

cd /d "%FRONTEND_DIR%" || (
    echo [ERROR] Failed to enter frontend directory.
    echo.
    pause
    exit /b 1
)

echo [1/2] Checking node dependencies...
if not exist "node_modules" (
    echo [ERROR] node_modules not found:
    echo         %FRONTEND_DIR%\node_modules
    echo.
    echo Please run npm install in the frontend directory first.
    pause
    exit /b 1
)
echo       OK node_modules ready
echo.

echo [2/2] Starting frontend dev server...
echo       URL: http://localhost:%PORT%
echo       Press Ctrl+C to stop.
echo.

call npm.cmd run dev -- --host %HOST% --port %PORT%

echo.
echo [INFO] Frontend process exited.
pause
