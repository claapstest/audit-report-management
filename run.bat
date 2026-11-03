@echo off
setlocal
cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing/checking dependencies...
pip install -q -r requirements.txt

if not exist data mkdir data

echo.
echo ========================================================
echo        Audit Report Stamping - HR Portal
echo ========================================================
echo Open http://localhost:8000 on this PC.
echo Or access from office network: http://YOUR-LAN-IP:8000
echo Default login: hr / hr123  (or demo / demo123)
echo Press Ctrl+C to stop the server.
echo ========================================================
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000
