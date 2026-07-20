# JARVIS Memory  Obsidian — Sync Script
#
# Mirror C:\Users\paule\Projects\jarvis-ai-assistant\Memory\ → vault do Obsidian.
# Quando o JARVIS atualiza qualquer arquivo .md de memoria, rodar isso no
# PowerShell pra ter a versao mais recente no celular tambem.
#
# Como rodar:
#   .\sync-jarvis-to-obsidian.ps1
#
# Para rodar automaticamente (a cada commit do JARVIS), adicionar um hook
# em .git/hooks/post-commit (veja README no fim).

[CmdletBinding()]
param(
    [string]$JarvisMemory = "C:\Users\paule\Projects\jarvis-ai-assistant\Memory",
    [string]$ObsidianVault = "C:\Users\paule\Documents\ObsidianVault\02-Projetos\JARVIS\Memory",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $JarvisMemory)) {
    Write-Host "[ERRO] Pasta JARVIS Memory nao encontrada: $JarvisMemory" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $ObsidianVault)) {
    Write-Host "[INFO] Criando pasta destino: $ObsidianVault" -ForegroundColor Yellow
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path "$ObsidianVault\Projects" | Out-Null
    }
}

# ─── Copia todos os .md de Memory/ (raiz) ───
$rootFiles = Get-ChildItem -Path $JarvisMemory -Filter "*.md" -File
$destRoot = $ObsidianVault

foreach ($f in $rootFiles) {
    $dest = Join-Path $destRoot $f.Name
    if ($DryRun) {
        Write-Host "[DRY] copiaria $($f.Name) -> $dest"
    } else {
        Copy-Item -Path $f.FullName -Destination $dest -Force
        Write-Host "[OK] $($f.Name)" -ForegroundColor Green
    }
}

# ─── Copia todos os .md de Memory/Projects/ ───
$srcProjects = Join-Path $JarvisMemory "Projects"
$dstProjects = Join-Path $ObsidianVault "Projects"

if (Test-Path $srcProjects) {
    if (-not (Test-Path $dstProjects)) {
        New-Item -ItemType Directory -Force -Path $dstProjects | Out-Null
    }
    $projFiles = Get-ChildItem -Path $srcProjects -Filter "*.md" -File
    foreach ($f in $projFiles) {
        $dest = Join-Path $dstProjects $f.Name
        if ($DryRun) {
            Write-Host "[DRY] copiaria Projects\$($f.Name) -> $dest"
        } else {
            Copy-Item -Path $f.FullName -Destination $dest -Force
            Write-Host "[OK] Projects/$($f.Name)" -ForegroundColor Green
        }
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Sync JARVIS  ObsidianVault concluido" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Origem : $JarvisMemory"
Write-Host "Destino: $ObsidianVault"
Write-Host "Arquivos: $((Get-ChildItem $ObsidianVault -Recurse -Filter *.md).Count) .md copiados"
Write-Host ""

# ─── Hook automatico opcional ───
$hookPath = Join-Path (Split-Path $JarvisMemory -Parent) ".git\hooks\post-commit"
$hookSnippet = @"
# Auto-sync Memory to Obsidian after every commit
powershell.exe -ExecutionPolicy Bypass -File "$PSCommandPath" -ErrorAction SilentlyContinue
"@
Write-Host "Para sincronizar automaticamente apos cada commit:" -ForegroundColor Yellow
Write-Host "  1. Crie o arquivo: $hookPath" -ForegroundColor Yellow
Write-Host "  2. Cole:" -ForegroundColor Yellow
Write-Host "     $hookSnippet"