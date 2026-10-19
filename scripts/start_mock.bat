@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" mock_service\server.py
pause
