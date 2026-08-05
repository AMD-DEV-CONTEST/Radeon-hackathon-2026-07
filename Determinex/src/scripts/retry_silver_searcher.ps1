# Retry silver_searcher with --docker-cpus 1 (xdist single-worker, no deadlock).
# Runs in the background and the watcher picks up the eval JSON once written.
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:DOCKER_CONFIG = "C:\Dev\Determinex\logs\docker_config"
$env:UV_CACHE_DIR = "C:\Dev\Determinex\logs\uv_cache"
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue

$ProgramBenchDir = "T:\Dev\ProgramBench"
$Exe = Join-Path $ProgramBenchDir ".venv\Scripts\programbench.exe"

# Wait until the main chain is past silver_searcher (already moved to git-graph)
# then run a fresh eval against the existing factory v1 scaffold.
$args = @(
    "eval", "T:\determinex-programbench\determinex_pb_factory_ggreer__the_silver_searcher.a61f178_v1",
    "--filter", "ggreer",
    "--workers", "1",
    "--branch-workers", "1",
    "--docker-cpus", "1",
    "--force"
)

$logDir = "C:\Dev\Determinex\logs"
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stdoutPath = Join-Path $logDir "silver_searcher_retry_${stamp}.out.log"
$stderrPath = Join-Path $logDir "silver_searcher_retry_${stamp}.err.log"

Write-Host "Launching silver_searcher retry with --docker-cpus 1"
Write-Host "  exe:    $Exe"
Write-Host "  args:   $($args -join ' ')"
Write-Host "  stdout: $stdoutPath"

$proc = Start-Process -FilePath $Exe `
    -ArgumentList $args `
    -WorkingDirectory $ProgramBenchDir `
    -NoNewWindow -PassThru `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath

Write-Host "  pid:    $($proc.Id)"
Write-Host ""
Write-Host "Watch progress with:"
Write-Host "  Get-Content -Tail 20 -Wait '$stdoutPath'"
Write-Host ""
Write-Host "Score when done:"
Write-Host "  Get-Content T:\determinex-programbench\determinex_pb_factory_ggreer__the_silver_searcher.a61f178_v1\ggreer__the_silver_searcher.a61f178\ggreer__the_silver_searcher.a61f178.eval.json | ConvertFrom-Json"
