#!/usr/bin/env python3
"""Append and validate Determinex memory learning inbox records.

Inbox records are raw lessons awaiting promotion. They are never training data
by default: training_eligible stays false until a separate verifier promotes the
lesson into a proof-bearing corpus or companion memory surface.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INBOX = ROOT / "assurance" / "memory" / "learning_inbox.jsonl"
ALLOWED_TARGET_PREFIXES = (
    "PROJECT.md",
    "docs/companions/",
    "corpus/",
    "docs/campaign/",
    "docs/programs/",
    "assurance/",
)


@dataclass
class InboxRecord:
    id: str
    created_at: str
    summary: str
    source: str
    target: str
    status: str = "pending"
    training_eligible: bool = False


def append_record(inbox: Path, summary: str, source: str, target: str) -> InboxRecord:
    record = InboxRecord(
        id=str(uuid4()),
        created_at=datetime.now(UTC).isoformat(),
        summary=summary,
        source=source,
        target=target.replace("\\", "/"),
    )
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with inbox.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
    return record


def load_records(inbox: Path) -> list[dict]:
    if not inbox.exists():
        return []
    records: list[dict] = []
    for line_number, line in enumerate(inbox.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{inbox}:{line_number}: invalid JSON: {exc}") from exc
        record["_line"] = line_number
        records.append(record)
    return records


def validate_records(inbox: Path) -> list[str]:
    errors: list[str] = []
    for record in load_records(inbox):
        line = record.get("_line", "?")
        status = record.get("status")
        if status not in {"pending", "promoted", "rejected"}:
            errors.append(f"line {line}: invalid status {status!r}")
        for field in ("summary", "source", "target"):
            if not str(record.get(field, "")).strip():
                errors.append(f"line {line}: missing {field}")
        if record.get("training_eligible") is not False:
            errors.append(f"line {line}: training_eligible must remain false in the inbox")
        target = str(record.get("target", "")).replace("\\", "/")
        if target and not target.startswith(ALLOWED_TARGET_PREFIXES):
            errors.append(f"line {line}: target is not an allowed memory surface: {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Determinex memory learning inbox")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    sub = parser.add_subparsers(dest="command", required=True)

    append_cmd = sub.add_parser("append", help="append a pending learning record")
    append_cmd.add_argument("--summary", required=True)
    append_cmd.add_argument("--source", required=True)
    append_cmd.add_argument("--target", required=True)

    sub.add_parser("validate", help="validate inbox records")

    args = parser.parse_args()
    if args.command == "append":
        record = append_record(args.inbox, args.summary, args.source, args.target)
        print(json.dumps(asdict(record), indent=2, sort_keys=True))
        return 0

    errors = validate_records(args.inbox)
    if errors:
        print(json.dumps({"status": "fail", "errors": errors}, indent=2, sort_keys=True))
        return 1
    print(json.dumps({"status": "pass", "inbox": str(args.inbox)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
