#Requires -Version 5.1
<#
.SYNOPSIS
    Determinex Windows Literacy — PowerShell sandbox harness.
    Runs AI-generated PowerShell inside Windows Sandbox for safe execution validation.

.DESCRIPTION
    For each task prompt:
      1. Calls the model API to generate a PowerShell script
      2. Writes the script + a validation shim to a temp dir
      3. Launches Windows Sandbox with a .wsb config pointing at the temp dir
      4. The sandbox runs the script, writes pass/fail JSON, exits
      5. Harness reads the result JSON and records it

    Requires Windows Sandbox feature enabled:
      Enable-WindowsOptionalFeature -FeatureName "Containers-DisposableClientVM" -Online

.PARAMETER Model
    deepseek | claude | gpt

.PARAMETER TaskIds
    Comma-separated list of task IDs. Default: all path+envvar tasks.

.PARAMETER SkipExecution
    Score responses purely on static rubric analysis — no sandbox execution.
    Useful for quick iteration without spinning up VMs.

.EXAMPLE
    .\ps_aishell_eval.ps1 -Model deepseek
    .\ps_aishell_eval.ps1 -Model claude -SkipExecution
#>
param(
    [ValidateSet("deepseek","claude","gpt")]
    [string]$Model = "deepseek",
    [string]$TaskIds = "",
    [switch]$SkipExecution
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RootDir   = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$LogsDir   = Join-Path $RootDir "logs\windows_bench"
$ScratchDir = Join-Path $env:TEMP "determinex_winbench_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $ScratchDir | Out-Null

# ── Task definitions (PS subset) ──────────────────────────────────────────────
$Tasks = @(
    @{
        Id       = "path_join_ps"
        Category = "path"
        Weight   = 3
        Prompt   = "Write PowerShell to build the path C:\Users\ryan\Documents\report.txt from its parts using the recommended method."
        ValidateScript = {
            param($Output)
            # Must produce a valid path — sandbox runs it and checks output
            $Output -match "C:\\Users\\ryan\\Documents\\report\.txt"
        }
        MustContain    = @("Join-Path")
        MustNotContain = @("/usr/", "/home/", "~/")
    },
    @{
        Id       = "envvar_read_ps"
        Category = "envvar"
        Weight   = 3
        Prompt   = "Write PowerShell to print the current user's home directory."
        ValidateScript = {
            param($Output)
            $Output -match "C:\\Users\\"
        }
        MustContain    = @('$env:USERPROFILE', '$env:HOME', '[Environment]::GetFolderPath')
        MustNotContain = @("~/", "/home/")
    },
    @{
        Id       = "process_list_ps"
        Category = "process"
        Weight   = 2
        Prompt   = "Write PowerShell to list the top 5 processes by memory usage, showing name and working set."
        ValidateScript = { param($Output) $Output -match "\w+" }
        MustContain    = @("Get-Process")
        MustNotContain = @("ps aux", "top ", "htop")
    },
    @{
        Id       = "fs_tempfile_ps"
        Category = "filesystem"
        Weight   = 2
        Prompt   = "Write PowerShell to create a temp file, write 'Determinex test' to it, then read and print it."
        ValidateScript = { param($Output) $Output -match "Determinex test" }
        MustContain    = @('$env:TEMP', 'New-TemporaryFile', '[System.IO.Path]::GetTempFileName')
        MustNotContain = @("/tmp/")
    }
)

if ($TaskIds) {
    $ids = $TaskIds -split ","
    $Tasks = $Tasks | Where-Object { $ids -contains $_.Id }
}

# ── API call helper ───────────────────────────────────────────────────────────
function Invoke-ModelAPI {
    param([string]$Prompt, [string]$Model)

    $system = @"
You are an expert Windows PowerShell developer. Write only PowerShell code.
Never use Linux tools, Unix paths, bash syntax, or non-Windows commands.
Use Join-Path, `$env: variables, Get-Process, icacls, winget, etc.
Return code only — no explanation, no markdown fences.
"@

    switch ($Model) {
        "deepseek" {
            $key = $env:DEEPSEEK_API_KEY
            if (-not $key) { throw "DEEPSEEK_API_KEY not set" }
            $body = @{
                model    = "deepseek-chat"
                messages = @(
                    @{ role = "system"; content = $system }
                    @{ role = "user";   content = $Prompt }
                )
                max_tokens  = 512
                temperature = 0.2
            } | ConvertTo-Json -Depth 5
            $resp = Invoke-RestMethod -Uri "https://api.deepseek.com/chat/completions" `
                -Method POST `
                -Headers @{ Authorization = "Bearer $key"; "Content-Type" = "application/json" } `
                -Body $body
            return $resp.choices[0].message.content
        }
        "claude" {
            $key = $env:ANTHROPIC_API_KEY
            if (-not $key) { throw "ANTHROPIC_API_KEY not set" }
            $body = @{
                model      = "claude-sonnet-4-6"
                max_tokens = 512
                system     = $system
                messages   = @(@{ role = "user"; content = $Prompt })
            } | ConvertTo-Json -Depth 5
            $resp = Invoke-RestMethod -Uri "https://api.anthropic.com/v1/messages" `
                -Method POST `
                -Headers @{ "x-api-key" = $key; "anthropic-version" = "2023-06-01"; "Content-Type" = "application/json" } `
                -Body $body
            return $resp.content[0].text
        }
        "gpt" {
            $key = $env:OPENAI_API_KEY
            if (-not $key) { throw "OPENAI_API_KEY not set" }
            $body = @{
                model    = "gpt-4o"
                messages = @(
                    @{ role = "system"; content = $system }
                    @{ role = "user";   content = $Prompt }
                )
                max_tokens  = 512
                temperature = 0.2
            } | ConvertTo-Json -Depth 5
            $resp = Invoke-RestMethod -Uri "https://api.openai.com/v1/chat/completions" `
                -Method POST `
                -Headers @{ Authorization = "Bearer $key"; "Content-Type" = "application/json" } `
                -Body $body
            return $resp.choices[0].message.content
        }
    }
}

