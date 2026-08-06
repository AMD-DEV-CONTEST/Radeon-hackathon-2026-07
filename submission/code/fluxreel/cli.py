"""fluxreel - FluxReel: AMD GPU short-video studio + remote server manager."""

import argparse
import os
import subprocess
import sys
import time


def ssh_cmd(ssh_base, remote_script):
    """Run a bash script on the remote server via SSH heredoc."""
    full_cmd = (
        f"""{ssh_base} 'bash -s' << 'REMOTE'\n"""
        f"""{remote_script}\n"""
        f"""REMOTE"""
    )
    print(f"🚀 {ssh_base.split()[0]} {ssh_base.split()[1][:20]}...")
    print()
    result = subprocess.run(full_cmd, shell=True, text=True)
    if result.returncode != 0:
        sys.exit(result.returncode)


def run_local(cmd):
    """Run a local shell command."""
    result = subprocess.run(cmd, shell=True, text=True)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    # Load ~/.config/fluxreel/.env (SDCPP_*, HF_TOKEN, provider overrides...)
    try:
        from fluxreel.env import load_env
        load_env()
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        prog="fluxreel",
        description="FluxReel — AMD GPU short-video studio: manage remote server, tunnel, downloads, video generation",
    )
    parser.add_argument(
        "--host", default="36.150.116.206", help="Remote server host"
    )
    parser.add_argument("-p", "--port", type=int, default=31005, help="SSH port")
    parser.add_argument("--user", default="root", help="SSH user")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── tunnel ──────────────────────────────────────────────
    tp = subparsers.add_parser("tunnel", help="Manage rc-tunnel")
    tsub = tp.add_subparsers(dest="tunnel_action", help="Tunnel actions")
    tsub.add_parser("setup", help="Install rc-tunnel and expose a port")
    tsub.add_parser("status", help="Check tunnel status")
    tsub.add_parser("stop", help="Stop the tunnel")
    tsub.add_parser("logs", help="Show tunnel logs")

    # ── download ────────────────────────────────────────────
    dp = subparsers.add_parser("download", help="Download models")
    dsub = dp.add_subparsers(dest="download_action", help="Download targets")

    fp = dsub.add_parser("flux", help="Download FLUX model")
    fp.add_argument(
        "variant", nargs="?", default="schnell",
        choices=["schnell", "dev", "2-dev"],
        help="FLUX variant (default: schnell)",
    )
    fp.add_argument("--token", default=None, help="HuggingFace token")
    fp.add_argument(
        "--local-dir", default=None,
        help="Download target directory on remote",
    )

    # ── gen-video ───────────────────────────────────────────
    gvp = subparsers.add_parser("gen-video", help="Generate short-form videos from markdown")
    gvsub = gvp.add_subparsers(dest="gen_video_action", help="gen-video actions")

    gv_generate = gvsub.add_parser("generate", help="Read markdown from pasteboard and submit to gen-video server")
    gv_generate.add_argument("--output", help="Output video path")
    gv_generate.add_argument("--model", help="LLM model override")
    gv_generate.add_argument("--image-model", help="Image generation model override")
    gv_generate.add_argument("--provider", default="openrouter", choices=["openrouter", "local", "sdcpp", "auto"], help="Image provider (default: openrouter)")
    gv_generate.add_argument("--local-variant", default="schnell", choices=["schnell", "dev", "2-dev"], help="Local FLUX variant (default: schnell)")
    gv_generate.add_argument("--server", help="Gen-video server URL override")
    gv_generate.add_argument("--poll", action="store_true", help="Wait for completion and download")
    gv_generate.add_argument("--upload", action="store_true", help="Upload to YouTube after creation")
    gv_generate.add_argument("--privacy", default="public", choices=["public", "private", "unlisted"], help="YouTube privacy (default: public)")

    gv_query = gvsub.add_parser("query", help="Query job status")
    gv_query.add_argument("job_id", help="Job ID to query")
    gv_query.add_argument("--server", help="Server URL override")
    gv_query.add_argument("--json", action="store_true", help="Output raw JSON")

    gv_server = gvsub.add_parser("server", help="Start the gen-video API server")
    gv_server.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    gv_server.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    gv_server.add_argument("--reload", action="store_true", help="Enable auto-reload")

    gv_video = gvsub.add_parser("video", help="Generate a video directly from a markdown file")
    gv_video.add_argument("file", help="Path to markdown file")
    gv_video.add_argument("--output", help="Output video path")
    gv_video.add_argument("--model", help="LLM model for script generation")
    gv_video.add_argument("--image-model", default="black-forest-labs/flux.2-pro", help="Image generation model")
    gv_video.add_argument("--provider", default="openrouter", choices=["openrouter", "local", "sdcpp", "auto"], help="Image provider (default: openrouter)")
    gv_video.add_argument("--local-variant", default="schnell", choices=["schnell", "dev", "2-dev"], help="Local FLUX variant (default: schnell)")
    gv_video.add_argument("--upload", action="store_true", help="Upload to YouTube after creation")
    gv_video.add_argument("--private", action="store_true", help="Set YouTube video to private")

    # ── img (local sd-cpp FLUX) ────────────────────────────────
    imgp = subparsers.add_parser("img", help="Generate an image locally with sd-cpp FLUX.1-schnell Q4_0")
    imgp.add_argument("prompt", nargs="?", default=None, help="Text prompt")
    imgp.add_argument("--width", type=int, default=None, help="Image width (default: 768; 1024 needs free VRAM)")
    imgp.add_argument("--height", type=int, default=None, help="Image height (default: 768)")
    imgp.add_argument("--steps", type=int, default=None, help="Inference steps (default: 4)")
    imgp.add_argument("--max-vram", type=int, default=None, help="VRAM budget in GB (default: 10)")
    imgp.add_argument("--seed", type=int, default=42, help="Seed (default: 42)")
    imgp.add_argument("--output", default=None, help="Output PNG path (default: flux_img_<timestamp>.png)")
    imgp.add_argument("--bin", default=None, help="Path to sd-cli binary (default: /mnt/data/zz/flux/sd_cpp/build/bin/sd-cli)")
    imgp.add_argument("--model-dir", default=None, help="Path to models dir (default: /mnt/data/zz/flux/models)")

    # ── generate ────────────────────────────────────────────
    genp = subparsers.add_parser("gen", help="Generate images with FLUX on remote")
    genp.add_argument("prompt", nargs="?", default=None, help="Text prompt for generation")
    genp.add_argument("--model", default="schnell", choices=["schnell", "dev", "2-dev"], help="FLUX variant (default: schnell)")
    genp.add_argument("--model-dir", default=None, help="Path to model on remote (default: /root/FLUX.<variant>)")
    genp.add_argument("--steps", type=int, default=4, help="Inference steps (default: 4)")
    genp.add_argument("--width", type=int, default=1024, help="Image width (default: 1024)")
    genp.add_argument("--height", type=int, default=1024, help="Image height (default: 1024)")
    genp.add_argument("--guidance", type=float, default=0.0, help="Guidance scale (default: 0.0)")
    genp.add_argument("--output", default=None, help="Output filename on remote (default: auto)")
    genp.add_argument("--download", action="store_true", help="Download the generated image to local")

    # ── server ────────────────────────────────────────────────
    server_parser = subparsers.add_parser("server", help="Start the gen-video API server")
    server_parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    server_parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    server_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    # ── ssh / shell / info / check ──────────────────────────
    subparsers.add_parser("ssh", help="Open an interactive SSH session")
    sp = subparsers.add_parser("shell", help="Run a shell command on remote")
    sp.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run")
    subparsers.add_parser("info", help="Show remote server info")
    subparsers.add_parser("check", help="Check download/progress status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    ssh_base = f"ssh -o StrictHostKeyChecking=no -p {args.port} {args.user}@{args.host}"

    if args.command == "tunnel":
        return handle_tunnel(args, ssh_base)
    elif args.command == "download":
        return handle_download(args, ssh_base)
    elif args.command == "gen-video":
        return handle_gen_video(args)
    elif args.command == "img":
        return handle_img(args)
    elif args.command == "gen":
        return handle_generate(args, ssh_base)
    elif args.command == "server":
        return handle_gen_video_server(args)
    elif args.command == "ssh":
        print(f"🔌 Connecting...")
        subprocess.run(f"{ssh_base} -t", shell=True)
    elif args.command == "shell":
        cmd = " ".join(args.cmd) if args.cmd else ""
        if cmd:
            subprocess.run(f"""{ssh_base} "cd /root && {cmd}" """, shell=True)
        else:
            print("❌ Specify a command to run")
    elif args.command == "info":
        show_info(ssh_base)
    elif args.command == "check":
        check_download(ssh_base)
    else:
        parser.print_help()


# ── Tunnel ─────────────────────────────────────────────────────

# ── Gen-Video ──────────────────────────────────────────────────

def handle_gen_video_server(args):
    """Start the gen-video API server directly (top-level `fluxreel server`)."""
    from fluxreel.gen_video.server import main as gv_server
    # The server's argparse only knows about --host, --port, --reload.
    # Strip everything else from sys.argv so it doesn't choke on "gen-video" etc.
    sys.argv = ["fluxreel"]
    if args.host:
        sys.argv += ["--host", args.host]
    if args.port:
        sys.argv += ["--port", str(args.port)]
    if args.reload:
        sys.argv += ["--reload"]
    gv_server()


def handle_gen_video(args):
    action = args.gen_video_action
    if not action:
        print("Usage: fluxreel gen-video {generate|query|server|video}")
        sys.exit(1)

    if action == "generate":
        from fluxreel.gen_video.generate import main as gv_generate
        sys.argv = ["fluxreel"]
        if args.output:
            sys.argv += ["--output", args.output]
        if args.model:
            sys.argv += ["--model", args.model]
        if args.image_model:
            sys.argv += ["--image-model", args.image_model]
        if args.provider:
            sys.argv += ["--provider", args.provider]
        if args.local_variant:
            sys.argv += ["--local-variant", args.local_variant]
        if args.server:
            sys.argv += ["--server", args.server]
        if args.poll:
            sys.argv += ["--poll"]
        if args.upload:
            sys.argv += ["--upload"]
        if args.privacy:
            sys.argv += ["--privacy", args.privacy]
        gv_generate()
    elif action == "query":
        from fluxreel.gen_video.query import main as gv_query
        sys.argv = ["fluxreel", args.job_id]
        if args.server:
            sys.argv += ["--server", args.server]
        if args.json:
            sys.argv += ["--json"]
        gv_query()
    elif action == "server":
        from fluxreel.gen_video.server import main as gv_server
        sys.argv = ["fluxreel"]
        if args.host:
            sys.argv += ["--host", args.host]
        if args.port:
            sys.argv += ["--port", str(args.port)]
        if args.reload:
            sys.argv += ["--reload"]
        gv_server()
    elif action == "video":
        from fluxreel.gen_video.video import main as gv_video
        sys.argv = ["fluxreel", args.file]
        if args.output:
            sys.argv += ["--output", args.output]
        if args.model:
            sys.argv += ["--model", args.model]
        if args.image_model:
            sys.argv += ["--image-model", args.image_model]
        if args.provider:
            sys.argv += ["--provider", args.provider]
        if args.local_variant:
            sys.argv += ["--local-variant", args.local_variant]
        if args.upload:
            sys.argv += ["--upload"]
        if args.private:
            sys.argv += ["--private"]
        gv_video()


def handle_tunnel(args, ssh_base):
    script = r"""
set -e
export FRP_BROKER_URL=$(grep -z FRP_BROKER_URL /proc/1/environ | tr '\0' '\n' | cut -d= -f2-)
export FRP_BROKER_TLS_SERVER_NAME=$(grep -z FRP_BROKER_TLS_SERVER_NAME /proc/1/environ | tr '\0' '\n' | cut -d= -f2-)
export PATH="$HOME/.local/bin:$PATH"
"""
    if args.tunnel_action == "setup":
        port = input("Port to expose (default: 8081): ").strip() or "8081"
        script += f"""
echo "=== Installing/checking rc-tunnel ==="
if ! command -v rc-tunnel &>/dev/null; then
    /var/run/secrets/frp-self-service/install
fi
rc-tunnel version
echo ""
echo "=== Exposing port {port} ==="
rc-tunnel expose --port {port}
"""
        ssh_cmd(ssh_base, script)

    elif args.tunnel_action == "status":
        ssh_cmd(ssh_base, script + "\nrc-tunnel status\n")
    elif args.tunnel_action == "stop":
        ssh_cmd(ssh_base, script + "\nrc-tunnel stop\n")
    elif args.tunnel_action == "logs":
        ssh_cmd(ssh_base, script + "\nrc-tunnel logs --lines 50\n")
    else:
        print("Usage: fluxreel tunnel {setup|status|stop|logs}")


# ── Download ───────────────────────────────────────────────────

def handle_download(args, ssh_base):
    variant = args.variant
    if variant == "2-dev":
        hf_model = "black-forest-labs/FLUX.2-dev"
        local_dir = args.local_dir or "/root/FLUX.2-dev"
    elif variant == "dev":
        hf_model = "black-forest-labs/FLUX.1-dev"
        local_dir = args.local_dir or "/root/FLUX.1-dev"
    else:
        hf_model = "black-forest-labs/FLUX.1-schnell"
        local_dir = args.local_dir or "/root/FLUX.1-schnell"

    token = args.token or os.environ.get("HF_TOKEN", "")
    if not token:
        print("❌ No HuggingFace token provided.")
        print("   Pass --token or set HF_TOKEN environment variable.")
        sys.exit(1)

    script = f"""set -e
source /opt/venv/bin/activate

echo "=== Logging into HuggingFace ==="
mkdir -p ~/.cache/huggingface
echo "{token}" > ~/.cache/huggingface/token
echo "Token saved"

echo ""
echo "=== Downloading {hf_model} ==="
echo "Target: {local_dir}"
echo ""

tmux kill-session -t flux-download 2>/dev/null || true

cat > /root/download_flux.sh << 'SCRIPT'
#!/bin/bash
source /opt/venv/bin/activate
export HF_ENDPOINT=https://hf-mirror.com
export HF_TOKEN={token}
echo "=== Downloading {hf_model} to {local_dir} ==="
echo "Started at: $(date)"
huggingface-cli download {hf_model} --local-dir {local_dir} --resume-download --quiet
echo ""
echo "=== Finished at: $(date) ==="
ls -lh {local_dir}/
SCRIPT

chmod +x /root/download_flux.sh
tmux new-session -d -s flux-download '/root/download_flux.sh'

echo "✅ Download started in tmux session 'flux-download'"
echo ""
echo "Monitor with:"
echo "  fluxreel check"
echo "  fluxreel shell 'du -sh {local_dir}/'"
echo ""
sleep 2
tmux capture-pane -t flux-download -p
"""
    ssh_cmd(ssh_base, script)


# ── Info ───────────────────────────────────────────────────────

def show_info(ssh_base):
    script = r"""source /opt/venv/bin/activate
echo "=== GPU ==="
rocm-smi 2>&1 | head -5
echo ""
echo "=== PyTorch ==="
python -c "import torch; print(f'Torch {torch.__version__}, CUDA: {torch.cuda.is_available()}, GPUs: {torch.cuda.device_count()}, HIP: {torch.version.hip}')" 2>&1
echo ""
echo "=== Disk ==="
df -h /
echo ""
echo "=== Memory ==="
free -h
echo ""
echo "=== CPU ==="
nproc
"""
    ssh_cmd(ssh_base, script)


# ── Check download ─────────────────────────────────────────────

def check_download(ssh_base):
    script = r"""echo "=== Download progress ==="
du -sh /root/FLUX.*/ 2>/dev/null || echo "No FLUX directories found"
echo ""
for d in /root/FLUX.*/; do
  if [ -d "$d" ]; then
    echo "--- $d ---"
    find "$d" -name "*.safetensors" -exec ls -lh {} \; 2>/dev/null
    echo ""
    inc=$(find "$d/.cache/huggingface/download/" -name "*.incomplete" 2>/dev/null)
    if [ -n "$inc" ]; then
      echo "⏳ Incomplete: $(ls -lh $inc | awk '{print $5}')"
    else
      echo "✅ No incomplete files"
    fi
    echo ""
  fi
done
echo "=== tmux ==="
tmux list-sessions 2>/dev/null || echo "no tmux sessions"
ps aux | grep huggingface | grep -v grep || echo "no download process"
"""
    ssh_cmd(ssh_base, script)


# ── Generate (FLUX inference on remote) ─────────────────────

def handle_generate(args, ssh_base):
    variant = args.model
    if variant == "2-dev":
        model_dir = args.model_dir or "/root/FLUX.2-dev"
    elif variant == "dev":
        model_dir = args.model_dir or "/root/FLUX.1-dev"
    else:
        model_dir = args.model_dir or "/root/FLUX.1-schnell"

    prompt = args.prompt
    if not prompt:
        prompt = input("Enter prompt: ").strip()
        if not prompt:
            print("❌ No prompt provided")
            sys.exit(1)

    port = args.port
    user = args.user
    host = args.host
    output = args.output or f"flux_output_{int(time.time())}.png"
    remote_path = f"/root/{output}"

    # Write a Python script to remote, then execute it (avoids quoting hell)
    py_script = rf'''import torch
from diffusers import FluxPipeline
import time

torch.cuda.empty_cache()

pipe = FluxPipeline.from_pretrained("{model_dir}", torch_dtype=torch.bfloat16)
pipe.enable_sequential_cpu_offload()
pipe.enable_attention_slicing()

prompt = """{prompt}"""
print(f"Prompt: {{prompt}}")
print(f"Generating {args.width}x{args.height}, {args.steps} steps...")
t0 = time.time()
image = pipe(
    prompt,
    num_inference_steps={args.steps},
    guidance_scale={args.guidance},
    width={args.width},
    height={args.height},
).images[0]
t1 = time.time()

image.save("{remote_path}")
print(f"Done in {{t1-t0:.1f}}s")
print(f"Saved: {remote_path} ({{image.size[0]}}x{{image.size[1]}})")
print(f"Max VRAM: {{torch.cuda.max_memory_allocated()/1e9:.2f}} GB")
'''

    # Escape for SSH heredoc: base64 encode to avoid any quoting issues
    import base64
    encoded = base64.b64encode(py_script.encode()).decode()

    script = f"""set -e
source /opt/venv/bin/activate
export USE_ROCM_AITER_ROPE_BACKEND=0
echo "{encoded}" | base64 -d > /root/_infer.py
python3 /root/_infer.py
rm -f /root/_infer.py
"""
    ssh_cmd(ssh_base, script)

    if args.download:
        local_path = os.path.join(os.getcwd(), output)
        print(f"📥 Downloading to {local_path}...")
        subprocess.run([
            "scp", "-P", str(port), "-o", "StrictHostKeyChecking=no",
            f"{user}@{host}:{remote_path}", local_path
        ])
        print(f"✅ Saved to {local_path}")


# ── img (local sd-cpp FLUX) ────────────────────────────────

def handle_img(args):
    """Generate an image locally with the sd-cpp FLUX.1-schnell Q4_0 setup."""
    from fluxreel.gen_video.providers.sd_cpp_provider import SdCppProvider

    prompt = args.prompt
    if not prompt:
        prompt = input("Enter prompt: ").strip()
        if not prompt:
            print("❌ No prompt provided")
            sys.exit(1)

    provider = SdCppProvider(
        bin_path=args.bin,
        model_dir=args.model_dir,
        width=args.width,
        height=args.height,
        steps=args.steps,
        max_vram=args.max_vram,
        seed=args.seed,
    )

    print(f"🧠 {provider.name}")
    print(f"   Model: {provider.model_name}")
    print(f"   Output size: {provider._width}x{provider._height}, {provider._steps} steps")

    out_path = provider.generate_image(prompt, scene_index=0)
    if not out_path:
        print("❌ Generation failed")
        sys.exit(1)

    if args.output:
        import shutil
        shutil.copy(out_path, args.output)
        print(f"✅ Saved to {args.output}")
    else:
        print(f"✅ Saved to {out_path}")


if __name__ == "__main__":
    main()
