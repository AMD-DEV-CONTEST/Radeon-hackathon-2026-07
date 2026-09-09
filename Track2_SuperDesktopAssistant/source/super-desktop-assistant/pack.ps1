# Super Desktop Assistant - 打包脚本 (Windows PowerShell)
# 输出: super-assistant-ubuntu24.zip

$ErrorActionPreference = "Stop"
$PKG = "super-assistant-ubuntu24"
$OUT = "$PKG.zip"

Write-Host "=== 打包 Super Desktop Assistant ===" -ForegroundColor Green

# 清理旧的
if (Test-Path $OUT) { Remove-Item $OUT }
$tmp = Join-Path $env:TEMP $PKG
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
$pkgDir = "$tmp\super-desktop-assistant"
New-Item -ItemType Directory -Path $pkgDir -Force | Out-Null

$FILES = @(
    "app.py", "requirements.txt", "config.json", ".env.example", "README.md",
    "LICENSE",
    "Dockerfile", "docker-compose.yml",
    "deploy-ubuntu24.sh", "deploy.sh", "pack.sh"
)

foreach ($f in $FILES) {
    if (Test-Path $f) {
        Copy-Item $f $pkgDir -Force
        Write-Host "  + $f"
    }
}

foreach ($d in @("src")) {
    $dest = "$pkgDir\$d"
    Copy-Item $d $dest -Recurse -Force
    Get-ChildItem $dest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -EA 0
    Write-Host "  + $d/ (cleaned __pycache__)"
}

New-Item -ItemType Directory -Path "$pkgDir\data\conversations" -Force | Out-Null
New-Item -ItemType Directory -Path "$pkgDir\outputs" -Force | Out-Null
Write-Host "  + data/ outputs/ (empty dirs)"

Compress-Archive -Path "$tmp\*" -DestinationPath $OUT -Force
Remove-Item $tmp -Recurse -Force

$size = [math]::Round((Get-Item $OUT).Length / 1KB, 1)
Write-Host ""
Write-Host "✅ 打包完成: $OUT (${size}KB)" -ForegroundColor Green
Write-Host ""
Write-Host "部署方式 (在 Ubuntu 24 上):" -ForegroundColor Cyan
Write-Host "  scp $OUT user@host:~/"
Write-Host "  unzip $OUT && cd super-desktop-assistant"
Write-Host "  chmod +x deploy-ubuntu24.sh && ./deploy-ubuntu24.sh"
