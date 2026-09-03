param(
    [int]$Port = 8081,
    [int]$ContextSize = 4096,
    [int]$GpuLayers = 8
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$modelPath = Join-Path $projectRoot "runtime\models\Qwen3-4B-Q4_K_M.gguf"
if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "The local model is not installed. Run scripts\setup_local_llm.ps1 first."
}

$bundled = Join-Path $projectRoot "runtime\llm\llama-server.exe"
if (Test-Path -LiteralPath $bundled) {
    $server = $bundled
} else {
  $command = Get-Command llama-server.exe,llama-server -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $command) {
    $wingetLink = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\llama-server.exe"
    if (Test-Path -LiteralPath $wingetLink) {
        $server = $wingetLink
    } else {
        throw "llama-server was not found. Run scripts\setup_local_llm.ps1 again."
    }
  } else {
    $server = $command.Source
  }
}

if ($env:YIJIAN_LLM_GPU_LAYERS -match '^\d+$') {
    $GpuLayers = [int]$env:YIJIAN_LLM_GPU_LAYERS
}
$threads = [Math]::Max(4, [Environment]::ProcessorCount - 2)
Write-Host "Starting Yijian offline mentor: Qwen3-4B Q4, GPU layers $GpuLayers, port $Port"
& $server --model $modelPath --alias Qwen3-4B-Q4_K_M `
    --host 127.0.0.1 --port $Port --ctx-size $ContextSize --parallel 1 `
    --threads $threads --n-gpu-layers $GpuLayers
