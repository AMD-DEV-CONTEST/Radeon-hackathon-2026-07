"""Monitor SmolVLA training: check process status and log tail."""
import os
import subprocess
import time

LOG = "/tmp/smolvla_train.log"

# Check if process is still running
r = subprocess.run(
    ["pgrep", "-f", "lerobot_train"],
    capture_output=True, text=True,
)
pids = r.stdout.strip().split("\n") if r.stdout.strip() else []
print(f"=== lerobot_train PIDs: {pids} ===")

# ROCm GPU usage
print()
print("=== ROCm SMI ===")
r2 = subprocess.run(["rocm-smi"], capture_output=True, text=True, timeout=10)
# Print only the concise table
lines = r2.stdout.split("\n")
for l in lines:
    if "GPU%" in l or "Device" in l or "=====" in l or l.strip().startswith("0"):
        print(l)

# Log tail
print()
print("=== LOG tail (last 3000 chars) ===")
if os.path.exists(LOG):
    with open(LOG, "r") as f:
        content = f.read()
    # Get last 3000 chars
    tail = content[-3000:] if len(content) > 3000 else content
    print(tail)
else:
    print(f"  LOG not found: {LOG}")

# Check output dir for checkpoints
print()
print("=== Checkpoints ===")
out_dir = "/workspace/franka_fruit_pick_demo/outputs/train/smolvla_lerobot"
if os.path.isdir(out_dir):
    for root, dirs, files in os.walk(out_dir):
        for f in files:
            full = os.path.join(root, f)
            size_mb = os.path.getsize(full) / (1024 * 1024)
            rel = os.path.relpath(full, out_dir)
            print(f"  {rel}: {size_mb:.1f} MB")
else:
    print(f"  OUT_DIR not found: {out_dir}")
