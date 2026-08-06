$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

uv sync --project backend
uv run --project backend uvicorn colorgraph.api.app:app --host 127.0.0.1 --port 8010 --reload
