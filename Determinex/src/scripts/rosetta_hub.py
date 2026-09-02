"""Publish and fetch the Rosetta projection shards via HuggingFace.

WHY THIS EXISTS
---------------
`rosetta_v1.pt` is 1.68 GB and `.gitignore` excludes `*.pt` -- correctly, it is a
model weight. So the latent bridge's weights could not travel with the repo, and a
rename silently orphaned them (see determinex_rosetta.LEGACY_ROSETTA_DIR). An
installer cannot carry 1.68 GB either.

The `.npz` export solves the size problem (839 MB total, 92-134 MB per
architecture) and the torch problem. This module solves distribution: the shards
live in a HuggingFace repo, and the IDE fetches ONLY the architectures it needs.

DESIGN NOTES THAT MATTER
------------------------
* The `.pt` is never uploaded. It is 2x the bytes, needs torch to read, and nothing
  at runtime wants it. Only the exported shards and their manifest go up.
* The repo is PRIVATE by default. Making it public is an explicit flag, because
  "publish weights" is not a decision a helper script should make quietly.
* Downloads are verified against the manifest's per-shard SHA256 by
  `NumpyRosettaStone`, so a truncated fetch fails loudly instead of projecting
  through half a weight matrix.
* The token comes from the environment (HF_TOKEN / HUGGINGFACE_API_KEY), never an
  argument, so it cannot end up in shell history or a process list.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# The HF namespace is the account username, which is darthceltic85 -- NOT the
# GitHub handle DarthCeltic. Getting this wrong creates a repo under a namespace
# the token cannot write to and fails at upload time.
REPO_ID_DEFAULT = "darthceltic85/determinex-rosetta"
MANIFEST_NAME = "rosetta_npz_manifest.json"


def _token() -> str:
    for name in ("HF_TOKEN", "HUGGINGFACE_API_KEY", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        tok = os.environ.get(name, "").strip()
        if tok:
            return tok
    # Fall back to the repo .env, loaded the same way the provider layer does.
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in ("HF_TOKEN", "HUGGINGFACE_API_KEY", "HUGGINGFACE_TOKEN"):
                v = v.strip().strip('"').strip("'")
                if v:
                    return v
    raise SystemExit(
        "No HuggingFace token found. Set HF_TOKEN in the environment or .env "
        "(the provider layer accepts HF_TOKEN / HUGGINGFACE_API_KEY / HUGGINGFACE_TOKEN)."
    )


def push(npz_dir: Path, repo_id: str, public: bool = False) -> int:
    """Upload the manifest + every shard it lists. Never the .pt."""
    from huggingface_hub import HfApi

    manifest_path = npz_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise SystemExit(
            f"No {MANIFEST_NAME} in {npz_dir}. Export first:\n"
            "  python scripts/determinex_rosetta_npz.py export <ckpt> --out <dir>"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    shards = manifest.get("shards") or {}
    if not shards:
        raise SystemExit("The manifest lists no shards; refusing to publish nothing.")

    # Verify locally BEFORE uploading. Publishing a shard whose bytes do not match
    # its recorded hash would push a poison pill that every client then rejects.
    missing, bad = [], []
    for _arch, entry in shards.items():
        p = npz_dir / entry["file"]
        if not p.is_file():
            missing.append(entry["file"])
            continue
        import hashlib

        if hashlib.sha256(p.read_bytes()).hexdigest() != entry["sha256"]:
            bad.append(entry["file"])
    if missing or bad:
        raise SystemExit(f"Refusing to publish. missing={missing} checksum_mismatch={bad}")

    api = HfApi(token=_token())
    api.create_repo(repo_id=repo_id, repo_type="model", private=not public, exist_ok=True)
    print(f"repo {repo_id} ready (private={not public})")

    total = 0
    api.upload_file(
        path_or_fileobj=str(manifest_path),
        path_in_repo=MANIFEST_NAME,
        repo_id=repo_id,
        repo_type="model",
    )
    print(f"  uploaded {MANIFEST_NAME}")
    for _arch, entry in sorted(shards.items()):
        p = npz_dir / entry["file"]
        api.upload_file(
            path_or_fileobj=str(p),
            path_in_repo=entry["file"],
            repo_id=repo_id,
            repo_type="model",
        )
        total += entry["bytes"]
        print(f"  uploaded {entry['file']:34} {entry['bytes'] / 1_000_000:7.1f} MB")

    readme = _repo_readme(manifest, repo_id)
    api.upload_file(
        path_or_fileobj=readme.encode("utf-8"),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="model",
    )
    print(f"\n{len(shards)} shards, {total / 1_000_000:.1f} MB -> https://huggingface.co/{repo_id}")
    return 0


def _repo_readme(manifest: dict, repo_id: str) -> str:
    arches = ", ".join(sorted((manifest.get("shards") or {}).keys()))
    return f"""---
