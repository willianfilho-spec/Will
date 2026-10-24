@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv
  if errorlevel 1 (
    echo Python 3 nao encontrado. Instale em https://www.python.org/downloads/ e marque "Add python.exe to PATH".
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
python -m streamlit run app.py
pause
