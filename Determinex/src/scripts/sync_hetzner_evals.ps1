param(
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_determinex",
    [string]$HetznerHost = "root@5.78.192.163",
    [string]$LocalFactoryRoot = "T:\determinex-programbench"
)
$ErrorActionPreference = "Stop"

Write-Host "Pulling Hetzner eval JSONs back to local..."

# Tarball the eval JSONs only (small, fast)
$remoteTar = "/tmp/hetz_evals_$(Get-Date -Format yyyyMMddHHmmss).tar.gz"
& ssh -i $SshKey -o StrictHostKeyChecking=no $HetznerHost @"
cd /root/determinex-programbench && \
find . -name '*.eval.json' -newer /root/queue/.lock 2>/dev/null | tar czf $remoteTar -T -
ls -la $remoteTar
"@

if ($LASTEXITCODE -ne 0) { Write-Host "SSH/tar failed"; exit 1 }

# Pull tarball
$localTar = "C:\tmp\hetz_evals.tar.gz"
& scp -i $SshKey -o StrictHostKeyChecking=no "${HetznerHost}:$remoteTar" $localTar
if ($LASTEXITCODE -ne 0) { Write-Host "scp failed"; exit 1 }

# Extract into factory root (preserves directory structure)
Write-Host "Extracting into $LocalFactoryRoot ..."
& tar -xzf $localTar -C $LocalFactoryRoot 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "tar extract failed (path may include forward slashes)" }

# Count + verify
$count = (Get-ChildItem -Path $LocalFactoryRoot -Recurse -Filter "*.eval.json" -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "Local now has $count eval.json files"

# Cleanup
& ssh -i $SshKey -o StrictHostKeyChecking=no $HetznerHost "rm -f $remoteTar"
Remove-Item -LiteralPath $localTar -Force -ErrorAction SilentlyContinue
Write-Host "sync complete"
