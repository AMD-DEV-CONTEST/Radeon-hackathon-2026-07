from __future__ import annotations

import argparse
import json
from pathlib import Path

from .generator import build_report, generate_package
from .gpu import write_status


def _print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="finmuse", description="FinMuse Radeon financial product multimodal demo")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gpu = sub.add_parser("check-gpu", help="Detect AMD Radeon / ROCm runtime and write gpu-status.json")
    p_gpu.add_argument("--out", default="outputs/gpu-status.json")

    p_gen = sub.add_parser("generate", help="Generate financial product promotional assets")
    p_gen.add_argument("--brief", required=True, help="Path to product brief JSON")
    p_gen.add_argument("--variants", type=int, default=3)
    p_gen.add_argument("--out", required=True, help="Output directory")

    p_report = sub.add_parser("report", help="Build markdown report from one or more run directories")
    p_report.add_argument("--run", action="append", required=True)
    p_report.add_argument("--out", default="outputs/demo-report.md")

    args = parser.parse_args(argv)
    if args.command == "check-gpu":
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        data = write_status(args.out)
        _print_json(data)
    elif args.command == "generate":
        data = generate_package(args.brief, args.out, args.variants)
        _print_json(data)
    elif args.command == "report":
        text = build_report(args.run, args.out)
        print(text)


if __name__ == "__main__":
    main()
