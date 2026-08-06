$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

npm install
npm run dev -- --host 127.0.0.1 --port 4173
