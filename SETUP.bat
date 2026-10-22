@echo off
rem Double-click this file to set up Content Automation on this PC. Safe to run again.
rem Inside the project folder it installs Git, uv, Python, the app and FFmpeg, creates .env and
rem the data folders, then checks everything (setup.ps1 does the work).
rem On its own (e.g. downloaded from GitHub before cloning) it installs Git only.
rem No labels or goto: this file must also run with LF line endings (a raw GitHub download).
setlocal
cd /d "%~dp0"
if exist "%~dp0setup.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
) else (
    echo This SETUP.bat is not inside the project folder, so it installs Git only.
    where git >nul 2>nul
    if errorlevel 1 (
        where winget >nul 2>nul
        if errorlevel 1 (
            echo   PROBLEM  winget is missing, so Git cannot be installed automatically.
            echo            Install "App Installer" from the Microsoft Store and run SETUP.bat again,
            echo            or install Git by hand: https://git-scm.com/download/win
        ) else (
            echo   Installing Git with winget. If Windows asks for permission, click Yes.
            winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
            echo   Done. Close this window before you continue.
        )
    ) else (
        echo   OK       Git is already installed.
    )
    echo.
    echo Next: clone the project, then double-click SETUP.bat inside the cloned folder.
    echo See HOW-TO-INSTALL.txt, step 2.
)
echo.
pause
