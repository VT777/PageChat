@echo off
setlocal
set ACTION=%1
if "%ACTION%"=="" set ACTION=restart

powershell -ExecutionPolicy Bypass -File "%~dp0manage_services.ps1" %ACTION%

echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
