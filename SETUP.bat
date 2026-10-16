@echo off
rem Double-click this file to set up Content Automation on this laptop.
rem Safe to run again. It installs uv, Python, the app and FFmpeg, then checks everything.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
