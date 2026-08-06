<#
Desktop release packaging notes:
- Build all desktop components with `npm.cmd --prefix frontend run tauri:build:host -- --no-bundle`.
- Keep `CARGO_TARGET_DIR` and `AETHERDB_BUILD_CACHE_ROOT` on the release drive for large builds.
- Do not use NSIS for offline packages that include bge-m3; the large ONNX data file has previously broken NSIS packaging.
- Run this script with `-ArchiveOnly` when disk space is tight. It creates and tests the 7z archive, then removes `release-package` and `.build-cache`.
- The generated release package is fail-closed: install/uninstall entries, backend, Tauri exe, sanitized config, and verified model packages are required; secrets, markdown, runtime data, and build folders are blocked.
#>

param(
    [string]$Version = "1.31.2",
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [string]$InstallRoot = "D:\AetherDB\AetherDB 1.31.2",
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    [string[]]$ModelPackageRoot = @(),
    [Parameter(Mandatory = $true)][string]$CargoReleaseRoot,
    [Parameter(Mandatory = $true)][string]$BackendRoot,
    [string]$PythonPath = "",
    [switch]$CreateArchive,
    [switch]$ArchiveOnly,
    [string]$SevenZipPath = "C:\Program Files\7-Zip\7z.exe"
)

$ErrorActionPreference = "Stop"

function Assert-Path {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label does not exist: $Path"
    }
}

function Assert-ChildPath {
    param([string]$Root, [string]$Path, [string]$Label)
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label is outside expected root: $pathFull"
    }
}

function Copy-DirectoryClean {
    param([string]$Source, [string]$Destination)
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function ConvertTo-SafeModelRelativePath {
    param([string]$RelativePath)

    $normalized = ($RelativePath -replace "\\", "/").Trim("/")
    if (-not $normalized) {
        throw "Model package relative path cannot be empty"
    }
    foreach ($part in $normalized.Split("/")) {
        if (-not $part -or $part -eq "." -or $part -eq "..") {
            throw "Unsafe model package relative path: $RelativePath"
        }
        if ($part.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
            throw "Invalid model package relative path segment: $part"
        }
    }
    return ($normalized -replace "/", [System.IO.Path]::DirectorySeparatorChar)
}

function Resolve-ModelPackageEntries {
    param(
        [string]$BgeModelRoot,
        [string[]]$ExtraModelRoots
    )

    $entries = @(
        [PSCustomObject]@{
            RelativePath = "bge-m3"
            Source = $BgeModelRoot
        }
    )
    foreach ($item in $ExtraModelRoots) {
        $split = $item.Split("=", 2, [System.StringSplitOptions]::None)
        if ($split.Count -ne 2) {
            throw "ModelPackageRoot entries must use relative/path=source/path: $item"
        }
        $entries += [PSCustomObject]@{
            RelativePath = ConvertTo-SafeModelRelativePath -RelativePath $split[0]
            Source = $split[1]
        }
    }
    return $entries
}

function Assert-ReleasePackage {
    param(
        [string]$Root,
        [object[]]$ModelEntries
    )

    $required = @(
        "Install AetherDB.cmd",
        "Uninstall AetherDB.cmd",
        "installer\install.ps1",
        "installer\uninstall.ps1",
        "payload\AetherDB.exe",
        "payload\build-manifest.json",
        "payload\Start AetherDB.cmd",
        "payload\backend\aetherdb-backend.exe",
        "payload\backend\build-manifest.json",
        "payload\backend\config.example.yaml"
    )
    foreach ($relative in $required) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Release package is missing required file: $relative"
        }
    }
    foreach ($entry in $ModelEntries) {
        $relative = Join-Path "payload\models" $entry.RelativePath
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "Release package is missing model package directory: $relative"
        }
        $fileCount = (Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($fileCount -le 0) {
            throw "Release package model package directory is empty: $relative"
        }
    }
    foreach ($relative in @(
        "payload\models\bge-m3\onnx\model.onnx",
        "payload\models\bge-m3\onnx\model.onnx_data"
    )) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Release package is missing required BGE-M3 file: $relative"
        }
    }

    $forbiddenDirectories = @(
        "node_modules",
        ".git",
        ".codex",
        ".agents",
        ".claude",
        "app_data",
        "logs",
        "dist",
        ".vite-check-dist"
    )
    $forbiddenFiles = @(
        ".env",
        ".api_keys.json",
        "api_keys.json",
        "config.local.yaml",
        "config.yaml"
    )
    foreach ($directory in Get-ChildItem -LiteralPath $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue) {
        if ($forbiddenDirectories -contains $directory.Name) {
            throw "Forbidden runtime/build directory found in release package: $($directory.FullName)"
        }
    }
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue) {
        if ($forbiddenFiles -contains $file.Name) {
            throw "Forbidden sensitive file found in release package: $($file.FullName)"
        }
        if ($file.Extension -ieq ".md" -or $file.Extension -ieq ".markdown") {
            throw "Markdown file found in release package: $($file.FullName)"
        }
    }

    $textExtensions = @(".json", ".yaml", ".yml", ".txt", ".ps1", ".cmd", ".html", ".css", ".js")
    $secretPatterns = @(
        "deepseek",
        "cold",
        "codex",
        "sk-[A-Za-z0-9_-]{20,}",
        "nvk_(admin_)?[a-f0-9]{32}",
        "ghp_[A-Za-z0-9]{30,}",
        "AIza[0-9A-Za-z_-]{30,}",
        "xox[baprs]-[A-Za-z0-9-]{20,}",
        "Bearer\s+[A-Za-z0-9._-]{24,}"
    )
    $modelPayloadRoot = Join-Path $Root "payload\models"
    $textFiles = Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Length -lt 5MB -and
            $textExtensions -contains $_.Extension.ToLowerInvariant() -and
            -not $_.FullName.StartsWith($modelPayloadRoot, [System.StringComparison]::OrdinalIgnoreCase)
        }
    foreach ($hit in Select-String -LiteralPath $textFiles.FullName -Pattern $secretPatterns -CaseSensitive:$false -ErrorAction SilentlyContinue) {
        throw "Provider name or secret-like value found in release text: $($hit.Path):$($hit.LineNumber)"
    }

    [scriptblock]::Create((Get-Content -LiteralPath (Join-Path $Root "installer\install.ps1") -Raw)) | Out-Null
    [scriptblock]::Create((Get-Content -LiteralPath (Join-Path $Root "installer\uninstall.ps1") -Raw)) | Out-Null
}

