@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-base.txt -r requirements-win.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
