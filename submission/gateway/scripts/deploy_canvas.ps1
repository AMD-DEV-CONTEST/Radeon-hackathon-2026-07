param(
    [string]$HostName = "111.228.42.18",
    [string]$RemoteUser = "root",
    [string]$CanvasDir = "canvas",
    [string]$RemoteDir = "/var/www/canvas"
)

$ErrorActionPreference = "Stop"

Push-Location $CanvasDir
try {
    $env:VITE_ORCHESTRATOR_URL = "http://$HostName`:8000"
    $env:VITE_STREAMING_URL = "http://$HostName`:8001"
    npm run build
}
finally {
    Pop-Location
}

ssh "$RemoteUser@$HostName" "mkdir -p $RemoteDir"
scp -r "$CanvasDir/dist/*" "$RemoteUser@$HostName`:$RemoteDir/"
scp "deploy/canvas-nginx.conf" "$RemoteUser@$HostName`:/etc/nginx/conf.d/unionagents-canvas.conf"
ssh "$RemoteUser@$HostName" "nginx -t && systemctl reload nginx"
