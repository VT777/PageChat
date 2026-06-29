@echo off
chcp 65001 >nul
setlocal EnableExtensions

title PageChat Frontend (Worktree)

set "PROJECT_DIR=%~dp0"
for %%I in ("%PROJECT_DIR%") do set "PROJECT_DIR=%%~fI"
set "FRONTEND_DIR=%PROJECT_DIR%\frontend"
set "HOST=0.0.0.0"
set "PORT=5173"

echo ==========================================
echo   PageChat Frontend (Worktree)
echo ==========================================
echo.
echo Source: %PROJECT_DIR%
git -C "%PROJECT_DIR%" branch --show-current 2>nul
echo.

if not exist "%FRONTEND_DIR%" (
    echo [ERROR] Frontend directory not found:
    echo         %FRONTEND_DIR%
    pause
    exit /b 1
)

cd /d "%FRONTEND_DIR%" || (
    echo [ERROR] Failed to enter frontend directory.
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo [ERROR] node_modules not found:
    echo         %FRONTEND_DIR%\node_modules
    echo Please run npm install in the frontend directory first.
    pause
    exit /b 1
)

echo URL: http://localhost:%PORT%
echo.

call npm.cmd run dev -- --host %HOST% --port %PORT%

echo.
echo [INFO] Frontend process exited.
pause
