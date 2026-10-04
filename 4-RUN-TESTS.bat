@echo off
title MineTrace tests
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0minetrace-backend"
if not exist venv\Scripts\python.exe (
  echo  Run 1-SETUP.bat first.
  pause
  exit /b 1
)
venv\Scripts\python.exe -m unittest discover tests -v
pause
