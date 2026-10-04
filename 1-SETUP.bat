@echo off
title MineTrace setup
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo.
echo  ==============================================
echo   MineTrace setup - run this once
echo   Needs internet. Takes about 10 minutes.
echo  ==============================================
echo.

rem ---- find Python ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo  Python was not found. Install Python 3.10 or newer from python.org,
  echo  tick "Add Python to PATH" during install, then run this file again.
  pause
  exit /b 1
)

rem ---- find Node.js ----
where npm >nul 2>nul
if errorlevel 1 (
  echo  Node.js was not found. Install the LTS version from nodejs.org,
  echo  then run this file again.
  pause
  exit /b 1
)

echo  [1/5] Creating the Python environment...
cd minetrace-backend
if not exist venv\Scripts\python.exe %PY% -m venv venv
if not exist venv\Scripts\python.exe goto fail

echo  [2/5] Installing Python packages...
venv\Scripts\python.exe -m pip install --upgrade pip >nul
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo  [3/5] Downloading trade data from UN Comtrade. This takes a few minutes.
echo        If it stops, just run this file again - it continues where it left off.
venv\Scripts\python.exe ingest_comtrade.py
echo.

echo  [4/5] Downloading sanctions data from OpenSanctions...
venv\Scripts\python.exe ingest_opensanctions.py
if errorlevel 1 echo  Sanctions download failed. The app still works; rule R5 will show "could not run".
echo.

echo  [5/5] Installing the web app...
cd ..\minetrace-frontend
call npm install
if errorlevel 1 goto fail
call npm run textures
if errorlevel 1 echo  Globe images could not be saved locally. The app will load them online instead.

echo.
echo  ==============================================
echo   Setup finished. Now double-click 2-START.bat
echo  ==============================================
pause
exit /b 0

:fail
echo.
echo  Setup stopped because of an error above.
echo  Take a screenshot of this window and send it for help.
pause
exit /b 1
