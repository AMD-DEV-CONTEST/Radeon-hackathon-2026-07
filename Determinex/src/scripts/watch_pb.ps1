# watch_pb.ps1 - live dashboard for the autonomous PB drive loop.
# Refreshes every $Interval seconds. Ctrl+C to stop.
#   powershell -ExecutionPolicy Bypass -File scripts\watch_pb.ps1
param(
    [int]$Interval = 20
)

$ErrorActionPreference = "SilentlyContinue"
$key = Join-Path $env:USERPROFILE ".ssh\id_determinex"
$rhost = "root@5.78.192.163"
$sshOpts = @("-o","StrictHostKeyChecking=no","-o","ConnectTimeout=15","-i",$key)
$driveLog = "C:\tmp\pb_drive.log"

function Invoke-RemoteCmd([string]$cmd) {
    & ssh @sshOpts $rhost $cmd 2>$null
}

while ($true) {
    Clear-Host
    $now = Get-Date -Format "HH:mm:ss"
    Write-Host "==================== DETERMINEX PB DRIVE - live ($now) ====================" -ForegroundColor Cyan

    # 1) current eval + elapsed
    $eval = Invoke-RemoteCmd "ps -eo etimes,args | grep '[p]rogrambench eval' | head -1"
    if ($eval) {
        $parts = $eval.Trim() -split '\s+', 2
        $secs = [int]$parts[0]
        $m = [System.Text.RegularExpressions.Regex]::Match($parts[1], 'determinex_pb_\w*?_?([\w\-\.]+?)_v1')
        $slug = if ($m.Success) { $m.Groups[1].Value } else { "?" }
        $mins = [math]::Floor($secs / 60)
        $rem = $secs % 60
        Write-Host ""
        Write-Host ("[EVAL RUNNING]  {0}   elapsed {1}m{2}s" -f $slug, $mins, $rem) -ForegroundColor Yellow
    } else {
        Write-Host ""
        Write-Host "[EVAL] none running (between tools / waiting)" -ForegroundColor DarkGray
    }

    # 2) pb_drive local progress
    Write-Host ""
    Write-Host "--- pb_drive (autonomous loop) ---" -ForegroundColor Green
    if (Test-Path $driveLog) {
        Get-Content $driveLog -Tail 8 | ForEach-Object { Write-Host "  $_" }
    } else {
        Write-Host "  (no pb_drive.log yet)" -ForegroundColor DarkGray
    }

    # 3) grind/eval log tail (results)
    Write-Host ""
    Write-Host "--- eval results (recent) ---" -ForegroundColor Green
    $grind = Invoke-RemoteCmd "grep -E 'passed=|RE-EVAL|done|LOCK|NEEDS|drive' /tmp/grind/_grind.log 2>/dev/null | tail -8"
    if ($grind) { $grind | ForEach-Object { Write-Host "  $_" } } else { Write-Host "  (none yet)" -ForegroundColor DarkGray }

    Write-Host ""
    Write-Host "--- first-pass scoreboard ---" -ForegroundColor Green
    Write-Host "  zk 21pct | serpl 17.2pct | duc 81.8pct | halite 2.3pct  (pb_drive iterating)" -ForegroundColor White

    Write-Host ""
    Write-Host "(refreshing every ${Interval}s - Ctrl+C to stop)" -ForegroundColor DarkGray
    Start-Sleep -Seconds $Interval
}
