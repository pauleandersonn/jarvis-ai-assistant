<#
.SYNOPSIS
  Configura a JARVIS_OPENAI_API_KEY de forma segura (Windows).

.DESCRIPTION
  - Persiste em HKCU\Environment via 'setx' (sobrevive a reboot).
  - Tambem atualiza a sessao atual do PowerShell.
  - Cria/atualiza .env no diretorio raiz do projeto (NUNCA commitar).
  - NUNCA mostra a chave inteira em log. Mascara como 'sk-abc...xyz'.
  - Se -ApiKey nao for passada, le interativamente de forma segura
    (host console com -AsSecureString -> converte e descarta).

.PARAMETER ApiKey
  A chave OpenAI. Se omitida, sera pedida via Read-Host -AsSecureString.

.PARAMETER EnvVar
  Nome da env var. Padrao: JARVIS_OPENAI_API_KEY.

.PARAMETER ProjectRoot
  Diretorio raiz do projeto (onde fica .env). Padrao:
    C:\Users\paule\Projects\jarvis-ai-assistant

.EXAMPLE
  .\Windows_Set-OpenAIKey.ps1 -ApiKey "sk-proj-..."
  .\Windows_Set-OpenAIKey.ps1           # pede a chave de forma segura
#>

[CmdletBinding()]
param(
    [string]$ApiKey,
    [string]$EnvVar = "JARVIS_OPENAI_API_KEY",
    [string]$ProjectRoot = "C:\Users\paule\Projects\jarvis-ai-assistant"
)

function _mask([string]$k) {
    if (-not $k -or $k.Length -le 8) { return "<empty>" }
    return "$($k.Substring(0, [Math]::Min(6, $k.Length)))...$($k.Substring($k.Length - 4))"
}

function _load_dotenv([string]$path) {
    $dict = @{}
    if (Test-Path $path) {
        Get-Content $path -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
            $k, $v = $line.Split("=", 2)
            $dict[$k.Trim()] = $v.Trim().Trim('"').Trim("'")
        }
    }
    return $dict
}

function _save_dotenv([string]$path, [hashtable]$dict) {
    $lines = @(
        "# .env do JARVIS - NAO commitar (git ignore cobre *.env, .env, .env.*)",
        "# Para obter uma chave OpenAI: https://platform.openai.com/api-keys",
        "# Voce tambem pode usar Groq, OpenRouter, DeepSeek ou Together mudando",
        "# JARVIS_OPENAI_BASE_URL em .env e usando a chave correspondente.",
        ""
    )
    foreach ($key in @("JARVIS_LLM_PROVIDER", "JARVIS_OPENAI_API_KEY",
                       "JARVIS_OPENAI_BASE_URL", "JARVIS_OPENAI_MODEL")) {
        if ($dict.ContainsKey($key) -and $dict[$key]) {
            $lines += "$key=$($dict[$key])"
        }
    }
    $lines | Set-Content -Path $path -Encoding UTF8 -Force
}

# Pega a chave
if (-not $ApiKey) {
    Write-Host ""
    Write-Host "  Insira sua chave OpenAI (a entrada fica ESCONDIDA no terminal):" -ForegroundColor Cyan
    $secure = Read-Host "  $EnvVar" -AsSecureString
    if (-not $secure -or $secure.Length -eq 0) {
        Write-Host "  Nada inserido - saindo sem alterar nada." -ForegroundColor Yellow
        exit 1
    }
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $ApiKey = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
    }
}

if (-not $ApiKey.Trim()) {
    Write-Host "  Chave vazia - cancelado." -ForegroundColor Yellow
    exit 1
}

# Persiste na sessao + via setx (Registry HKCU\Environment)
Write-Host ""
Write-Host "  [1/3] Definindo `$Env:$EnvVar na sessao atual..." -ForegroundColor Cyan
Set-Item -Path "Env:$EnvVar" -Value $ApiKey

Write-Host "  [2/3] Persistindo via setx (sobrevive a reboot)..." -ForegroundColor Cyan
# setx nao escapou com "$" no nome - usar cmd.exe
try {
    cmd.exe /c "setx $EnvVar `"$ApiKey`"" | Out-Null
    Write-Host "        setx OK" -ForegroundColor Green
} catch {
    Write-Host "        setx falhou (continua na sessao): $_" -ForegroundColor Yellow
}

# Atualiza .env na raiz do projeto
Write-Host "  [3/3] Atualizando .env em $ProjectRoot..." -ForegroundColor Cyan
if (-not (Test-Path $ProjectRoot)) {
    Write-Host "        Diretorio nao existe - pulando." -ForegroundColor Yellow
} else {
    $envPath = Join-Path $ProjectRoot ".env"
    $dot     = _load_dotenv $envPath
    $dot[$EnvVar] = $ApiKey
    # Forca provider = openai_cloud (sem chave nao funciona)
    if (-not $dot["JARVIS_LLM_PROVIDER"]) {
        $dot["JARVIS_LLM_PROVIDER"] = "openai_cloud"
    }
    _save_dotenv $envPath $dot
    Write-Host "        .env escrito" -ForegroundColor Green
}

# Testa a chave (HEAD /v1/models)
Write-Host ""
Write-Host "  Testando a chave em https://api.openai.com/v1/models ..." -ForegroundColor Cyan
try {
    $headers = @{ Authorization = "Bearer $ApiKey" }
    $resp    = Invoke-WebRequest -Uri "https://api.openai.com/v1/models" `
                                  -Headers $headers -Method Get `
                                  -TimeoutSec 10 -ErrorAction Stop
    if ($resp.StatusCode -eq 200) {
        Write-Host "  OK HTTP 200 - chave aceita." -ForegroundColor Green
    } else {
        Write-Host "  HTTP $($resp.StatusCode) - chave pode estar invalida." -ForegroundColor Yellow
    }
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code) {
        Write-Host "  HTTP $code - verifique a chave:" -ForegroundColor Yellow
        switch ($code) {
            401 { Write-Host "    401: chave invalida ou revogada."            -ForegroundColor Yellow }
            403 { Write-Host "    403: chave sem permissao para /v1/models."    -ForegroundColor Yellow }
            429 { Write-Host "    429: rate-limit; tente mais tarde."           -ForegroundColor Yellow }
            default { Write-Host "    Erro HTTP $code." -ForegroundColor Yellow }
        }
    } else {
        Write-Host "  Sem resposta (rede?) - chave gravada mesmo assim." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  Chave ativa. Pode rodar start-jarvis.ps1 agora." -ForegroundColor Green
Write-Host "  Chave salva (mascarada): $(_mask $ApiKey)" -ForegroundColor DarkGray
Write-Host ""
