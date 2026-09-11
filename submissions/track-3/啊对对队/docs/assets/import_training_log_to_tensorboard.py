#!/usr/bin/env python3
"""Import the recorded SmolVLA text log into TensorBoard scalar events."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from tensorboard.compat.proto.event_pb2 import Event
from tensorboard.compat.proto.summary_pb2 import Summary
from tensorboard.summary.writer.event_file_writer import EventFileWriter


UPDATE_RE = re.compile(r"loss:(?P<loss>[0-9.]+)\s+grdn:(?P<grad>[0-9.]+)")


def read_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw[:1024]:
        return raw.decode("utf-16")
    return raw.decode("utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = [
        (float(match.group("loss")), float(match.group("grad")))
        for match in UPDATE_RE.finditer(read_log(args.log))
    ]
    if len(rows) != 2800:
        raise RuntimeError(f"expected 2800 updates, parsed {len(rows)}")

    args.output.mkdir(parents=True, exist_ok=True)
    writer = EventFileWriter(str(args.output))
    writer.add_event(Event(wall_time=time.time(), file_version="brain.Event:2"))
    for update, (loss, grad) in enumerate(rows, start=1):
        summary = Summary(
            value=[
                Summary.Value(tag="train/imitation_loss", simple_value=loss),
                Summary.Value(tag="train/gradient_norm", simple_value=grad),
            ]
        )
        writer.add_event(Event(wall_time=time.time(), step=update, summary=summary))
    try:
        writer.flush()
    finally:
        writer.close()

    manifest = {
        "schema_version": 1,
        "source_log": args.log.name,
        "source_log_sha256": hashlib.sha256(args.log.read_bytes()).hexdigest(),
        "updates": len(rows),
        "tags": ["train/imitation_loss", "train/gradient_norm"],
        "provenance": "Imported after training from the recorded text log for TensorBoard visualization.",
    }
    (args.output / "import_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Imported {len(rows)} updates into {args.output}")


if __name__ == "__main__":
    main()
