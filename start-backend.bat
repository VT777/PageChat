@echo off
chcp 65001 >nul
setlocal EnableExtensions

title PageChat Backend (Worktree)

set "PROJECT_DIR=%~dp0"
for %%I in ("%PROJECT_DIR%") do set "PROJECT_DIR=%%~fI"
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "PYTHON_EXE=%BACKEND_DIR%\venv\Scripts\python.exe"
set "ENV_FILE=%BACKEND_DIR%\.env"
set "HOST=0.0.0.0"
set "PORT=8000"

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
    echo [ERROR] Python venv not found.
    echo         %PYTHON_EXE%
    echo Create it with:
    echo         cd backend
    echo         python -m venv venv
    echo         venv\Scripts\activate
    echo         pip install -r requirements.txt
    pause
    exit /b 1
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
