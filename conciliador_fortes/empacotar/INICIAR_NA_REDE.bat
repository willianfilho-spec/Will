@echo off
chcp 65001 >nul
title Conciliador - versao de teste (rede interna)
cd /d "%~dp0"
echo ATENCAO: outras pessoas da MESMA rede poderao abrir o Conciliador.
echo Use somente em rede interna de confianca e com dados de teste. Nao ha HTTPS.
echo O Windows pode perguntar sobre o Firewall: permita apenas para rede PRIVADA.
echo.
pause
"%~dp0python\python.exe" "%~dp0app\scripts\iniciar_mvp.py" --rede
if errorlevel 1 (
  echo.
  echo Algo deu errado. Tire um print desta tela e envie para quem preparou o teste.
  pause
)