function New-ReleaseArchive {
    param([string]$Root, [string]$ArchivePath, [string]$ToolPath)

    Assert-Path $ToolPath "7-Zip executable"
    Assert-ChildPath -Root $ReleaseRoot -Path $ArchivePath -Label "Archive output"
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }
    Push-Location -LiteralPath $Root
    try {
        & $ToolPath a -t7z $ArchivePath ".\*" -mx=5 -mmt=on -bso1 -bsp1
        if ($LASTEXITCODE -ne 0) {
            throw "7-Zip archive creation failed with exit code $LASTEXITCODE"
        }
        & $ToolPath t $ArchivePath -bso1 -bsp1
        if ($LASTEXITCODE -ne 0) {
            throw "7-Zip archive test failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Remove-ReleaseWorkingDirectories {
    param([string]$Root)

    foreach ($relative in @("release-package", ".build-cache")) {
        $target = Join-Path $Root $relative
        if (Test-Path -LiteralPath $target) {
            Assert-ChildPath -Root $Root -Path $target -Label "Cleanup target"
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
}

function Remove-UnneededReleaseFiles {
    param([string]$Root)
    Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -ieq ".gitkeep" -or
            $_.Extension -ieq ".md" -or
            $_.Extension -ieq ".markdown"
        } |
        Remove-Item -Force
}

function Invoke-PackagedBackendSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$BackendDirectory,
        [Parameter(Mandatory = $true)][string]$RuntimeParent
    )

    $SmokeScript = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\check_desktop_backend.py"
    Assert-Path $Python "Python runtime for packaged smoke test"
    Assert-Path $SmokeScript "Packaged backend smoke test"
    New-Item -ItemType Directory -Force -Path $RuntimeParent | Out-Null
    & $Python $SmokeScript `
        --backend-executable (Join-Path $BackendDirectory "aetherdb-backend.exe") `
        --resource-root $BackendDirectory `
        --runtime-parent $RuntimeParent
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged backend smoke test failed with exit code $LASTEXITCODE"
    }
}

function Write-SanitizedReleaseConfig {
    param([string]$Path)
    $config = @'
# AetherDB release runtime configuration template.
# User secrets are generated or entered locally after installation.

app:
  secret_key: ""
  workspace_id: "default"
  admin_api_key: ""
  user_api_key: ""

database:
  path: "novel_world_zh.db"

logging:
  level: INFO
  max_bytes: 10485760
  backup_count: 5

backup:
  enabled: true
  keep_last: 10
  auto_backup_on_startup: true

extractor:
  backend: "ollama"
  openai_compatible:
    api_base: ""
    api_key: ""
    model: ""
  ollama:
    model: "qwen2.5:7b"
    host: "localhost:11434"
  prompt_template: "prompts/extract_entities.txt"

app_data:
  root: "app_data"
  registry: "app_data/registry.db"
  databases: "app_data/databases"
  cache: "app_data/cache"
  logs: "logs"

registry:
  enabled: true
  default_database_id: "default"

deploy:
  mode: "desktop"
  host: "127.0.0.1"
  port: 0
  workers: 1

llm:
  initialized: false
  mode: "local"
  cloud:
    active_provider: ""
    providers: {}
  local:
    enabled: false
    runtime: "ollama"
    api_base: "http://localhost:11434"
    model: "qwen2.5"
  safety:
    ask_before_cloud_fallback: true
    max_daily_cloud_cost: null
    log_token_usage: true
'@
    Set-Content -LiteralPath $Path -Value $config -Encoding UTF8
}

$PackageRoot = Join-Path $ReleaseRoot "release-package"
$PayloadRoot = Join-Path $PackageRoot "payload"
$InstallerRoot = Join-Path $PackageRoot "installer"
$ArchivePath = Join-Path $ReleaseRoot "AetherDB_V$Version`_release-package.7z"

if ($ArchiveOnly) {
    $CreateArchive = $true
}

Assert-Path (Join-Path $CargoReleaseRoot "worldview.exe") "Tauri release executable"
Assert-Path $BackendRoot "Packaged backend resources"
Assert-Path $ModelRoot "BGE-M3 model root"
$ModelEntries = Resolve-ModelPackageEntries -BgeModelRoot $ModelRoot -ExtraModelRoots $ModelPackageRoot
foreach ($entry in $ModelEntries) {
    Assert-Path $entry.Source "Model package source [$($entry.RelativePath)]"
}
$HostManifestPath = Join-Path $CargoReleaseRoot "build-manifest.json"
if (-not (Test-Path -LiteralPath $HostManifestPath)) {
    $HostManifestPath = Join-Path $CargoReleaseRoot "backend\build-manifest.json"
}
$BackendManifestPath = Join-Path $BackendRoot "build-manifest.json"
Assert-Path $HostManifestPath "Tauri build manifest"
Assert-Path $BackendManifestPath "Backend build manifest"
$HostManifest = Get-Content -LiteralPath $HostManifestPath -Raw | ConvertFrom-Json
$BackendManifest = Get-Content -LiteralPath $BackendManifestPath -Raw | ConvertFrom-Json
if (
    -not $HostManifest.build_id -or
    $HostManifest.build_id -ne $BackendManifest.build_id -or
    $HostManifest.version -ne $BackendManifest.version -or
    $HostManifest.version -ne $Version -or
    $HostManifest.protocol_version -ne "1.0" -or
    $BackendManifest.protocol_version -ne "1.0"
) {
    throw "Desktop host and backend sidecar were not produced by the same AetherDB build"
}
New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
Assert-ChildPath -Root $ReleaseRoot -Path $PackageRoot -Label "Package root"

if (Test-Path -LiteralPath $PackageRoot) {
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PayloadRoot, $InstallerRoot | Out-Null

Copy-Item -LiteralPath (Join-Path $CargoReleaseRoot "worldview.exe") -Destination (Join-Path $PayloadRoot "AetherDB.exe") -Force
Copy-Item -LiteralPath $HostManifestPath -Destination (Join-Path $PayloadRoot "build-manifest.json") -Force
Copy-DirectoryClean -Source $BackendRoot -Destination (Join-Path $PayloadRoot "backend")
foreach ($entry in $ModelEntries) {
    $destination = Join-Path (Join-Path $PayloadRoot "models") $entry.RelativePath
    Assert-ChildPath -Root (Join-Path $PayloadRoot "models") -Path $destination -Label "Model package destination"
    Copy-DirectoryClean -Source $entry.Source -Destination $destination
}
Write-SanitizedReleaseConfig -Path (Join-Path $PayloadRoot "backend\config.example.yaml")

$StartCmd = @'
@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0AetherDB.exe"
'@
Set-Content -LiteralPath (Join-Path $PayloadRoot "Start AetherDB.cmd") -Value $StartCmd -Encoding UTF8

$InstallCmd = @'
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1"
pause
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "Install AetherDB.cmd") -Value $InstallCmd -Encoding UTF8

$UninstallCmd = @'
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\uninstall.ps1"
pause
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "Uninstall AetherDB.cmd") -Value $UninstallCmd -Encoding UTF8

