param(
    [int]$LocalPort = 18082,
    [int]$RemotePort = 8082,
    [string]$SshHost = "radeon-yijian"
)

$ErrorActionPreference = "Stop"
$healthUrl = "http://127.0.0.1:$LocalPort/v1/models"

try {
    $ready = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1
    if ($ready.StatusCode -eq 200) {
        Write-Host "W7900 mentor tunnel is ready."
        exit 0
    }
} catch {}

$ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
$arguments = @(
    "-N",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-L", "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}",
    $SshHost
)
$process = Start-Process -FilePath $ssh -ArgumentList $arguments `
    -WindowStyle Hidden -PassThru

$deadline = (Get-Date).AddSeconds(30)
do {
    if ($process.HasExited) {
        throw "SSH tunnel exited with code $($process.ExitCode)."
    }
    try {
        $ready = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1
        if ($ready.StatusCode -eq 200) {
            Write-Host "W7900 mentor tunnel is ready (PID $($process.Id))."
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 300
} while ((Get-Date) -lt $deadline)

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
throw "SSH tunnel opened, but the remote mentor did not respond in 30 seconds."
