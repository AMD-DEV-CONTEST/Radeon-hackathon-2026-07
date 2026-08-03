#!/usr/bin/env python3
"""Reproducible W7900 KataGo analysis-protocol benchmark.

The position is synthetic and checked in here, so the benchmark never needs
to read or upload a user's SGF. Startup/tuning time, a 32-visit batch scan,
and a 128-visit interactive review are reported separately.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time


MODEL_SHA256 = "15fb3baf85cdb6578e6c19b65e6201ca906cec3ba5fee19039d05221d57eb0e8"
FIXED_MOVES = [
    ["B", "Q16"], ["W", "D16"], ["B", "D4"], ["W", "Q4"],
    ["B", "C14"], ["W", "C6"], ["B", "R14"], ["W", "R6"],
    ["B", "O17"], ["W", "O3"], ["B", "E17"], ["W", "E3"],
    ["B", "K16"], ["W", "K4"], ["B", "Q10"], ["W", "D10"],
    ["B", "N15"], ["W", "F15"], ["B", "N5"], ["W", "F5"],
    ["B", "R11"], ["W", "C11"], ["B", "R8"], ["W", "C8"],
    ["B", "L14"], ["W", "H14"], ["B", "L6"], ["W", "H6"],
    ["B", "P12"], ["W", "E12"], ["B", "P8"], ["W", "E8"],
]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture(command: list[str]) -> str:
    try:
        return subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def runtime_evidence(katago: Path) -> dict:
    katago_version = capture([str(katago), "version"])
    amd_version = capture(["amd-smi", "version"])
    amd_static = capture(["amd-smi", "static", "--asic", "--vram", "--driver"])
    clinfo = capture(["clinfo"])
    lscpu = capture(["lscpu"])

    def find(pattern: str, text: str, default: str = "unknown") -> str:
        match = re.search(pattern, text, re.MULTILINE)
        return match.group(1).strip() if match else default

    return {
        "platform": platform.platform(),
        "katago": katago_version,
        "amdSmi": amd_version,
        "cpu": {
            "model": find(r"^Model name:\s*([^\n]+)", lscpu),
            "sockets": int(find(r"^Socket\(s\):\s*(\d+)", lscpu, "0")),
            "coresPerSocket": int(
                find(r"^Core\(s\) per socket:\s*(\d+)", lscpu, "0")
            ),
            "threadsPerCore": int(
                find(r"^Thread\(s\) per core:\s*(\d+)", lscpu, "0")
            ),
            "logicalCpus": int(find(r"^CPU\(s\):\s*(\d+)", lscpu, "0")),
        },
        "gpu": {
            "architecture": find(r"TARGET_GRAPHICS_VERSION:\s*(\S+)", amd_static),
            "computeUnits": int(find(r"NUM_COMPUTE_UNITS:\s*(\d+)", amd_static, "0")),
            "vram": find(r"SIZE:\s*([^\n]+)", amd_static),
            "driver": find(r"^\s*VERSION:\s*([^\n]+)", amd_static),
            "openclPlatform": find(r"Platform Version:\s*([^\n]+)", clinfo),
            "openclDevice": find(r"^\s*Name:\s*(gfx\d+)\s*$", clinfo),
            "fp16": "cl_khr_fp16" in clinfo,
        },
    }


def configured(
    base: str, analysis_threads: int, search_threads: int, batch_size: int
) -> str:
    replacements = {
        "numAnalysisThreads": analysis_threads,
        "numSearchThreadsPerAnalysisThread": search_threads,
        "nnMaxBatchSize": batch_size,
    }
    output = base
    for key, value in replacements.items():
        pattern = rf"(?m)^\s*{re.escape(key)}\s*=.*$"
        output, count = re.subn(pattern, f"{key} = {value}", output)
        if count != 1:
            raise ValueError(f"configuration must contain exactly one {key}")
    return output


class AnalysisProcess:
    def __init__(self, executable: Path, model: Path, config: Path):
        started = time.perf_counter()
        self.proc = subprocess.Popen(
            [str(executable), "analysis", "-model", str(model), "-config", str(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.responses: queue.Queue[dict] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.spawn_seconds = time.perf_counter() - started

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                self.responses.put(json.loads(line))
            except json.JSONDecodeError:
                self.stderr.append(f"invalid JSON: {line.rstrip()}")

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())
            del self.stderr[:-120]

    def query(self, query_id: str, moves: list[list[str]], turns: list[int], visits: int,
              timeout: float = 600.0) -> tuple[list[dict], float]:
        payload = {
            "id": query_id,
            "moves": moves,
            "rules": "chinese",
            "komi": 7.5,
            "boardXSize": 19,
            "boardYSize": 19,
            "analyzeTurns": turns,
            "maxVisits": visits,
            "analysisPVLen": 12,
        }
        assert self.proc.stdin is not None
        started = time.perf_counter()
        self.proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()
        results: dict[int, dict] = {}
        deadline = started + timeout
        while len(results) < len(turns):
            if self.proc.poll() is not None:
                raise RuntimeError("KataGo exited:\n" + "\n".join(self.stderr[-20:]))
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError(f"KataGo query {query_id} exceeded {timeout:g}s")
            try:
                item = self.responses.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if item.get("id") != query_id or item.get("isDuringSearch", False):
                continue
            if "error" in item:
                raise RuntimeError(str(item["error"]))
            if "turnNumber" in item:
                results[int(item["turnNumber"])] = item
        elapsed = time.perf_counter() - started
        return [results[turn] for turn in turns], elapsed

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def summarize(items: list[dict], elapsed: float) -> dict:
    visits = sum(int(item.get("rootInfo", {}).get("visits", 0)) for item in items)
    final = items[-1]
    infos = final.get("moveInfos") or []
    root = final.get("rootInfo") or {}
    return {
        "positions": len(items),
        "elapsedSeconds": round(elapsed, 4),
        "positionsPerSecond": round(len(items) / elapsed, 3),
        "reportedVisits": visits,
        "bestMove": infos[0].get("move") if infos else None,
        "winrateBlack": round(float(root.get("winrate", 0.5)), 6),
        "scoreLeadBlack": round(float(root.get("scoreLead", 0.0)), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--katago", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--analysis-threads", type=int, default=64)
    parser.add_argument("--search-threads", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-model-hash", action="store_true")
    args = parser.parse_args()

    for path in (args.katago, args.model, args.config):
        if not path.is_file():
            parser.error(f"missing file: {path}")
    model_hash = file_sha256(args.model) if not args.skip_model_hash else "not-checked"
    if not args.skip_model_hash and model_hash != MODEL_SHA256:
        parser.error(f"model SHA-256 mismatch: {model_hash}")
    evidence = runtime_evidence(args.katago)

    with tempfile.TemporaryDirectory(prefix="yijian-katago-benchmark-") as temp_dir:
        runtime_config = Path(temp_dir) / "analysis.cfg"
        runtime_config.write_text(
            configured(
                args.config.read_text(encoding="utf-8"),
                args.analysis_threads,
                args.search_threads,
                args.batch_size,
            ),
            encoding="utf-8",
        )
        engine = AnalysisProcess(args.katago, args.model, runtime_config)
        try:
            _, warm_seconds = engine.query("warmup", [], [0], 1)
            turns = list(range(len(FIXED_MOVES) + 1))
            scan, scan_seconds = engine.query("scan-32", FIXED_MOVES, turns, 32)
            review, review_seconds = engine.query(
                "review-128", FIXED_MOVES, [len(FIXED_MOVES)], 128
            )
            result = {
                "schemaVersion": 1,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "katagoVersion": "1.16.5",
                "backend": "OpenCL",
                "runtimeEvidence": evidence,
                "model": args.model.name,
                "modelBytes": args.model.stat().st_size,
                "modelSha256": model_hash,
                "analysisThreads": args.analysis_threads,
                "searchThreadsPerAnalysisThread": args.search_threads,
                "nnMaxBatchSize": args.batch_size,
                "fixedPositionId": "synthetic-19x19-v1",
                "startup": {
                    "spawnSeconds": round(engine.spawn_seconds, 4),
                    "warmupSeconds": round(warm_seconds, 4),
                },
                "scan32": summarize(scan, scan_seconds),
                "review128": summarize(review, review_seconds),
            }
        finally:
            engine.close()

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
