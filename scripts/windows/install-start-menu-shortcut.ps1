# Pin "BotverseX" to Windows Start Menu (Programs list) — one-click restart.
$ErrorActionPreference = "Stop"
$Root = "C:\Users\AMD\dev\botversex"
$RestartCmd = Join-Path $Root "scripts\windows\restart-botversex.cmd"
$StartMenu = [Environment]::GetFolderPath("Programs")
$ShortcutPath = Join-Path $StartMenu "BotverseX.lnk"

if (-not (Test-Path $RestartCmd)) {
    Write-Error "Missing $RestartCmd — sync project first."
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $RestartCmd
$Shortcut.WorkingDirectory = Join-Path $Root "scripts\windows"
$Shortcut.Description = "Restart BotverseX — kill old processes, start API + Realtime + Web"
# Robot / gear style icon from Windows imageres
$Shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$Shortcut.Save()

Write-Host "Start menu shortcut created:"
Write-Host "  $ShortcutPath"
Write-Host ""
Write-Host "Tomorrow: Start Menu -> BotverseX (click to restart everything)"
