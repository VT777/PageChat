@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"

echo ==========================================
echo   PageChat Docker Launcher
echo ==========================================
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker was not found. Please install and start Docker Desktop first.
    pause
    exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running.
    echo         Start Docker Desktop, wait until it is ready, then run this script again.
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [INFO] Created .env from .env.example.
        echo        You can edit .env later to add model, OCR, or web search keys.
        echo.
    )
)

set "PAGECHAT_HTTP_PORT=8080"
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /I "%%A"=="PAGECHAT_HTTP_PORT" set "PAGECHAT_HTTP_PORT=%%B"
    )
)

echo [1/3] Starting PageChat containers...
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start PageChat.
    echo         Run logs-pagechat-docker.bat for details.
    pause
    exit /b 1
)

echo.
echo [2/3] Current container status:
docker compose ps

echo.
echo [3/3] Opening PageChat...
start "" "http://localhost:%PAGECHAT_HTTP_PORT%"

echo.
echo PageChat is starting at http://localhost:%PAGECHAT_HTTP_PORT%
echo Backend health check: http://localhost:%PAGECHAT_HTTP_PORT%/health
echo.
pause
