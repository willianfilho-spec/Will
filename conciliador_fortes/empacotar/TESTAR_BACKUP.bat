@echo off
chcp 65001 >nul
title Conciliador - teste de backup e restauracao
cd /d "%~dp0"
echo Faz um backup dos dados, restaura numa pasta temporaria e compara com o original.
echo Feche o Conciliador antes (janela preta do INICIAR).
echo.
"%~dp0python\python.exe" "%~dp0app\scripts\teste_restauracao.py" --data-dir "%~dp0dados" --saida "%~dp0resultado_teste_backup.json"
echo.
echo Guarde o arquivo resultado_teste_backup.json: ele e a evidencia do teste de backup.
pause
