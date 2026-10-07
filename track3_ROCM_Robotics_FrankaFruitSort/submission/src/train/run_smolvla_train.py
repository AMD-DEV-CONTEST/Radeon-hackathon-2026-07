"""Background launcher for SmolVLA fine-tuning on the sort_fruit dataset.

Uses start_new_session=True to survive JupyterLab kernel timeouts (training
will run for many minutes; the kernel WebSocket would otherwise time out).

Usage (on remote JupyterLab):
    cd /workspace/franka_fruit_pick_demo
    .venv/bin/python /tmp/run_smolvla_train.py

Logs to /tmp/smolvla_train.log.
"""
import os
import subprocess
import time

VENV_PYTHON = "/workspace/franka_fruit_pick_demo/.venv/bin/python"
WORKDIR = "/workspace/franka_fruit_pick_demo"
LOG = "/tmp/smolvla_train.log"

env = dict(os.environ)
env["MPLBACKEND"] = "Agg"
# NOTE: HF_HUB_OFFLINE is intentionally NOT set:
# - Dataset loading now works without Hub calls (path resolution fixed:
#   omitting --dataset.root makes LeRobot use HF_LEROBOT_HOME/<repo_id>).
# - SmolVLA's VLM backbone (HuggingFaceTB/SmolVLM2-500M-Video-Instruct) must
#   be downloaded from HF Hub; HF_HUB_OFFLINE=1 breaks this.
# - The base policy snapshot (lerobot/smolvla_base) is already cached, so
#   transformers/huggingface_hub will use the cache and not re-download.
# Reduce verbosity / disable unwanted features.
env["TOKENIZERS_PARALLELISM"] = "false"

# Clean old log
try:
    os.remove(LOG)
except FileNotFoundError:
    pass

# Pre-clean any previous training output dir (avoids resume prompts).
OUT_DIR = os.path.join(WORKDIR, "outputs/train/smolvla_lerobot")
import shutil
if os.path.isdir(OUT_DIR):
    print(f"[pre-clean] removing old {OUT_DIR}")
    shutil.rmtree(OUT_DIR, ignore_errors=True)

cmd = [
    VENV_PYTHON, "-m", "lerobot.scripts.lerobot_train",
    "--policy.path=lerobot/smolvla_base",
    "--dataset.repo_id=local/sort_fruit",
    # NOTE: omit --dataset.root so LeRobot defaults to HF_LEROBOT_HOME/<repo_id>,
    # which is /root/.cache/huggingface/lerobot/local/sort_fruit -- the actual
    # location of our dataset. Setting --dataset.root to the parent dir causes
    # _load_metadata() to look at <root>/meta/info.json (missing) and triggers
    # get_safe_version() which fails for local datasets (401 on HF Hub).
    "--output_dir=outputs/train/smolvla_lerobot",
    "--job_name=smolvla_lerobot",
    "--batch_size=4",
    "--steps=2000",
    "--save_freq=500",
    "--log_freq=50",
    "--num_workers=4",
    "--seed=1000",
    "--policy.device=cuda",
    "--policy.push_to_hub=false",
    "--wandb.enable=false",
    "--dataset.video_backend=pyav",
    '--rename_map={"observation.images.world": "observation.images.camera1", "observation.images.wrist": "observation.images.camera2"}',
]

print(f"[cmd] {' '.join(cmd)}")
print(f"[log] {LOG}")

proc = subprocess.Popen(
    cmd,
    cwd=WORKDIR,
    stdout=open(LOG, "wb"),
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    env=env,
    start_new_session=True,
    close_fds=True,
)
print(f"started SmolVLA training PID={proc.pid}, log={LOG}")

# Wait 90s: SmolVLA needs to download SmolVLM2-500M-Video-Instruct backbone
# (~1 GB) and initialize the model before training starts.
time.sleep(90)
poll = proc.poll()
print(f"90s status: {'running' if poll is None else f'exited({poll})'}")

# Always dump the log tail (helps debug if it crashed, or shows progress if running).
with open(LOG, "r") as f:
    content = f.read()
    print(f"=== LOG (last 5000 chars) ===")
    print(content[-5000:] if len(content) > 5000 else content)
