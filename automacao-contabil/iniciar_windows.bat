@echo off
rem Abre a interface de conferencia no navegador deste computador.
rem Ajuste a pasta de dados abaixo se ela nao for C:\Contabil\dados.
cd /d "%~dp0"
set MOTOR_CONTABIL_DADOS=C:\Contabil\dados
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente nao instalado. Siga o passo 3 do INSTALACAO.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py
pause
