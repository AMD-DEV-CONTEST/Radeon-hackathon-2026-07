#!/usr/bin/env python3
"""Execute a frozen JSONL query set with KataGo's analysis protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Engine:
    def __init__(self, binary: Path, model: Path, config: Path):
        self.process = subprocess.Popen(
            [str(binary), "analysis", "-model", str(model), "-config", str(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._stdout, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    def _stdout(self) -> None:
        assert self.process.stdout
        for line in self.process.stdout:
            try:
                self.responses.put(json.loads(line))
            except json.JSONDecodeError:
                self.stderr.append("invalid stdout JSON")

    def _stderr(self) -> None:
        assert self.process.stderr
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())
            del self.stderr[:-100]

    def query(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        assert self.process.stdin
        started = time.perf_counter()
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        deadline = started + timeout
        expected_turn = int((payload.get("analyzeTurns") or [len(payload.get("moves") or [])])[-1])
        while True:
            if self.process.poll() is not None:
                raise RuntimeError("KataGo exited: " + "\n".join(self.stderr[-20:]))
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError(str(payload.get("id")))
            try:
                item = self.responses.get(timeout=min(.25, remaining))
            except queue.Empty:
                continue
            if item.get("id") != payload.get("id") or item.get("isDuringSearch"):
                continue
            if item.get("error"):
                raise RuntimeError(str(item["error"]))
            if int(item.get("turnNumber", expected_turn)) == expected_turn:
                item["elapsedSeconds"] = round(time.perf_counter() - started, 6)
                return item

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--katago", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    for path in (args.katago, args.model, args.config, args.queries):
        if not path.is_file():
            parser.error(f"missing file: {path}")
    queries = read_jsonl(args.queries)
    if not queries or any(int(row.get("maxVisits") or 0) != 128 for row in queries):
        parser.error("queries must be non-empty and fixed to 128 visits")
    engine = Engine(args.katago, args.model, args.config)
    try:
        results = [engine.query(query, args.timeout) for query in queries]
    finally:
        engine.close()
    output = {
        "schemaVersion": "yijian-katago-query-set-result-v1",
        "passed": len(results) == len(queries),
        "cases": len(results),
        "visitsPerCase": 128,
        "queriesSha256": sha256_file(args.queries),
        "engineSha256": sha256_file(args.katago),
        "modelSha256": sha256_file(args.model),
        "configSha256": sha256_file(args.config),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({"passed": output["passed"], "cases": output["cases"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
