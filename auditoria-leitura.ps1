# AUDITORIA WINDOWS 11 - FASE 1 (SOMENTE LEITURA)
# Nao encerra processos, nao apaga, nao move, nao altera configuracoes.
# Unica escrita: o arquivo de relatorio na Area de Trabalho.
# Como usar: abra o PowerShell (de preferencia como Administrador), va ate a pasta do arquivo e rode:
#   powershell -ExecutionPolicy Bypass -File .\auditoria-leitura.ps1
# Obs.: este script nao foi testado em um Windows real por quem o escreveu.

$ErrorActionPreference = 'SilentlyContinue'
$saida = Join-Path ([Environment]::GetFolderPath('Desktop')) ("relatorio-auditoria-{0:yyyyMMdd-HHmm}.txt" -f (Get-Date))
$perfil = $env:USERPROFILE
$ehAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Secao($t) { "`r`n==================== $t ====================" }
function Tam($b) { if ($b -ge 1GB) { '{0:N2} GB' -f ($b/1GB) } else { '{0:N1} MB' -f ($b/1MB) } }

& {
"Executado como Administrador: $ehAdmin  (se False, alguns dados saem como 'nao verificado')"
"Data/hora: $(Get-Date)"

Secao 'SISTEMA (Get-CimInstance)'
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
"Modelo: $($cs.Manufacturer) $($cs.Model)"
"Windows: $($os.Caption) build $($os.BuildNumber)"
"CPU: $($cpu.Name)  nucleos logicos: $($cpu.NumberOfLogicalProcessors)"
"RAM total: $(Tam ($cs.TotalPhysicalMemory))   livre agora: $(Tam ($os.FreePhysicalMemory*1KB))"
"Ligado desde: $($os.LastBootUpTime)"
"Plano de energia (powercfg /getactivescheme): $(powercfg /getactivescheme)"

Secao 'MODULO 3 - DISCOS'
Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
  "{0}  total {1}  usado {2}  livre {3}" -f $_.DeviceID, (Tam $_.Size), (Tam ($_.Size-$_.FreeSpace)), (Tam $_.FreeSpace)
}
Get-PhysicalDisk | ForEach-Object { "Disco fisico: $($_.FriendlyName) tipo $($_.MediaType) saude $($_.HealthStatus)" }

Secao 'MODULO 1 - PROCESSOS (3 leituras, 10 s de intervalo; demora ~30 s)'
$n = $cpu.NumberOfLogicalProcessors
$amostras = @()
1..3 | ForEach-Object {
  $a = Get-Process | Select-Object Id, ProcessName, CPU, WorkingSet64
  Start-Sleep -Seconds 10
  $b = Get-Process | Select-Object Id, ProcessName, CPU, WorkingSet64
  $ia = @{}; $a | ForEach-Object { $ia[$_.Id] = $_.CPU }
  $amostras += ,($b | ForEach-Object {
    if ($ia.ContainsKey($_.Id) -and $null -ne $_.CPU) {
      [pscustomobject]@{ Id=$_.Id; Nome=$_.ProcessName; Cpu=(($_.CPU-$ia[$_.Id])/10/$n*100); Ram=$_.WorkingSet64 }
    } })
}
$todos = $amostras | ForEach-Object { $_ } | Where-Object { $_ }
$medias = $todos | Group-Object Id | ForEach-Object {
  [pscustomobject]@{ Id=$_.Name; Nome=$_.Group[0].Nome
    CpuMedia=[math]::Round(($_.Group | Measure-Object Cpu -Average).Average,1)
    RamPct=[math]::Round((($_.Group | Measure-Object Ram -Average).Average)/$cs.TotalPhysicalMemory*100,1)
    RamMB=[math]::Round((($_.Group | Measure-Object Ram -Average).Average)/1MB,0) } }
