<#
.SYNOPSIS
    Keeps scripts/corpus_sentinel.py alive across crashes and reboots.

.DESCRIPTION
    corpus_sentinel.py is a bare background process (started via nohup/&) --
    it has no supervisor, so a crash or a box reboot kills it silently with
    no one telling you it's gone (the same failure mode already seen once in
    this project for a different daemon: a nohup'd loop that dies on reboot
    with no systemd unit to restart it).

    This script is the supervisor: check whether the PID in
    logs/corpus_sentinel/sentinel.pid is still a live process; if not
    (missing pidfile, stale PID, or process gone), relaunch it. Idempotent --
    safe to run repeatedly on a schedule.

    Install as a self-healing Scheduled Task with:
        powershell -File scripts/corpus_sentinel_watchdog.ps1 -Install

    This registers TWO triggers: AtLogOn (recovers after a reboot) and every
    5 minutes (recovers from an in-session crash without waiting for a
    reboot). Both run this same script with -Check (its default action).
#>
param(
    [switch]$Install,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $RepoRoot "logs\corpus_sentinel\sentinel.pid"
$ConsoleLog = Join-Path $RepoRoot "logs\corpus_sentinel\console.log"
$TaskName = "DeterminexCorpusSentinelWatchdog"

function Test-SentinelAlive {
    if (-not (Test-Path $PidFile)) { return $false }
    $procId = (Get-Content $PidFile -Raw).Trim()
    if (-not $procId) { return $false }
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    # PID reuse guard: confirm it's actually a python process, not some
    # unrelated process that happens to have recycled this PID.
    return $proc.ProcessName -like "python*"
}

function Start-Sentinel {
    Write-Host "corpus_sentinel_watchdog: (re)starting corpus_sentinel.py"
    New-Item -ItemType Directory -Force -Path (Split-Path $PidFile) | Out-Null
    Start-Process -FilePath "python3" `
        -ArgumentList "scripts/corpus_sentinel.py" `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ConsoleLog `
        -RedirectStandardError "$ConsoleLog.err"
}

function Install-WatchdogTask {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -File `"$PSCommandPath`" -Check"
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn
    $triggerInterval = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($triggerLogon, $triggerInterval) -Settings $settings -Force | Out-Null
    Write-Host "Installed scheduled task '$TaskName' (triggers: at logon, every 5 min)"
}

if ($Install) {
    Install-WatchdogTask
    exit 0
}

# Default action (including -Check, or no flag at all): verify and heal.
if (Test-SentinelAlive) {
    exit 0
}
Start-Sentinel
