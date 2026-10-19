@echo off
cd /d "%~dp0.."
".venv\Scripts\streamlit.exe" run frontend\app.py --server.port 8502
pause