"Processos com media acima de 5% de CPU ou 5% de RAM:"
$medias | Where-Object { $_.CpuMedia -gt 5 -or $_.RamPct -gt 5 } | ForEach-Object {
  $p = Get-Process -Id $_.Id
  $caminho = $p.Path
  $sig = if ($caminho) { Get-AuthenticodeSignature $caminho } else { $null }
  "{0} (PID {1}) CPU {2}% RAM {3} MB ({4}%) | caminho: {5} | editor: {6} | assinatura: {7}" -f `
    $_.Nome, $_.Id, $_.CpuMedia, $_.RamMB, $_.RamPct,
    $(if ($caminho) {$caminho} else {'nao verificado (sem permissao)'}),
    $(if ($p.Company) {$p.Company} else {'nao informado'}),
    $(if ($sig) {$sig.Status} else {'nao verificado'})
}

Secao 'MODULO 2 - INICIALIZACAO'
"-- Win32_StartupCommand (Inicializar / pastas / Run):"
Get-CimInstance Win32_StartupCommand | ForEach-Object { "{0} | {1} | {2}" -f $_.Name, $_.Command, $_.Location }
"-- Chaves Run (HKLM/HKCU, 64 e 32 bits):"
'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' | ForEach-Object {
  $k = $_; (Get-ItemProperty $k).PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } | ForEach-Object { "{0} | {1} | {2}" -f $k, $_.Name, $_.Value } }
"-- Tarefas agendadas disparadas no logon:"
Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' -and ($_.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }) } |
  ForEach-Object { "{0}{1} | {2}" -f $_.TaskPath, $_.TaskName, (($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join '; ') }

Secao 'MODULO 3 - ARMAZENAMENTO (no perfil do usuario)'
"-- Pastas de primeiro nivel do perfil, maiores primeiro (top 20):"
Get-ChildItem $perfil -Directory -Force | ForEach-Object {
  [pscustomobject]@{ Pasta=$_.FullName; Bytes=(Get-ChildItem $_.FullName -Recurse -File -Force | Measure-Object Length -Sum).Sum } } |
  Sort-Object Bytes -Descending | Select-Object -First 20 | ForEach-Object { "{0}  {1}" -f (Tam $_.Bytes), $_.Pasta }
"-- 20 maiores arquivos do perfil:"
Get-ChildItem $perfil -Recurse -File -Force | Sort-Object Length -Descending | Select-Object -First 20 |
  ForEach-Object { "{0}  {1}" -f (Tam $_.Length), $_.FullName }
$dl = Join-Path $perfil 'Downloads'
$antigos = Get-ChildItem $dl -Recurse -File -Force | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) }
"-- Downloads sem modificacao ha mais de 90 dias: $($antigos.Count) arquivos, total $(Tam (($antigos | Measure-Object Length -Sum).Sum))"
"-- Instaladores (.exe .msi .iso .zip) em Downloads e Area de Trabalho:"
$pastasInst = @($dl, [Environment]::GetFolderPath('Desktop'))
Get-ChildItem $pastasInst -Recurse -File -Force -Include *.exe,*.msi,*.iso,*.zip | ForEach-Object { "{0}  {1}" -f (Tam $_.Length), $_.FullName }
"-- Fotos duplicadas por hash (Imagens, Downloads, Area de Trabalho):"
$pastasFoto = @([Environment]::GetFolderPath('MyPictures'), $dl, [Environment]::GetFolderPath('Desktop'))
$fotos = Get-ChildItem $pastasFoto -Recurse -File -Force -Include *.jpg,*.jpeg,*.png,*.heic,*.gif,*.bmp,*.webp
$recuperavel = 0
$fotos | Group-Object Length | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Group } |
  ForEach-Object { [pscustomobject]@{ Hash=(Get-FileHash $_.FullName -Algorithm SHA256).Hash; Arq=$_ } } |
  Group-Object Hash | Where-Object { $_.Count -gt 1 } | ForEach-Object {
    $recuperavel += $_.Group[0].Arq.Length * ($_.Count-1)
    "Grupo (hash " + $_.Name.Substring(0,12) + "):"; $_.Group | ForEach-Object { "   " + $_.Arq.FullName } }
"Espaco recuperavel se so uma copia de cada ficasse: $(Tam $recuperavel)"
"-- Tamanhos (sem apagar):"
$temp = (Get-ChildItem $env:TEMP -Recurse -File -Force | Measure-Object Length -Sum).Sum
"Temp do usuario ($env:TEMP): $(Tam $temp)"
$wutemp = (Get-ChildItem 'C:\Windows\Temp' -Recurse -File -Force | Measure-Object Length -Sum).Sum
"C:\Windows\Temp: $(Tam $wutemp)"
$wu = (Get-ChildItem 'C:\Windows\SoftwareDistribution\Download' -Recurse -File -Force | Measure-Object Length -Sum).Sum
"Cache de atualizacoes (SoftwareDistribution\Download): $(Tam $wu)"
$lix = (Get-ChildItem 'C:\$Recycle.Bin' -Recurse -File -Force | Measure-Object Length -Sum).Sum
"Lixeira (C:): $(if ($ehAdmin) { Tam $lix } else { 'nao verificado (precisa de Administrador)' })"

Secao 'MODULO 4 - PROGRAMAS INSTALADOS'
"(Windows nao registra data de ultimo uso de forma confiavel: tudo abaixo e 'sem dado de uso')"
'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' |
  ForEach-Object { Get-ItemProperty $_ } | Where-Object { $_.DisplayName } | Sort-Object DisplayName | ForEach-Object {
    "{0} | versao {1} | instalado em {2} | {3}" -f $_.DisplayName, $_.DisplayVersion,
      $(if ($_.InstallDate) {$_.InstallDate} else {'sem data'}),
      $(if ($_.EstimatedSize) {Tam ($_.EstimatedSize*1KB)} else {'sem tamanho'}) }

Secao 'MODULO 5 - SEGURANCA'
"-- Defender (Get-MpComputerStatus):"
$mp = Get-MpComputerStatus
if ($mp) { "Antivirus ativo: $($mp.AntivirusEnabled) | Protecao em tempo real: $($mp.RealTimeProtectionEnabled) | Definicoes de: $($mp.AntivirusSignatureLastUpdated) | Ultima verificacao rapida: $($mp.QuickScanEndTime) | Ultima completa: $($mp.FullScanEndTime)" } else { 'nao verificado' }
"-- Firewall:"
Get-NetFirewallProfile | ForEach-Object { "{0}: ativo={1}" -f $_.Name, $_.Enabled }
"-- Ultimas atualizacoes instaladas (Get-HotFix):"
Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 5 | ForEach-Object { "{0} em {1}" -f $_.HotFixID, $_.InstalledOn }
"Atualizacoes pendentes: nao verificado por este script (veja Configuracoes > Windows Update)"
"-- Processos rodando de Temp/AppData ou sem assinatura valida:"
Get-Process | Where-Object { $_.Path } | ForEach-Object {
  $s = Get-AuthenticodeSignature $_.Path
  if ($_.Path -match '\\Temp\\|\\AppData\\' -or $s.Status -ne 'Valid') { "{0} (PID {1}) | {2} | assinatura: {3}" -f $_.ProcessName, $_.Id, $_.Path, $s.Status } }
"-- Conexoes de rede estabelecidas por processo:"
Get-NetTCPConnection -State Established | ForEach-Object {
  $p = Get-Process -Id $_.OwningProcess; "{0} (PID {1}) -> {2}:{3}" -f $p.ProcessName, $_.OwningProcess, $_.RemoteAddress, $_.RemotePort } | Sort-Object -Unique
"-- Extensoes de navegador: nao verificado por este script (abra chrome://extensions e edge://extensions e me envie os nomes)"

Secao 'MODULO 6 - BACKUP'
"-- Pontos de restauracao (Get-ComputerRestorePoint):"
$pr = Get-ComputerRestorePoint
if ($pr) { $pr | ForEach-Object { "{0} | {1}" -f $_.CreationTime, $_.Description } } else { 'nenhum encontrado ou nao verificado (pode exigir Administrador)' }
"-- OneDrive: pasta $env:OneDrive"
if ($env:OneDrive) { "Existe: $(Test-Path $env:OneDrive)" } else { 'variavel OneDrive nao definida' }
"-- Backup do Windows / Historico de Arquivos: nao verificado por este script (veja Painel de Controle > Historico de Arquivos)"
} *>&1 | Out-File -FilePath $saida -Encoding UTF8

"Pronto. Relatorio salvo em: $saida"
