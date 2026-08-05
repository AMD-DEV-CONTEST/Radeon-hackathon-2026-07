"""
fleet.cli -- operator entrypoint for the node side.
===================================================
    python -m fleet.cli keygen --out-dir secrets/         # generate node identity
    python -m fleet.cli ingest shard1.sealed.json ...     # open + re-verify + admit

The node private key is read from the env var DETERMINEX_FLEET_NODE_PRIVKEY (never a
CLI argument, so it can't land in shell history / process listings).

Re-verification of untrusted contributions runs through intake.hardened_runner
(env-scrubbed, NETWORK DENIED, workspace-bounded) by default. For maximum assurance
against hostile contributions, run this whole command inside a disposable VM/Docker.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from . import crypto  # noqa: E402
from .ingest_verify import IngestResult, ingest_shard  # noqa: E402
from .protocol import Shard  # noqa: E402

# language -> the command the oracle uses, run here under the hardened runner.
_SANDBOX_CMD = {
    "python": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
    "go": ["go", "test", "./..."],
    "rust": ["cargo", "test", "--quiet"],
    "typescript": ["npx", "--no-install", "jest", "--silent"],
    "javascript": ["npx", "--no-install", "jest", "--silent"],
}


def _hardened_verify(lang: str, workdir: Path) -> bool:
    from intake.hardened_runner import run as hrun

    cmd = _SANDBOX_CMD.get(lang.lower())
    if not cmd:
        # no sandboxed recipe -> fail closed (do NOT silently pass)
        return False
    res = hrun(
        cmd, workspace=workdir, cwd=workdir, timeout=120, allow_network=False, allow_docker=False
    )
    return getattr(res, "ok", False) or getattr(res, "returncode", 1) == 0


def cmd_keygen(a: argparse.Namespace) -> int:
    pub, priv = crypto.generate_node_keypair()
    kid = crypto.key_id(crypto.load_public(pub))
    if a.out_dir:
        d = Path(a.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "node_public.txt").write_text(pub + "\n", encoding="utf-8")
        priv_path = d / "node_private.txt"
        priv_path.write_text(priv + "\n", encoding="utf-8")
        try:
            os.chmod(priv_path, 0o600)
        except OSError:
            pass
        print(f"node key_id: {kid}")
        print(f"PUBLIC  -> {d / 'node_public.txt'} (publish this; ships in the client)")
        print(f"PRIVATE -> {priv_path} (KEEP ON NODE ONLY; gitignored; never commit)")
        print(f'\nSet on the node:  export DETERMINEX_FLEET_NODE_PRIVKEY="$(cat {priv_path})"')
    else:
        print(f"# node key_id: {kid}")
        print(f"PUBLIC={pub}")
        print(f"PRIVATE={priv}   # store securely; do not commit")
    return 0


def cmd_ingest(a: argparse.Namespace) -> int:
    priv = os.environ.get("DETERMINEX_FLEET_NODE_PRIVKEY", "").strip()
    if not priv:
        print("ERROR: set DETERMINEX_FLEET_NODE_PRIVKEY (node private key).", file=sys.stderr)
        return 2
    corpus = Path(a.corpus)
    if a.unsafe_no_sandbox:
        sandbox = None
        allow_unsandboxed = True
        print("WARNING: --unsafe-no-sandbox: running untrusted code WITHOUT isolation.")
    else:
        sandbox = _hardened_verify
        allow_unsandboxed = False

    total = IngestResult(admitted=[], dropped={}, duplicates=[])
    for shard_path in a.shards:
        env = json.loads(Path(shard_path).read_text(encoding="utf-8"))
        shard = Shard.from_dict(crypto.open_json(priv, env))
        print(f"\n[{shard_path}] {shard.summary()} handle={shard.contributor_handle}")
        res = ingest_shard(
            shard, corpus, sandbox=sandbox, allow_unsandboxed=allow_unsandboxed, apply=a.apply
        )
        print(f"  {res.summary()}")
        for iid, reason in res.dropped.items():
            print(f"  drop {iid[:12]}: {reason}")
        total.admitted += res.admitted
        total.dropped.update(res.dropped)
        total.duplicates += res.duplicates

    print(
        f"\nTOTAL: {total.summary()}  -> {corpus} "
        f"({'WRITTEN' if a.apply else 'dry-run, not written'})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleet.cli", description="Determinex fleet node CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    kg = sub.add_parser("keygen", help="generate a node keypair")
    kg.add_argument("--out-dir", default=None)
    kg.set_defaults(fn=cmd_keygen)

    ig = sub.add_parser("ingest", help="open + re-verify + admit sealed shards")
    ig.add_argument("shards", nargs="+")
    ig.add_argument("--corpus", default="corpus/programbench/training_corpus/fleet_corpus.jsonl")
    ig.add_argument("--apply", action="store_true", help="write admitted pairs (default dry-run)")
    ig.add_argument(
        "--unsafe-no-sandbox",
        action="store_true",
        help="DANGEROUS: skip isolation (only for trusted local fixtures)",
    )
    ig.set_defaults(fn=cmd_ingest)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
