# Copia o atalho JARVIS Dashboard pra pasta de inicializacao do Windows
$ErrorActionPreference = 'Stop'

$sourceShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'JARVIS Dashboard.lnk'
$startupDir = [Environment]::GetFolderPath('Startup')   # shell:startup
$destShortcut = Join-Path $startupDir 'JARVIS Dashboard.lnk'

if (-not (Test-Path $sourceShortcut)) {
  Write-Host "ERRO: atalho fonte nao encontrado em $sourceShortcut"
  Write-Host "Execute primeiro create-shortcut.ps1"
  exit 1
}

Copy-Item -Path $sourceShortcut -Destination $destShortcut -Force
Write-Host "Atalho copiado para pasta de inicializacao:"
Write-Host "  $destShortcut"
Write-Host ""
Write-Host "O JARVIS sera iniciado automaticamente toda vez que o Windows iniciar."
Write-Host "Para desativar: Delete o atalho acima, ou rode:"
Write-Host "  Remove-Item '$destShortcut'"