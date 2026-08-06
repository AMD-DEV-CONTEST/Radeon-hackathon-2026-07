#!/usr/bin/env python3
"""Submit a Qualia pi05 finetune job for B601 icehockey datasets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(ROOT))

from app.services import qualia_service as q  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--dataset",
        default="userresu2026/b601-dm-icehockey-v1",
        help="HF dataset id",
    )
    p.add_argument("--hours", type=float, default=5.0)
    p.add_argument("--instance", default="n3-L40x1")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--model-id", default="lerobot/pi05_base")
    p.add_argument("--name", default="botversex-pi05-icehockey")
    args = p.parse_args()

    result = q.create_training_job(
        dataset_hf_id=args.dataset,
        algorithm="pi05",
        params={
            "hours": args.hours,
            "instance_type": args.instance,
            "batch_size": args.batch_size,
            "model_id": args.model_id,
            "camera_keys": [
                "observation.images.front",
                "observation.images.side",
            ],
            "project_name": args.name,
            "job_description": f"pi05 on {args.dataset}",
        },
    )
    print(json.dumps(result, indent=2, default=str))
    out = Path("/tmp") / f"qualia_pi05_{args.dataset.replace('/', '_')}.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    print("wrote", out)
    if result.get("status") == "error" or not result.get("job_id"):
        sys.exit(1)


if __name__ == "__main__":
    main()
