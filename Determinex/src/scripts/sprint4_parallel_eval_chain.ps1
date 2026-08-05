param(
    [string]$ProgramBenchDir = "T:\Dev\ProgramBench",
    [string]$LogPath = "C:\Dev\Determinex\logs\sprint4_parallel_eval_chain.log",
    [int]$ToolTimeoutMinutes = 45,
    [int]$Tier = 10,
    [int]$Lanes = 2,
    [string]$QueueJson = "C:\Dev\Determinex\logs\mass_run_v2\sprint4_eval_queue.json",
    [string[]]$SkipInstances = @()
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:DOCKER_CONFIG = "C:\Dev\Determinex\logs\docker_config"
$env:UV_CACHE_DIR = "C:\Dev\Determinex\logs\uv_cache"
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue

$ProgramBenchExe = Join-Path $ProgramBenchDir ".venv\Scripts\programbench.exe"
$LockPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_parallel_eval_chain.lock"
$QuarantineFamilies = @("benchmark_timing", "animation_output")

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

function Write-ChainLog {
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    Write-Host $line
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding Unicode } catch {}
}

function Assert-DirectPowerShellLaunch {
    try {
        $me = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($me.ParentProcessId)"
        if ($parent.Name -match "bash|sh.exe|zsh|fish") {
            Write-ChainLog "!! REFUSING LAUNCH: parent process is $($parent.Name). Run directly from PowerShell."
            exit 2
        }
    } catch {}
}

function Acquire-ChainLock {
    if (Test-Path -LiteralPath $LockPath) {
        $old = Get-Content -LiteralPath $LockPath -ErrorAction SilentlyContinue | Select-Object -First 1
        $oldPid = 0
        [void][int]::TryParse([string]$old, [ref]$oldPid)
        if ($oldPid -gt 0 -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Write-ChainLog "!! REFUSING LAUNCH: existing parallel chain PID $oldPid is alive."
            exit 3
        }
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
    }
    Set-Content -LiteralPath $LockPath -Value "$PID" -Encoding ASCII
}

function Release-ChainLock {
    try {
        if (Test-Path -LiteralPath $LockPath) {
            $old = Get-Content -LiteralPath $LockPath -ErrorAction SilentlyContinue | Select-Object -First 1
            if ([string]$old -eq [string]$PID) { Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue }
        }
    } catch {}
}

function Assert-DockerHealthy {
    param([string]$Where)
    $out = & docker ps 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-ChainLog "!! DOCKER UNHEALTHY $Where"
        Write-ChainLog ($out | Out-String)
        exit 1
    }
}

function Stop-ProgramBenchContainers {
    param([string]$Why)
    $ids = @(& docker ps --filter "name=programbench-" --format "{{.ID}}" 2>$null)
    foreach ($id in $ids) {
        if ($id) {
            Write-ChainLog "  stopping ProgramBench container $id ($Why)"
            try { docker stop $id | Out-Null } catch {}
        }
    }
}

function Stop-ProcessTree {
    param([int]$RootPid)
    $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $RootPid })
    foreach ($child in $children) { Stop-ProcessTree -RootPid ([int]$child.ProcessId) }
    try { Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue } catch {}
}

function Get-Score {
    param([string]$Root, [string]$Instance)
    $ej = Join-Path $Root "$Instance\$Instance.eval.json"
    if (-not (Test-Path -LiteralPath $ej)) { return $null }
    try {
        $json = Get-Content -Raw -LiteralPath $ej | ConvertFrom-Json
        $results = @($json.test_results)
        $passed = @($results | Where-Object { $_.status -eq "passed" }).Count
        $total = $results.Count
        if ($total -le 0) { return 0.0 }
        return [Math]::Round(100.0 * $passed / $total, 2)
    } catch { return $null }
}

