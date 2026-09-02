"""Drive the vertical slice: datagen -> train -> eval -> export.

Usage:
    python run_slice.py --config configs/local_4060.toml
    python run_slice.py --config configs/local_4060.toml --stages train,eval --run-dir runs/slice-...
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from foundry import config as config_mod
from foundry.teacher import TeacherClient, start_server, stop_server

STAGES = ["datagen", "train", "eval", "export"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/local_4060.toml")
    ap.add_argument("--stages", default="all")
    ap.add_argument("--run-dir", default=None)
    args = ap.parse_args()

    cfg = config_mod.load(args.config)
    stages = STAGES if args.stages == "all" else args.stages.split(",")
    for s in stages:
        if s not in STAGES:
            raise SystemExit(f"unknown stage {s!r}; valid: {STAGES}")

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        run_dir = Path(cfg["run"]["out_root"]) / f"slice-{datetime.now():%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config_used.json").write_text(
        json.dumps(cfg, indent=2, default=str)
    )
    print(f"run dir: {run_dir}", flush=True)

    summary, timings = {}, {}

    if "datagen" in stages:
        t0 = time.time()
        from foundry.spec import TaskSpec
        spec = TaskSpec.load(cfg["task"]["spec"])
        spec.save(run_dir / "spec.json")
        client = TeacherClient(cfg["teacher"]["base_url"])
        proc = None
        if not client.healthy():
            print("starting teacher server...", flush=True)
            port = int(cfg["teacher"]["base_url"].rsplit(":", 1)[1].split("/")[0])
            proc = start_server(
                cfg["teacher"]["server_exe"], cfg["teacher"]["gguf"], port,
                cfg["teacher"]["n_gpu_layers"], cfg["teacher"]["parallel"],
                cfg["teacher"]["ctx_per_slot"],
            )
        try:
            from foundry.datagen import generate
            summary["datagen"] = generate(cfg, run_dir, spec)
        finally:
            if proc is not None:
                stop_server(proc)
        timings["datagen"] = round(time.time() - t0, 1)

    if "train" in stages:
        t0 = time.time()
        from foundry.train import train
        summary["train"] = train(cfg, run_dir)
        timings["train"] = round(time.time() - t0, 1)

    if "eval" in stages:
        t0 = time.time()
        from foundry.evaluate import evaluate
        summary["eval"] = evaluate(cfg, run_dir)
        timings["eval"] = round(time.time() - t0, 1)

    if "export" in stages:
        t0 = time.time()
        from foundry.export import export
        summary["export"] = export(cfg, run_dir)
        timings["export"] = round(time.time() - t0, 1)

    summary["timings_sec"] = timings
    (run_dir / "slice_summary.json").write_text(json.dumps(summary, indent=2))
    print("SLICE COMPLETE\n" + json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
