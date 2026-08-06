# Also pin BotverseX restart to Desktop (easier to find than Start Menu search).
$ErrorActionPreference = "Stop"
$Root = "C:\Users\AMD\dev\botversex"
$RestartCmd = Join-Path $Root "scripts\windows\restart-botversex.cmd"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "BotverseX.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $RestartCmd
$Shortcut.WorkingDirectory = Join-Path $Root "scripts\windows"
$Shortcut.Description = "Restart BotverseX — kill old, start new"
$Shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$Shortcut.Save()

Write-Host "Desktop shortcut: $ShortcutPath"

# Re-run start menu installer too
& (Join-Path $Root "scripts\windows\install-start-menu-shortcut.ps1")
