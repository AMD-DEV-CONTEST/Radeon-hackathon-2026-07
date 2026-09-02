# Watch the 6-tool sprint chain.
$LogPath  = 'C:/Dev/Determinex/logs/programbench_remaining_chain.log'
$ChainPID = $null
try {
    $chainProc = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like '*run_programbench_remaining_chain.ps1*' } |
        Sort-Object ProcessId -Descending |
        Select-Object -First 1
    if ($chainProc) {
        $ChainPID = [int]$chainProc.ProcessId
    }
} catch {}
$StartSec = [int][double]::Parse((Get-Date -UFormat %s))
$LastSize = 0
$LastTool = ''

while ($true) {
    $now     = [int][double]::Parse((Get-Date -UFormat %s))
    $elapsed = $now - $StartSec

    # Docker health
    $dockerOut = (docker ps --format '{{.Names}} {{.Status}}' 2>&1) -join "`n"
    if ($dockerOut -match '500 Internal Server Error') {
        Write-Output ('[t+{0}s] !! DOCKER DAEMON CRASHED !!' -f $elapsed)
        break
    }

    # Container state
    $contLine = ($dockerOut -split "`n" | Where-Object { $_ -match 'programbench-' } | Select-Object -First 1)
    if ($contLine) {
        $contName   = ($contLine -split ' ', 2)[0]
        $contStatus = ($contLine -split ' ', 2)[1]
        if ($contStatus.Length -gt 40) { $contStatus = $contStatus.Substring(0, 40) }
        $stats = (docker stats --no-stream --format '{{.MemUsage}} cpu={{.CPUPerc}} pids={{.PIDs}}' $contName 2>$null | Select-Object -First 1)
    } else {
        $contName = '(none)'; $contStatus = 'no container'; $stats = ''
    }

    # Chain PID alive?
    $pidAlive = $false
    if ($ChainPID) {
        try { $null = Get-Process -Id $ChainPID -ErrorAction Stop; $pidAlive = $true } catch { $pidAlive = $false }
    }

    # Read log (UTF-16) for current tool + completion
    $logLen = 0; $latestTool = ''; $chainComplete = $false
    try {
        $logBytes = [System.IO.File]::ReadAllBytes($LogPath)
        $logLen = $logBytes.Length
        $logText = [System.Text.Encoding]::Unicode.GetString($logBytes)
        $runText = $logText
        $runStartMatches = [regex]::Matches($logText, '=== sprint chain start:')
        if ($runStartMatches.Count -gt 0) {
            $latestStart = $runStartMatches[$runStartMatches.Count - 1].Index
            $runText = $logText.Substring($latestStart)
        }
        $startMatches = [regex]::Matches($runText, '=== (\S+) starting ===')
        if ($startMatches.Count -gt 0) { $latestTool = $startMatches[$startMatches.Count - 1].Groups[1].Value }
        if ($runText -match '=== chain complete in \d+s ===') { $chainComplete = $true }
    } catch {}
    $logGrew = $logLen - $LastSize
    $LastSize = $logLen

    if ($latestTool -ne $LastTool -and $latestTool -ne '') {
        Write-Output ('[t+{0}s] >> tool transition: {1} -> {2}' -f $elapsed, $LastTool, $latestTool)
        $LastTool = $latestTool
    }

    $msg = '[t+{0}s] tool={1} container={2} status="{3}" {4} chain_pid={5} pid_alive={6} log_grew={7}b' -f `
        $elapsed, $latestTool, $contName, $contStatus, $stats, $ChainPID, $pidAlive, $logGrew
    Write-Output $msg

    if ($chainComplete) {
        Write-Output ('[t+{0}s] !! CHAIN COMPLETE !!' -f $elapsed)
        break
    }
    if (-not $pidAlive) {
        Write-Output ('[t+{0}s] !! CHAIN PID EXITED !!' -f $elapsed)
        break
    }

    Start-Sleep -Seconds 60
}
