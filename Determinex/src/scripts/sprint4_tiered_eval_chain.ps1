param(
    [string]$ProgramBenchDir = "T:\Dev\ProgramBench",
    [string]$LogPath = "C:\Dev\Determinex\logs\sprint4_tiered_eval_chain.log",
    [int]$ToolTimeoutMinutes = 30,
    [int]$Tier = 10,                    # 10, 25, 50, or 105
    [string]$QueueJson = "C:\Dev\Determinex\logs\mass_run_v2\sprint4_eval_queue.json",
    [string[]]$SkipInstances = @()      # instance_ids to skip (already scored)
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:DOCKER_CONFIG = "C:\Dev\Determinex\logs\docker_config"
$env:UV_CACHE_DIR = "C:\Dev\Determinex\logs\uv_cache"
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue
$ProgramBenchExe = Join-Path $ProgramBenchDir ".venv\Scripts\programbench.exe"
$LockPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_tiered_eval_chain.lock"

# Quarantined families — skip entirely (Docker memory or structural)
$QuarantineFamilies = @("benchmark_timing", "animation_output")
$QuarantineFamiliesSet = @{}
foreach ($f in $QuarantineFamilies) { $QuarantineFamiliesSet[$f] = $true }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

function Write-ChainLog {
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    Write-Host $line
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding Unicode } catch { }
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

function Assert-DirectPowerShellLaunch {
    try {
        $me = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($me.ParentProcessId)"
        if ($parent.Name -match "bash|sh.exe|zsh|fish") {
            Write-ChainLog "!! REFUSING LAUNCH: parent process is $($parent.Name)."
            Write-ChainLog "!! Run directly from PowerShell, not Git Bash/background shell."
            exit 2
        }
    } catch {
        Write-ChainLog "!! launch-parent check failed: $($_.Exception.Message)"
    }
}

function Acquire-ChainLock {
    if (Test-Path -LiteralPath $LockPath) {
        $old = Get-Content -LiteralPath $LockPath -ErrorAction SilentlyContinue | Select-Object -First 1
        $oldPid = 0
        [void][int]::TryParse([string]$old, [ref]$oldPid)
        if ($oldPid -gt 0) {
            $oldProc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
            if ($oldProc) {
                Write-ChainLog "!! REFUSING LAUNCH: existing sprint4 chain PID $oldPid is still alive."
                exit 3
            }
        }
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
    }
    Set-Content -LiteralPath $LockPath -Value "$PID" -Encoding ASCII
}

function Release-ChainLock {
    try {
        if (Test-Path -LiteralPath $LockPath) {
            $old = Get-Content -LiteralPath $LockPath -ErrorAction SilentlyContinue | Select-Object -First 1
            if ([string]$old -eq [string]$PID) {
                Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

function Get-ProgramBenchContainers {
    $rows = @()
    $out = & docker ps --filter "name=programbench-" --format "{{.ID}}|{{.Names}}|{{.CreatedAt}}|{{.Image}}" 2>$null
    foreach ($line in @($out)) {
        if (-not $line) { continue }
        $parts = $line -split "\|", 4
        if ($parts.Count -ge 4) {
            $rows += [pscustomobject]@{ Id=$parts[0]; Name=$parts[1]; CreatedAt=$parts[2]; Image=$parts[3] }
        }
    }
    return @($rows)
}

function Stop-ProgramBenchContainers {
    param([string]$Why)
    $containers = Get-ProgramBenchContainers
    foreach ($c in $containers) {
        Write-ChainLog "  stopping stale ProgramBench container $($c.Name) ($Why)"
        try { docker stop $c.Id | Out-Null } catch {}
    }
}

# ──────────────────────────────────────────────────────────────────────────
# Worker policy.
# IMPORTANT: compile.sh cannot reliably patch the task image's eval/run.sh.
# If docker_cpus is 2+, pytest -n auto can spawn xdist workers inside the
# container and deadlock on sys.stdin.readline(). Speed comes from running
# multiple independent tool evals, not nested branch/xdist workers.
# ──────────────────────────────────────────────────────────────────────────

# Each entry: branch_workers, docker_cpus
$Script:WORKER_POLICY = @{
    # LIGHT — read stdin/write stdout, low subprocess fan-out
    "text_diff"                          = @(1, 1)
    "shell_coreutils"                    = @(1, 1)
    "shell_coreutils.ls_listing"         = @(1, 1)
    "shell_coreutils.du_tree"            = @(1, 1)
    "shell_coreutils.table_filter"       = @(1, 1)
    "formatters"                         = @(1, 1)
    "formatters.linter"                  = @(1, 1)
    "json_yaml_toml"                     = @(1, 1)
    "csv_table"                          = @(1, 1)
    "html_converter"                     = @(1, 1)
    "binary_inspector"                   = @(1, 1)
    "config_env"                         = @(1, 1)
    "regex_tools"                        = @(1, 1)
    "biosequence"                        = @(1, 1)
    "rust_cli"                           = @(1, 1)
    "go_cli"                             = @(1, 1)
    "python_cli"                         = @(1, 1)
    "node_cli"                           = @(1, 1)
    # MEDIUM — modest subprocess use
    "search_grep"                        = @(1, 1)
    "search_grep.code_rewriter"          = @(1, 1)
    "file_renamers"                      = @(1, 1)
    # HEAVY — fork-bombs / git subprocess / TUI
    "git_wrappers"                       = @(1, 1)
    "git_wrappers.log_graph"             = @(1, 1)
    "git_wrappers.changelog_generator"   = @(1, 1)
    "tui_terminal"                       = @(1, 1)
    "editor_integrated"                  = @(1, 1)
    "network_http"                       = @(1, 1)
    "database"                           = @(1, 1)
    "compiler_wrappers"                  = @(1, 1)
    "codegen"                            = @(1, 1)
    "package_manager"                    = @(1, 1)
    "security_scanner"                   = @(1, 1)
    "archive_compression"                = @(1, 1)
    "docs_static_site"                   = @(1, 1)
    "latex_document"                     = @(1, 1)
    # QUARANTINE — should already be filtered by ranker; safety net cap
    "animation_output"                   = @(1, 1)
    "benchmark_timing"                   = @(1, 1)
    "image_terminal_render"              = @(1, 1)
    "game_simulator"                     = @(1, 1)
}

$Script:DEFAULT_POLICY = @(1, 1)

function Get-WorkerPolicy {
    param([string]$Family, [string]$Subtype)
    # Hard override by design. Keep the table above as classification metadata,
    # but never let it re-enable xdist fan-out.
    return @(1, 1)
}

# ──────────────────────────────────────────────────────────────────────────
# Adaptive timeout. After each successful eval, append duration to history.
# Next-tool timeout = max($TimeoutFloorMin*60, avg(history) + $TimeoutPaddingSec).
# ──────────────────────────────────────────────────────────────────────────

$Script:CompletedDurationsSec = @()
$Script:TimeoutFloorMin = 10            # never timeout below 10 minutes
$Script:TimeoutPaddingSec = 60          # avg + 60 seconds

function Get-AdaptiveTimeoutMinutes {
    param([int]$DefaultMinutes)
    if ($Script:CompletedDurationsSec.Count -eq 0) {
        return $DefaultMinutes
    }
    $sum = ($Script:CompletedDurationsSec | Measure-Object -Sum).Sum
    $avg = $sum / $Script:CompletedDurationsSec.Count
    $proposed = ($avg + $Script:TimeoutPaddingSec) / 60.0
    $floor = $Script:TimeoutFloorMin
    return [int][Math]::Max($floor, [Math]::Ceiling($proposed))
}

function Stop-ProcessTree {
    param([int]$RootPid)
    $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $RootPid })
    foreach ($child in $children) {
        Stop-ProcessTree -RootPid ([int]$child.ProcessId)
    }
    try {
        Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
    } catch {}
}

function Get-RunningContainerSummary {
    # Diagnostic snapshot of PB containers, never killing. ProgramBench legitimately
    # uses multiple image namespaces during a single eval (programbench-compiled/...
    # for setup, programbench/<sanitized>:task for run), and may spawn multiple
    # containers when branch-workers > 1. The chain brackets each tool with
    # Stop-ProgramBenchContainers pre/post; we DO NOT kill during the eval.
    $containers = Get-ProgramBenchContainers
    return $containers.Count
}

function Invoke-ProgramBenchWithTimeout {
    param([string]$Exe, [string[]]$ProgramArgs, [string]$ToolName, [int]$TimeoutMinutes)
    $safeName = $ToolName -replace '[^A-Za-z0-9_.-]', '_'
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $stdoutPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_tiered_${safeName}_${stamp}.out.log"
    $stderrPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_tiered_${safeName}_${stamp}.err.log"
    $proc = Start-Process -FilePath $Exe -ArgumentList $ProgramArgs `
        -WorkingDirectory $ProgramBenchDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while (-not $proc.HasExited) {
        # Do not kill containers during the eval. ProgramBench legitimately uses
        # multiple image namespaces (programbench-compiled/<instance>:<hash> for
        # setup, programbench/<sanitized>:task for the actual test run) and may
        # spawn N parallel containers when branch-workers gt 1. The chain
        # brackets each tool with Stop-ProgramBenchContainers pre and post; that
        # is sufficient.
        if ((Get-Date) -gt $deadline) {
            Write-ChainLog "!! $ToolName exceeded ${TimeoutMinutes}m timeout; killing"
            Stop-ProcessTree -RootPid $proc.Id
            Stop-ProgramBenchContainers "tool timeout"
            return @{ Rc = 124 }
        }
        Start-Sleep -Seconds 5
        try { $proc.Refresh() } catch { }
    }
    return @{ Rc = $proc.ExitCode }
}

Assert-DirectPowerShellLaunch
Acquire-ChainLock
trap {
    Release-ChainLock
    throw $_
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

# Load ranked queue
if (-not (Test-Path -LiteralPath $QueueJson)) {
    Write-ChainLog "!! queue JSON not found: $QueueJson"
    Write-ChainLog "Run scripts/sprint4_rank_eval_queue.py first."
    exit 1
}
$queue = (Get-Content -Raw -LiteralPath $QueueJson | ConvertFrom-Json).ranked
$eligible = @($queue | Where-Object {
    ($_.PSObject.Properties.Name -notcontains "eval_worthiness") -or ([int]$_.eval_worthiness -gt 0)
})
if ($eligible.Count -eq 0) {
    Write-ChainLog "!! no eval-worthy queue entries found. Re-run ranker or inspect family classification."
    exit 1
}
$slice = $eligible[0..([Math]::Min($Tier - 1, $eligible.Count - 1))]

$start = Get-Date
Write-ChainLog "=== sprint4 tiered eval chain start (tier=$Tier): $($start.ToUniversalTime().ToString('s'))Z ==="
Write-ChainLog "policy: --workers 1 --branch-workers 1 --docker-cpus 1 (xdist single-worker; prevents pytest-xdist deadlock)"
Write-ChainLog "queue: $QueueJson  (eligible=$($eligible.Count), slice 0..$($slice.Count - 1))"
Write-ChainLog "programbench: $ProgramBenchExe"
Write-ChainLog ""
Stop-ProgramBenchContainers "chain start cleanup"

$evaluated = @()
$skipped = @()
$SkipSet = @{}
foreach ($s in $SkipInstances) { $SkipSet[$s] = $true }
foreach ($entry in $slice) {
    if ($SkipSet[$entry.instance]) {
        Write-ChainLog "  [SKIP] $($entry.instance) (user-requested via -SkipInstances)"
        $skipped += $entry
        continue
    }
    if ($QuarantineFamiliesSet[$entry.family]) {
        Write-ChainLog "  [SKIP] $($entry.instance) family=$($entry.family) (quarantined family)"
        $skipped += $entry
        continue
    }
    $elapsed = [int]((Get-Date) - $start).TotalSeconds

    # Variable worker policy per family/subtype
    $policy = Get-WorkerPolicy -Family $entry.family -Subtype $entry.subtype
    $branchWorkers = $policy[0]
    $dockerCpus    = $policy[1]

    # Adaptive timeout: avg(completed) + 60s, floored at 10min, only after we
    # have at least 1 completed eval to base it on.
    $effectiveTimeoutMin = Get-AdaptiveTimeoutMinutes -DefaultMinutes $ToolTimeoutMinutes

    Write-ChainLog "[t+$($elapsed)s] === $($entry.instance) (rank=$($entry.rank), family=$($entry.family), base=$($entry.base_score)%) starting ==="
    Write-ChainLog "  policy: branch-workers=$branchWorkers docker-cpus=$dockerCpus timeout=${effectiveTimeoutMin}min"
    Assert-DockerHealthy "before $($entry.instance)"
    Stop-ProgramBenchContainers "before $($entry.instance)"

    # Derive filter: everything before '__'
    $filter = ($entry.instance -split '__')[0]
    $cmdArgs = @(
        "eval", $entry.factory_dir,
        "--filter", $filter,
        "--workers", "1",
        "--branch-workers", $branchWorkers.ToString(),
        "--docker-cpus", $dockerCpus.ToString(),
        "--force"
    )
    $toolStart = Get-Date
    $run = Invoke-ProgramBenchWithTimeout `
        -Exe $ProgramBenchExe -ProgramArgs $cmdArgs `
        -ToolName $entry.instance -TimeoutMinutes $effectiveTimeoutMin
    $rc = [int]$run.Rc
    $toolDurationSec = [int]((Get-Date) - $toolStart).TotalSeconds

    $score = Get-Score $entry.factory_dir $entry.instance
    $base = [double]($entry.base_score)
    $delta = if ($score -ne $null) { [Math]::Round([double]$score - $base, 2) } else { $null }

    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    Write-ChainLog "[t+$($elapsed)s] === $($entry.instance) finished rc=$rc  score=$score% delta=$delta pp ==="

    Assert-DockerHealthy "after $($entry.instance)"
    Stop-ProgramBenchContainers "after $($entry.instance)"

    # Feed adaptive timeout history: only record durations from REAL evals
    # (eval JSON written). Hung/killed tools must not poison the average.
    if ($null -ne $score -and $toolDurationSec -gt 30) {
        $Script:CompletedDurationsSec += $toolDurationSec
        $avgSec = ($Script:CompletedDurationsSec | Measure-Object -Average).Average
        Write-ChainLog "  duration=${toolDurationSec}s; rolling avg=$([int]$avgSec)s over $($Script:CompletedDurationsSec.Count) successful evals"
    }

    $evaluated += @{
        rank = $entry.rank
        instance = $entry.instance
        family = $entry.family
        base_score = $base
        v1_score = $score
        delta_pp = $delta
        rc = $rc
        duration_sec = $toolDurationSec
    }
}

$total = [int]((Get-Date) - $start).TotalSeconds
Write-ChainLog "=== tier $Tier chain complete in ${total}s ==="

# Summary + promotion bucketing
$promote_v2 = @()
$keep_v1 = @()
$baseline = @()
$regressed = @()
$infra_fail = @()
foreach ($r in $evaluated) {
    if ($r.delta_pp -eq $null) { $infra_fail += $r; continue }
    if ($r.delta_pp -ge 10) { $promote_v2 += $r }
    elseif ($r.delta_pp -ge 3) { $keep_v1 += $r }
    elseif ($r.delta_pp -ge 0) { $baseline += $r }
    else { $regressed += $r }
}

$avg_lift = 0.0
$n_lifts = ($evaluated | Where-Object { $_.delta_pp -ne $null }).Count
if ($n_lifts -gt 0) {
    $sum = ($evaluated | Where-Object { $_.delta_pp -ne $null } | ForEach-Object { $_.delta_pp } | Measure-Object -Sum).Sum
    $avg_lift = [Math]::Round($sum / $n_lifts, 2)
}
Write-ChainLog ""
Write-ChainLog "=== tier $Tier summary ==="
Write-ChainLog "  evaluated:       $($evaluated.Count)"
Write-ChainLog "  skipped:         $($skipped.Count)"
Write-ChainLog "  promote to v2 (>=+10pp):  $($promote_v2.Count)"
Write-ChainLog "  keep v1 (+3 to +10pp):    $($keep_v1.Count)"
Write-ChainLog "  baseline (0 to +3pp):     $($baseline.Count)"
Write-ChainLog "  regressed (<0pp):         $($regressed.Count)"
Write-ChainLog "  infra fail (no JSON):     $($infra_fail.Count)"
Write-ChainLog "  avg lift:                 $avg_lift pp"

# Persist machine-readable summary
$summaryPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_tier${Tier}_summary.json"
$summary = @{
    tier = $Tier
    started_at = $start.ToUniversalTime().ToString('s') + "Z"
    elapsed_s = $total
    evaluated = $evaluated
    skipped = $skipped
    buckets = @{
        promote_v2 = $promote_v2
        keep_v1 = $keep_v1
        baseline = $baseline
        regressed = $regressed
        infra_fail = $infra_fail
    }
    avg_lift_pp = $avg_lift
} | ConvertTo-Json -Depth 6
Set-Content -LiteralPath $summaryPath -Value $summary -Encoding Unicode
Write-ChainLog "  summary: $summaryPath"

# Gate decisions (advisory; chain itself stops at end-of-tier per design)
Write-ChainLog ""
if ($Tier -eq 10) {
    if ($avg_lift -ge 3.0) {
        Write-ChainLog ">>> GATE PASSED: avg lift >= +3pp. Safe to run tier=25 next."
    } else {
        Write-ChainLog ">>> GATE FAILED: avg lift < +3pp. Halt before tier=25; review v1 mixins."
    }
} elseif ($Tier -eq 25) {
    if ($avg_lift -ge 2.0) {
        Write-ChainLog ">>> GATE PASSED: avg lift >= +2pp. Safe to run tier=50 next."
    } else {
        Write-ChainLog ">>> GATE FAILED: avg lift < +2pp. Halt before tier=50."
    }
} elseif ($Tier -eq 50) {
    Write-ChainLog ">>> Tier 50 done. Tier 105 is overnight-only."
}
Release-ChainLock
