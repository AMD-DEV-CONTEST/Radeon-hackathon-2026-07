#!/usr/bin/env python3
"""Who started watching, starring, forking, or following? Diff against last run.

GitHub notifies you about issues and PRs. It does not notify you when someone starts
WATCHING a repository, stars it, forks it, or follows you -- and during a competition
those are the signals that matter, because they tell you who is paying attention before
they do anything visible.

There is no event API for this either: GitHub stopped emitting FollowEvent to public
timelines, so a follow cannot be timestamped after the fact. The only reliable method is
to snapshot the lists and diff them, which means the FIRST run establishes a baseline and
sees nothing. That is stated rather than hidden, because a monitoring tool that reports
"no changes" on its first run is indistinguishable from one that is broken.

    python scripts/dev/watch_alert.py                    # diff against the last snapshot
    python scripts/dev/watch_alert.py --json             # machine-readable, for a scheduler
    python scripts/dev/watch_alert.py --repos a/b c/d    # override the watched set
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent.parent / ".determinex" / "watch_alert.json"
USER = "DarthCeltic"
REPOS = ["DarthCeltic/Determinex"]


def gh(path: str) -> list:
    """One paged GitHub API call. Returns [] on any failure -- a monitor must not crash."""
    try:
        r = subprocess.run(
            ["gh", "api", f"{path}?per_page=100", "--jq", ".[].login"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return [x for x in r.stdout.split() if x]
    except Exception:
        return []


def collect(repos: list[str]) -> dict[str, list[str]]:
    snap = {"followers": gh(f"users/{USER}/followers")}
    for repo in repos:
        snap[f"{repo}::stars"] = gh(f"repos/{repo}/stargazers")
        snap[f"{repo}::watchers"] = gh(f"repos/{repo}/subscribers")
        snap[f"{repo}::forks"] = [
            x
            for x in subprocess.run(
                ["gh", "api", f"repos/{repo}/forks?per_page=100", "--jq", ".[].owner.login"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            ).stdout.split()
            if x
        ]
    return snap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of prose")
    ap.add_argument("--repos", nargs="*", default=REPOS)
    args = ap.parse_args()

    now = collect(args.repos)
    prev = {}
    first_run = not STATE.is_file()
    if not first_run:
        try:
            prev = json.loads(STATE.read_text(encoding="utf-8")).get("snapshot", {})
        except Exception:
            prev, first_run = {}, True

    new: dict[str, list[str]] = {}
    gone: dict[str, list[str]] = {}
    for key, names in now.items():
        before = set(prev.get(key, []))
        added = [n for n in names if n not in before]
        removed = [n for n in before if n not in names]
        if added:
            new[key] = added
        if removed:
            gone[key] = removed

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps({"checked_at": datetime.now(UTC).isoformat(), "snapshot": now}, indent=2),
        encoding="utf-8",
    )

    if args.json:
        print(
            json.dumps(
                {
                    "first_run": first_run,
                    "new": new,
                    "gone": gone,
                    "totals": {k: len(v) for k, v in now.items()},
                },
                indent=2,
            )
        )
        return 0

    if first_run:
        print("BASELINE ESTABLISHED (first run sees nothing by construction):")
        for k, v in now.items():
            print(f"  {k:<44} {len(v)}")
        print("\n  Run again later to see changes.")
        return 0

    if not new and not gone:
        print(
            "no change since last check.  "
            + "  ".join(f"{k.split('::')[-1]}={len(v)}" for k, v in now.items())
        )
        return 0

    for key, names in new.items():
        print(f"NEW {key}:")
        for n in names:
            print(f"  + {n}   https://github.com/{n}")
    for key, names in gone.items():
        print(f"LOST {key}:")
        for n in names:
            print(f"  - {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