# ── Static rubric scoring ─────────────────────────────────────────────────────
function Get-RubricScore {
    param([hashtable]$Task, [string]$Response)

    $checks = @()
    $passed = 0; $total = 0

    foreach ($pat in $Task.MustContain) {
        $total++
        $hit = $Response -match [regex]::Escape($pat)
        if ($hit) { $passed++ }
        $checks += @{ pattern = $pat; required = $true; passed = $hit }
    }
    foreach ($pat in $Task.MustNotContain) {
        $total++
        $hit = -not ($Response -match [regex]::Escape($pat))
        if ($hit) { $passed++ }
        $checks += @{ pattern = $pat; required = $false; passed = $hit }
    }

    # Linux-ism detection
    $linuxisms = @("/usr/","/home/","~/","apt install","yum install","chmod ","chown ",
                   "ln -s","pkill","export ","systemctl","iptables","sed -i","#!/bin/bash")
    $linuxCount = ($linuxisms | Where-Object { $Response -match [regex]::Escape($_) }).Count

    return @{
        Score      = if ($total -gt 0) { [math]::Round($passed / $total, 3) } else { 1.0 }
        Checks     = $checks
        LinuxIsms  = $linuxCount
    }
}

# ── Windows Sandbox runner ────────────────────────────────────────────────────
function Invoke-InSandbox {
    param([string]$ScriptContent, [string]$TaskId, [string]$ScratchDir)

    $taskDir    = Join-Path $ScratchDir $TaskId
    New-Item -ItemType Directory -Force -Path $taskDir | Out-Null

    $scriptFile  = Join-Path $taskDir "task.ps1"
    $resultFile  = Join-Path $taskDir "result.json"
    $wrapperFile = Join-Path $taskDir "run.ps1"
    $wsbFile     = Join-Path $taskDir "sandbox.wsb"

    $ScriptContent | Set-Content -Path $scriptFile -Encoding UTF8

    # Wrapper: run task, capture output+exitcode, write result JSON, then shutdown
    @"
`$output = ""
`$exitCode = 0
try {
    `$output = & powershell -NonInteractive -ExecutionPolicy Bypass -File 'C:\sandbox\task.ps1' 2>&1 | Out-String
    `$exitCode = `$LASTEXITCODE
} catch {
    `$output = `$_.ToString()
    `$exitCode = 1
}
`$result = @{ output = `$output; exitCode = `$exitCode } | ConvertTo-Json
`$result | Set-Content -Path 'C:\sandbox\result.json' -Encoding UTF8
Stop-Computer -Force
"@ | Set-Content -Path $wrapperFile -Encoding UTF8

    # Windows Sandbox config — maps $taskDir to C:\sandbox inside VM
    @"
<Configuration>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$taskDir</HostFolder>
      <SandboxFolder>C:\sandbox</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell -NonInteractive -ExecutionPolicy Bypass -File C:\sandbox\run.ps1</Command>
  </LogonCommand>
  <Networking>Disable</Networking>
</Configuration>
"@ | Set-Content -Path $wsbFile -Encoding UTF8

    Write-Host "    [SANDBOX] Launching Windows Sandbox for $TaskId..." -ForegroundColor DarkCyan
    $proc = Start-Process -FilePath $wsbFile -PassThru
    # Wait up to 90 seconds for sandbox to finish and write result
    $deadline = (Get-Date).AddSeconds(90)
    while (-not (Test-Path $resultFile) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
    }
    if (Test-Path $resultFile) {
        $result = Get-Content $resultFile -Raw | ConvertFrom-Json
        return @{ output = $result.output; exitCode = $result.exitCode; timedOut = $false }
    } else {
        # Kill sandbox if still running
        if (-not $proc.HasExited) { $proc | Stop-Process -Force }
        return @{ output = "TIMEOUT"; exitCode = -1; timedOut = $true }
    }
}

