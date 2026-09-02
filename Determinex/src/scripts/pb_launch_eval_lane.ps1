param(
    [Parameter(Mandatory=$true)][string]$Slug,
    [Parameter(Mandatory=$true)][string]$RunRoot,
    [Parameter(Mandatory=$true)][string]$Name
)

$ErrorActionPreference = "Stop"

$determinexRoot = "C:\Dev\Determinex"
$programBenchRoot = "T:\Dev\ProgramBench"
$logDir = Join-Path $determinexRoot "logs\programbench_factory"
$cacheDir = Join-Path "C:\tmp\uvcache" $Name

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

$resolvedRunRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RunRoot)

$outLog = Join-Path $logDir "$Name.out.log"
$errLog = Join-Path $logDir "$Name.err.log"

$cmd = @"
`$ErrorActionPreference = 'Stop'
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
`$env:PYTHONUTF8 = '1'
`$env:PYTHONIOENCODING = 'utf-8'
`$env:UV_CACHE_DIR = '$cacheDir'
Set-Location '$programBenchRoot'
uv run programbench eval '$resolvedRunRoot' --filter '$Slug' --force
"@

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd) `
    -WorkingDirectory $programBenchRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

Write-Output "launched $Slug -> $resolvedRunRoot"
Write-Output "stdout: $outLog"
Write-Output "stderr: $errLog"
