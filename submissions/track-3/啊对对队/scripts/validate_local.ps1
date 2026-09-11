param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ($PythonPath) {
    $PythonExecutable = (Resolve-Path -LiteralPath $PythonPath).Path
}
else {
    $PythonExecutable = (Get-Command python -ErrorAction Stop).Source
}
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$env:PYTHONDONTWRITEBYTECODE = "1"

Push-Location $ProjectRoot
try {
    & $PythonExecutable -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed"
    }
    & $PythonExecutable -m parcel_sorter --config configs/baseline.toml
    if ($LASTEXITCODE -ne 0) {
        throw "CPU dry run failed"
    }
}
finally {
    Pop-Location
}
