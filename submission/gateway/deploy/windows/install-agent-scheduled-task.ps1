param(
    [string]$TaskName = "UnionAgents-wuying-01",
    [string]$RepoRoot = "D:\UnionAgents",
    [string]$AgentName = "wuying-01",
    [string]$AgentType = "reasonix",
    [string]$OrchestratorUrl = "http://111.228.42.18:8000",
    [string]$WorkspaceRoot = "D:\UnionAgents"
)

$ErrorActionPreference = "Stop"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false; Write-Host "Removed existing task: $TaskName" }

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) { throw "Python not found in PATH" }

$caps = '{\"coding\":true,\"reasonix\":true,\"standby\":true,\"list_dir\":true,\"edit_file\":true,\"read_file\":true,\"create_dir\":true,\"write_file\":true,\"delete_file\":true,\"run_command\":true,\"search_files\":true}'

$workerScript = Join-Path $RepoRoot "worker\worker_cli.py"
$logPath = Join-Path $RepoRoot "worker.log"

$argument = "--name $AgentName --host-id $AgentName --agent-type $AgentType --orchestrator-url $OrchestratorUrl --workspace-root $WorkspaceRoot --poll-interval 5 --log-path $logPath --capabilities `"$caps`" run"

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Seconds 10) -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "UnionAgents wuying-01 agent worker"
Write-Host "Task '$TaskName' registered"

Start-ScheduledTask -TaskName $TaskName
Start-Sleep 3
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "State: $($task.State)"
