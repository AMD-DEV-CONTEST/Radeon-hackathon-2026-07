#!/usr/bin/env python3
"""Export a portable ProgramBench native-eval shard for a remote worker.

The local workstation remains the source of truth for the board and gates.
This script only packages already-packed native candidate run roots so a
remote machine can run official ProgramBench evals and return eval JSON/logs.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from determinex_atomic_io import write_text_atomic as _write_text_atomic  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_QUEUE.json"
PB_STAGING_ROOT = Path(os.environ.get("DETERMINEX_PB_STAGING_ROOT", "T:/determinex-staging"))
SHARD_ROOT = PB_STAGING_ROOT / "hetzner_shards"
AUDIT = ROOT / "logs" / "programbench_factory" / "LANGUAGE_AUDIT.json"
RESERVATIONS = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_RESERVATIONS.json"
GUARD_SKIP_DIR = ROOT / "logs" / "programbench_factory"


def _split_csv_values(values: list[str]) -> set[str]:
    """Accept repeated flags and comma-separated shorthand."""
    out: set[str] = set()
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.add(part)
    return out


def _load_json_file(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json_atomic(path: Path, data: Any) -> None:
    _write_text_atomic(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _load_queue() -> list[dict[str, Any]]:
    if not QUEUE.is_file():
        raise SystemExit(f"{QUEUE} missing; run scripts/pb_native_eval_queue.py first")
    return _load_json_file(QUEUE, [])


def _audit_by_slug() -> dict[str, dict[str, Any]]:
    return {r.get("slug"): r for r in _load_json_file(AUDIT, []) if r.get("slug")}


def _write_reservations(rows: list[dict[str, Any]], shard_name: str) -> None:
    reservations = _load_json_file(RESERVATIONS, {})
    for r in rows:
        reservations[r["slug"]] = f"hetzner:{shard_name}"
        reservations[r["base_slug"]] = f"hetzner:{shard_name}"
    _write_json_atomic(RESERVATIONS, reservations)


def _base_slug(slug: str) -> str:
    return slug.rsplit(".", 1)[0] if "." in slug else slug


def _parse_run_root_specs(values: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"--run-root must be formatted as slug=path, got: {raw!r}")
        slug, path = raw.split("=", 1)
        slug = slug.strip()
        path = path.strip()
        if not slug or not path:
            raise SystemExit(f"--run-root must include both slug and path, got: {raw!r}")
        rows.append(
            {
                "slug": slug,
                "base_slug": _base_slug(slug),
                "run_root": path,
                "score": 0.0,
                "status": "explicit:run-root",
            }
        )
    return rows


def _native_lang(src: Path) -> str | None:
    if (src / "Cargo.toml").is_file() or any(src.glob("src/**/*.rs")):
        return "rust"
    if (src / "go.mod").is_file() or any(src.glob("*.go")) or any(src.glob("cmd/**/*.go")):
        return "go"
    if any(src.glob("*.cpp")) or any(src.glob("**/*.cpp")) or (src / "CMakeLists.txt").is_file():
        return "cpp"
    if any(src.glob("*.c")) or any(src.glob("**/*.c")):
        return "c"
    if (
        any(src.glob("*.cabal"))
        or (src / "stack.yaml").is_file()
        or (src / "cabal.project").is_file()
        or any(src.glob("**/*.hs"))
    ):
        return "haskell"
    if (
        (src / "pom.xml").is_file()
        or (src / "build.gradle").is_file()
        or (src / "project.clj").is_file()
        or any(src.glob("**/*.java"))
        or any(src.glob("**/*.clj"))
    ):
        return "java"
    return None


def _python_ok(src: Path, audit_row: dict[str, Any]) -> tuple[bool, str]:
    if audit_row.get("source_language") == "python" or audit_row.get("action") == "keep-python":
        return True, "python upstream"
    if audit_row.get("action") == "keep-thin":
        return True, "keep-thin: scaffold main.py, real impl in compile.sh"
    main_py = src / "main.py"
    if not main_py.is_file():
        return True, "no main.py"
    text = main_py.read_text(encoding="utf-8", errors="replace")
    lines = [
        ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    thin = len(lines) <= 8 and ("os.execv(" in text or "os.execvp(" in text)
    if thin:
        return True, "thin exec wrapper"
    return False, "substantive Python implementation in non-Python tool"


def _candidate_ok(
    candidate_dir: Path, slug: str, audit: dict[str, dict[str, Any]]
) -> tuple[bool, str]:
    source = candidate_dir / "source"
    if not source.is_dir():
        return False, "missing source directory"
    audit_row = audit.get(slug, {})
    py_ok, py_reason = _python_ok(source, audit_row)
    if not py_ok:
        return False, py_reason
    if audit_row.get("source_language") == "python" or audit_row.get("action") == "keep-python":
        return True, py_reason
    if audit_row.get("action") == "keep-thin":
        return True, "keep-thin wrapper/binary"
    lang = _native_lang(source)
    if not lang:
        return False, "no native source marker"
    return True, f"native source present: {lang}"


def _strip_crlf(path: Path) -> None:
    """Convert CRLF → LF in a text file (shell scripts must be LF on Linux)."""
    try:
        raw = path.read_bytes()
        if b"\r\n" in raw:
            path.write_bytes(raw.replace(b"\r\n", b"\n"))
    except Exception:
        pass


def _strip_crlf_in_tarball(tar_path: Path) -> None:
    """Repack a .tar.gz so all .sh members are LF-only.

    ProgramBench extracts submission.tar.gz and runs compile.sh from inside it.
    If the tarball was created on Windows, .sh files may have CRLF endings that
    corrupt the heredoc-generated executable's shebang line on Linux.
    """
    try:
        buf = io.BytesIO()
        needs_repack = False
        with tarfile.open(tar_path, "r:gz") as src:
            members = src.getmembers()
            contents: list[tuple[tarfile.TarInfo, bytes]] = []
            for m in members:
                if m.isfile():
                    f = src.extractfile(m)
                    data = f.read() if f else b""
                    if m.name.endswith(".sh") and b"\r\n" in data:
                        data = data.replace(b"\r\n", b"\n")
                        needs_repack = True
                    contents.append((m, data))
                else:
                    contents.append((m, b""))
        if not needs_repack:
            return
        with tarfile.open(fileobj=buf, mode="w:gz") as dst:
            for m, data in contents:
                if m.isfile():
                    m2 = tarfile.TarInfo(name=m.name)
                    m2.size = len(data)
                    m2.mode = m.mode
                    m2.mtime = m.mtime
                    m2.type = m.type
                    m2.uid = m.uid
                    m2.gid = m.gid
                    m2.uname = m.uname
                    m2.gname = m.gname
                    dst.addfile(m2, io.BytesIO(data))
                else:
                    dst.addfile(m)
        tar_path.write_bytes(buf.getvalue())
    except Exception as exc:
        print(f"warning: could not strip CRLF from {tar_path}: {exc}")


def _copy_run_root(src: Path, dst: Path, slug: str) -> None:
    # Do NOT rmtree dst — multiple slugs may share the same run_root name,
    # so dst may already contain sibling slugs copied in earlier iterations.
    slug_dst = dst / slug
    if slug_dst.exists():
        shutil.rmtree(slug_dst)
    dst.mkdir(parents=True, exist_ok=True)
    slug_src = src / slug
    if not slug_src.is_dir():
        raise SystemExit(f"missing candidate dir: {slug_src}")
    shutil.copytree(
        slug_src,
        slug_dst,
        ignore=shutil.ignore_patterns("*.eval.json", "gate_result.json"),
    )
    # Strip CRLF from all shell scripts so heredoc output on Linux is LF-only.
    # Windows git checkouts (autocrlf=true) produce CRLF .sh files; CRLF in a
    # heredoc body writes \r into the generated executable's shebang, which
    # causes /bin/sh to fail with "exec: -a: not found" or similar errors.
    for sh_file in slug_dst.rglob("*.sh"):
        _strip_crlf(sh_file)
    # ProgramBench extracts submission.tar.gz and runs compile.sh from INSIDE it.
    # The tarball may contain CRLF .sh files from a Windows-origin staging dir.
    # Repack the tarball with LF-only shell scripts so the in-tarball compile.sh
    # also gets stripped (the source/ copy above only covers the unpacked copy).
    sub_tar = slug_dst / "submission.tar.gz"
    if sub_tar.is_file():
        _strip_crlf_in_tarball(sub_tar)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="slug/base_slug to skip; pass once per active local lane",
    )
    ap.add_argument(
        "--include",
        action="append",
        default=[],
        help="only include this slug/base_slug; pass multiple times for a targeted shard",
    )
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--name", default=None)
    ap.add_argument(
        "--run-root",
        action="append",
        default=[],
        help="explicit packed candidate as slug=run_root; may be repeated",
    )
    ap.add_argument(
        "--fill-queue",
        action="store_true",
        help="with --run-root, top up remaining shard slots from the native queue",
    )
    args = ap.parse_args()

    excluded = _split_csv_values(args.exclude)
    included = _split_csv_values(args.include)
    audit = _audit_by_slug()
    rows = []
    skips: list[dict[str, Any]] = []
    for r in _parse_run_root_specs(args.run_root):
        run_root = Path(r["run_root"])
        if not run_root.is_absolute():
            run_root = ROOT / run_root
        ok, reason = _candidate_ok(run_root / r["slug"], r["slug"], audit)
        if not ok:
            print(f"SKIP {r['slug']}: {reason}")
            skips.append(
                {
                    "slug": r["slug"],
                    "base_slug": r["base_slug"],
                    "run_root": r["run_root"],
                    "score": r.get("score"),
                    "reason": reason,
                }
            )
            continue
        r["native_guard"] = reason
        rows.append(r)

    if not args.run_root or args.fill_queue:
        for r in _load_queue():
            if len(rows) >= args.count:
                break
            if r.get("status") != "queued":
                continue
            if float(r.get("score") or 0) < args.min_score:
                continue
            if r.get("slug") in excluded or r.get("base_slug") in excluded:
                continue
            if included and r.get("slug") not in included and r.get("base_slug") not in included:
                continue
            run_root = Path(r["run_root"])
            if not run_root.is_absolute():
                run_root = ROOT / run_root
            ok, reason = _candidate_ok(run_root / r["slug"], r["slug"], audit)
            if not ok:
                print(f"SKIP {r['slug']}: {reason}")
                skips.append(
                    {
                        "slug": r["slug"],
                        "base_slug": r["base_slug"],
                        "run_root": r["run_root"],
                        "score": r.get("score"),
                        "reason": reason,
                    }
                )
                continue
            r = dict(r)
            r["native_guard"] = reason
            rows.append(r)

    stamp = args.name or time.strftime("native_%Y%m%d_%H%M%S")
    _write_json_atomic(GUARD_SKIP_DIR / f"NATIVE_GUARD_SKIPS_{stamp}.json", skips)
    shard = SHARD_ROOT / stamp
    if shard.exists():
        shutil.rmtree(shard)
    shard.mkdir(parents=True)

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_root": str(ROOT),
        "queue_path": str(QUEUE),
        "count": len(rows),
        "items": [],
    }

    runs_dir = shard / "runs"
    runs_dir.mkdir()
    for r in rows:
        src = Path(r["run_root"])
        if not src.is_absolute():
            src = ROOT / src
        dst = runs_dir / src.name
        _copy_run_root(src, dst, r["slug"])
        item = dict(r)
        item["remote_run_root"] = f"runs/{src.name}"
        manifest["items"].append(item)

    (shard / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copy2(ROOT / "scripts" / "pb_hetzner_eval_shard.sh", shard / "run.sh")
    _write_reservations(rows, stamp)

    print(shard)
    print(f"items={len(rows)}")
    for r in rows:
        print(f"{r['score']:6.2f} {r['slug']} {r['run_root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