$InstallPs1 = @"
`$ErrorActionPreference = "Stop"
`$PackageRoot = Split-Path -Parent `$PSScriptRoot
`$PayloadRoot = Join-Path `$PackageRoot "payload"
`$InstallRoot = "$InstallRoot"

if (-not (Test-Path -LiteralPath "D:\")) {
    throw "D drive is required for the default AetherDB installation path."
}
if (-not (Test-Path -LiteralPath `$PayloadRoot)) {
    throw "Payload directory is missing: `$PayloadRoot"
}

Write-Host ""
Write-Host "AetherDB $Version installer" -ForegroundColor Cyan
Write-Host "Default install path: `$InstallRoot" -ForegroundColor Cyan
Write-Host ""
`$answer = Read-Host "Create desktop shortcut? Press Enter for Yes, type N for No"
`$CreateDesktopShortcut = `$answer.Trim().ToUpperInvariant() -ne "N"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent `$InstallRoot) | Out-Null
if (Test-Path -LiteralPath `$InstallRoot) {
    `$stamp = Get-Date -Format "yyyyMMddHHmmss"
    `$backup = "`$InstallRoot.previous.`$stamp"
    Move-Item -LiteralPath `$InstallRoot -Destination `$backup -Force
    Write-Host "Previous install moved to: `$backup" -ForegroundColor Yellow
}
Copy-Item -LiteralPath `$PayloadRoot -Destination `$InstallRoot -Recurse -Force

if (`$CreateDesktopShortcut) {
    `$ShortcutTarget = Join-Path `$InstallRoot "Start AetherDB.cmd"
    `$Desktop = [Environment]::GetFolderPath("Desktop")
    `$ShortcutPath = Join-Path `$Desktop "AetherDB.lnk"
    `$Shell = New-Object -ComObject WScript.Shell
    `$Shortcut = `$Shell.CreateShortcut(`$ShortcutPath)
    `$Shortcut.TargetPath = `$ShortcutTarget
    `$Shortcut.WorkingDirectory = `$InstallRoot
    `$Shortcut.Description = "AetherDB"
    `$Shortcut.Save()
    Write-Host "Desktop shortcut: `$ShortcutPath" -ForegroundColor Cyan
} else {
    Write-Host "Desktop shortcut skipped by user choice." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "AetherDB $Version installed successfully." -ForegroundColor Green
Write-Host "Install path: `$InstallRoot" -ForegroundColor Cyan
Write-Host "Start manually: `$InstallRoot\Start AetherDB.cmd" -ForegroundColor Cyan
Write-Host ""
"@
Set-Content -LiteralPath (Join-Path $InstallerRoot "install.ps1") -Value $InstallPs1 -Encoding UTF8

$UninstallPs1 = @"
`$ErrorActionPreference = "Stop"

`$InstallRoot = "$InstallRoot"
`$InstallParent = Split-Path -Parent `$InstallRoot
`$InstallName = Split-Path -Leaf `$InstallRoot

function Assert-SafeInstallPath {
    param([Parameter(Mandatory=`$true)][string]`$Path)

    `$full = [System.IO.Path]::GetFullPath(`$Path)
    `$parent = [System.IO.Path]::GetFullPath(`$InstallParent)
    if (-not `$full.StartsWith(`$parent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside install parent: `$full"
    }
    `$leaf = Split-Path -Leaf `$full
    if (`$leaf -ne `$InstallName -and `$leaf -notlike "`$InstallName.previous.*") {
        throw "Refusing to remove unexpected directory: `$full"
    }
    return `$full
}

function Remove-PathIfPresent {
    param([Parameter(Mandatory=`$true)][string]`$Path)

    if (Test-Path -LiteralPath `$Path) {
        `$safePath = Assert-SafeInstallPath -Path `$Path
        Write-Host "Removing: `$safePath" -ForegroundColor Yellow
        Remove-Item -LiteralPath `$safePath -Recurse -Force
    }
}

Write-Host ""
Write-Host "AetherDB $Version uninstaller" -ForegroundColor Cyan
Write-Host "This will remove the installed application and runtime data under:" -ForegroundColor Cyan
Write-Host "  `$InstallRoot" -ForegroundColor Cyan
Write-Host "It will also remove installer-created previous install folders:" -ForegroundColor Cyan
Write-Host "  `$InstallRoot.previous.*" -ForegroundColor Cyan
Write-Host ""
`$answer = Read-Host "Type UNINSTALL to continue"
if (`$answer.Trim() -ne "UNINSTALL") {
    Write-Host "Uninstall cancelled." -ForegroundColor Yellow
    exit 0
}

