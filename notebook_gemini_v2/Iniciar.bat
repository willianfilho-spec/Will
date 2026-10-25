@echo off
cd /d "%~dp0"
title Notebook de Pesquisa com Gemini
echo.
echo  Preparando o programa. Na primeira vez isso leva alguns minutos.
echo  NAO FECHE esta janela enquanto estiver usando o programa.
echo.

set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if "%PY%"=="" python --version >nul 2>&1 && set PY=python
if "%PY%"=="" goto sempython

if not exist .venv\Scripts\python.exe %PY% -m venv .venv
if not exist .venv\Scripts\python.exe goto erro

if not exist .venv\instalado.txt (
  echo  Instalando os componentes. Aguarde...
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\python -m pip install --quiet -r requirements.txt
  if errorlevel 1 goto erro
  echo ok> .venv\instalado.txt
)

echo  Abrindo o navegador. Se nao abrir, entre em http://localhost:8765
start "" /min cmd /c "timeout /t 6 >nul & start http://localhost:8765"
.venv\Scripts\python -m streamlit run app.py
echo.
echo  O programa foi encerrado. Se apareceu "Port 8765 is already in use", ele ja esta aberto
echo  em outra janela preta: feche as outras janelas pretas e de dois cliques aqui de novo.
pause
exit /b 0

:sempython
echo  O Python nao esta instalado neste computador.
echo.
echo   1. Vai abrir o site do Python. Baixe o instalador (botao amarelo).
echo   2. Na primeira tela do instalador, MARQUE a caixinha "Add python.exe to PATH".
echo   3. Clique em Install Now e espere terminar.
echo   4. Depois de dois cliques neste arquivo (Iniciar.bat) de novo.
start https://www.python.org/downloads/
pause
exit /b 1

:erro
echo.
echo  Algo deu errado na instalacao. Tire uma foto desta janela e envie para quem esta ajudando.
pause
exit /b 1
