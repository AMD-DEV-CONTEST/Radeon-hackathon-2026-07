# Register + run BotverseX as a detached Scheduled Task (survives SSH disconnect)
$ErrorActionPreference = "Stop"
$Root = "C:\Users\AMD\dev\botversex"
$Run = Join-Path $Root "scripts\windows\run-detached.cmd"
$Stop = Join-Path $Root "scripts\windows\stop-detached.cmd"

$action = New-ScheduledTaskAction -Execute $Run -WorkingDirectory $Root
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "BotverseX-Dev" -Action $action -Settings $settings -Force | Out-Null

Write-Host "Registered BotverseX-Dev task. Starting..."
Start-ScheduledTask -TaskName "BotverseX-Dev"
Start-Sleep -Seconds 18

foreach ($port in 8000, 8002, 5173) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) { Write-Host "port $port LISTENING" } else { Write-Host "port $port DOWN" }
}

try {
    $h = (Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/setup/health" -UseBasicParsing -TimeoutSec 8).Content
    Write-Host "health: $h"
} catch {
    Write-Host "health check failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Stop later: schtasks /end /tn BotverseX-Dev & $Stop"
Write-Host "Start again: schtasks /run /tn BotverseX-Dev"
