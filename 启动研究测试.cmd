@echo off
setlocal
cd /d "%~dp0"
python -B src\research_preview.py --profile "%~dp0local-notes\research-preview"
if errorlevel 1 pause
