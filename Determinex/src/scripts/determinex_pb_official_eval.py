#!/usr/bin/env python3
"""
determinex_pb_official_eval.py -- score a REIMPLEMENTATION under the OFFICIAL v1.2.2 harness
========================================================================================
Gate 2. Takes a from-scratch reimplementation `main.py`, packages it as a submission
(main.py + a compile.sh that makes ./executable a no-internet wrapper to `python3 main.py`),
stages it in the ProgramBench layout, and runs the OFFICIAL eval (defaults to the
task_cleanroom_v6 image with build-internet blocked). Then computes the official metric
(for_branches + without_ignored; solved iff n_resolved==len). This is the real score --
our local observe-oracle is only a proxy until this agrees.

Usage:
  python scripts/determinex_pb_official_eval.py <slug> <main.py> [--image-tag task_cleanroom_v6]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

PB = Path("T:/Dev/ProgramBench")
TASKS = PB / "src" / "programbench" / "data" / "tasks"
STAGING = Path("T:/determinex-programbench")

_COMPILE_SH = """#!/bin/sh
# No-internet wrapper: the reimplementation is pure Python (python3 is in the image for the
# test harness). Build = make ./executable call our main.py. No downloads.
cd "$(dirname "$0")"
cat > executable <<'WRAP'
#!/bin/sh
exec python3 "$(cd "$(dirname "$0")" && pwd)/main.py" "$@"
WRAP
chmod +x executable
"""

# DETERMINEX RULE: native submissions. Per-language compile.sh that builds ./executable from the
# native source -- NO internet (stdlib only). The task cleanroom image ships the tool's native
# toolchain (it was built to compile the original).
_NATIVE_COMPILE_SH = {
    "go": """#!/bin/sh
cd "$(dirname "$0")"
export GO111MODULE=on GOFLAGS=-mod=mod GOPROXY=off
go mod init m 2>/dev/null || true
go build -o executable .
""",
    "rust": """#!/bin/sh
cd "$(dirname "$0")"
rustc -O -o executable main.rs
""",
    "c": """#!/bin/sh
cd "$(dirname "$0")"
{ command -v cc >/dev/null && cc -O2 -o executable main.c; } || gcc -O2 -o executable main.c
""",
    "cpp": """#!/bin/sh
cd "$(dirname "$0")"
{ command -v c++ >/dev/null && c++ -O2 -std=c++17 -o executable main.cpp; } || g++ -O2 -std=c++17 -o executable main.cpp
""",
    "haskell": """#!/bin/sh
