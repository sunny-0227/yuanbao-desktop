@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\build_exe.py %*
) else (
    python scripts\build_exe.py %*
)
if errorlevel 1 exit /b 1
pause
