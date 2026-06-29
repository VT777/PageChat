@echo off
chcp 65001 >nul
setlocal EnableExtensions

title PageChat Backend (Worktree)

set "PROJECT_DIR=%~dp0"
for %%I in ("%PROJECT_DIR%") do set "PROJECT_DIR=%%~fI"
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "LEGACY_PROJECT_DIR=D:\projects\page_chat"
set "PYTHON_EXE=%BACKEND_DIR%\venv\Scripts\python.exe"
set "LEGACY_PYTHON_EXE=%LEGACY_PROJECT_DIR%\backend\venv\Scripts\python.exe"
set "ENV_FILE=%BACKEND_DIR%\.env"
set "LEGACY_ENV_FILE=%LEGACY_PROJECT_DIR%\backend\.env"
set "HOST=0.0.0.0"
set "PORT=8000"

if not exist "%ENV_FILE%" (
    if exist "%LEGACY_ENV_FILE%" set "ENV_FILE=%LEGACY_ENV_FILE%"
)

echo ==========================================
echo   PageChat Backend (Worktree)
echo ==========================================
echo.
echo Source: %PROJECT_DIR%
git -C "%PROJECT_DIR%" branch --show-current 2>nul
echo.

if not exist "%BACKEND_DIR%" (
    echo [ERROR] Backend directory not found:
    echo         %BACKEND_DIR%
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    if exist "%LEGACY_PYTHON_EXE%" (
        set "PYTHON_EXE=%LEGACY_PYTHON_EXE%"
    ) else (
        echo [ERROR] Python venv not found.
        echo         %PYTHON_EXE%
        echo         %LEGACY_PYTHON_EXE%
        pause
        exit /b 1
    )
)

cd /d "%BACKEND_DIR%" || (
    echo [ERROR] Failed to enter backend directory.
    pause
    exit /b 1
)

echo Python: %PYTHON_EXE%
echo Env:    %ENV_FILE%
echo URL:    http://localhost:%PORT%
echo.

"%PYTHON_EXE%" -c "from dotenv import load_dotenv; import uvicorn; load_dotenv(r'%ENV_FILE%', override=False); uvicorn.run('app.main:app', host='%HOST%', port=%PORT%)"

echo.
echo [INFO] Backend process exited.
pause
