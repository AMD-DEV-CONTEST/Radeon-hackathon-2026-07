#!/usr/bin/env python3
"""pb_sync -- the single-source-of-truth discipline for ProgramBench per-tool code.

THE RULE (why this exists): the corpus is authoritative for SCORES, the git repo is
authoritative for CODE. The Hetzner box is a RUNNER, not a home. The htmlq 4098 build was lost
because its reimpl was edited only on the box and never committed -> the box was later overwritten
and the score became unreproducible. Never again:

  - AFTER editing a tool on the box:  pb_sync.py capture <tool>   (box -> repo, then commit)
  - BEFORE a run that needs canon:    pb_sync.py deploy <tool>    (repo -> box)
  - ANYTIME, to see the drift:        pb_sync.py audit            (box vs repo, all tools)

`capture` enforces commit-after-edit (the rule that prevents lost builds). `audit` is the
box<->repo reconciliation (uncommitted = lost-build risk; diverged = box drifted from canon).
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OVR_REL = "corpus/programbench/per_tool_overrides"
BOX = "root@5.78.192.163"
KEY = str(Path.home() / ".ssh" / "id_citadel")
BOX_ROOT = "/root/Citadel"

# Per-tool CODE = anything the build consumes. We track ALL source (not just *_reimpl.*: the
# walk/bat native builds were `reimpl.go`/`gron_claude.go` and the old glob missed them entirely).
# Denylist the rest: compiled binaries (no extension), eval artifacts, tarballs, logs, backups.
_SRC_EXT = {
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".cc",
    ".h",
    ".hpp",
    ".py",
    ".sh",
    ".txt",
    ".mod",
    ".sum",
    ".toml",
    ".md",
    ".rb",
    ".java",
}
_DENY_SUFFIX = (
    ".bak",
    ".regressed",
    ".json",
    ".xml",
    ".log",
    ".err",
    ".pyc",
    ".tar.gz",
    ".tgz",
    ".orig",
)


def _is_source(name: str) -> bool:
    """True if `name` is a build input we should track (not an artifact/binary)."""
    if name.endswith(_DENY_SUFFIX):
        return False
    ext = name[name.rfind(".") :] if "." in name else ""
    return ext in _SRC_EXT  # no-extension files are compiled binaries -> excluded


def _ssh(cmd: str) -> str:
    r = subprocess.run(["ssh", "-i", KEY, BOX, cmd], capture_output=True, text=True)
    return r.stdout


def _sha(b: bytes) -> str:
    # normalize line endings: the box files are often CRLF, repo HEAD is LF -- compare CONTENT,
    # not byte-for-byte, or every CRLF file false-reports as diverged.
    return hashlib.sha256(b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()[:16]


def _box_manifest() -> dict[str, str]:
    """rel-path -> content-sha16 for every per-tool SOURCE file on the box.

    Hashes line-ending-normalized content (tr -d '\\r') so CRLF/LF differences don't masquerade
    as drift. Uses a scp'd hasher script -- inline grep/hash over ssh dies on quoting."""
    import tempfile

    names = " -o ".join(f'-name "*{e}"' for e in sorted(_SRC_EXT))
    hasher = (
        "#!/bin/sh\n"
        'cd "$1" || exit 1\n'
        f"find . -maxdepth 2 -type f \\( {names} -o -name go.mod -o -name go.sum \\) "
        "| while IFS= read -r f; do\n"
        '  h=$(tr -d "\\r" < "$f" | sha256sum | cut -d" " -f1)\n'
        '  printf "%s %s\\n" "$h" "${f#./}"\n'
        "done\n"
    )
    tf = Path(tempfile.gettempdir()) / "_pbsync_hash.sh"
    tf.write_text(hasher, newline="\n")
    subprocess.run(["scp", "-i", KEY, str(tf), f"{BOX}:/tmp/_pbsync_hash.sh"], capture_output=True)
    out = _ssh(f"sh /tmp/_pbsync_hash.sh {BOX_ROOT}/{OVR_REL}")
    m = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and _is_source(parts[1].strip().rsplit("/", 1)[-1]):
            m[parts[1].strip()] = parts[0][:16]
    return m


