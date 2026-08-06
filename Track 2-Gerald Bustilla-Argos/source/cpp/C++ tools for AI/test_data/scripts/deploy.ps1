$ErrorActionPreference = "Stop"
$appName = "aisearch"
$installPath = "C:\Program Files\$appName"

Write-Host "Installing $appName..."
New-Item -ItemType Directory -Force -Path $installPath
Copy-Item "build\$appName.exe" $installPath
Write-Host "Installation complete."
