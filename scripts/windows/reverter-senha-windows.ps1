#Requires -RunAsAdministrator
<#
  reverter-senha-windows.ps1

  Desfaz o remover-senha-windows.ps1.

  Uso (PowerShell aberto como administrador):
    powershell -ExecutionPolicy Bypass -File .\reverter-senha-windows.ps1
#>
param(
    [string]$Usuario = $env:USERNAME
)

$ErrorActionPreference = 'Stop'

# Volta a pedir senha ao sair da suspensao.
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 1
powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 1
powercfg /SETACTIVE SCHEME_CURRENT

$conta = Get-LocalUser -Name $Usuario -ErrorAction SilentlyContinue
if ($conta -and "$($conta.PrincipalSource)" -eq 'MicrosoftAccount') {
    Write-Host "Conta Microsoft: no netplwiz, MARQUE de novo a caixa"
    Write-Host "'Os usuarios devem digitar um nome de usuario e uma senha' e clique OK."
    Start-Process netplwiz
}
elseif ($conta) {
    Write-Host "Digite a nova senha para '$Usuario':"
    net user $Usuario *
}

Write-Host "Pronto. Reinicie o computador para testar."
