param(
    [int]$Port = 8600
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$healthUrl = "http://127.0.0.1:$Port/api/health"

try {
    $existing = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1
    if ($existing.StatusCode -eq 200) {
        Write-Host "YIJIAN competition workspace is already ready."
        exit 0
    }
} catch {}

& (Join-Path $PSScriptRoot "start_cloud_mentor_tunnel.ps1")

$env:YIJIAN_CLOUD_LLM_URL = "http://127.0.0.1:18082/v1"
$env:YIJIAN_CLOUD_LLM_MODEL = "Yijian-Qwen3.6-27B-GoCoach"
$env:YIJIAN_MENTOR_MODEL_REVISION = "qwen3.6-27b-q4-k-m-go-evidence-v1"
$env:GOMENTOR_BATCH_MENTOR_PROVIDER = "cloud"
$env:GOMENTOR_BATCH_NARRATIVE_NODES = "6"
$env:YIJIAN_LLM_TIMEOUT = "18"
$env:YIJIAN_CHAT_TIMEOUT = "30"
$env:KATAGO_REMOTE_ENABLED = "1"
$env:KATAGO_REMOTE_HOST = "radeon-yijian"
$env:KATAGO_REMOTE_PATH = "/persistent/yijian/katago-v1.16.5/build/katago"
$env:KATAGO_REMOTE_MODEL = "/persistent/yijian/katago-models/kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz"
$env:KATAGO_REMOTE_CONFIG = "/persistent/yijian/project/gomentor/deploy/cloud/katago_analysis_w7900.cfg"
$env:KATAGO_CONFIG = Join-Path $projectRoot "deploy\cloud\katago_analysis_w7900.cfg"
$env:KATAGO_CHUNK_SIZE = "64"

$stdout = Join-Path $projectRoot "runtime\competition-27b.out.log"
$stderr = Join-Path $projectRoot "runtime\competition-27b.err.log"
$backend = Join-Path $projectRoot "backend"
$process = Start-Process -FilePath "py.exe" `
    -ArgumentList @("-3", "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $backend -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

$deadline = (Get-Date).AddSeconds(20)
do {
    if ($process.HasExited) {
        throw "YIJIAN backend exited with code $($process.ExitCode). See $stderr"
    }
    try {
        $ready = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1
        if ($ready.StatusCode -eq 200) {
            Write-Host "YIJIAN 27B competition workspace is ready (PID $($process.Id))."
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 300
} while ((Get-Date) -lt $deadline)

Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
throw "YIJIAN backend did not become ready within 20 seconds. See $stderr"
