@echo off
rem ============================================================================
rem cnc_conflict_check.bat - MTClaw FR tool execution fallback wrapper
rem
rem Contract (see MTClaw function_router/server.py execute_tool):
rem   - Invoked as: cmd /c cnc_conflict_check.bat
rem   - Tool arguments arrive on STDIN as a single JSON string, e.g.
rem     {"material": "304", "surface_treatment": "anodize", "tolerance": "IT8"}
rem   - This script must print ONE JSON object to STDOUT.
rem
rem Behaviour:
rem   Reads the arguments JSON from stdin, injects a "message" field built
rem   from the arguments (required by /api/cnc-quick), then forwards the
rem   payload to the cnc-ai-brain fast path with curl.exe and prints the
rem   response JSON (ASCII-escaped so any console codepage passes it safely).
rem   NOTE: no `chcp` here - chcp empties redirected stdin (breaks FR input).
rem ============================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { Write-Output '{\"error\": \"curl.exe not found on this system\"}'; exit 9009 }; $raw=[Console]::In.ReadToEnd(); try { $j = $raw | ConvertFrom-Json } catch { $j = [pscustomobject]@{} }; if ($null -eq $j) { $j = [pscustomobject]@{} }; if (-not ($j.PSObject.Properties.Name -contains 'message')) { $pairs = @($j.PSObject.Properties | ForEach-Object { $_.Name + '=' + $(if ($_.Value -is [string]) { $_.Value } else { ($_.Value | ConvertTo-Json -Compress -Depth 6) }) }); $msg = if ($pairs.Count -gt 0) { 'CNC conflict check: ' + ($pairs -join '; ') } else { 'CNC conflict check' }; $j | Add-Member -NotePropertyName 'message' -NotePropertyValue $msg }; $id = [guid]::NewGuid().ToString('N'); $pf = Join-Path $env:TEMP ('cnc_fr_' + $id + '.json'); $rf = Join-Path $env:TEMP ('cnc_fr_' + $id + '.out'); [IO.File]::WriteAllText($pf, ($j | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false))); & curl.exe -s -X POST -H 'Content-Type: application/json' --data-binary ('@' + $pf) -o $rf http://localhost:7862/api/cnc-quick; $code = $LASTEXITCODE; if ($code -ne 0) { Write-Output ('{\"error\": \"cnc-quick request failed\", \"returncode\": ' + $code + '}'); Remove-Item $pf,$rf -ErrorAction SilentlyContinue; exit 0 }; $text = [IO.File]::ReadAllText($rf, [Text.Encoding]::UTF8); $sb = New-Object Text.StringBuilder; foreach ($ch in $text.ToCharArray()) { $c = [int]$ch; if ($c -lt 128) { [void]$sb.Append($ch) } else { [void]$sb.Append(('\u{0:X4}' -f $c)) } }; Write-Output $sb.ToString(); Remove-Item $pf,$rf -ErrorAction SilentlyContinue"
exit /b %ERRORLEVEL%
