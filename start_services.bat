@echo off
setlocal

call "%~dp0manage_services.bat" restart

echo.
echo Services started with single-instance guard.
pause
