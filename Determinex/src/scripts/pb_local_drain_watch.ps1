param(
    [int]$TargetActive = 5,
    [int]$IntervalSeconds = 120,
    [string]$LogPath = "logs\programbench_factory\local_drain_watch.log"
)

$ErrorActionPreference = "Continue"
$Python = ".\.venv\Scripts\python.exe"

function Write-DrainLog($Message) {
    $ts = Get-Date -Format o
    Add-Content -Path $LogPath -Value "$ts $Message"
}

while ($true) {
    try {
        $paused = docker ps -q --filter status=paused 2>$null
        foreach ($id in $paused) {
            docker unpause $id 2>&1 | ForEach-Object { Write-DrainLog "unpause $_" }
        }

        & $Python scripts\pb_native_eval_queue.py --top 5 2>&1 |
            ForEach-Object { Write-DrainLog "queue $_" }

        & $Python scripts\pb_gate_evaluated_queue.py 2>&1 |
            ForEach-Object { Write-DrainLog "gate $_" }

        & $Python scripts\pb_reject_triage_queue.py --top 12 2>&1 |
            ForEach-Object { Write-DrainLog "triage $_" }

        $active = @(docker ps --format "{{.Names}}" 2>$null | Where-Object { $_ -like "programbench-*" }).Count
        $need = $TargetActive - $active
        Write-DrainLog "active=$active target=$TargetActive need=$need"
        if ($need -gt 0) {
            & $Python scripts\pb_native_eval_queue.py --launch $need 2>&1 |
                ForEach-Object { Write-DrainLog "launch $_" }
        }
    } catch {
        Write-DrainLog "ERROR $($_.Exception.Message)"
    }

    Start-Sleep -Seconds $IntervalSeconds
}
