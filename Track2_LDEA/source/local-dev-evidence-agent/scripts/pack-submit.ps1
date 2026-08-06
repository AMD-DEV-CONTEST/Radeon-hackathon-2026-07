$ErrorActionPreference = 'Stop'
$staging = Join-Path $env:TEMP ("LDEA-submit-" + [guid]::NewGuid().ToString('N').Substring(0,8))
$dest = Join-Path ([Environment]::GetFolderPath('Desktop')) 'LDEA-AMD-DevMaster-submit.zip'
New-Item -ItemType Directory -Path $staging | Out-Null
Write-Host "STAGING=$staging"

function Copy-Project {
  param([string]$src, [string]$dstName)
  $dst = Join-Path $staging $dstName
  New-Item -ItemType Directory -Path $dst -Force | Out-Null
  $xd = @('node_modules','.git','.ldea','.turbo','.cache','coverage','.vscode','.idea')
  $args = @($src, $dst, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/XF', '.env', '.env.local', '.env.production', 'id_rsa', 'id_ed25519')
  $args += '/XD'
  $args += $xd
  & robocopy @args | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed $LASTEXITCODE for $src" }
  Write-Host "copied $dstName exit=$LASTEXITCODE"
}

Copy-Project 'C:\WoRk\Local Dev Evidence Agent' 'Local Dev Evidence Agent'
Copy-Project 'C:\WoRk\AiRecap Plus' 'AiRecap Plus'

Get-ChildItem $staging -Recurse -Force -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -eq '.env' -or $_.Name -eq '.env.local' -or $_.Extension -eq '.pem' -or $_.Name -match '^id_(rsa|ed25519)$' } |
  ForEach-Object {
    Write-Host "STRIP $($_.FullName)"
    [System.IO.File]::Delete($_.FullName)
  }

if ([System.IO.File]::Exists($dest)) { [System.IO.File]::Delete($dest) }

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($staging, $dest, [System.IO.Compression.CompressionLevel]::Optimal, $false)

$item = Get-Item -LiteralPath $dest
Write-Host ("ZIP={0}" -f $item.FullName)
Write-Host ("SIZE_MB={0:N1}" -f ($item.Length/1MB))
Write-Host ("TOP={0}" -f ((Get-ChildItem $staging | ForEach-Object Name) -join ','))
$fc = (Get-ChildItem $staging -Recurse -File).Count
Write-Host "FILES=$fc"
$nm = @(Get-ChildItem $staging -Recurse -Directory -Filter node_modules -ErrorAction SilentlyContinue).Count
Write-Host "node_modules_dirs=$nm"
$v = Get-ChildItem $staging -Recurse -Filter 'LDEA-Demo-AMD-ROCm.mp4' -ErrorAction SilentlyContinue | Select-Object -First 1
$p = Get-ChildItem $staging -Recurse -Filter 'LDEA-pitch-editorial.pdf' -ErrorAction SilentlyContinue | Select-Object -First 1
Write-Host ("video={0}" -f $(if($v){$v.FullName}else{'MISSING'}))
Write-Host ("pdf={0}" -f $(if($p){$p.FullName}else{'MISSING'}))

[System.IO.Directory]::Delete($staging, $true)
Write-Host DONE