license: agpl-3.0
tags:
  - determinex
  - representation-alignment
---

# Determinex Rosetta Stone — projection shards

Torch-free projection weights for [Determinex](https://github.com/DarthCeltic/Determinex)'s
Rosetta Stone: MLP encoder/decoder pairs that map several model families' hidden
states into one shared {manifest.get("d_rosetta")}-dim space, so one model's
internal state can be projected into another's.

**Architectures**: {arches}

Each `.npz` holds one architecture's encoder and decoder as
`Linear -> GELU -> LayerNorm -> Linear`. Storage is
`{manifest.get("storage_dtype")}`; the forward pass runs in float32. No torch is
required to use them -- `scripts/determinex_rosetta_npz.py` runs them with numpy.

Download only the architectures you need (92-134 MB each) rather than the full
1.68 GB source checkpoint:

```python
from huggingface_hub import hf_hub_download
for f in ["{MANIFEST_NAME}", "rosetta_v1_qwen2_1b5.npz"]:
    hf_hub_download("{repo_id}", f, local_dir="~/.determinex/rosetta/npz")
```

Every shard's SHA256 is recorded in `{MANIFEST_NAME}` and checked on load, so a
truncated download fails instead of silently projecting through partial weights.

Provenance: exported from `{manifest.get("source_checkpoint")}`
(weights sha256 `{str(manifest.get("source_weights_sha256"))[:16]}...`,
anchor `{manifest.get("anchor")}`). Numpy inference is verified against torch to
better than 1e-05 relative on float32 weights.
"""


def pull(repo_id: str, out_dir: Path, arches: list[str] | None = None) -> int:
    """Fetch the manifest, then only the requested architectures."""
    from huggingface_hub import hf_hub_download

    out_dir.mkdir(parents=True, exist_ok=True)
    tok = _token()
    mp = hf_hub_download(
        repo_id, MANIFEST_NAME, repo_type="model", token=tok, local_dir=str(out_dir)
    )
    manifest = json.loads(Path(mp).read_text(encoding="utf-8"))
    shards = manifest.get("shards") or {}

    wanted = arches or list(shards.keys())
    unknown = [a for a in wanted if a not in shards]
    if unknown:
        raise SystemExit(f"Unknown architectures {unknown}. Available: {sorted(shards)}")

    got = 0
    for a in wanted:
        entry = shards[a]
        hf_hub_download(
            repo_id, entry["file"], repo_type="model", token=tok, local_dir=str(out_dir)
        )
        got += entry["bytes"]
        print(f"  {a:12} {entry['bytes'] / 1_000_000:7.1f} MB")
    print(f"\n{len(wanted)} shards, {got / 1_000_000:.1f} MB -> {out_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("push", help="Upload shards to HuggingFace (private by default)")
    p.add_argument("--npz", required=True)
    p.add_argument("--repo", default=REPO_ID_DEFAULT)
    p.add_argument(
        "--public",
        action="store_true",
        help="Publish publicly. Explicit on purpose -- the default is private.",
    )

    g = sub.add_parser("pull", help="Download shards (optionally only some arches)")
    g.add_argument("--repo", default=REPO_ID_DEFAULT)
    g.add_argument("--out", default=str(Path.home() / ".determinex" / "rosetta" / "npz"))
    g.add_argument("--arch", action="append", help="Repeatable; default is all")

    args = ap.parse_args()
    if args.cmd == "push":
        return push(Path(args.npz), args.repo, args.public)
    return pull(args.repo, Path(args.out), args.arch)


if __name__ == "__main__":
    sys.exit(main())
