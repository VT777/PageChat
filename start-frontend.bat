chcp 65001 > nul
@echo off
echo ==========================================
echo   PageChat Frontend (with cache clean)
echo ==========================================
echo.

cd /d D:\projects\page_chat\frontend

echo [1/3] Cleaning Vite cache...
if exist "node_modules\.vite" (
    rmdir /s /q "node_modules\.vite"
    echo       OK Vite cache cleared
) else (
    echo       - No Vite cache to clean
)

echo.
echo [2/3] Checking node_modules...
if not exist "node_modules" (
    echo [WARNING] node_modules not found, installing...
    call npm.cmd install
    if errorlevel 1 (
        echo [ERROR] npm install failed
        pause
        exit /b 1
    )
) else (
    echo       OK node_modules ready
)

echo.
echo [3/3] Starting frontend dev server...
echo       URL: http://localhost:5173
echo       Press Ctrl+C to stop
echo.

start "PageChat Frontend" cmd /k "cd /d D:\projects\page_chat\frontend && npm.cmd run dev"

echo       OK Frontend window opened
echo.
pause
