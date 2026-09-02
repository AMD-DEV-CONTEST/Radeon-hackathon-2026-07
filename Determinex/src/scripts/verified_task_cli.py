"""CLI for the universal verified task harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verified_task import CorpusWriter, RetryLoop, TaskSpec, WorkspaceManager
from verified_task.adapters import terminal_task_spec
from verified_task.paths import default_verified_root
from verified_task.storage import compress_directory, inventory


def cmd_run_spec(args: argparse.Namespace) -> None:
    spec = TaskSpec.from_dict(json.loads(Path(args.spec).read_text(encoding="utf-8")))
    manager = WorkspaceManager(Path(args.root) if args.root else None)
    lease = manager.create(spec, copy_source=not args.no_copy)
    corpus = CorpusWriter(lease.corpus / "verified_task_trace.jsonl")
    result = RetryLoop(corpus_writer=corpus).run(spec, lease)
    print(json.dumps({"passed": result.passed, "result": str(result.final_verdict_path)}, indent=2))


def cmd_terminal(args: argparse.Namespace) -> None:
    spec = terminal_task_spec(
        task_id=args.id,
        instruction=args.instruction,
        workspace=Path(args.workspace),
        setup_commands=args.setup or [],
        validation_commands=args.validate,
        language=args.language,
        timeout_seconds=args.timeout,
        max_attempts=args.max_attempts,
    )
    manager = WorkspaceManager(Path(args.root) if args.root else None)
    lease = manager.create(spec)
    corpus = CorpusWriter(lease.corpus / "verified_task_trace.jsonl")
    result = RetryLoop(corpus_writer=corpus).run(spec, lease)
    print(
        json.dumps(
            {
                "passed": result.passed,
                "workspace": str(lease.workspace),
                "result": str(result.final_verdict_path),
            },
            indent=2,
        )
    )


def cmd_inventory(args: argparse.Namespace) -> None:
    root = Path(args.root) if args.root else default_verified_root()
    rows = [entry.to_dict() for entry in inventory(root, min_age_seconds=args.min_age_seconds)]
    print(json.dumps({"root": str(root), "entries": rows}, indent=2))


def cmd_compress(args: argparse.Namespace) -> None:
    out = compress_directory(Path(args.path), delete_original=args.delete_original)
    print(
        json.dumps({"archive": str(out), "deleted_original": bool(args.delete_original)}, indent=2)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=None, help=f"staging root, default {default_verified_root()}"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_spec = sub.add_parser("run-spec", help="run a JSON TaskSpec")
    p_spec.add_argument("spec")
    p_spec.add_argument("--no-copy", action="store_true")
    p_spec.set_defaults(func=cmd_run_spec)

    p_term = sub.add_parser("terminal", help="run a generic terminal task")
    p_term.add_argument("--id", required=True)
    p_term.add_argument("--instruction", required=True)
    p_term.add_argument("--workspace", required=True)
    p_term.add_argument("--validate", action="append", required=True)
    p_term.add_argument("--setup", action="append")
    p_term.add_argument("--language", default="bash")
    p_term.add_argument("--timeout", type=int, default=600)
    p_term.add_argument("--max-attempts", type=int, default=3)
    p_term.set_defaults(func=cmd_terminal)

    p_inv = sub.add_parser("inventory", help="list T-backed verified task storage")
    p_inv.add_argument("--min-age-seconds", type=int, default=0)
    p_inv.set_defaults(func=cmd_inventory)

    p_zip = sub.add_parser("compress", help="zip one T-backed run directory")
    p_zip.add_argument("path")
    p_zip.add_argument("--delete-original", action="store_true")
    p_zip.set_defaults(func=cmd_compress)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
