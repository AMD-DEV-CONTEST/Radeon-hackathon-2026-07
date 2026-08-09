$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "data\run"
foreach ($Name in @("frontend", "backend", "ai-service")) {
    $PidFile = Join-Path $RunDir "$Name.pid"
    if (Test-Path $PidFile) {
        $ProcessId = [int](Get-Content -LiteralPath $PidFile)
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PidFile -Force
        Write-Host "Stopped $Name"
    }
}
foreach ($Port in @(8000, 8081, 5173)) {
    $Conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($Conns) {
        foreach ($Conn in $Conns) {
            if ($Conn.OwningProcess -gt 0) {
                Stop-Process -Id $Conn.OwningProcess -Force -ErrorAction SilentlyContinue
                Write-Host "Stopped process ($($Conn.OwningProcess)) on port $Port"
            }
        }
    }
}

