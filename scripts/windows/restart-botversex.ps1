# Kill old BotverseX + Reachy daemon processes, then start fresh detached stack.
$ErrorActionPreference = "SilentlyContinue"
$Root = "C:\Users\AMD\dev\botversex"
$Scripts = Join-Path $Root "scripts\windows"

Write-Host "== BotverseX restart =="

Write-Host "[1/4] Stop scheduled task (if any) ..."
schtasks /end /tn BotverseX-Dev 2>$null | Out-Null
Start-Sleep -Seconds 2

Write-Host "[2/4] Stop API / Realtime / Web ..."
cmd /c "`"$Scripts\stop-detached.cmd`"" | Out-Null

Write-Host "[3/4] Stop Reachy daemon on COM3 / port 8010 ..."
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'reachy_mini\.daemon\.app\.main' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

foreach ($port in 8010) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

Start-Sleep -Seconds 3

Write-Host "[4/4] Start BotverseX detached ..."
Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "`"$Scripts\run-detached.cmd`"") `
    -WorkingDirectory $Root `
    -WindowStyle Minimized

Start-Sleep -Seconds 20

$ports = @(8000, 8002, 5173)
$allUp = $true
foreach ($port in $ports) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        Write-Host "  port $port LISTENING"
    } else {
        Write-Host "  port $port DOWN"
        $allUp = $false
    }
}

$health = "unknown"
try {
    $health = (Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/setup/health" -UseBasicParsing -TimeoutSec 10).Content
    Write-Host "  health OK"
} catch {
    Write-Host "  health check failed: $($_.Exception.Message)"
    $allUp = $false
}

Add-Type -AssemblyName System.Windows.Forms
$msg = if ($allUp) {
    "BotverseX 已重启完成。`n`n演示页：`nhttp://127.0.0.1:5173/robots/reachy_mini`n`n局域网：`nhttp://$((Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.*' } | Select-Object -First 1).IPAddress):5173/robots/reachy_mini"
} else {
    "BotverseX 已尝试重启，但部分服务未就绪。`n请检查机器人是否上电，或稍后再点一次。"
}
[System.Windows.Forms.MessageBox]::Show($msg, "BotverseX", [System.Windows.Forms.MessageBoxButtons]::OK, $(if ($allUp) { "Information" } else { "Warning" })) | Out-Null
