@echo off
chcp 65001 >nul
setlocal

title PageChat Backend

set "PROJECT_DIR=D:\projects\page_chat"
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "PYTHON_EXE=%BACKEND_DIR%\venv\Scripts\python.exe"
set "HOST=0.0.0.0"
set "PORT=8000"

echo ==========================================
echo   PageChat Backend
echo ==========================================
echo.

if not exist "%BACKEND_DIR%" (
    echo [ERROR] Backend directory not found:
    echo         %BACKEND_DIR%
    echo.
    pause
    exit /b 1
)

cd /d "%BACKEND_DIR%" || (
    echo [ERROR] Failed to enter backend directory.
    echo.
    pause
    exit /b 1
)

echo [1/2] Checking virtual environment...
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment not found:
    echo         %PYTHON_EXE%
    echo.
    echo Please create/install the backend venv first.
    pause
    exit /b 1
)
echo       OK %PYTHON_EXE%
echo.

echo [2/3] Checking port %PORT%...
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    set "PORT_PID=%%P"
    goto :PORT_CHECK_DONE
)
:PORT_CHECK_DONE

if defined PORT_PID (
    echo [WARNING] Port %PORT% is already in use by PID %PORT_PID%.
    echo.
    tasklist /FI "PID eq %PORT_PID%"
    echo.

    echo [INFO] Checking whether the existing backend is healthy...
    "%PYTHON_EXE%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%PORT%/health', timeout=3).read(); print('      OK Existing backend is already running at http://localhost:%PORT%')" 2>nul
    if not errorlevel 1 (
        echo.
        echo [INFO] No new backend was started because the service is already available.
        echo       Press Ctrl+C in the existing backend window to stop it.
        pause
        exit /b 0
    )

    echo [WARNING] Port %PORT% is occupied, but health check failed.
    choice /C YN /N /M "Stop the occupying process and start backend? [Y/N]: "
    if errorlevel 2 (
        echo.
        echo [INFO] Backend was not started. Close the existing process or choose Y next time.
        pause
        exit /b 1
    )

    echo.
    echo [INFO] Stopping PID %PORT_PID% and its child processes...
    taskkill /PID %PORT_PID% /T /F
    if errorlevel 1 (
        echo [ERROR] Failed to stop PID %PORT_PID%.
        pause
        exit /b 1
    )

    echo [INFO] Waiting for port %PORT% to be released...
    for /L %%I in (1,1,10) do (
        timeout /t 1 /nobreak >nul
        netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
        if errorlevel 1 goto :PORT_RELEASED
    )

    echo [ERROR] Port %PORT% is still in use after stopping PID %PORT_PID%.
    echo         A parent monitor process may have restarted the backend.
    echo         Please close the old backend cmd window, then run this script again.
    pause
    exit /b 1

    :PORT_RELEASED
    echo       OK Port %PORT% released
) else (
    echo       OK Port %PORT% is available
)
echo.

echo [3/3] Starting backend server...
echo       URL:      http://localhost:%PORT%
echo       API Docs: http://localhost:%PORT%/docs
echo       Press Ctrl+C to stop.
echo.

"%PYTHON_EXE%" -m uvicorn app.main:app --host %HOST% --port %PORT%

echo.
echo [INFO] Backend process exited.
pause
