@echo off
cd /d "%~dp0"
call setup.bat
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m lacuna %*
