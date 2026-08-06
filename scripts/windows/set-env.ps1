# Persist BotverseX demo environment for AMD user (run once after sync)
$ErrorActionPreference = "Stop"
$Root = "C:\Users\AMD\dev\botversex"

$vars = @{
    BOTVERSEX_ROBOTS_CONFIG = "$Root\apps\realtime\config\robots.windows-demo.json"
    REACHY_MINI_SDK_PATH = "C:\Users\AMD\sdk\reachy_mini_Allan"
    BOTVERSEX_SEEED_CONVERSATION_DIR = "$env:USERPROFILE\.local\share\botversex\seeed_reachymini_conversation"
    BOTVERSEX_SEEED_KEYS_FILE = "$env:USERPROFILE\.config\botversex\reachy_seeed_keys.json"
    BOTVERSEX_LOG_DIR = "$env:USERPROFILE\AppData\Local\Temp"
}

foreach ($k in $vars.Keys) {
    [Environment]::SetEnvironmentVariable($k, $vars[$k], "User")
    Set-Item -Path "env:$k" -Value $vars[$k]
    Write-Host "set $k=$($vars[$k])"
}

Write-Host "Done. Open a new PowerShell or log off/on for SSH sessions to pick up user env."
