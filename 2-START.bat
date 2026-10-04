@echo off
title MineTrace
cd /d "%~dp0"

if not exist "minetrace-backend\venv\Scripts\python.exe" (
  echo  Run 1-SETUP.bat first.
  pause
  exit /b 1
)
if not exist "minetrace-frontend\node_modules" (
  echo  Run 1-SETUP.bat first.
  pause
  exit /b 1
)

echo  Starting MineTrace...
start "MineTrace API - keep this open" /D "%~dp0minetrace-backend" cmd /k venv\Scripts\python.exe -m uvicorn main:app --port 8000
start "MineTrace App - keep this open" /D "%~dp0minetrace-frontend" cmd /k npm run dev

echo  Opening your browser in a few seconds...
timeout /t 8 /nobreak >nul
start "" http://localhost:5173

echo.
echo  MineTrace is running. To stop it, close the two black windows.
timeout /t 5 >nul
