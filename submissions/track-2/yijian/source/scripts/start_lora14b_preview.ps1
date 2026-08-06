param(
    [int]$Port = 8600
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$healthUrl = "http://127.0.0.1:$Port/api/health"

# Start the frozen v3 adapter on the W7900 first.  The command verifies the
# adapter hashes before replacing the previous preview process.
& ssh radeon-yijian "/workspace/yijian/lora-runtime-v3-lr3e5/bin/start_lora14b_v3_fast_preview.sh"
if ($LASTEXITCODE -ne 0) {
    throw "The W7900 YIJIAN LoRA v3 service did not start."
}

# The desktop workbench reads its cloud model at process startup. Stop only the
# process listening on this dedicated local port; no user data is removed.
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300

& (Join-Path $PSScriptRoot "start_cloud_mentor_tunnel.ps1") -LocalPort 18083 -RemotePort 8083

$env:YIJIAN_CLOUD_LLM_URL = "http://127.0.0.1:18083/v1"
$env:YIJIAN_CLOUD_LLM_MODEL = "YIJIAN-Qwen3-14B-LoRA-gold-runtime-v3-Q4"
$env:YIJIAN_MENTOR_MODEL_REVISION = "qwen3-14b-40c0698+yijian-lora-gold-runtime-v3"
$env:GOMENTOR_BATCH_MENTOR_PROVIDER = "cloud"
$env:GOMENTOR_BATCH_NARRATIVE_NODES = "6"
$env:YIJIAN_LLM_TIMEOUT = "20"
$env:YIJIAN_CHAT_TIMEOUT = "30"
$env:KATAGO_REMOTE_ENABLED = "1"
$env:KATAGO_REMOTE_HOST = "radeon-yijian"
$env:KATAGO_REMOTE_PATH = "/persistent/yijian/katago-v1.16.5/build/katago"
$env:KATAGO_REMOTE_MODEL = "/persistent/yijian/katago-models/kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz"
$env:KATAGO_REMOTE_CONFIG = "/persistent/yijian/project/gomentor/deploy/cloud/katago_analysis_w7900.cfg"
$env:KATAGO_CONFIG = Join-Path $projectRoot "deploy\cloud\katago_analysis_w7900.cfg"
$env:KATAGO_CHUNK_SIZE = "64"

$stdout = Join-Path $projectRoot "runtime\lora14b-preview.out.log"
$stderr = Join-Path $projectRoot "runtime\lora14b-preview.err.log"
$backend = Join-Path $projectRoot "backend"
$process = Start-Process -FilePath "py.exe" `
    -ArgumentList @("-3", "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $backend -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

$deadline = (Get-Date).AddSeconds(20)
do {
    if ($process.HasExited) { throw "YIJIAN LoRA preview backend exited with code $($process.ExitCode). See $stderr" }
    try {
        $ready = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1
        if ($ready.StatusCode -eq 200) {
            Write-Host "YIJIAN 14B LoRA preview workbench is ready (PID $($process.Id))."
            Start-Process "http://127.0.0.1:$Port/"
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 300
} while ((Get-Date) -lt $deadline)

Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
throw "YIJIAN LoRA preview backend did not become ready within 20 seconds. See $stderr"