def _repo_head_sha(rel: str) -> str | None:
    path = f"{OVR_REL}/{rel}"
    r = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{path}"], capture_output=True)
    return _sha(r.stdout) if r.returncode == 0 else None


def _is_gitignored(rel: str) -> bool:
    """A box-only file that the repo deliberately ignores (conftest.c autoconf temp, etc.)
    is NOT a lost-build risk -- it's excluded on purpose. Don't false-flag it."""
    r = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-q", f"{OVR_REL}/{rel}"], capture_output=True
    )
    return r.returncode == 0


def audit() -> int:
    box = _box_manifest()
    synced = diverged = uncommitted = ignored = 0
    div, unc = [], []
    for rel, bsha in sorted(box.items()):
        rsha = _repo_head_sha(rel)
        if rsha is None:
            if _is_gitignored(rel):
                ignored += 1
            else:
                uncommitted += 1
                unc.append(rel)
        elif rsha == bsha:
            synced += 1
        else:
            diverged += 1
            div.append(rel)
    print(f"pb_sync audit  ({len(box)} box per-tool source files)")
    print(f"  SYNCED:      {synced}")
    print(f"  DIVERGED:    {diverged}   (box drifted from canon repo)")
    print(f"  UNCOMMITTED: {uncommitted}   (BOX-ONLY -> lost-build risk; capture+commit now)")
    print(f"  ignored:     {ignored}   (gitignored on purpose -- not a risk)")
    for rel in unc[:30]:
        print(f"     LOST-RISK  {rel}")
    for rel in div[:30]:
        print(f"     diverged   {rel}")
    return 1 if uncommitted else 0


def _tool_files(tool: str) -> list[str]:
    out = _ssh(f"cd {BOX_ROOT} && ls {OVR_REL}/{tool}/ 2>/dev/null")
    return [f for f in out.split() if _is_source(f)]


def capture(tool: str) -> int:
    files = _tool_files(tool)
    if not files:
        print(f"no code files for {tool} on box")
        return 1
    for f in files:
        src = f"{BOX}:{BOX_ROOT}/{OVR_REL}/{tool}/{f}"
        dst = REPO / OVR_REL / tool / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["scp", "-i", KEY, src, str(dst)], check=False)
        subprocess.run(["git", "-C", str(REPO), "add", f"{OVR_REL}/{tool}/{f}"], check=False)
    print(f"captured {tool}: {files} -> repo (staged). Now COMMIT (commit-after-edit rule).")
    subprocess.run(
        ["git", "-C", str(REPO), "diff", "--cached", "--stat", f"{OVR_REL}/{tool}"], check=False
    )
    return 0


def deploy(tool: str) -> int:
    d = REPO / OVR_REL / tool
    if not d.is_dir():
        print(f"{tool} not in repo")
        return 1
    import tempfile

    for f in d.iterdir():
        if f.is_file() and _is_source(f.name):
            # Strip CR so the box always receives LF -- a CRLF compile.sh breaks dash (`set -e\r`)
            # even when the worktree is CRLF from autocrlf. Deploy normalizes regardless.
            data = f.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            tmp = Path(tempfile.gettempdir()) / f".pbsync_{f.name}"
            tmp.write_bytes(data)
            subprocess.run(
                ["scp", "-i", KEY, str(tmp), f"{BOX}:{BOX_ROOT}/{OVR_REL}/{tool}/{f.name}"],
                check=False,
            )
            tmp.unlink(missing_ok=True)
    print(f"deployed repo/{tool} -> box runner")
    return 0


def _passed(path: Path) -> int:
    """passed-count in an eval_report.json, or -1 if missing/unparseable."""
    if not path.exists():
        return -1
    try:
        import json
        from collections import Counter

        d = json.loads(path.read_text(encoding="utf-8"))
        return Counter(x.get("status") for x in (d.get("test_results") or [])).get("passed", 0)
    except Exception:
        return -1


