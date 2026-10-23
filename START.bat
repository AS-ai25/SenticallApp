@echo off
cd /d "%~dp0"
echo Starting Senticall on http://127.0.0.1:8050 ...
start "" http://127.0.0.1:8050
python -m uvicorn app.main:app --host 127.0.0.1 --port 8050
