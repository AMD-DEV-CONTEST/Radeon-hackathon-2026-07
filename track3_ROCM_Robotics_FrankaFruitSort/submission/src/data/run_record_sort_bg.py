"""Background launcher for record_sort_dataset.py.
Uses start_new_session=True to survive JupyterLab kernel timeouts.

Usage (on remote JupyterLab):
    cd /workspace/franka_fruit_pick_demo
    .venv/bin/python /tmp/run_record_bg.py
"""
import subprocess
import time
import os

VENV_PYTHON = "/workspace/franka_fruit_pick_demo/.venv/bin/python"
WORKDIR = "/workspace/franka_fruit_pick_demo"
LOG = "/tmp/record_sort.log"

env = dict(os.environ)
env["MPLBACKEND"] = "Agg"

# Clean old log
try:
    os.remove(LOG)
except FileNotFoundError:
    pass

cmd = [
    VENV_PYTHON, "franka_fruit_pick/record_sort_dataset.py",
    "--episodes", "5",
    "--max-attempts", "25",
    "--fps", "30",
    "--img-wh", "224", "224",
    "--dataset-name", "sort_fruit",
    "--repo-id", "local/sort_fruit",
]

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
print(f"started record_sort_dataset PID={proc.pid}, log={LOG}")

time.sleep(10)
poll = proc.poll()
print(f"10s status: {'running' if poll is None else f'exited({poll})'}")