def capture_scores() -> int:
    """Pull the box's eval RESULTS (every eval_report.json + autodrive_results.json) into the repo,
    keeping the BEST per tool -- more `passed` wins -- so a flaky/memory-starved box re-eval can't
    lose a good score and a worse box result can't regress the repo. pb_sync's code-capture EXCLUDES
    .json (scores), so WITHOUT this the box's near-locks are never committed: the lost-build failure,
    but for SCORES. One tar+scp (not 222 scps); git-adds the changed files (then COMMIT)."""
    import shutil
    import tarfile
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="pbscores_"))
    tar = tmp / "scores.tar.gz"
    _ssh(
        f"cd {BOX_ROOT} && tar czf /tmp/_pbscores.tar.gz {OVR_REL}/*/eval_report.json "
        f"corpus/programbench/autodrive_results.json corpus/programbench/build_knowledge.json 2>/dev/null"
    )
    subprocess.run(["scp", "-i", KEY, f"{BOX}:/tmp/_pbscores.tar.gz", str(tar)], check=False)
    _ssh("rm -f /tmp/_pbscores.tar.gz")
    if not tar.exists():
        print("capture-scores: no scores tar from box")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    with tarfile.open(tar, "r:gz") as t:
        t.extractall(tmp)
    captured, kept, total = [], 0, 0
    for boxf in sorted((tmp / OVR_REL).glob("*/eval_report.json")):
        total += 1
        slug = boxf.parent.name
        repof = REPO / OVR_REL / slug / "eval_report.json"
        bp, rp = _passed(boxf), _passed(repof)
        if bp > rp:  # box has a strictly BETTER eval -> capture it
            repof.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(boxf, repof)
            subprocess.run(
                ["git", "-C", str(REPO), "add", f"{OVR_REL}/{slug}/eval_report.json"], check=False
            )
            captured.append(f"{slug} {rp}->{bp}")
        else:
            kept += 1  # repo's >= box's -> keep repo (never regress the best)
    boxlog = tmp / "corpus/programbench/autodrive_results.json"
    if boxlog.exists():  # the run log: box is authoritative (its run history)
        shutil.copy2(boxlog, REPO / "corpus/programbench/autodrive_results.json")
        subprocess.run(
            ["git", "-C", str(REPO), "add", "corpus/programbench/autodrive_results.json"],
            check=False,
        )
    # FLYWHEEL durability: merge the box's LEARNED classes (distilled from its own verified solves)
    # into the repo's build_knowledge, UNION by key -- never touch the hand-curated class_patterns.
    boxkn = tmp / "corpus/programbench/build_knowledge.json"
    if boxkn.exists():
        try:
            import json as _j

            bkn = _j.loads(boxkn.read_text(encoding="utf-8"))
            rkn_path = REPO / "corpus/programbench/build_knowledge.json"
            rkn = _j.loads(rkn_path.read_text(encoding="utf-8"))
            box_lc = bkn.get("learned_classes", {}) if isinstance(bkn, dict) else {}
            rlc = rkn.setdefault("learned_classes", {})
            added = sum(1 for k in box_lc if k not in rlc)
            for k, v in box_lc.items():
                rlc.setdefault(k, v)
            if added:
                rkn_path.write_text(
                    _j.dumps(rkn, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                subprocess.run(
                    ["git", "-C", str(REPO), "add", "corpus/programbench/build_knowledge.json"],
                    check=False,
                )
                print(f"  + merged {added} flywheel-learned class(es) from box")
        except Exception as e:
            print(f"  learned-class merge skipped: {e}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(
        f"capture-scores: {len(captured)} better from box, {kept} repo kept, {total} tools scanned"
    )
    for c in captured[:50]:
        print(f"  + {c}")
    print("staged -> COMMIT now (commit-after rule).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit")
    c = sub.add_parser("capture")
    c.add_argument("tool")
    d = sub.add_parser("deploy")
    d.add_argument("tool")
    sub.add_parser("capture-scores")
    a = ap.parse_args()
    if a.cmd == "audit":
        return audit()
    if a.cmd == "capture":
        return capture(a.tool)
    if a.cmd == "deploy":
        return deploy(a.tool)
    if a.cmd == "capture-scores":
        return capture_scores()
    return 1


if __name__ == "__main__":
    sys.exit(main())
