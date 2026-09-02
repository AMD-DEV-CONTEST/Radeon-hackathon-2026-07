#!/usr/bin/env python3
"""Freshen submission.tar.gz files on Hetzner.

For each tool with a per_tool_overrides/compile.sh, this script:
  1. Checks if the Hetzner submission.tar.gz has a stale compile.sh (different from local)
  2. If stale: extracts the tarball, replaces compile.sh with current local version,
     repacks with current timestamps (not epoch 0), and uploads.

This prevents the 'stale tarball' problem where per_tool_overrides compile.sh is
updated locally but Hetzner still runs the old version.

Usage:
  python scripts/pb_freshen_tarball.py [--slug SLUG] [--run-dir HETZNER_DIR] [--dry-run]

  SLUG: specific tool slug (e.g. sigoden__argc.04a08f1). Omit to process all tools.
  HETZNER_DIR: remote path on Hetzner (default: /root/citadel-programbench)
  --dry-run: show what would be done without making changes

Requirements:
  - SSH key at ~/.ssh/id_citadel
  - Hetzner host: root@5.78.192.163
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

# Windows consoles default to cp1252 stdout, which crashes on the status arrow (U+2192)
# and any other non-latin-1 glyph. Force UTF-8 so the script's own prints never abort it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

HETZNER_HOST = "root@5.78.192.163"
SSH_KEY = str(Path.home() / ".ssh" / "id_citadel")
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-i", SSH_KEY]

# Root of the per_tool_overrides on local machine
LOCAL_OVERRIDES = Path(__file__).parent.parent / "corpus" / "programbench" / "per_tool_overrides"


def ssh_run(cmd: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["ssh"] + SSH_OPTS + [HETZNER_HOST, cmd], capture_output=True, text=True, timeout=60
    )
    return result.returncode, result.stdout, result.stderr


def scp_get(remote_path: str, local_path: str) -> bool:
    result = subprocess.run(
        ["scp"] + SSH_OPTS + [f"{HETZNER_HOST}:{remote_path}", local_path],
        capture_output=True,
        timeout=120,
    )
    return result.returncode == 0


def scp_put(local_path: str, remote_path: str) -> bool:
    result = subprocess.run(
        ["scp"] + SSH_OPTS + [local_path, f"{HETZNER_HOST}:{remote_path}"],
        capture_output=True,
        timeout=120,
    )
    return result.returncode == 0


def get_compile_sh_from_tarball(tarball_bytes: bytes) -> bytes | None:
    """Extract compile.sh content from a tarball."""
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tf:
            for member in tf.getmembers():
                if member.name in ("./compile.sh", "compile.sh"):
                    f = tf.extractfile(member)
                    if f:
                        return f.read()
    except Exception:
        pass
    return None


def rebuild_tarball_with_new_compile_sh(
    original_tarball_bytes: bytes,
    new_compile_sh: bytes,
) -> bytes:
    """Replace compile.sh in a tarball, update all mtimes to now."""
    now = int(time.time())
    output = io.BytesIO()

    with (
        tarfile.open(fileobj=io.BytesIO(original_tarball_bytes), mode="r:gz") as src_tf,
        tarfile.open(fileobj=output, mode="w:gz") as dst_tf,
    ):
        members = src_tf.getmembers()
        for member in members:
            if member.name in ("./compile.sh", "compile.sh"):
                # Replace with new version
                content = new_compile_sh.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                info = tarfile.TarInfo(name=member.name)
                info.size = len(content)
                info.mtime = now
                info.mode = 0o755
                dst_tf.addfile(info, io.BytesIO(content))
            else:
                f = src_tf.extractfile(member)
                if f is None:
                    # Directory or symlink
                    member.mtime = now
                    dst_tf.addfile(member)
                else:
                    content = f.read()
                    member.mtime = now
                    # Ensure execute bit on binaries
                    if not member.name.endswith((".toml", ".lock", ".md", ".txt")):
                        if member.name.endswith(".sh") or member.name in ("executable",):
                            member.mode = 0o755
                    dst_tf.addfile(member, io.BytesIO(content))

    return output.getvalue()


def find_hetzner_submission_paths(
    hetzner_base: str,
    slug: str | None,
) -> list[tuple[str, str]]:
    """Return list of (hetzner_tarball_path, instance_id) for tools on Hetzner."""
    if slug:
        # Find all dirs matching this slug on Hetzner
        rc, stdout, _ = ssh_run(
            f"find {hetzner_base} -name submission.tar.gz -path '*{slug}*' 2>/dev/null"
        )
    else:
        rc, stdout, _ = ssh_run(
            f"find {hetzner_base} -name submission.tar.gz 2>/dev/null | head -500"
        )

    paths = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parent = line[: line.rfind("/")]
        instance_id = parent.split("/")[-1]
        paths.append((line, instance_id))
    return paths


def local_compile_sh_for(slug: str) -> bytes | None:
    """Read local compile.sh for a tool slug (try exact match then prefix match)."""
    # Direct match
    p = LOCAL_OVERRIDES / slug / "compile.sh"
    if p.exists():
        return p.read_bytes()

    # Prefix match (slug without hash suffix)
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    for d in LOCAL_OVERRIDES.iterdir():
        if d.name.startswith(base) and (d / "compile.sh").exists():
            return (d / "compile.sh").read_bytes()

    return None


def process_tool(
    tarball_path: str,
    instance_id: str,
    dry_run: bool,
) -> str:
    """Check and optionally freshen one tool. Returns status string."""
    # Find matching local compile.sh
    local_sh = local_compile_sh_for(instance_id)
    if local_sh is None:
        return "NO_LOCAL_COMPILE_SH"

    local_sh_clean = local_sh.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    # Fetch the remote tarball
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if not scp_get(tarball_path, tmp_path):
            return "SCP_FETCH_FAILED"

        remote_bytes = Path(tmp_path).read_bytes()
        remote_sh = get_compile_sh_from_tarball(remote_bytes)
        if remote_sh is None:
            return "NO_COMPILE_SH_IN_TARBALL"

        remote_sh_clean = remote_sh.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

        if remote_sh_clean == local_sh_clean:
            return "UP_TO_DATE"

        if dry_run:
            return "STALE (would rebuild)"

        # Rebuild tarball
        new_bytes = rebuild_tarball_with_new_compile_sh(remote_bytes, local_sh_clean)

        # Write new tarball locally
        Path(tmp_path).write_bytes(new_bytes)

        # Upload
        if not scp_put(tmp_path, tarball_path):
            return "SCP_UPLOAD_FAILED"

        return f"REFRESHED ({len(remote_bytes)}→{len(new_bytes)} bytes)"

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--slug", help="Specific tool slug to freshen")
    ap.add_argument(
        "--run-dir",
        default="/root/citadel-programbench",
        help="Hetzner base directory (default: /root/citadel-programbench)",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Show what would change without uploading"
    )
    args = ap.parse_args()

    print(f"[freshen] scanning {args.run_dir} on {HETZNER_HOST}")
    if args.dry_run:
        print("[freshen] DRY RUN — no uploads will be made")

    paths = find_hetzner_submission_paths(args.run_dir, args.slug)
    print(f"[freshen] found {len(paths)} submission tarballs")

    counts = {"UP_TO_DATE": 0, "REFRESHED": 0, "STALE": 0, "NO_LOCAL_COMPILE_SH": 0, "OTHER": 0}

    for tarball_path, instance_id in paths:
        status = process_tool(tarball_path, instance_id, args.dry_run)
        tag = (
            "REFRESHED"
            if status.startswith("REFRESHED")
            else "STALE"
            if status.startswith("STALE")
            else status
            if status in counts
            else "OTHER"
        )
        counts[tag] = counts.get(tag, 0) + 1
        if status != "UP_TO_DATE" and status != "NO_LOCAL_COMPILE_SH":
            print(f"  {instance_id}: {status}")

    print(f"\n[freshen] summary: {counts}")


if __name__ == "__main__":
    main()
