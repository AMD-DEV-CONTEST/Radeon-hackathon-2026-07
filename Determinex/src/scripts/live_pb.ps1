# live_pb.ps1 - second-by-second live stream of the ACTIVE PB eval.
# Follows the newest eval log on Hetzner and auto-switches as pb_drive moves to
# the next tool. The follow loop lives in /tmp/grind/live.sh on the box (no quoting
# pitfalls). Ctrl+C to stop.
#   powershell -ExecutionPolicy Bypass -File scripts\live_pb.ps1
$key = Join-Path $env:USERPROFILE ".ssh\id_determinex"
& ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 -i $key root@5.78.192.163 "bash /tmp/grind/live.sh"
