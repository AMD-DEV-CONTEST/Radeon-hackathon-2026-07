#!/usr/bin/env python3
"""pb_provenance_verify.py -- the VERIFICATION arm of the build-provenance gate.

determinex_pb_provenance_guard FLAGS a locked submission that ships a prebuilt binary
(it could pass via that answer-key ELF instead of building from source -- the atlas
failure mode). This RESOLVES each flag: it removes the shipped binary and runs the
tool's own compile.sh in its REFERENCE task image, then asks the Crucible's own
from-source detector whether a real build happened.

  PASS  -> the lock builds from source; the shipped binary was dead weight (repack to
           drop it + record a from-source proof -> the flag clears legitimately).
  FAIL  -> the lock CANNOT build from source without the answer key (a fake lock, like
           atlas was) -> must be fixed (e.g. go-toolchain) or demoted.

Reuses determinex_crucible's _BUNDLED_MARKERS / _has_real_build_cmd (no reimplementation);
only the execution transport differs (Hetzner docker over SSH, since the :task images
live there). Build-only by default (fast); the question is provenance, not the score.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from determinex_crucible import _BUNDLED_MARKERS, resolve_base_image  # reuse

HETZNER_IP = os.environ.get("DETERMINEX_HETZNER_IP", "5.78.192.163")
SSH_KEY = str(Path.home() / ".ssh" / "id_citadel")
SSH = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no"]
SCP = ["scp", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no"]


def verify(slug: str, tarball: Path, timeout: int = 600) -> dict:
    image = resolve_base_image(slug)
    rd = f"/root/prov_verify/{slug}"
    host = f"root@{HETZNER_IP}"
    try:
        subprocess.run(
            SSH + [host, f"rm -rf {rd} && mkdir -p {rd}"],
            check=True,
            timeout=60,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            SCP + [str(tarball), f"{host}:{rd}/s.tar.gz"],
            check=True,
            timeout=300,
            capture_output=True,
            text=True,
        )
        # extract, REMOVE any shipped ELF (the answer key), run compile.sh in the task image,
        # capture build stderr + what `executable`/binary resolves to.
        inner = (
            "cd /w && tar xzf /src/s.tar.gz 2>/dev/null; "
            "for f in $(find . -maxdepth 2 -type f); do "
            '  if head -c4 "$f" 2>/dev/null | grep -q ELF && [ $(wc -c <"$f") -gt 2000000 ]; '
            '  then echo "REMOVED_ELF=$f"; rm -f "$f"; fi; done; '
            'sh compile.sh >/tmp/build.log 2>&1; echo "COMPILE_RC=$?"; '
            "echo ===BUILDLOG===; tail -25 /tmp/build.log"
        )
        cmd = SSH + [
            host,
            f"docker run --rm -v {rd}:/src programbench/{slug.replace('__', '_1776_')}:task "
            f"bash -c 'cp -r /src /w && {inner}'",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = p.stdout + "\n" + p.stderr
        subprocess.run(SSH + [host, f"rm -rf {rd}"], check=False, timeout=60, capture_output=True)
    except subprocess.TimeoutExpired:
        return {"slug": slug, "verdict": "TIMEOUT", "image": image}
    except Exception as e:
        return {"slug": slug, "verdict": "ERROR", "why": str(e)[:200], "image": image}

    rc_ok = "COMPILE_RC=0" in out
    low = out.lower()
    used_bundled = any(m in low for m in _BUNDLED_MARKERS)
    removed = [ln.split("=", 1)[1] for ln in out.splitlines() if ln.startswith("REMOVED_ELF=")]
    # PASS = compile.sh succeeded AND did not announce a bundled fallback (answer key was removed)
    verdict = "FROM_SOURCE" if (rc_ok and not used_bundled) else "FAKE_OR_BROKEN"
    res = {
        "slug": slug,
        "verdict": verdict,
        "compile_rc_ok": rc_ok,
        "used_bundled": used_bundled,
        "removed_elfs": removed,
        "log_tail": out[-700:] if verdict != "FROM_SOURCE" else "",
        "image": image,
    }
    if verdict == "FROM_SOURCE":  # record a proof so the guard clears this lock's binary flag
        try:
            import datetime as _dt

            import determinex_pb_provenance_guard as PG

            PG.record_proof(
                slug,
                {
                    "verified": _dt.datetime.now(_dt.UTC).isoformat(),
                    "removed_elfs": removed,
                    "method": "hetzner-from-source-build",
                },
            )
            res["proof_recorded"] = True
        except Exception as e:  # pragma: no cover
            res["proof_recorded"] = False
            res["proof_error"] = str(e)[:120]
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--tarball", required=True, type=Path)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args(argv)
    r = verify(a.slug, a.tarball, a.timeout)
    import json

    print(json.dumps(r, indent=2))
    return 0 if r.get("verdict") == "FROM_SOURCE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
