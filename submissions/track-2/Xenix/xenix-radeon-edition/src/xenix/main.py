from __future__ import annotations

import argparse
import hashlib
import os
from multiprocessing import freeze_support
from pathlib import Path
from typing import Sequence

from .app import run
from .single_instance import SingleInstanceGuard


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xenix")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Initialize the native app and exit after startup validation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    freeze_support()
    args = build_argument_parser().parse_args(list(argv) if argv is not None else None)
    # Both development and packaged GUI entry points arrive here.  Workers
    # branch before this module, so one guard protects the only Conversation
    # writer without making worker startup part of recovery semantics.
    guard = SingleInstanceGuard(_instance_mutex_name(smoke_test=args.smoke_test))
    try:
        return run(smoke_test=args.smoke_test)
    finally:
        guard.close()


def _instance_mutex_name(*, smoke_test: bool) -> str:
    if not smoke_test:
        return "Local\\dev.lanzhijiang.xenix.gui"
    runtime_home = str(Path(os.environ.get("XENIX_APP_HOME", ".")).expanduser().resolve())
    fingerprint = hashlib.sha256(runtime_home.encode("utf-8")).hexdigest()[:24]
    return f"Local\\dev.lanzhijiang.xenix.smoke.{fingerprint}"


if __name__ == "__main__":
    raise SystemExit(main())
