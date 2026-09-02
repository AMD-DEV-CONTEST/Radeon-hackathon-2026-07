param(
    [string]$ProgramBenchDir = "T:\Dev\ProgramBench",
    [string]$LogPath = "C:\Dev\Determinex\logs\sprint4_factory_eval_chain.log",
    [int]$ToolTimeoutMinutes = 30
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:DOCKER_CONFIG = "C:\Dev\Determinex\logs\docker_config"
$env:UV_CACHE_DIR = "C:\Dev\Determinex\logs\uv_cache"
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue
$ProgramBenchExe = Join-Path $ProgramBenchDir ".venv\Scripts\programbench.exe"

# First 5 of the 10 factory targets (per user: "5 evaluated" as min)
$tools = @(
    @{ Instance = "dalance__amber.69a0f52";              Filter = "dalance" },
    @{ Instance = "pls-rs__pls.4e1ae50";                 Filter = "pls-rs" },
    @{ Instance = "ksxgithub__parallel-disk-usage.96978ed"; Filter = "ksxgithub" },
    @{ Instance = "pier-cli__pier.5e1bde9";              Filter = "pier-cli" },
    @{ Instance = "ecumene__rust-sloth.051c559";         Filter = "ecumene" }
)

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

function Invoke-ProgramBenchWithTimeout {
    param([string]$Exe, [string[]]$ProgramArgs, [string]$ToolName, [int]$TimeoutMinutes)
    $safeName = $ToolName -replace '[^A-Za-z0-9_.-]', '_'
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $stdoutPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_${safeName}_${stamp}.out.log"
    $stderrPath = Join-Path (Split-Path -Parent $LogPath) "sprint4_${safeName}_${stamp}.err.log"
    $proc = Start-Process -FilePath $Exe -ArgumentList $ProgramArgs `
        -WorkingDirectory $ProgramBenchDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while (-not $proc.HasExited) {
        if ((Get-Date) -gt $deadline) {
            Write-ChainLog "!! $ToolName exceeded ${TimeoutMinutes}m timeout; killing"
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch { }
            return @{ Rc = 124; Output = @("TIMEOUT") }
        }
        Start-Sleep -Seconds 5
        try { $proc.Refresh() } catch { }
    }
    $lines = @()
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) {
            try { $lines += Get-Content -LiteralPath $path -Tail 8 -ErrorAction SilentlyContinue } catch { }
        }
    }
    return @{ Rc = $proc.ExitCode; Output = $lines }
}

function Write-Score {
    param([hashtable]$Tool, [string]$Root)
    try {
        $files = Get-ChildItem -Path $Root -Recurse -Filter "*.eval.json" -ErrorAction SilentlyContinue
        if (-not $files) {
            Write-ChainLog "  $($Tool.Instance): NO EVAL JSON WRITTEN"
            return [bool]$false
        }
        $latest = $files | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $json = Get-Content -Raw -LiteralPath $latest.FullName | ConvertFrom-Json
        $results = @($json.test_results)
        $passed = @($results | Where-Object { $_.status -eq "passed" }).Count
        $total = $results.Count
        $score = if ($total -gt 0) { 100.0 * $passed / $total } else { 0.0 }
        Write-ChainLog ("  {0}: {1}/{2} = {3:N2}%" -f $Tool.Instance, $passed, $total, $score)
        return [bool]$true
    } catch {
        Write-ChainLog "  $($Tool.Instance): score parse failed: $($_.Exception.Message)"
        return [bool]$true
    }
}

$start = Get-Date
Write-ChainLog "=== sprint4 factory eval chain start: $($start.ToUniversalTime().ToString('s'))Z ==="
Write-ChainLog "policy: --workers 1 --branch-workers 1 --docker-cpus 1 (sprint4 factory; xdist-safe)"
Write-ChainLog "programbench: $ProgramBenchExe"

foreach ($tool in $tools) {
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    Write-ChainLog "[t+$($elapsed)s] === $($tool.Instance) starting ==="
    Assert-DockerHealthy "before $($tool.Instance)"

    $root = "T:\determinex-programbench\determinex_pb_factory_$($tool.Instance)_v1"
    $cmdArgs = @(
        "eval", $root,
        "--filter", $tool.Filter,
        "--workers", "1",
        "--branch-workers", "1",
        "--docker-cpus", "1",
        "--force"
    )
    $run = Invoke-ProgramBenchWithTimeout `
        -Exe $ProgramBenchExe `
        -ProgramArgs $cmdArgs `
        -ToolName $tool.Instance `
        -TimeoutMinutes $ToolTimeoutMinutes
    $rc = [int]$run.Rc
    $tail = @($run.Output | Select-Object -Last 8)
    foreach ($line in $tail) { Write-ChainLog "  $line" }

    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    Write-ChainLog "[t+$($elapsed)s] === $($tool.Instance) finished (rc=$rc) ==="
    $producedResult = @(Write-Score $tool $root)
    $produced = if ($producedResult.Count -gt 0) { [bool]$producedResult[-1] } else { $false }
    Assert-DockerHealthy "after $($tool.Instance)"

    if ($rc -ne 0) {
        if (-not $produced) {
            Write-ChainLog "!! $($tool.Instance) produced no eval JSON (rc=$rc); halting chain"
            exit $rc
        }
        Write-ChainLog "  $($tool.Instance): rc=$rc but eval JSON exists; continuing chain"
    }
}

$total = [int]((Get-Date) - $start).TotalSeconds
Write-ChainLog "=== chain complete in ${total}s ==="
