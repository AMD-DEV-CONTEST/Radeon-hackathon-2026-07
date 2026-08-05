param(
    [string]$WorkerId = "local-1",
    [int]$TimeoutMin = 20,
    [string]$Tier = "light",  # local prefers light tools by default
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_determinex",
    [string]$HetznerHost = "root@5.78.192.163",
    [string]$LogPath = "C:\Dev\Determinex\logs\pool_$($WorkerId).log"
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:DOCKER_CONFIG = "C:\Dev\Determinex\logs\docker_config"
$env:UV_CACHE_DIR = "C:\Dev\Determinex\logs\uv_cache"
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue

$PB_EXE = "T:\Dev\ProgramBench\.venv\Scripts\programbench.exe"
$PB_DIR = "T:\Dev\ProgramBench"
$FACTORY_ROOT = "T:\determinex-programbench"

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format o) [$WorkerId] $msg"
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Invoke-Ssh {
    param([string]$cmd)
    & ssh -i $SshKey -o StrictHostKeyChecking=no -o ServerAliveInterval=30 $HetznerHost $cmd
}

Write-Log "worker start. timeout=${TimeoutMin}m"

while ($true) {
    $tool = (Invoke-Ssh "/root/queue/claim_next.sh '$WorkerId' '$Tier'") | Out-String
    $tool = $tool.Trim()
    if (-not $tool) {
        Write-Log "queue empty, exiting"
        break
    }
    Write-Log "claimed $tool"

    $factory = Join-Path $FACTORY_ROOT "determinex_pb_factory_${tool}_v1"
    if (-not (Test-Path -LiteralPath $factory)) {
        Write-Log "no factory dir for $tool, marking MISSING"
        Invoke-Ssh "/root/queue/mark_done.sh '$tool' MISSING - -"
        continue
    }

    $filter = ($tool -split '__')[0]
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $safe = $tool -replace '[^A-Za-z0-9_.-]', '_'
    $stdout = "C:\Dev\Determinex\logs\pool_${safe}_${stamp}.out.log"
    $stderr = "C:\Dev\Determinex\logs\pool_${safe}_${stamp}.err.log"
    $started = Get-Date
    $procArgs = @("eval", $factory, "--filter", $filter, "--workers", "1",
                  "--branch-workers", "1", "--docker-cpus", "1", "--force")
    $p = Start-Process -FilePath $PB_EXE -ArgumentList $procArgs -WorkingDirectory $PB_DIR `
         -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Write-Log "spawned pb.exe pid=$($p.Id) for $tool"

    # Wait with timeout, kill if exceeded
    $deadline = (Get-Date).AddMinutes($TimeoutMin)
    while (-not $p.HasExited) {
        if ((Get-Date) -gt $deadline) {
            Write-Log "TIMEOUT $tool - killing"
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
            docker ps --filter 'name=programbench-' --format '{{.ID}}|{{.Image}}' | ForEach-Object {
                $parts = $_ -split '\|'
                if ($parts.Count -eq 2 -and $parts[1] -like "*$tool*") {
                    docker kill $parts[0] 2>$null | Out-Null
                }
            }
            break
        }
        Start-Sleep -Seconds 5
        try { $p.Refresh() } catch {}
    }
    $age = [int]((Get-Date) - $started).TotalSeconds
    $rc = if ($p.HasExited) { $p.ExitCode } else { 124 }

    $ej = Join-Path $FACTORY_ROOT "determinex_pb_factory_${tool}_v1\${tool}\${tool}.eval.json"
    $score = "-"
    if (Test-Path -LiteralPath $ej) {
        try {
            $j = Get-Content -Raw -LiteralPath $ej | ConvertFrom-Json
            $r = @($j.test_results)
            $passed = @($r | Where-Object { $_.status -eq "passed" }).Count
            if ($r.Count -gt 0) {
                $score = "$passed/$($r.Count)=$([Math]::Round(100.0 * $passed / $r.Count, 2))%"
            }
        } catch {}
    }
    Write-Log "done $tool rc=$rc dur=${age}s score=$score"
    Invoke-Ssh "/root/queue/mark_done.sh '$tool' '$score' 'rc=$rc' '${age}s'"
}
Write-Log "worker exit"
