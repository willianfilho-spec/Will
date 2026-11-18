@echo off
chcp 65001 >nul
title Conciliador - arquivo de teste do limite do historico
cd /d "%~dp0"
echo Gera um arquivo com 11 lancamentos de R$ 0,01 e historicos de 80 a 200 caracteres.
echo IMPORTE SOMENTE EM UMA EMPRESA DE TESTE DO FORTES.
echo.
set /p DEB=Codigo reduzido da conta de DEBITO (empresa de teste): 
set /p CRE=Codigo reduzido da conta de CREDITO (empresa de teste): 
set /p DAT=Data do lancamento (dd/mm/aaaa): 
"%~dp0python\python.exe" "%~dp0app\scripts\gerar_lote_homologacao.py" --debito %DEB% --credito %CRE% --data %DAT% --saida "%~dp0lote_teste_historico.csv"
echo.
echo Pronto. Importe o arquivo lote_teste_historico.csv no Fortes (empresa de teste)
echo e preencha a planilha lote_teste_historico_esperado.csv conforme o roteiro.
pause