`$targets = @()
if (Test-Path -LiteralPath `$InstallRoot) {
    `$targets += `$InstallRoot
}
if (Test-Path -LiteralPath `$InstallParent) {
    `$targets += Get-ChildItem -LiteralPath `$InstallParent -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { `$_.Name -like "`$InstallName.previous.*" } |
        ForEach-Object { `$_.FullName }
}

foreach (`$name in @("AetherDB", "aetherdb-backend")) {
    Get-Process -Name `$name -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            `$processPath = `$_.Path
            if (`$processPath -and `$processPath.StartsWith(`$InstallParent, [System.StringComparison]::OrdinalIgnoreCase)) {
                Write-Host "Stopping process: `$(`$_.ProcessName) [`$(`$_.Id)]" -ForegroundColor Yellow
                Stop-Process -Id `$_.Id -Force -ErrorAction Stop
            }
        } catch {
            Write-Host "Could not stop process `$(`$_.ProcessName) [`$(`$_.Id)]: `$(`$_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

foreach (`$target in `$targets) {
    Remove-PathIfPresent -Path `$target
}

`$desktop = [Environment]::GetFolderPath("Desktop")
foreach (`$shortcutName in @("AetherDB.lnk", "AetherDB $Version.lnk")) {
    `$shortcutPath = Join-Path `$desktop `$shortcutName
    if (Test-Path -LiteralPath `$shortcutPath) {
        Write-Host "Removing shortcut: `$shortcutPath" -ForegroundColor Yellow
        Remove-Item -LiteralPath `$shortcutPath -Force
    }
}

if (Test-Path -LiteralPath `$InstallParent) {
    `$remaining = Get-ChildItem -LiteralPath `$InstallParent -Force -ErrorAction SilentlyContinue
    if ((`$remaining | Measure-Object).Count -eq 0) {
        Write-Host "Removing empty parent directory: `$InstallParent" -ForegroundColor Yellow
        Remove-Item -LiteralPath `$InstallParent -Force
    }
}

Write-Host ""
Write-Host "AetherDB $Version uninstall completed." -ForegroundColor Green
Write-Host ""
"@
Set-Content -LiteralPath (Join-Path $InstallerRoot "uninstall.ps1") -Value $UninstallPs1 -Encoding UTF8

Remove-UnneededReleaseFiles -Root $PackageRoot
Assert-ReleasePackage -Root $PackageRoot -ModelEntries $ModelEntries
if (-not $PythonPath) {
    $PythonPath = Join-Path (Split-Path -Parent $PSScriptRoot) "venv\Scripts\python.exe"
}
Invoke-PackagedBackendSmoke `
    -Python $PythonPath `
    -BackendDirectory (Join-Path $PayloadRoot "backend") `
    -RuntimeParent (Join-Path $ReleaseRoot ".build-cache\packaged-runtime-smoke")

if ($CreateArchive) {
    New-ReleaseArchive -Root $PackageRoot -ArchivePath $ArchivePath -ToolPath $SevenZipPath
}

if ($ArchiveOnly) {
    Remove-ReleaseWorkingDirectories -Root $ReleaseRoot
}

$files = @()
$total = 0
if (Test-Path -LiteralPath $PackageRoot) {
    $files = Get-ChildItem -LiteralPath $PackageRoot -Recurse -File -Force
    $total = ($files | Measure-Object -Property Length -Sum).Sum
}
[PSCustomObject]@{
    PackageRoot = $PackageRoot
    ArchivePath = if ($CreateArchive) { $ArchivePath } else { "" }
    ArchiveOnly = [bool]$ArchiveOnly
    InstallRoot = $InstallRoot
    FileCount = $files.Count
    SizeGB = [Math]::Round($total / 1GB, 2)
}
