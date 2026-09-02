```bash
cat > docs/cloudflare-tunnel.md <<'EOF'
# Cloudflare Tunnel

## Purpose

Cloudflare Tunnel exposes only the Go backend during development.

```text
Public HTTPS
    ↓
cloudflared
    ↓
127.0.0.1:8080
Do not expose:
127.0.0.1:8001
127.0.0.1:8188
Quick Tunnel
Quick Tunnel is intended for development.
Properties:
Random trycloudflare.com URL
No Cloudflare account required
URL changes after restart
Not suitable for stable production deployment
Does not support Server-Sent Events
Limited concurrent request capacity
Install with APT
mkdir -p --mode=0755 /usr/share/keyrings

curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

echo \
  "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  > /etc/apt/sources.list.d/cloudflared.list

apt-get update
apt-get install -y cloudflared

cloudflared --version
Install Standalone Binary
curl -L \
  -o /usr/local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

chmod +x /usr/local/bin/cloudflared

cloudflared --version
Start with nohup
cd /workspace/poster-engine/backend

mkdir -p logs run

nohup cloudflared tunnel \
  --no-autoupdate \
  --url http://127.0.0.1:8080 \
  > logs/cloudflared.log 2>&1 &

echo $! > run/cloudflared.pid
Get Public URL
grep -oE \
  'https://[a-zA-Z0-9-]+\.trycloudflare\.com' \
  logs/cloudflared.log \
  | tail -1
Or:
tail -f logs/cloudflared.log
Stop
kill "$(cat run/cloudflared.pid)"
rm -f run/cloudflared.pid
Fallback:
pkill -f 'cloudflared tunnel'
Status
ps -fp "$(cat run/cloudflared.pid)"
Test
PUBLIC_URL="$(
  grep -oE \
    'https://[a-zA-Z0-9-]+\.trycloudflare\.com' \
    logs/cloudflared.log \
  | tail -1
)"

curl -i \
  "$PUBLIC_URL/api/ai/sessions/not-found"
Expected:
HTTP 404
Access-Control-Allow-Origin: *
{"error":"AI session not found"}
Common Warnings
ICMP proxy disabled
Example:
ICMP proxy feature is disabled
This does not block HTTP Tunnel operation.
UDP receive buffer warning
Example:
failed to sufficiently increase receive buffer size
If the tunnel still reports:
Registered tunnel connection
Environment is healthy
the HTTP tunnel can remain usable.
No URL in tail output
Search the complete log:
grep -i trycloudflare logs/cloudflared.log
Named Tunnel
For a stable demo or production URL:
api.example.com
use a Named Tunnel instead of Quick Tunnel.
A Named Tunnel should be:
Created in Cloudflare
Bound to a fixed DNS name
Installed as a systemd service
Protected by authentication and restricted CORS
EOF

---

# 10. `docs/model-downloads.md`

```bash
cat > docs/model-downloads.md <<'EOF'
# Model Downloads

## VLM

Model:

```text
Qwen/Qwen3.5-9B
Destination:
/workspace/poster-engine/models/Qwen3.5-9B
Download:
hf download \
  Qwen/Qwen3.5-9B \
  --local-dir /workspace/poster-engine/models/Qwen3.5-9B
Expected weight shards:
model.safetensors-00001-of-00004.safetensors
model.safetensors-00002-of-00004.safetensors
model.safetensors-00003-of-00004.safetensors
model.safetensors-00004-of-00004.safetensors
ComfyUI Z-Image-Turbo
Repository:
Comfy-Org/z_image_turbo
Diffusion Model
Remote:
split_files/diffusion_models/z_image_turbo_bf16.safetensors
Destination:
ComfyUI/models/diffusion_models/z_image_turbo_bf16.safetensors
Text Encoder
Remote:
split_files/text_encoders/qwen_3_4b.safetensors
Destination:
ComfyUI/models/text_encoders/qwen_3_4b.safetensors
VAE
Remote:
split_files/vae/ae.safetensors
Destination:
ComfyUI/models/vae/ae.safetensors
Optional Distill Patch LoRA
Remote:
split_files/loras/z_image_turbo_distill_patch_lora_bf16.safetensors
Destination:
ComfyUI/models/loras/z_image_turbo_distill_patch_lora_bf16.safetensors
Automated Download
./scripts/download-models.sh
Authentication
For public repositories, a token may not be required.
When needed:
export HF_TOKEN=<token>
Never place the token in:
README.md
shell history
Git commits
screenshots
public logs
Verify Files
find \
  /workspace/poster-engine/models \
  /workspace/poster-engine/ComfyUI/models \
  -type f \
  -name '*.safetensors' \
  -printf '%s\t%p\n' \
  | sort -n
Disk Requirement
Reserve substantial free disk space.
Approximate model storage includes:
Qwen3.5-9B: about 19 GB
Z-Image-Turbo diffusion model: about 12 GB
Z-Image text encoder: about 8 GB
VAE and LoRA: additional storage
Keep at least 50 GB free for models, caches, outputs, and temporary downloads.
