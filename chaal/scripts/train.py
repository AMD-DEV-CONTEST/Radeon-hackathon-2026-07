"""Train a locomotion policy. Usage: train.py [num_envs] [iterations] [log_dir]"""
import sys

from chaal.train import run

run(
    num_envs=int(sys.argv[1]) if len(sys.argv) > 1 else 4096,
    max_iterations=int(sys.argv[2]) if len(sys.argv) > 2 else 300,
    log_dir=sys.argv[3] if len(sys.argv) > 3 else "runs/go2",
)
