param(
    [string]$HostName = "root@5.78.192.163",
    [string]$KeyPath = "$HOME\.ssh\id_determinex",
    [int]$IntervalSeconds = 60,
    [string]$LogPath = "logs\programbench_factory\hetzner_unpause_watch.log"
)

$ErrorActionPreference = "Continue"

while ($true) {
    $ts = Get-Date -Format o
    try {
        $out = & C:\Windows\System32\OpenSSH\ssh.exe -i $KeyPath $HostName "docker ps -q --filter status=paused | xargs -r docker unpause" 2>&1
        foreach ($line in $out) {
            Add-Content -Path $LogPath -Value "$ts $line"
        }
    } catch {
        Add-Content -Path $LogPath -Value "$ts ERROR $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $IntervalSeconds
}
