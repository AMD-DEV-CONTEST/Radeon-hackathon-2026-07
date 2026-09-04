"""Command-line entry point for offline and AMD-local private-agent demos."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Sequence

from .analysis import load_parameter_ranges
from .llm import OpenAICompatibleClient, validate_local_base_url
from .pipeline import run_full_demo, run_library_scenario
from .reporting import generate_demo_artifacts
from .workflow import LocalWorkflowPlanner


_PACKAGE_DATA = Path(__file__).with_name("data")


def validate_llm_base_url(value: str) -> str:
    """Accept only credential-free HTTP(S) endpoints on a loopback host."""
    return validate_local_base_url(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the private nuclear emergency screening agent locally."
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=_PACKAGE_DATA / "scenarios" / "cs137_emergency_full.json",
        help="Scenario JSON (default: packaged demonstration case)",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/demo"), help="Output directory"
    )
    parser.add_argument(
        "--potassium-levels",
        type=float,
        nargs="+",
        default=(0.0, 20.0),
        metavar="MG_L",
        help="K+ levels for a legacy flat scenario (default: 0 20)",
    )
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        default=_PACKAGE_DATA / "knowledge",
        help="Bundled local Markdown knowledge base",
    )
    parser.add_argument(
        "--uncertainty-ranges",
        type=Path,
        default=_PACKAGE_DATA / "scenarios" / "uncertainty_ranges.json",
        help="JSON parameter ranges with provenance",
    )
    parser.add_argument(
        "--samples", type=int, default=512, help="Seeded uncertainty samples"
    )
    parser.add_argument("--seed", type=int, default=42, help="Uncertainty RNG seed")
    parser.add_argument(
        "--session-id", default="demo-session", help="Local memory session ID"
    )
    parser.add_argument(
        "--planner",
        choices=("deterministic", "llm"),
        default="deterministic",
        help="Offline deterministic planner or private AMD-local LLM planner",
    )
    parser.add_argument(
        "--llm-base-url",
        default=os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        help="Local OpenAI-compatible base URL",
    )
    parser.add_argument(
        "--llm-model",
        default=os.environ.get("LLM_MODEL", "qwen35-9b-q8"),
        help="Local model alias",
    )
    return parser


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{description} JSON root must be an object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _read_json_object(args.scenario, "scenario")
        if payload.get("schema_version") == "nuclidepath-scenario-1.0":
            if args.planner != "deterministic":
                raise ValueError("versioned library scenarios use the deterministic validation pipeline")
            artifacts = run_library_scenario(
                payload, args.output, samples=args.samples, seed=args.seed
            )
        elif "site" in payload or "transport" in payload:
            ranges_payload = _read_json_object(
                args.uncertainty_ranges, "uncertainty ranges"
            )
            planner = None
            if args.planner == "llm":
                base_url = validate_llm_base_url(args.llm_base_url)
                client = OpenAICompatibleClient(
                    base_url,
                    model=args.llm_model,
                    api_key=os.environ.get("LLM_API_KEY"),
                )
                planner = LocalWorkflowPlanner(client)
            artifacts = run_full_demo(
                payload,
                args.output,
                knowledge_dir=args.knowledge_dir,
                parameter_ranges=load_parameter_ranges(ranges_payload),
                uncertainty_samples=args.samples,
                seed=args.seed,
                session_id=args.session_id,
                planner=planner,
            )
        else:
            legacy = generate_demo_artifacts(
                payload, args.output, args.potassium_levels
            )
            artifacts = {
                "report_json": legacy["json"],
                "report_markdown": legacy["markdown"],
                "concentration_svg": legacy["svg"],
            }
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