# ── Main loop ─────────────────────────────────────────────────────────────────
$allResults = @()
$ts = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "`nDeterminex Windows Literacy — PS Sandbox Eval" -ForegroundColor Cyan
Write-Host "Model: $Model  Tasks: $($Tasks.Count)  Sandbox: $(-not $SkipExecution)" -ForegroundColor Cyan
Write-Host ("=" * 60)

foreach ($task in $Tasks) {
    Write-Host "`n[$($task.Id)] $($task.Category) weight=$($task.Weight)" -ForegroundColor Yellow

    $t0 = Get-Date
    try {
        $response = Invoke-ModelAPI -Prompt $task.Prompt -Model $Model
    } catch {
        Write-Host "  ERROR generating: $_" -ForegroundColor Red
        $allResults += @{ taskId = $task.Id; error = $_.ToString(); score = 0 }
        continue
    }
    $latency = ((Get-Date) - $t0).TotalSeconds

    # Static rubric scoring
    $rubric = Get-RubricScore -Task $task -Response $response

    # Sandbox execution (unless skipped)
    $execResult = $null
    if (-not $SkipExecution) {
        $execResult = Invoke-InSandbox -ScriptContent $response -TaskId $task.Id -ScratchDir $ScratchDir
    }

    $execPassed = if ($execResult) { $execResult.exitCode -eq 0 } else { $null }

    # Combined score: rubric 70% + exec 30% (if available)
    $finalScore = if ($null -ne $execPassed) {
        [math]::Round($rubric.Score * 0.7 + ([int]$execPassed) * 0.3, 3)
    } else { $rubric.Score }

    $status = if ($finalScore -ge 0.9) { "PASS" } elseif ($finalScore -ge 0.6) { "WARN" } else { "FAIL" }
    $color  = if ($status -eq "PASS") { "Green" } elseif ($status -eq "WARN") { "Yellow" } else { "Red" }
    Write-Host "  [$status] score=$($finalScore.ToString('P0'))  linux-isms=$($rubric.LinuxIsms)  latency=$([math]::Round($latency,1))s" -ForegroundColor $color

    $allResults += @{
        taskId        = $task.Id
        category      = $task.Category
        weight        = $task.Weight
        model         = $Model
        prompt        = $task.Prompt
        response      = $response
        rubricScore   = $rubric.Score
        execPassed    = $execPassed
        finalScore    = $finalScore
        linuxIsmCount = $rubric.LinuxIsms
        latencySec    = [math]::Round($latency, 2)
        checks        = $rubric.Checks
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────
$totalWeight = ($Tasks | Measure-Object -Property Weight -Sum).Sum
$weightedScore = if ($totalWeight -gt 0) {
    ($allResults | ForEach-Object { $_.finalScore * $_.weight } | Measure-Object -Sum).Sum / $totalWeight
} else { 0 }

$totalLinux = ($allResults | Measure-Object -Property linuxIsmCount -Sum).Sum
$passCount  = ($allResults | Where-Object { $_.finalScore -ge 0.9 }).Count

$summary = @{
    model              = $Model
    timestamp          = $ts
    sandboxExecution   = -not $SkipExecution
    tasksRun           = $allResults.Count
    weightedScorePct   = [math]::Round($weightedScore * 100, 1)
    totalLinuxIsms     = $totalLinux
    passCount          = $passCount
    failCount          = $allResults.Count - $passCount
    results            = $allResults
}

$outPath = Join-Path $LogsDir "${ts}_ps_${Model}.json"
$summary | ConvertTo-Json -Depth 10 | Set-Content -Path $outPath -Encoding UTF8

Write-Host ("`n" + "=" * 60) -ForegroundColor Cyan
Write-Host "RESULTS — $Model (PowerShell harness)" -ForegroundColor Cyan
Write-Host "  Windows Literacy Score: $($summary.weightedScorePct)%"
Write-Host "  Linux-ism injections:   $totalLinux"
Write-Host "  Pass: $($summary.passCount)  Fail: $($summary.failCount)"
Write-Host "  Results: $outPath" -ForegroundColor DarkGray
Write-Host ("=" * 60) -ForegroundColor Cyan

# Cleanup scratch
Remove-Item -Recurse -Force $ScratchDir -ErrorAction SilentlyContinue
