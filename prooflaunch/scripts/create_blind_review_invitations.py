#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create five private, slot-bound blind-review invitations."
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / ".prooflaunch-secrets/blind-review-invitations.json"),
    )
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing invitation file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)
    tokens = {str(slot): secrets.token_urlsafe(32) for slot in range(1, 6)}
    atomic_write_text(
        output,
        json.dumps(tokens, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    output.chmod(0o600)
    fingerprints = {
        slot: hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        for slot, token in tokens.items()
    }
    print(f"Created five private reviewer invitations: {output}")
    print("Token fingerprints (tokens are not echoed):")
    for slot, fingerprint in fingerprints.items():
        print(f"  slot {slot}: sha256:{fingerprint}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
