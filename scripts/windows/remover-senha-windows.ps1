#Requires -RunAsAdministrator
<#
  remover-senha-windows.ps1

  Faz o Windows entrar direto na area de trabalho, sem pedir senha, para o
  usuario informado (padrao: o usuario logado).

  - Conta LOCAL: define a senha como vazia.
  - Conta MICROSOFT: o Windows nao aceita senha vazia nesse tipo de conta.
    O script libera a opcao de login automatico e abre o netplwiz, onde voce
    desmarca a caixa e digita a senha uma vez (ela fica guardada como segredo
    do sistema, nao em texto puro).
  - Nos dois casos: deixa de pedir senha ao voltar da suspensao.

  Uso (PowerShell aberto como administrador):
    powershell -ExecutionPolicy Bypass -File .\remover-senha-windows.ps1
    powershell -ExecutionPolicy Bypass -File .\remover-senha-windows.ps1 -Usuario "Maria"

  Para desfazer: reverter-senha-windows.ps1
#>
param(
    [string]$Usuario = $env:USERNAME
)

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "ATENCAO: sem senha, qualquer pessoa com acesso fisico ao computador"
Write-Host "abre sua sessao, seus arquivos e os navegadores ja logados."
$ok = Read-Host "Continuar para o usuario '$Usuario'? (S/N)"
if ($ok -notmatch '^[sS]') { Write-Host "Cancelado."; exit 0 }

$conta = Get-LocalUser -Name $Usuario -ErrorAction SilentlyContinue
if (-not $conta) {
    Write-Host "Usuario '$Usuario' nao encontrado entre as contas locais."
    Write-Host "Contas de dominio/empresa (Azure AD/Entra) nao sao tratadas por este script."
    exit 1
}

# 1) Libera a caixa "Os usuarios devem digitar um nome de usuario e senha" no
#    netplwiz e desliga a exigencia de entrar so com Windows Hello (PIN).
$chaveHello = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device'
if (-not (Test-Path $chaveHello)) { New-Item -Path $chaveHello -Force | Out-Null }
Set-ItemProperty -Path $chaveHello -Name 'DevicePasswordLessBuildVersion' -Value 0 -Type DWord

# 2) Nao pedir senha ao voltar da suspensao (na tomada e na bateria).
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 0
powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 0
powercfg /SETACTIVE SCHEME_CURRENT

# 3) Remove a senha conforme o tipo de conta.
if ("$($conta.PrincipalSource)" -eq 'MicrosoftAccount') {
    Write-Host ""
    Write-Host "Conta Microsoft detectada: nao da para deixar a senha vazia."
    Write-Host "Na janela que vai abrir:"
    Write-Host "  1. Selecione seu usuario."
    Write-Host "  2. Desmarque 'Os usuarios devem digitar um nome de usuario e uma senha'."
    Write-Host "  3. Clique em OK e digite a senha da conta Microsoft duas vezes."
    Start-Process netplwiz
}
else {
    try {
        $adsi = [ADSI]"WinNT://$env:COMPUTERNAME/$Usuario,user"
        $adsi.SetPassword('')
        $adsi.SetInfo()
        Write-Host "Senha da conta local '$Usuario' removida."
    }
    catch {
        Write-Host "Nao foi possivel deixar a senha vazia: $($_.Exception.Message)"
        Write-Host "Causa provavel: politica de tamanho minimo de senha (comum em PCs de empresa)."
        exit 1
    }
}

Write-Host ""
Write-Host "Se voce usa PIN, remova-o em Configuracoes > Contas > Opcoes de entrada."
Write-Host "Reinicie o computador para testar."
