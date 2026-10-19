@echo off
cd /d "%~dp0..\backend"
"..\.venv\Scripts\python.exe" manage.py notification_worker
pause
