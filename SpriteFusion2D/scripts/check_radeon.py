#!/usr/bin/env python3
"""Read-only Radeon environment probe CLI (luna-workpack R01).

Read-only checks for the SpriteFusion 2D Radeon stack: Python, PyTorch (lazy),
HIP, GPU, VRAM, a subprocess operator smoke test with a timeout, ComfyUI
health, and the generation checkpoint (presence plus optional SHA-256).

Paths and non-loopback endpoints are masked in both output modes by default;
pass --reveal-paths / --reveal-endpoints for private debugging.

Exit codes aligned with sprite_workshop.errors.ExitCode: 0 pass, 2 argparse/usage
error only, 4 runtime or environment error (incl. SHA-256 mismatch), 5 missing
dependency / backend unavailable.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_probe_module() -> Any:
    """Import the probe module, tolerating a bare Python environment.

    Prefers the normal package import; if ``sprite_workshop.__init__`` cannot
    be imported (for example numpy is missing), the stdlib-only probe module is
    loaded directly so the probe still runs to a structured conclusion.
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    try:
        import sprite_workshop.radeon_probe as radeon_probe

        return radeon_probe
    except Exception:
        spec = importlib.util.spec_from_file_location(
            "radeon_probe_standalone",
            _REPO_ROOT / "sprite_workshop" / "radeon_probe.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module.__name__] = module
        spec.loader.exec_module(module)
        return module


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_radeon.py",
        description="Read-only Radeon environment probe for SpriteFusion 2D.",
        epilog=(
            "Exit codes: 0 pass, 2 argparse/usage error only, "
            "4 runtime or environment error (incl. SHA-256 mismatch), "
            "5 missing dependency / backend unavailable."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="emit a structured JSON receipt"
    )
    parser.add_argument(
        "--reveal-paths",
        action="store_true",
        help="show real filesystem paths (default: masked)",
    )
    parser.add_argument(
        "--reveal-endpoints",
        action="store_true",
        help="show real non-loopback endpoints (default: masked)",
    )
    parser.add_argument(
        "--verify-sha256",
        action="store_true",
        help="verify the model SHA-256 when a model path is configured",
    )
    parser.add_argument(
        "--model",
        metavar="PATH",
        help="model checkpoint path (env: RADEON_PROBE_MODEL_PATH)",
    )
    parser.add_argument(
        "--comfyui-endpoint",
        metavar="URL",
        help="ComfyUI endpoint (default: http://127.0.0.1:8188)",
    )
    parser.add_argument(
        "--smoke-timeout",
        type=float,
        metavar="SECONDS",
        help="operator smoke timeout (default: 120)",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        metavar="SECONDS",
        help="ComfyUI health timeout (default: 5)",
    )
    parser.add_argument(
        "--expected-sha256",
        metavar="HEX",
        help="expected model SHA-256 (overrides the built-in default)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    probe = _load_probe_module()
    overrides: dict[str, Any] = {}
    if args.reveal_paths:
        overrides["reveal_paths"] = True
    if args.reveal_endpoints:
        overrides["reveal_endpoints"] = True
    if args.model:
        overrides["model_path"] = Path(args.model).expanduser()
    if args.comfyui_endpoint:
        overrides["comfyui_endpoint"] = args.comfyui_endpoint
    if args.smoke_timeout is not None:
        overrides["smoke_timeout"] = args.smoke_timeout
    if args.http_timeout is not None:
        overrides["http_timeout"] = args.http_timeout
    if args.verify_sha256:
        overrides["verify_sha256"] = True
    if args.expected_sha256:
        overrides["expected_sha256"] = args.expected_sha256

    env = probe.ProbeEnv.from_os(**overrides)
    report = probe.run_probe(env)
    if args.json:
        sys.stdout.write(report.to_json())
    else:
        sys.stdout.write(probe.render_human(report, env) + "\n")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