cd "$(dirname "$0")"
ghc -O2 -o executable main.hs
""",
}
_SRC_NAME = {
    "python": "main.py",
    "go": "main.go",
    "rust": "main.rs",
    "c": "main.c",
    "cpp": "main.cpp",
    "haskell": "main.hs",
}


def package(slug: str, main_py: Path, lang: str = "python") -> Path:
    out = Path("C:/tmp") / f"reimpl_sub_{slug}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    srcname = _SRC_NAME.get(lang, "main.py")
    compile_sh = _COMPILE_SH if lang == "python" else _NATIVE_COMPILE_SH[lang]
    with tarfile.open(out, "w:gz") as tf:
        data = main_py.read_bytes()
        ti = tarfile.TarInfo(srcname)
        ti.size = len(data)
        ti.mode = 0o644
        tf.addfile(ti, __import__("io").BytesIO(data))
        cs = compile_sh.encode()
        ti = tarfile.TarInfo("compile.sh")
        ti.size = len(cs)
        ti.mode = 0o755
        tf.addfile(ti, __import__("io").BytesIO(cs))
    return out


def official_score(eval_json: Path, slug: str) -> dict:
    inst = json.loads((TASKS / slug / "tests.json").read_text(encoding="utf-8"))
    er = json.loads(eval_json.read_text(encoding="utf-8", errors="replace"))
    tr = er.get("test_results") or []
    active = {n for n, i in (inst.get("branches") or {}).items() if not i.get("ignored")}
    ign = set()
    for b, i in (inst.get("branches") or {}).items():
        for t in i.get("ignored_tests") or []:
            ign.add(f"{b}/{t['name']}")

    def full(t):
        return f"{t['branch']}/{t['name']}" if t.get("branch") else t["name"]

    off = [t for t in tr if t["branch"] in active and full(t) not in ign]
    npass = sum(1 for t in off if t["status"] == "passed")
    return {
        "official_passed": npass,
        "official_total": len(off),
        "solved": (npass == len(off) and len(off) > 0),
        "raw_total": len(tr),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("main_py", type=Path)
    ap.add_argument("--image-tag", default="task_cleanroom_v6")
    ap.add_argument(
        "--lang", default="python", help="DETERMINEX native rule: go/rust/c/cpp/haskell"
    )
    args = ap.parse_args()

    author = args.slug.split("__")[0]
    tar = package(args.slug, args.main_py, args.lang)
    stage = STAGING / f"official_{args.slug}_{int(time.time())}"
    (stage / args.slug).mkdir(parents=True, exist_ok=True)
    shutil.copy2(tar, stage / args.slug / "submission.tar.gz")

    # Purge the cached compiled image so the CHANGED reimpl candidate actually rebuilds. Without
    # this the harness reuses the stale programbench-compiled/<slug>:<image_tag> build -> the reimpl
    # loop scores a PREVIOUS candidate's binary (the same stale-cache bug the eval path had).
    subprocess.run(
        ["docker", "rmi", "-f", f"programbench-compiled/{args.slug}:{args.image_tag}"],
        capture_output=True,
        timeout=60,
    )

    cmd = [
        "uv",
        "run",
        "programbench",
        "eval",
        str(stage),
        "--filter",
        author,
        "--force",
        "--image-tag",
        args.image_tag,
    ]
    print(f"[official] {' '.join(cmd)}")
    # Use LOCAL test blobs (avoids HF snapshot_download, which PermissionErrors on this box).
    blob_dir = os.environ.get(
        "PROGRAMBENCH_BLOB_DIR", "T:/determinex-programbench/_hf_tests_direct"
    )
    env = {**os.environ, "PYTHONUTF8": "1", "PROGRAMBENCH_BLOB_DIR": blob_dir}
    r = subprocess.run(cmd, cwd=str(PB), env=env, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        print("STDERR:", (r.stderr or "")[:800])
    ejs = list(stage.rglob("*.eval.json"))
    if not ejs:
        print("NO eval.json produced. stdout tail:", (r.stdout or "")[-800:])
        return 1
    sc = official_score(ejs[0], args.slug)
    print(f"\n=== OFFICIAL {args.slug} (image {args.image_tag}) ===")
    print(
        f"OFFICIAL: {sc['official_passed']}/{sc['official_total']}  "
        f"solved={sc['solved']}  (raw {sc['raw_total']})"
    )
    shutil.copy2(ejs[0], Path("C:/tmp") / f"official_{args.slug}.eval.json")
    # LEARN: corpus records the official score; LOCKS a verified skill on a genuine pass.
    try:
        import sys as _s

        _s.path.insert(0, str(Path(__file__).resolve().parent))
        import determinex_reimpl_corpus as CORPUS

        short = args.slug.split("__")[-1].split(".")[0]
        rec = CORPUS.record_run(
            short,
            best_official=sc["official_passed"],
            official_total=sc["official_total"],
            candidate_path=str(args.main_py),
        )
        if rec.get("verified_skill"):
            print(
                f"[corpus] *** VERIFIED SKILL LOCKED: {short} (official {sc['official_passed']}/{sc['official_total']}) ***"
            )
        else:
            print(
                f"[corpus] recorded official {sc['official_passed']}/{sc['official_total']} for {short} "
                f"(best={rec.get('best_official')})"
            )
    except Exception as e:
        print(f"[corpus] record skipped: {e}")
    shutil.rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
