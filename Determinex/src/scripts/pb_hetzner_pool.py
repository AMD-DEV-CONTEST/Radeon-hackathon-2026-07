#!/usr/bin/env python3
"""Coordinate a remote Hetzner ProgramBench native-eval drain pool.

Local remains authoritative for board/gate/corpus mutation. Hetzner only runs
evals and returns eval JSONs/logs. This script can:

- deploy the next queued native shard to Hetzner,
- watch a remote shard until it drains,
- pull returned artifacts,
- import eval JSONs into the local staging run roots,
- mirror the returned shard under T:/determinex-programbench/hetzner_results,
- gate imported evals locally and optionally apply accepted gates.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# sys.executable is the interpreter actually running this script, which is what a
# hardcoded pythoncore path was standing in for -- and it works on any machine.
PY = Path(sys.executable)
SSH = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")
SCP = Path(r"C:\Windows\System32\OpenSSH\scp.exe")
SSH_KEY = Path.home() / ".ssh" / "id_citadel"
REMOTE = "root@5.78.192.163"
REMOTE_BASE = "/root/determinex-native-shards"
PB_STAGING_ROOT = Path(os.environ.get("DETERMINEX_PB_STAGING_ROOT", "T:/determinex-staging"))
LOCAL_SHARDS = PB_STAGING_ROOT / "hetzner_shards"
LOCAL_RETURNS = PB_STAGING_ROOT / "hetzner_returns"
T_MIRROR = Path("T:/determinex-programbench/hetzner_results")
BOARD = ROOT / "logs" / "programbench_lock_board.json"
RESERVATIONS = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_RESERVATIONS.json"
FACTORY = ROOT / "logs" / "programbench_factory"
ACTIVE_MANIFEST = FACTORY / "HETZNER_ACTIVE_MANIFEST.json"
DEFAULT_ACTIVE_SHARDS = 3


def run(
    cmd: list[str], *, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(str(x) for x in cmd))
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd or ROOT),
        text=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
        check=check,
    )


def run_logged(
    cmd: list[str],
    log_path: Path,
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a noisy local command, save full output, and keep the console compact."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("+", " ".join(str(x) for x in cmd), f"> {log_path}")
    result = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd or ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    log_path.write_text(
        f"$ {' '.join(str(x) for x in cmd)}\n\n"
        f"EXIT={result.returncode}\n\n"
        f"STDOUT\n{result.stdout}\n\n"
        f"STDERR\n{result.stderr}\n",
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, [str(x) for x in cmd], result.stdout, result.stderr
        )
    return result


def capture(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd or ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    if r.stderr:
        print(r.stderr, file=sys.stderr, end="")
    return r.stdout


def ssh(remote_cmd: str, *, check: bool = True) -> str:
    return capture([SSH, "-i", SSH_KEY, REMOTE, remote_cmd], check=check)


def remote_shard_names() -> list[str]:
    out = ssh(
        f"find {REMOTE_BASE} -maxdepth 2 -name manifest.json -printf '%h\\n' 2>/dev/null "
        "| sed 's#.*/##' | sort",
        check=False,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def remote_cleanup(name: str) -> None:
    ssh(f"rm -rf {REMOTE_BASE}/{name} {REMOTE_BASE}/{name}.tar.gz", check=False)
    print(f"remote_cleaned={name}")
    record_shard(name, "cleaned")


def mirror_verified(name: str) -> bool:
    mirror = T_MIRROR / name
    return (
        mirror.is_dir() and (mirror / "manifest.json").is_file() and (mirror / "results").is_dir()
    )


def _load_json_file(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _load_active_manifest() -> dict[str, Any]:
    data = _load_json_file(ACTIVE_MANIFEST, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema_version", "determinex-pb-hetzner-active-v1")
    data.setdefault("updated_at", _utc_now())
    data.setdefault("shards", {})
    return data


def _save_active_manifest(data: dict[str, Any]) -> None:
    data["updated_at"] = _utc_now()
    _write_json(ACTIVE_MANIFEST, data)


def record_shard(name: str, state: str, **fields: Any) -> None:
    data = _load_active_manifest()
    shards = data.setdefault("shards", {})
    row = shards.get(name) or {"name": name, "created_at": _utc_now()}
    row.update(fields)
    row["state"] = state
    row["updated_at"] = _utc_now()
    shards[name] = row
    _save_active_manifest(data)


def active_manifest_names(*, include_terminal: bool = False) -> list[str]:
    terminal = {"cleaned", "failed", "ignored"}
    shards = _load_active_manifest().get("shards", {})
    names = []
    for name, row in shards.items():
        if include_terminal or str(row.get("state") or "") not in terminal:
            names.append(str(name))
    return sorted(names)


def prune_reservations(args: argparse.Namespace | None = None) -> int:
    reservations = _load_json_file(RESERVATIONS, {})
    if not reservations:
        print("reservations_pruned=0")
        return 0
    remote_names = set(remote_shard_names())
    kept: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    for key, value in reservations.items():
        text = str(value)
        if text.startswith("hetzner:"):
            shard = text.split(":", 1)[1]
            if shard not in remote_names:
                removed[key] = value
                continue
        kept[key] = value
    if removed:
        _write_json(RESERVATIONS, kept)
    print(f"reservations_pruned={len(removed)}")
    for key, value in sorted(removed.items()):
        print(f"  {key}: {value}")
    return 0


def make_tar(shard_dir: Path) -> Path:
    archive = shard_dir.with_suffix(".tar.gz")
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        for p in shard_dir.rglob("*"):
            if p.is_file():
                tar.add(p, arcname=p.relative_to(shard_dir).as_posix(), recursive=False)
    return archive


def shard_item_count(shard_dir: Path) -> int:
    manifest_path = shard_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing shard manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
    return len(manifest.get("items") or [])


def deploy_shard_dir(name: str, shard_dir: Path, workers: int, docker_cpus: int) -> int:
    count = shard_item_count(shard_dir)
    if count <= 0:
        raise SystemExit(
            f"refusing to deploy empty Hetzner shard {name}; "
            "refresh queue/reservations or export with valid --include values"
        )
    archive = make_tar(shard_dir)
    print(f"archive={archive} items={count} size_mb={archive.stat().st_size / 1024 / 1024:.2f}")
    record_shard(
        name,
        "deploying",
        shard_dir=str(shard_dir),
        archive=str(archive),
        items=count,
        workers=workers,
        docker_cpus=docker_cpus,
    )

    ssh(f"mkdir -p {REMOTE_BASE}")
    remote_archive = f"{REMOTE_BASE}/{archive.name}"
    run([SCP, "-i", SSH_KEY, archive, f"{REMOTE}:{remote_archive}"])
    ssh(
        "set -e; "
        f"cd {REMOTE_BASE}; "
        f"rm -rf {name}; mkdir {name}; "
        f"tar -xzf {archive.name} -C {name}; "
        f"cp {name}/run.sh {name}/run.sh.orig; "
        f"chmod +x {name}/run.sh; "
        f"cd {name}; "
        f"nohup env WORKERS={workers} PROGRAMBENCH_ROOT=/root/ProgramBench "
        f"PROGRAMBENCH_DOCKER_CPUS={docker_cpus} "
        f"./run.sh {REMOTE_BASE}/{name} > shard.out.log 2> shard.err.log < /dev/null & "
        "echo $! > shard.pid; cat shard.pid"
    )
    print(f"deployed={name}")
    record_shard(name, "remote_running")
    return 0


def deploy_next(args: argparse.Namespace) -> int:
    name = args.name or time.strftime("hetzner_native_%Y%m%d_%H%M%S")
    run([PY, ROOT / "scripts" / "pb_native_eval_queue.py", "--top", "1"])
    export_cmd = [
        PY,
        ROOT / "scripts" / "pb_export_hetzner_shard.py",
        "--count",
        str(args.count),
        "--name",
        name,
    ]
    for ex in args.exclude:
        export_cmd.extend(["--exclude", ex])
    for inc in args.include:
        export_cmd.extend(["--include", inc])
    run(export_cmd)
    shard_dir = LOCAL_SHARDS / name
    return deploy_shard_dir(name, shard_dir, args.workers, args.docker_cpus)


def deploy_existing(args: argparse.Namespace) -> int:
    shard_dir = LOCAL_SHARDS / args.name
    if not shard_dir.is_dir():
        legacy = ROOT / ".determinex_staging" / "hetzner_shards" / args.name
        if legacy.is_dir():
            shard_dir = legacy
    if not shard_dir.is_dir():
        raise SystemExit(f"missing local shard dir: {shard_dir}")
    return deploy_shard_dir(args.name, shard_dir, args.workers, args.docker_cpus)


def remote_done(name: str) -> bool:
    cmd = (
        f"cd {REMOTE_BASE}/{name} 2>/dev/null || exit 2; "
        "if [ -f shard.pid ] && kill -0 $(cat shard.pid) 2>/dev/null; then "
        "echo running; else echo done; fi"
    )
    out = ssh(cmd, check=False).strip()
    return out.endswith("done")


def status(args: argparse.Namespace) -> int:
    name = args.name
    remote = ssh(
        f"cd {REMOTE_BASE}/{name} 2>/dev/null || exit 0; "
        "echo HOST; uptime; free -h | head -2; df -h / /root 2>/dev/null | tail -n +2; "
        "echo PROC; if [ -f shard.pid ]; then ps -fp $(cat shard.pid) || true; fi; "
        "echo SUMMARY; cat results/summary.json 2>/dev/null || true; "
        "echo DOCKER; docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}'",
        check=False,
    )
    print(remote)
    return 0


def pull(args: argparse.Namespace) -> int:
    name = args.name
    record_shard(name, "pulling")
    dest = LOCAL_RETURNS / name
    if dest.exists():
        try:
            shutil.rmtree(dest)
        except PermissionError:
            # A previous watcher/import may still have a file handle open on
            # Windows. Keep the pull moving by writing this retrieval to a
            # unique return directory; import/gate uses the manifest inside.
            dest = LOCAL_RETURNS / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    # Only pull result artifacts. Copying the full shard also transfers the
    # packed run roots/source trees back from Hetzner and can stall for a long
    # time after all eval JSONs are already complete.
    run(
        [SCP, "-i", SSH_KEY, f"{REMOTE}:{REMOTE_BASE}/{name}/manifest.json", dest / "manifest.json"]
    )
    run([SCP, "-i", SSH_KEY, "-r", f"{REMOTE}:{REMOTE_BASE}/{name}/results", dest / "results"])
    run([SCP, "-i", SSH_KEY, "-r", f"{REMOTE}:{REMOTE_BASE}/{name}/logs", dest / "logs"])
    for log_name in ("shard.out.log", "shard.err.log"):
        run(
            [SCP, "-i", SSH_KEY, f"{REMOTE}:{REMOTE_BASE}/{name}/{log_name}", dest / log_name],
            check=False,
        )

    T_MIRROR.mkdir(parents=True, exist_ok=True)
    mirror = T_MIRROR / name
    if mirror.exists():
        shutil.rmtree(mirror)
    shutil.copytree(dest, mirror)
    print(f"mirrored={mirror}")
    record_shard(name, "mirrored", local_return=str(dest), mirror=str(mirror))

    run([PY, ROOT / "scripts" / "pb_import_hetzner_shard.py", dest, "--copy-logs"])
    if args.gate:
        summary = gate_imported(
            dest, apply_accepts=args.apply_accepts, ingest_rejects=args.ingest_rejects
        )
        record_shard(name, "gated", gate_summary=summary)
    if getattr(args, "cleanup_remote", False):
        if mirror_verified(name):
            remote_cleanup(name)
            prune_reservations()
        else:
            print(f"skip remote cleanup, mirror verification failed: {name}")
    return 0


def _board_by_base() -> dict[str, dict[str, Any]]:
    rows = json.loads(BOARD.read_text(encoding="utf-8"))
    return {r["base_slug"]: r for r in rows if r.get("base_slug")}


def gate_imported(
    return_dir: Path, *, apply_accepts: bool, ingest_rejects: bool
) -> list[dict[str, Any]]:
    manifest = json.loads((return_dir / "manifest.json").read_text(encoding="utf-8"))
    board = _board_by_base()
    summary: list[dict[str, Any]] = []
    gate_log_dir = return_dir / "gate_logs"
    for item in manifest["items"]:
        slug = item["slug"]
        base = item["base_slug"]
        run_root = Path(item["run_root"])
        if not run_root.is_absolute():
            run_root = ROOT / run_root
        eval_path = run_root / slug / f"{slug}.eval.json"
        if not eval_path.is_file():
            print(f"skip gate, no eval: {slug}")
            summary.append({"slug": slug, "decision": "skip", "reason": "no eval"})
            continue
        gate_path = run_root / "gate_result.json"
        if gate_path.is_file():
            print(f"skip gate, exists: {slug}")
        else:
            baseline = board.get(base, {}).get("best_eval_path")
            if not baseline:
                print(f"skip gate, no baseline: {slug}")
                summary.append({"slug": slug, "decision": "skip", "reason": "no baseline"})
                continue
            run_logged(
                [
                    PY,
                    ROOT / "scripts" / "pb_candidate_gate.py",
                    slug,
                    run_root,
                    "--baseline-eval",
                    baseline,
                    "--min-baseline-passed",
                    "1",
                    "--skip-eval",
                ],
                gate_log_dir / f"{slug}.candidate_gate.log",
                check=False,
            )

        if not gate_path.is_file():
            summary.append({"slug": slug, "decision": "skip", "reason": "missing gate_result.json"})
            continue
        gate = json.loads(gate_path.read_text(encoding="utf-8", errors="replace"))
        decision = gate.get("decision")
        print(f"gate {slug}: {decision} {gate.get('reason', '')}")
        row: dict[str, Any] = {
            "slug": slug,
            "decision": decision,
            "reason": gate.get("reason", ""),
            "gate_path": str(gate_path),
        }
        if decision == "accept" and apply_accepts:
            run_logged(
                [
                    PY,
                    ROOT / "scripts" / "pb_apply_gate_decision.py",
                    slug,
                    gate_path,
                    "--run-root",
                    run_root,
                    "--refresh-board",
                ],
                gate_log_dir / f"{slug}.apply_accept.log",
                check=False,
            )
            row["applied"] = True
        elif decision != "accept" and ingest_rejects:
            run_logged(
                [PY, ROOT / "scripts" / "pb_verdict_corpus.py", gate_path],
                gate_log_dir / f"{slug}.verdict_corpus.log",
                check=False,
            )
            run_logged(
                [
                    PY,
                    ROOT / "scripts" / "pb_corpus_hint_audit.py",
                    "--slug",
                    slug,
                    "--eval",
                    eval_path,
                    "--input",
                    gate_path,
                    "--source",
                    run_root,
                    "--write-note",
                ],
                gate_log_dir / f"{slug}.hint_audit.log",
                check=False,
            )
            hint = _latest_hint_note(slug)
            if hint:
                row["hint_audit"] = {
                    "matched_patterns": hint.get("matched_patterns") or [],
                    "hook_status": hint.get("hook_status") or {},
                    "likely_cause": hint.get("likely_cause") or "",
                    "next_action": hint.get("next_action") or "",
                    "requeue_priority": hint.get("requeue_priority") or "",
                }
                _print_hint_summary(row["hint_audit"])
        summary.append(row)
    (return_dir / "gate_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def _latest_hint_note(slug: str) -> dict[str, Any] | None:
    notes_dir = ROOT / "corpus" / "programbench" / "training_corpus" / "reject_notes"
    if not notes_dir.is_dir():
        return None
    latest: dict[str, Any] | None = None
    for path in notes_dir.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("slug") != slug:
                continue
            if latest is None or str(rec.get("captured_at", "")) >= str(
                latest.get("captured_at", "")
            ):
                latest = rec
    return latest


def _print_hint_summary(hint: dict[str, Any]) -> None:
    print("HINT_AUDIT:")
    print(f"  matched_patterns: {hint.get('matched_patterns') or []}")
    print(f"  hook_status: {hint.get('hook_status') or {}}")
    print(f"  likely_cause: {hint.get('likely_cause') or ''}")
    print(f"  next_action: {hint.get('next_action') or ''}")
    print(f"  requeue_priority: {hint.get('requeue_priority') or ''}")


def watch(args: argparse.Namespace) -> int:
    while True:
        status(args)
        if remote_done(args.name):
            print(f"{args.name}: remote shard done; pulling")
            pull(args)
            return 0
        time.sleep(args.interval)


def active_remote_shards(names: list[str]) -> list[str]:
    active: list[str] = []
    for name in names:
        if not remote_done(name):
            active.append(name)
    return active


def conveyor(args: argparse.Namespace) -> int:
    """Drain completed shards, clean verified remote copies, then refill slots."""
    processed = 0
    deployed = 0
    while True:
        names = remote_shard_names()
        if args.active_manifest_only:
            managed = set(active_manifest_names())
            names = [n for n in names if n in managed]
        if args.name or args.name_prefix:
            names = [
                n
                for n in names
                if n in args.name or any(n.startswith(prefix) for prefix in args.name_prefix)
            ]
        active = []
        for name in names:
            if remote_done(name):
                print(f"{name}: done -> pull/gate/audit")
                pull_args = argparse.Namespace(
                    name=name,
                    gate=True,
                    apply_accepts=True,
                    ingest_rejects=True,
                    cleanup_remote=True,
                )
                try:
                    pull(pull_args)
                    processed += 1
                except Exception as exc:
                    print(f"pull failed for {name}: {exc}", file=sys.stderr)
                    record_shard(name, "failed", error=str(exc))
            else:
                active.append(name)

        # Refresh board/queue after any pulls before filling new slots.
        if processed:
            prune_reservations()
            run([PY, ROOT / "scripts" / "pb_hint_repair_queue.py"], check=False)
            run([PY, ROOT / "scripts" / "pb_pool_status.py"], check=False)

        active = active_remote_shards(remote_shard_names())
        if args.active_manifest_only:
            managed = set(active_manifest_names())
            active = [n for n in active if n in managed]
        open_slots = max(0, args.max_active - len(active))
        if args.max_deploy is not None:
            open_slots = min(open_slots, max(0, args.max_deploy - deployed))

        for _ in range(open_slots):
            stamp = time.strftime("hetzner_conveyor_%Y%m%d_%H%M%S")
            deploy_args = argparse.Namespace(
                name=stamp,
                count=args.count,
                workers=args.workers,
                docker_cpus=args.docker_cpus,
                exclude=args.exclude,
                include=args.include,
            )
            try:
                deploy_next(deploy_args)
                deployed += 1
            except Exception as exc:
                print(f"deploy-next failed: {exc}", file=sys.stderr)
                break
            time.sleep(1)

        print(
            json.dumps(
                {
                    "processed": processed,
                    "deployed": deployed,
                    "active": active_remote_shards(remote_shard_names()),
                    "max_active": args.max_active,
                },
                indent=2,
            )
        )
        if args.once:
            return 0
        time.sleep(args.interval)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("deploy-next")
    d.add_argument("--name")
    d.add_argument("--count", type=int, default=20)
    d.add_argument("--workers", type=int, default=4)
    d.add_argument("--docker-cpus", type=int, default=2)
    d.add_argument("--exclude", action="append", default=[])
    d.add_argument("--include", action="append", default=[])
    d.set_defaults(func=deploy_next)

    de = sub.add_parser("deploy-existing")
    de.add_argument("name")
    de.add_argument("--workers", type=int, default=4)
    de.add_argument("--docker-cpus", type=int, default=2)
    de.set_defaults(func=deploy_existing)

    s = sub.add_parser("status")
    s.add_argument("name")
    s.set_defaults(func=status)

    p = sub.add_parser("pull")
    p.add_argument("name")
    p.add_argument("--gate", action="store_true")
    p.add_argument("--apply-accepts", action="store_true")
    p.add_argument("--ingest-rejects", action="store_true")
    p.add_argument("--cleanup-remote", action="store_true")
    p.set_defaults(func=pull)

    w = sub.add_parser("watch")
    w.add_argument("name")
    w.add_argument("--interval", type=int, default=120)
    w.add_argument("--gate", action="store_true", default=True)
    w.add_argument("--apply-accepts", action="store_true", default=True)
    w.add_argument("--ingest-rejects", action="store_true", default=True)
    w.set_defaults(func=watch)

    pr = sub.add_parser("prune-reservations")
    pr.set_defaults(func=prune_reservations)

    am = sub.add_parser("active-manifest")
    am.add_argument("--include-terminal", action="store_true")
    am.set_defaults(
        func=lambda args: (
            print(json.dumps(_load_active_manifest(), indent=2, sort_keys=True)),
            0,
        )[1]
    )

    c = sub.add_parser("conveyor")
    c.add_argument("--max-active", type=int, default=DEFAULT_ACTIVE_SHARDS)
    c.add_argument("--max-deploy", type=int)
    c.add_argument("--count", type=int, default=1)
    c.add_argument("--workers", type=int, default=1)
    c.add_argument("--docker-cpus", type=int, default=1)
    c.add_argument("--interval", type=int, default=180)
    c.add_argument("--once", action="store_true")
    c.add_argument("--exclude", action="append", default=[])
    c.add_argument("--include", action="append", default=[])
    c.add_argument(
        "--name", action="append", default=[], help="existing remote shard name to drain/watch"
    )
    c.add_argument(
        "--name-prefix",
        action="append",
        default=[],
        help="only drain/watch existing shards with this prefix",
    )
    c.add_argument(
        "--active-manifest-only",
        action="store_true",
        help="only count/drain remote shards tracked in HETZNER_ACTIVE_MANIFEST.json unless explicitly named",
    )
    c.set_defaults(func=conveyor)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
