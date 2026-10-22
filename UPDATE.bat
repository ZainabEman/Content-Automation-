@echo off
rem Double-click to get the newest version of Content Automation. Safe to run any time:
rem it never resets, stashes or deletes anything; with local changes it stops and asks for help.
rem No labels or goto: this file must also run with LF line endings (see SETUP.bat).
setlocal
cd /d "%~dp0"
set "STEP=ok"
echo === Content Automation update ===
echo Folder: %CD%
echo.
git --version >nul 2>nul || set "STEP=nogit"
if "%STEP%"=="ok" git diff --quiet HEAD -- || set "STEP=local"
if "%STEP%"=="ok" echo Step 1 of 3: getting the newest version with git pull ...
if "%STEP%"=="ok" git pull --ff-only || set "STEP=pull"
if "%STEP%"=="ok" echo Step 2 of 3: installing what changed with uv sync ...
if "%STEP%"=="ok" uv sync || set "STEP=sync"
if "%STEP%"=="ok" echo Step 3 of 3: checking that the app starts with uv run ca --help ...
if "%STEP%"=="ok" uv run ca --help >nul 2>nul || set "STEP=check"
echo.
if "%STEP%"=="ok" echo Update OK.
if "%STEP%"=="nogit" echo ERROR: Git is not installed. Double-click SETUP.bat first, then UPDATE.bat again.
if "%STEP%"=="local" echo STOPPED: files of the project were changed on this PC, so nothing was updated:
if "%STEP%"=="local" git status --short --untracked-files=no
if "%STEP%"=="local" echo Nothing was reset or deleted. Please send this screen to Zainu.
if "%STEP%"=="pull" echo ERROR: git pull failed, see the lines above. Nothing was reset or deleted.
if "%STEP%"=="pull" echo Please send this screen to Zainu.
if "%STEP%"=="sync" echo ERROR: uv sync failed. Check the internet connection and run UPDATE.bat again.
if "%STEP%"=="sync" echo If it fails again, double-click SETUP.bat, then send this screen to Zainu.
if "%STEP%"=="check" echo ERROR: the app does not start. Double-click SETUP.bat, then UPDATE.bat again.
if "%STEP%"=="check" echo If it fails again, please send this screen to Zainu.
echo.
pause
