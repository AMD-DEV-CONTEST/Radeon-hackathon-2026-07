#!/usr/bin/env python3
"""Validate a frozen campaign and optionally print its fingerprint."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parcel_sorter.campaign import campaign_fingerprint, load_campaign  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a one-Radeon experiment campaign")
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    payload = load_campaign(args.campaign)
    print(f"campaign_id={payload['metadata']['campaign_id']}")
    print(f"fingerprint={campaign_fingerprint(payload)}")
    print(f"evaluation_episodes={len(payload['evaluation']['episode_ids'])}")
    print(f"experiments={len(payload['experiments'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
