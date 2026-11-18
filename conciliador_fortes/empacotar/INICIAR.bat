@echo off
chcp 65001 >nul
title Conciliador - versao de teste
cd /d "%~dp0"
echo Iniciando o Conciliador. Aguarde, o navegador vai abrir sozinho...
"%~dp0python\python.exe" "%~dp0app\scripts\iniciar_mvp.py"
if errorlevel 1 (
  echo.
  echo Algo deu errado. Tire um print desta tela e envie para quem preparou o teste.
  pause
)
