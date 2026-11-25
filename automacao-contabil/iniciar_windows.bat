@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
  set "PYTHON=runtime\python.exe"
  if not defined MOTOR_CONTABIL_DADOS set "MOTOR_CONTABIL_DADOS=%LOCALAPPDATA%\Conciliador Fortes\dados"
) else (
  set "PYTHON=.venv\Scripts\python.exe"
  if not defined MOTOR_CONTABIL_DADOS set "MOTOR_CONTABIL_DADOS=C:\Contabil\dados"
)
if not exist "%PYTHON%" (
  echo Extraia o ZIP inteiro ou instale o ambiente conforme INSTALACAO.md.
  pause
  exit /b 1
)
"%PYTHON%" -s -m streamlit run app.py --server.address localhost
set "RESULTADO=%ERRORLEVEL%"
if not "%RESULTADO%"=="0" pause
exit /b %RESULTADO%
