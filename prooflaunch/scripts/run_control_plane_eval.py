from __future__ import annotations

import argparse
import json

from prooflaunch_remix.evaluation import run_control_plane_eval


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-per-mode", type=int, default=20)
    parser.add_argument(
        "--output",
        default="evidence/local/control-plane-eval.json",
    )
    args = parser.parse_args()
    payload = run_control_plane_eval(
        cases_per_mode=args.cases_per_mode,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "case_count": payload["case_count"],
                "passed": payload["passed"],
                "pass_rate": payload["pass_rate"],
                "latency_ms": payload["latency_ms"],
                "output": args.output,
            },
            indent=2,
        )
    )
    raise SystemExit(0 if payload["pass_rate"] == 1 else 1)


if __name__ == "__main__":
    main()