function Start-EvalLane {
    param($Entry)
    $safe = $Entry.instance -replace '[^A-Za-z0-9_.-]', '_'
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $stdoutPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_parallel_${safe}_${stamp}.out.log"
    $stderrPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_parallel_${safe}_${stamp}.err.log"
    $filter = ($Entry.instance -split "__")[0]
    $args = @(
        "eval", $Entry.factory_dir,
        "--filter", $filter,
        "--workers", "1",
        "--branch-workers", "1",
        "--docker-cpus", "1",
        "--force"
    )
    $proc = Start-Process -FilePath $ProgramBenchExe -ArgumentList $args `
        -WorkingDirectory $ProgramBenchDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    return [pscustomobject]@{
        Entry = $Entry
        Process = $proc
        StartedAt = Get-Date
        Stdout = $stdoutPath
        Stderr = $stderrPath
    }
}

Assert-DirectPowerShellLaunch
Acquire-ChainLock
trap {
    Stop-ProgramBenchContainers "trap cleanup"
    Release-ChainLock
    throw $_
}

if ($Lanes -lt 1) { $Lanes = 1 }
if ($Lanes -gt 3) { $Lanes = 3 } # Docker Desktop stays sane here.

if (-not (Test-Path -LiteralPath $QueueJson)) {
    Write-ChainLog "!! queue JSON not found: $QueueJson"
    exit 1
}

$queue = (Get-Content -Raw -LiteralPath $QueueJson | ConvertFrom-Json).ranked
$skip = @{}
foreach ($s in $SkipInstances) { $skip[$s] = $true }
$eligible = @($queue | Where-Object {
    # eval_worthiness: -1=defer, 0=weak, 1=medium, 2=moderate, 3=strong.
    # For mass-eval we include weak (0); only skip explicit defer (-1).
    ((($_.PSObject.Properties.Name -notcontains "eval_worthiness") -or ([int]$_.eval_worthiness -ge 0)) -and
     ($QuarantineFamilies -notcontains [string]$_.family) -and
     (-not $skip[$_.instance]))
})
$slice = @($eligible[0..([Math]::Min($Tier - 1, $eligible.Count - 1))])

$start = Get-Date
Write-ChainLog "=== sprint4 parallel eval chain start tier=$Tier lanes=$Lanes ==="
Write-ChainLog "policy: parallel tool lanes=$Lanes; per-tool flags --workers 1 --branch-workers 1 --docker-cpus 1"
Write-ChainLog "queue: $QueueJson eligible=$($eligible.Count) selected=$($slice.Count)"
Assert-DockerHealthy "chain start"
Stop-ProgramBenchContainers "chain start cleanup"

$pending = New-Object System.Collections.Queue
foreach ($entry in $slice) { $pending.Enqueue($entry) }
$active = New-Object System.Collections.ArrayList
$done = New-Object System.Collections.ArrayList

while ($pending.Count -gt 0 -or $active.Count -gt 0) {
    while ($pending.Count -gt 0 -and $active.Count -lt $Lanes) {
        $entry = $pending.Dequeue()
        $elapsed = [int]((Get-Date) - $start).TotalSeconds
        Write-ChainLog "[t+$($elapsed)s] START $($entry.instance) rank=$($entry.rank) family=$($entry.family) base=$($entry.base_score)%"
        [void]$active.Add((Start-EvalLane -Entry $entry))
    }

    Start-Sleep -Seconds 5
    foreach ($lane in @($active)) {
        try { $lane.Process.Refresh() } catch {}
        $age = [int]((Get-Date) - $lane.StartedAt).TotalSeconds
        if (-not $lane.Process.HasExited -and $age -gt ($ToolTimeoutMinutes * 60)) {
            # Per-lane timeout: kill ONLY this lane's process tree + ITS
            # containers, record an empty-score DONE, free the lane so the
            # next queued tool can dispatch. Do NOT kill other lanes.
            Write-ChainLog "!! TIMEOUT $($lane.Entry.instance) after ${age}s; killing this lane, others continue"
            Stop-ProcessTree -RootPid $lane.Process.Id
            # Kill only containers whose image matches this lane's tool.
            $toolName = $lane.Entry.instance
            $matchingIds = @(& docker ps --filter "name=programbench-" --format "{{.ID}}|{{.Image}}" 2>$null |
                ForEach-Object { $parts = $_ -split "\|", 2; if ($parts.Count -eq 2 -and $parts[1] -like "*$toolName*") { $parts[0] } })
            foreach ($id in $matchingIds) {
                Write-ChainLog "  stopping ProgramBench container $id (per-lane timeout $toolName)"
                try { docker stop $id | Out-Null } catch {}
            }
            $elapsed = [int]((Get-Date) - $start).TotalSeconds
            Write-ChainLog "[t+$($elapsed)s] DONE  $($lane.Entry.instance) rc=124 score= delta= pp (timeout)"
            [void]$done.Add([pscustomobject]@{
                instance = $lane.Entry.instance
                family = $lane.Entry.family
                base_score = [double]$lane.Entry.base_score
                v1_score = $null
                delta_pp = $null
                rc = 124
            })
            [void]$active.Remove($lane)
            continue
        }
        if ($lane.Process.HasExited) {
            $score = Get-Score $lane.Entry.factory_dir $lane.Entry.instance
            $base = [double]$lane.Entry.base_score
            $delta = if ($null -ne $score) { [Math]::Round([double]$score - $base, 2) } else { $null }
            $elapsed = [int]((Get-Date) - $start).TotalSeconds
            Write-ChainLog "[t+$($elapsed)s] DONE  $($lane.Entry.instance) rc=$($lane.Process.ExitCode) score=$score% delta=$delta pp"
            [void]$done.Add([pscustomobject]@{
                instance = $lane.Entry.instance
                family = $lane.Entry.family
                base_score = $base
                v1_score = $score
                delta_pp = $delta
                rc = $lane.Process.ExitCode
            })
            [void]$active.Remove($lane)
        }
    }
    Assert-DockerHealthy "parallel loop"
}

Stop-ProgramBenchContainers "chain complete cleanup"
$summaryPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_parallel_eval_summary.json"
$done | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Write-ChainLog "=== sprint4 parallel eval chain complete; summary=$summaryPath ==="
Release-ChainLock
