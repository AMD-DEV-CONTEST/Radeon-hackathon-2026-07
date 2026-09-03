# -*- coding: utf-8 -*-
"""Build 28 deterministic project-original, non-training Go evaluation positions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


TRAINING_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TRAINING_ROOT.parent / "backend"))
import goboard  # noqa: E402
import sgf  # noqa: E402


SCHEMA = "yijian-unseen-position-eval-v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def transformed(grid: bytes, size: int, kind: int) -> bytes:
    out = bytearray(size * size)
    for y in range(size):
        for x in range(size):
            if kind == 0: nx, ny = x, y
            elif kind == 1: nx, ny = size - 1 - y, x
            elif kind == 2: nx, ny = size - 1 - x, size - 1 - y
            elif kind == 3: nx, ny = y, size - 1 - x
            elif kind == 4: nx, ny = size - 1 - x, y
            elif kind == 5: nx, ny = x, size - 1 - y
            elif kind == 6: nx, ny = y, x
            else: nx, ny = size - 1 - y, size - 1 - x
            out[ny * size + nx] = grid[y * size + x]
    return bytes(out)


def symmetry_fingerprints(grid: bytes, size: int, to_play: str) -> list[str]:
    return sorted({hashlib.sha256(bytes([size]) + to_play.encode("ascii") + transformed(grid, size, kind)).hexdigest() for kind in range(8)})


def build(sgf_paths: list[Path]) -> list[dict[str, Any]]:
    if len(sgf_paths) < 25:
        raise ValueError("at least 25 independent SGFs are required")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for game_index, path in enumerate(sorted(sgf_paths)[:25]):
        game = sgf.parse_file(str(path))
        if len(game.moves) < 24 or game.size != 19:
            continue
        fractions = (.42, .64) if game_index < 3 else (.55,)
        for fraction in fractions:
            upto = max(12, min(len(game.moves) - 2, round(len(game.moves) * fraction)))
            board, states = goboard.replay(game, upto=upto)
            to_play = "B" if upto % 2 == 0 else "W"
            fingerprints = symmetry_fingerprints(states[-1], game.size, to_play)
            identity = fingerprints[0]
            if identity in seen:
                continue
            seen.add(identity)
            moves = [[move.color, "pass" if move.is_pass else goboard.gtp_name(move.coord, game.size)] for move in game.moves[:upto]]
            case_id = f"project-unseen-{path.stem}-{upto:03d}"
            target = ("actual", "best", "comparison")[len(rows) % 3]
            rows.append({
                "schemaVersion": SCHEMA,
                "caseId": case_id,
                "suite": "unseen_project_position",
                "target": target,
                "question": {
                    "actual": "实战最后一手的主要作用和取舍是什么？",
                    "best": "KataGo 首选在哪里？为什么它符合当前全局局面？",
                    "comparison": "只根据给定证据，比较实战最后一手与 KataGo 首选。",
                }[target],
                "source": {"kind": "project-bundled-public-game", "sgf": path.name, "moveNumber": upto},
                "position": {"boardSize": 19, "toPlay": to_play, "moves": moves},
                "positionHash": digest({"size": 19, "toPlay": to_play, "grid": states[-1].hex()}),
                "boardFingerprint": identity,
                "symmetryFingerprints": fingerprints,
                "trainingEligible": False,
                "sealed": False,
            })
    if len(rows) != 28:
        raise ValueError(f"expected exactly 28 positions, got {len(rows)}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sgf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = build(list(args.sgf_dir.glob("*.sgf")))
    queries = [{
        "id": row["caseId"], "moves": row["position"]["moves"], "rules": "chinese",
        "komi": 7.5, "boardXSize": 19, "boardYSize": 19,
        "analyzeTurns": [len(row["position"]["moves"])], "maxVisits": 128,
        "analysisPVLen": 12,
    } for row in rows]
    cases_path = args.output_dir / "cases.jsonl"
    queries_path = args.output_dir / "katago-queries.jsonl"
    atomic(cases_path, "".join(canonical(row) + "\n" for row in rows))
    atomic(queries_path, "".join(canonical(row) + "\n" for row in queries))
    manifest = {
        "schemaVersion": "yijian-unseen-position-eval-manifest-v1",
        "passed": True,
        "cases": 28,
        "visitsPerPosition": 128,
        "trainingEligible": False,
        "casesSha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "queriesSha256": hashlib.sha256(queries_path.read_bytes()).hexdigest(),
        "uniqueSymmetryFingerprints": len({fingerprint for row in rows for fingerprint in row["symmetryFingerprints"]}),
    }
    atomic(args.output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
