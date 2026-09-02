param(
    [string]$QueueFile = "",        # legacy single-queue mode
    [string]$LightQueue = "",       # tier-mode: local + Hetzner-fallback
    [string]$HeavyQueue = "",       # tier-mode: Hetzner primary
    [int]$HetznerLanes = 8,
    [int]$LocalLanes = 2,
    [int]$TimeoutMin = 15,
    # Tier-aware timeouts: light tools get less, heavy tools get more.
    # If not specified, derived from $TimeoutMin (light=$TimeoutMin/3, heavy=$TimeoutMin*2).
    [int]$LightTimeoutMin = 0,
    [int]$HeavyTimeoutMin = 0,
    # Hetzner split between tiers (default: 3 light workers + 5 heavy workers).
    [int]$HetznerLightLanes = 3,
    [int]$HetznerHeavyLanes = 5,
    [switch]$ResetQueue,
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_determinex",
    [string]$HetznerHost = "root@5.78.192.163"
)

# Derive tier timeouts if not specified
if ($LightTimeoutMin -eq 0) { $LightTimeoutMin = [Math]::Max(3, [Math]::Floor($TimeoutMin / 3)) }
if ($HeavyTimeoutMin -eq 0) { $HeavyTimeoutMin = [Math]::Max($TimeoutMin, $TimeoutMin * 2) }
$ErrorActionPreference = "Stop"

function Invoke-Ssh {
    param([string]$cmd)
    & ssh -i $SshKey -o StrictHostKeyChecking=no -o ServerAliveInterval=30 $HetznerHost $cmd
}

if ($ResetQueue) {
    Write-Host "Resetting queue on Hetzner..."
    Invoke-Ssh "rm -f /root/queue/pending*.txt /root/queue/claimed.txt /root/queue/done.txt; touch /root/queue/pending.txt /root/queue/pending_light.txt /root/queue/pending_heavy.txt /root/queue/claimed.txt /root/queue/done.txt"
}

if ($QueueFile) {
    if (-not (Test-Path -LiteralPath $QueueFile)) { Write-Host "queue file not found: $QueueFile"; exit 1 }
    Write-Host "Uploading legacy queue file to Hetzner..."
    & scp -i $SshKey -o StrictHostKeyChecking=no $QueueFile "${HetznerHost}:/root/queue/pending.txt"
    Invoke-Ssh "sed -i 's/\r$//' /root/queue/pending.txt"
}
if ($LightQueue) {
    if (-not (Test-Path -LiteralPath $LightQueue)) { Write-Host "light queue not found: $LightQueue"; exit 1 }
    Write-Host "Uploading LIGHT queue..."
    & scp -i $SshKey -o StrictHostKeyChecking=no $LightQueue "${HetznerHost}:/root/queue/pending_light.txt"
    Invoke-Ssh "sed -i 's/\r$//' /root/queue/pending_light.txt"
}
if ($HeavyQueue) {
    if (-not (Test-Path -LiteralPath $HeavyQueue)) { Write-Host "heavy queue not found: $HeavyQueue"; exit 1 }
    Write-Host "Uploading HEAVY queue..."
    & scp -i $SshKey -o StrictHostKeyChecking=no $HeavyQueue "${HetznerHost}:/root/queue/pending_heavy.txt"
    Invoke-Ssh "sed -i 's/\r$//' /root/queue/pending_heavy.txt"
}

$N = (Invoke-Ssh "cat /root/queue/pending*.txt 2>/dev/null | wc -l" | Out-String).Trim()
Write-Host ""
Write-Host "=== launching pool ==="
Write-Host "  pending:       $N tools"
Write-Host "  hetzner light: $HetznerLightLanes workers @ ${LightTimeoutMin}m cap"
Write-Host "  hetzner heavy: $HetznerHeavyLanes workers @ ${HeavyTimeoutMin}m cap"
Write-Host "  local:         $LocalLanes workers @ ${LightTimeoutMin}m cap (light tier)"
Write-Host ""

# 1. Spawn Hetzner workers via SSH. Tier-aware: separate light + heavy worker
# sets with different timeout caps.
Write-Host "Spawning Hetzner workers..."
$launcher = @"
#!/bin/bash
LANES=`$1
TIMEOUT_MIN=`$2
TIER=`${3:-heavy}
PREFIX=`${4:-hetz}
for i in `$(seq 1 `$LANES); do
    nohup /root/queue/worker.sh "`${PREFIX}-`$i" "`$TIMEOUT_MIN" "`$TIER" > /root/queue/`${PREFIX}-`$i.out 2>&1 &
done
echo "spawned `$LANES `${PREFIX} workers (tier=`$TIER, timeout=`${TIMEOUT_MIN}m)"
"@
# Write the launcher to the box, then invoke it
$launcher | & ssh -i $SshKey -o StrictHostKeyChecking=no $HetznerHost "cat > /root/queue/_spawn.sh; chmod +x /root/queue/_spawn.sh"
# Heavy-tier workers: bigger timeout, claim from heavy queue (fallback to light when heavy empty)
Invoke-Ssh "nohup /root/queue/_spawn.sh $HetznerHeavyLanes $HeavyTimeoutMin heavy hetzH > /root/queue/_spawn_heavy.log 2>&1 & disown"
# Light-tier workers: smaller timeout, claim from light queue only
Invoke-Ssh "nohup /root/queue/_spawn.sh $HetznerLightLanes $LightTimeoutMin light hetzL > /root/queue/_spawn_light.log 2>&1 & disown"
Start-Sleep -Seconds 5
$liveHetz = (Invoke-Ssh "ps -ef | grep '/root/queue/worker.sh hetz' | grep -v grep | wc -l") | Out-String
Write-Host "Hetzner workers alive: $($liveHetz.Trim())"

# 2. Spawn local workers — always tier=light with the light timeout cap
Write-Host "Spawning local workers..."
$localPids = @()
for ($i = 1; $i -le $LocalLanes; $i++) {
    $p = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","C:\Dev\Determinex\scripts\pool_local_worker.ps1","-WorkerId","local-$i","-TimeoutMin",$LightTimeoutMin,"-Tier","light" `
        -WindowStyle Hidden -PassThru
    $localPids += $p.Id
    Write-Host "  local-$i pid=$($p.Id)  tier=light  cap=${LightTimeoutMin}m"
}

Write-Host ""
Write-Host "Pool active. Monitor:"
Write-Host "  ssh -i $SshKey $HetznerHost /root/queue/status.sh"
Write-Host "  Get-Content C:\Dev\Determinex\logs\pool_local-1.log -Tail 5 -Wait"
Write-Host ""
Write-Host "Local PIDs: $($localPids -join ', ')"
