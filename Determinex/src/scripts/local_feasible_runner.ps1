param(
    [string]$QueueFile = "C:\tmp\feasible_local.txt",
    [int]$Lanes = 2,
    [int]$TimeoutMin = 25,
    [string]$LogPath = "C:\Dev\Determinex\logs\local_feasible_runner.log"
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:DOCKER_CONFIG = "C:\Dev\Determinex\logs\docker_config"
$env:UV_CACHE_DIR = "C:\Dev\Determinex\logs\uv_cache"
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue

$PB_EXE = "T:\Dev\ProgramBench\.venv\Scripts\programbench.exe"
$PB_DIR = "T:\Dev\ProgramBench"
$FACTORY_ROOT = "T:\determinex-programbench"
$SUMMARY = "C:\Dev\Determinex\logs\local_feasible_summary.tsv"

if (-not (Test-Path -LiteralPath $QueueFile)) { Write-Host "queue file missing: $QueueFile"; exit 1 }
$queue = Get-Content -LiteralPath $QueueFile | Where-Object { $_.Trim() -ne "" }

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format o) $msg"
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding Unicode
}

Write-Log "=== local feasible runner start. Lanes=$Lanes timeout=${TimeoutMin}m queue=$($queue.Count) ==="

$active = [System.Collections.ArrayList]@()
$pending = New-Object System.Collections.Queue
foreach ($q in $queue) { $pending.Enqueue($q) }

while ($pending.Count -gt 0 -or $active.Count -gt 0) {
    while ($pending.Count -gt 0 -and $active.Count -lt $Lanes) {
        $inst = $pending.Dequeue()
        $factory = Join-Path $FACTORY_ROOT "determinex_pb_factory_${inst}_v1"
        if (-not (Test-Path -LiteralPath $factory)) {
            Write-Log "[skip] $inst (no factory dir)"
            "$(Get-Date -Format o)`t$inst`tMISSING`t-`t-" | Out-File -Append -LiteralPath $SUMMARY -Encoding UTF8
            continue
        }
        $filter = ($inst -split '__')[0]
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $safe = $inst -replace '[^A-Za-z0-9_.-]', '_'
        $stdout = "C:\Dev\Determinex\logs\local_${safe}_${stamp}.out.log"
        $stderr = "C:\Dev\Determinex\logs\local_${safe}_${stamp}.err.log"
        $procArgs = @("eval", $factory, "--filter", $filter, "--workers", "1",
                      "--branch-workers", "1", "--docker-cpus", "1", "--force")
        $p = Start-Process -FilePath $PB_EXE -ArgumentList $procArgs -WorkingDirectory $PB_DIR `
             -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        Write-Log "[start] $inst (pid=$($p.Id))"
        [void]$active.Add([pscustomobject]@{
            Process = $p; Instance = $inst; Started = Get-Date
            Stdout = $stdout; Stderr = $stderr
        })
    }
    Start-Sleep -Seconds 8
    foreach ($l in @($active)) {
        try { $l.Process.Refresh() } catch {}
        $age = [int]((Get-Date) - $l.Started).TotalSeconds
        if (-not $l.Process.HasExited -and $age -gt ($TimeoutMin * 60)) {
            Write-Log "[timeout] $($l.Instance) after ${age}s"
            try { Stop-Process -Id $l.Process.Id -Force -ErrorAction SilentlyContinue } catch {}
            docker ps --filter "name=programbench-" --format "{{.ID}}|{{.Image}}" | ForEach-Object {
                $parts = $_ -split "\|"
                if ($parts.Count -eq 2 -and $parts[1] -like "*$($l.Instance)*") {
                    docker kill $parts[0] 2>$null | Out-Null
                }
            }
            $score = "-"
            "$(Get-Date -Format o)`t$($l.Instance)`tTIMEOUT`tdur=${age}s`t$score" | Out-File -Append -LiteralPath $SUMMARY -Encoding UTF8
            [void]$active.Remove($l)
            continue
        }
        if ($l.Process.HasExited) {
            $ej = Join-Path $FACTORY_ROOT "determinex_pb_factory_$($l.Instance)_v1\$($l.Instance)\$($l.Instance).eval.json"
            $score = "-"
            if (Test-Path -LiteralPath $ej) {
                try {
                    $j = Get-Content -Raw -LiteralPath $ej | ConvertFrom-Json
                    $r = @($j.test_results)
                    $passed = @($r | Where-Object { $_.status -eq "passed" }).Count
                    if ($r.Count -gt 0) { $score = "{0}/{1}={2:0.00}%" -f $passed, $r.Count, (100 * $passed / $r.Count) }
                } catch {}
            }
            Write-Log "[done] $($l.Instance) rc=$($l.Process.ExitCode) dur=${age}s score=$score"
            "$(Get-Date -Format o)`t$($l.Instance)`trc=$($l.Process.ExitCode)`tdur=${age}s`t$score" | Out-File -Append -LiteralPath $SUMMARY -Encoding UTF8
            [void]$active.Remove($l)
        }
    }
}

Write-Log "=== complete ==="
