@echo off
title MineTrace data update
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0minetrace-backend"
if not exist venv\Scripts\python.exe (
  echo  Run 1-SETUP.bat first.
  pause
  exit /b 1
)
echo  Fetching any missing trade data. Needs internet.
venv\Scripts\python.exe ingest_comtrade.py
venv\Scripts\python.exe ingest_opensanctions.py
echo.
echo  Done. Restart MineTrace with 2-START.bat to see the new data.
pause
