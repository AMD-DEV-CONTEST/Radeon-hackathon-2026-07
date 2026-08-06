#!/usr/bin/env python3
"""Poll a Qualia pi05 job until terminal status.

Defaults to the formal icehockey-v1 job; override with --job-id.
Legacy smoke job: 43722198-dada-4505-96eb-39ab8f16b36c
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(ROOT))

from app.services import qualia_service as q  # noqa: E402

DEFAULT_FULL_JOB = "e829bf6d-e249-45c3-b0c6-8c9672e6d068"
DEFAULT_SMOKE_JOB = "43722198-dada-4505-96eb-39ab8f16b36c"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", default=DEFAULT_FULL_JOB)
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--max-iters", type=int, default=180)
    p.add_argument("--out", default=None, help="status json path")
    p.add_argument("--log", default=None, help="append log path")
    args = p.parse_args()

    job_id = args.job_id
    tag = "smoke" if job_id == DEFAULT_SMOKE_JOB else "full"
    out = Path(args.out or f"/tmp/qualia_pi05_{tag}_job.json")
    log = Path(args.log or f"/tmp/qualia_pi05_{tag}_poll.log")

    for _ in range(args.max_iters):
        st = q.get_training_status(job_id)
        status = (st.get("status") or "").lower()
        phase = st.get("phase")
        model = st.get("output_model_id")
        line = (
            f"{time.strftime('%H:%M:%S')} status={status} "
            f"phase={phase} model={model}\n"
        )
        with log.open("a") as f:
            f.write(line)
        print(line, end="")
        out.write_text(json.dumps({"job_id": job_id, **st}, indent=2, default=str))
        if status in ("succeeded", "completed", "done", "success", "failed", "cancelled", "error"):
            with log.open("a") as f:
                f.write("TERMINAL\n")
            break
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()
