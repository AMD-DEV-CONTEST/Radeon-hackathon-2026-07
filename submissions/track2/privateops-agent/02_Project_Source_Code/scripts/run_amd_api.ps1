param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ApiKey = $env:PRIVATEOPS_MODEL_API_KEY

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    $ApiKey = Get-Clipboard -Raw
}
if ($ApiKey -notmatch '^rc-[A-Za-z0-9-]+$') {
    throw "Copy the Radeon API key before starting PrivateOps."
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv Python runtime."
}

$env:PRIVATEOPS_PROVIDER_MODE = "development"
$env:PRIVATEOPS_ALLOW_REMOTE_MODEL = "true"
$env:PRIVATEOPS_MODEL_ENDPOINT = "https://developer.amd.com.cn/radeon/api/v1/chat/completions"
$env:PRIVATEOPS_MODEL_NAME = "DeepSeek-V4-Flash"
$env:PRIVATEOPS_MODEL_API_KEY = $ApiKey
$env:PRIVATEOPS_REQUEST_TIMEOUT = "90"

$PublicConfiguration = [ordered]@{
    provider_mode = $env:PRIVATEOPS_PROVIDER_MODE
    model_endpoint = $env:PRIVATEOPS_MODEL_ENDPOINT
    model_name = $env:PRIVATEOPS_MODEL_NAME
    remote_model_allowed = $true
    competition_eligible = $false
}

if ($ValidateOnly) {
    $PublicConfiguration | ConvertTo-Json -Compress
    exit 0
}

$Process = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m", "privateops.server" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

$PublicConfiguration["pid"] = $Process.Id
$PublicConfiguration | ConvertTo-Json -Compress
