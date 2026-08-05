"""
fleet.ingest_verify -- THE KEYSTONE. Re-prove every contribution before it trains.
==================================================================================
Runs on the node (Hetzner, private). Opens a sealed shard, and for each item:

  1. Reconstruct the workdir from `item.files`.
  2. Re-verify it against the SAME deterministic oracle that built the corpus
     (`get_oracle(lang).verify(workdir)`).
  3. Admit the training pair to the master corpus ONLY if it PASSes; dedup by id.
  4. Drop (with a reason) anything that fails, errors, or has no available oracle.

Contributed data is NEVER trusted. A poisoned/garbage contribution cannot compile
or pass tests, so it is dropped -- it can never become training data. This is what
makes crowdsourced corpus growth safe.

SECURITY (non-negotiable): contributed code is UNTRUSTED. Re-verification executes
arbitrary build scripts / test code, so it MUST run sandboxed (Docker or
intake.hardened_runner). This module FAILS CLOSED: without a sandbox runner it
refuses to verify, unless the caller explicitly opts into `allow_unsandboxed=True`
(only safe for our own trusted test fixtures, never for real contributions).
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from determinex_oracle import OracleUnavailable, get_oracle  # noqa: E402

from .protocol import ContributionItem, Shard  # noqa: E402

# A sandbox runner takes (lang, workdir) and returns True iff the oracle PASSed
# *inside isolation*. Production callers pass a Docker / hardened-runner-backed one.
SandboxVerify = Callable[[str, Path], bool]


@dataclass
class IngestResult:
    admitted: list[str]  # item ids accepted into the corpus
    dropped: dict[str, str]  # item id -> reason
    duplicates: list[str]  # item ids already present

    def summary(self) -> str:
        return (
            f"admitted={len(self.admitted)} dropped={len(self.dropped)} dup={len(self.duplicates)}"
        )


def _write_workdir(files: dict[str, str], root: Path) -> None:
    for rel, content in files.items():
        # defense-in-depth: keep writes inside root (no traversal/absolute escape)
        p = (root / rel).resolve()
        if not str(p).startswith(str(root.resolve())):
            raise ValueError(f"path escapes workdir: {rel!r}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _local_oracle_verify(lang: str, workdir: Path) -> bool:
    """UNSAFE for untrusted input -- runs the oracle on the host with no isolation.
    Only for our own trusted test fixtures. Real ingest passes a sandbox runner."""
    try:
        return bool(get_oracle(lang).verify(workdir).passed)
    except OracleUnavailable:
        raise
    except Exception:
        return False


def verify_item(
    item: ContributionItem,
    sandbox: SandboxVerify | None = None,
    *,
    allow_unsandboxed: bool = False,
) -> tuple[bool, str]:
    """Return (passed, reason). Fails CLOSED if no sandbox and not explicitly allowed."""
    runner = sandbox
    if runner is None:
        if not allow_unsandboxed:
            return False, "refused: untrusted code requires a sandbox runner"
        runner = _local_oracle_verify
    with tempfile.TemporaryDirectory(prefix="fleet_verify_") as td:
        root = Path(td)
        try:
            _write_workdir(item.files, root)
        except Exception as e:
            return False, f"bad workdir: {e}"
        try:
            ok = runner(item.lang, root)
        except OracleUnavailable as e:
            return False, f"no oracle for {item.lang}: {e}"
        except Exception as e:
            return False, f"verify error: {e}"
    return (True, "oracle PASS") if ok else (False, "oracle FAIL (did not re-verify)")


def _load_existing_ids(corpus_path: Path) -> set[str]:
    ids: set[str] = set()
    if corpus_path.exists():
        for line in corpus_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                fid = (rec.get("metadata") or {}).get("fleet_item_id")
                if fid:
                    ids.add(fid)
            except Exception:
                continue
    return ids


def ingest_shard(
    shard: Shard,
    corpus_path: Path,
    sandbox: SandboxVerify | None = None,
    *,
    allow_unsandboxed: bool = False,
    apply: bool = False,
) -> IngestResult:
    """Re-verify every item; append admitted pairs to `corpus_path` (if apply=True)."""
    existing = _load_existing_ids(corpus_path)
    admitted: list[str] = []
    dropped: dict[str, str] = {}
    duplicates: list[str] = []
    to_write: list[dict[str, Any]] = []

    for item in shard.items:
        if item.id in existing:
            duplicates.append(item.id)
            continue
        passed, reason = verify_item(item, sandbox, allow_unsandboxed=allow_unsandboxed)
        if not passed:
            dropped[item.id] = reason
            continue
        rec = dict(item.pair)
        meta = dict(rec.get("metadata") or {})
        meta["fleet_item_id"] = item.id
        meta["fleet_origin"] = item.origin
        meta["fleet_reverified"] = True
        rec["metadata"] = meta
        to_write.append(rec)
        admitted.append(item.id)
        existing.add(item.id)

    if apply and to_write:
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        with corpus_path.open("a", encoding="utf-8") as fh:
            for rec in to_write:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return IngestResult(admitted=admitted, dropped=dropped, duplicates=duplicates)
