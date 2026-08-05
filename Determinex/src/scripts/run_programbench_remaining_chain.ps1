param(
    [string]$ProgramBenchDir = "T:\Dev\ProgramBench",
    [string]$LogPath = "C:\Dev\Determinex\logs\programbench_remaining_chain.log",
    [string]$StartFrom = "",
    [int]$ToolTimeoutMinutes = 45
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:DOCKER_CONFIG = "C:\Dev\Determinex\logs\docker_config"
$env:UV_CACHE_DIR = "C:\Dev\Determinex\logs\uv_cache"
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $env:DOCKER_CONFIG | Out-Null
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null
$ProgramBenchExe = Join-Path $ProgramBenchDir ".venv\Scripts\programbench.exe"

$tools = @(
    @{ Root = "T:\determinex-programbench\determinex_pb_tex-fmt_v1";    Filter = "wgunderwood";    Name = "tex-fmt" },
    @{ Root = "T:\determinex-programbench\determinex_pb_cheat_v1";      Filter = "cheat__";        Name = "cheat" },
    @{ Root = "T:\determinex-programbench\determinex_pb_genact_v1";     Filter = "svenstaro";      Name = "genact" },
    @{ Root = "T:\determinex-programbench\determinex_pb_tuc_v1";        Filter = "riquito";        Name = "tuc" },
    @{ Root = "T:\determinex-programbench\determinex_pb_svd2rust_v1";   Filter = "rust-embedded";  Name = "svd2rust" },
    @{ Root = "T:\determinex-programbench\determinex_pb_git-trim_v1";   Filter = "foriequal0";     Name = "git-trim" }
)

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

function Write-ChainLog {
    # IMPORTANT: must not emit to the pipeline. Tee-Object writes the line to
    # BOTH file and pipeline, which pollutes any function return that calls
    # Write-ChainLog before its `return` (e.g. Write-Score). We separate
    # console echo from file write and explicitly use Out-Null on both.
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    Write-Host $line
    try {
        Add-Content -LiteralPath $LogPath -Value $line -Encoding Unicode
    }
    catch {
        # best-effort; do not throw
    }
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
    param(
        [string]$Exe,
        [string[]]$ProgramArgs,
        [string]$ToolName,
        [int]$TimeoutMinutes
    )

    $safeName = $ToolName -replace '[^A-Za-z0-9_.-]', '_'
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $stdoutPath = Join-Path (Split-Path -Parent $LogPath) "programbench_${safeName}_${stamp}.out.log"
    $stderrPath = Join-Path (Split-Path -Parent $LogPath) "programbench_${safeName}_${stamp}.err.log"

    $proc = Start-Process -FilePath $Exe `
        -ArgumentList $ProgramArgs `
        -WorkingDirectory $ProgramBenchDir `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while (-not $proc.HasExited) {
        if ((Get-Date) -gt $deadline) {
            Write-ChainLog "!! $ToolName exceeded ${TimeoutMinutes}m timeout; terminating process tree"
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            } catch {}
            return @{
                Rc = 124
                Output = @("TIMEOUT after ${TimeoutMinutes}m", "stdout=$stdoutPath", "stderr=$stderrPath")
            }
        }
        Start-Sleep -Seconds 5
        try { $proc.Refresh() } catch {}
    }

    $lines = @()
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) {
            try {
                $lines += Get-Content -LiteralPath $path -Tail 8 -ErrorAction SilentlyContinue
            } catch {}
        }
    }
    return @{
        Rc = $proc.ExitCode
        Output = $lines
    }
}

function Write-Score {
    # Returns $true if eval JSON was produced for this tool (regardless of score),
    # $false if no eval JSON was written. Used to decide whether a non-zero rc
    # represents a real infra failure (no JSON) or just imperfect scores (JSON exists).
    param([hashtable]$Tool)
    try {
        $files = Get-ChildItem -Path $Tool.Root -Recurse -Filter "*.eval.json" -ErrorAction SilentlyContinue
        if (-not $files) {
            Write-ChainLog "  $($Tool.Name): NO EVAL JSON WRITTEN"
            return [bool]$false
        }
        $latest = $files | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $json = Get-Content -Raw -LiteralPath $latest.FullName | ConvertFrom-Json
        $results = @($json.test_results)
        $passed = @($results | Where-Object { $_.status -eq "passed" }).Count
        $total = $results.Count
        $score = if ($total -gt 0) { 100.0 * $passed / $total } else { 0.0 }
        Write-ChainLog ("  {0}: {1}/{2} = {3:N2}% ({4})" -f $Tool.Name, $passed, $total, $score, $latest.FullName)
        return [bool]$true
    }
    catch {
        Write-ChainLog "  $($Tool.Name): score parse failed but chain continues: $($_.Exception.Message)"
        return [bool]$true   # JSON exists but parse failed - still treat as "ran"
    }
}

if ($StartFrom) {
    $startIndex = -1
    for ($i = 0; $i -lt $tools.Count; $i++) {
        if ($tools[$i].Name -eq $StartFrom) {
            $startIndex = $i
            break
        }
    }
    if ($startIndex -lt 0) {
        throw "unknown -StartFrom '$StartFrom'. Valid: $($tools.Name -join ', ')"
    }
    $tools = @($tools[$startIndex..($tools.Count - 1)])
}

$start = Get-Date
Write-ChainLog "=== sprint chain start: $($start.ToUniversalTime().ToString("s"))Z ==="
Write-ChainLog "policy: --workers 1 --branch-workers 1 --docker-cpus 1 (xdist-safe)"
Write-ChainLog "programbench: $ProgramBenchExe"
Write-ChainLog "tool-timeout: ${ToolTimeoutMinutes}m"
if ($StartFrom) {
    Write-ChainLog "resume: StartFrom=$StartFrom"
}

foreach ($tool in $tools) {
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    Write-ChainLog "[t+$($elapsed)s] === $($tool.Name) starting ==="
    Assert-DockerHealthy "before $($tool.Name)"

    Push-Location $ProgramBenchDir
    try {
        $args = @(
            "eval",
            $tool.Root,
            "--filter", $tool.Filter,
            "--workers", "1",
            "--branch-workers", "1",
            "--docker-cpus", "1",
            "--force"
        )
        $run = Invoke-ProgramBenchWithTimeout `
            -Exe $ProgramBenchExe `
            -ProgramArgs $args `
            -ToolName $tool.Name `
            -TimeoutMinutes $ToolTimeoutMinutes
        $rc = [int]$run.Rc
        $tail = @($run.Output | Select-Object -Last 8)
        foreach ($line in $tail) {
            Write-ChainLog "  $line"
        }
    }
    finally {
        Pop-Location
    }

    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    Write-ChainLog "[t+$($elapsed)s] === $($tool.Name) finished (rc=$rc) ==="
    $producedResult = @(Write-Score $tool)
    $produced = if ($producedResult.Count -gt 0) { [bool]$producedResult[-1] } else { $false }
    Assert-DockerHealthy "after $($tool.Name)"

    # Halt only on true infra failure (no eval JSON). A non-zero rc with valid
    # JSON is just the programbench score signal, not a chain stop condition.
    if ($rc -ne 0) {
        if (-not $produced) {
            $haltMsg = "!! " + $tool.Name + " produced no eval JSON (rc=" + $rc + "); halting chain"
            Write-ChainLog $haltMsg
            exit $rc
        }
        $warnMsg = "  " + $tool.Name + ": rc=" + $rc + " but eval JSON exists; continuing chain"
        Write-ChainLog $warnMsg
    }
}

$total = [int]((Get-Date) - $start).TotalSeconds
Write-ChainLog "=== chain complete in ${total}s ==="
