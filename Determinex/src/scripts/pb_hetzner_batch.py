"""
pb_hetzner_batch.py — Full Hetzner lifecycle for parallel ProgramBench evaluation.

Phases:
  1. preflight   — apply changes A/B/C, produce submission_uncapped.tar.gz + uncap_manifest.json
  2. upload      — scp all ready submissions to Hetzner nodes
  3. execute     — run all evals sequentially on each node via SSH
  4. monitor     — poll node progress every 30s, print live table
  5. download    — scp all results back, clean remote
  6. promote     — auto-promote locks via pb_promote.py

Usage:
  python scripts/pb_hetzner_batch.py --phase all
  python scripts/pb_hetzner_batch.py --phase preflight
  python scripts/pb_hetzner_batch.py --phase upload
  python scripts/pb_hetzner_batch.py --phase execute
  python scripts/pb_hetzner_batch.py --phase monitor
  python scripts/pb_hetzner_batch.py --phase download
  python scripts/pb_hetzner_batch.py --phase promote
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table

    _rich = True
except ImportError:
    _rich = False

_console = None


def _get_console():
    global _console
    if _rich and _console is None:
        _console = Console()
    return _console


ROOT = Path(__file__).parent.parent
PB_DIR = ROOT / "corpus" / "programbench"
PENDING_BASE = PB_DIR / "pending_unlock"
RESULTS_BASE = PB_DIR / "results"
HETZNER_CONFIG = ROOT / "config" / "hetzner.json"
INDEX_FILE = PB_DIR / "eval_index.json"

CAP_PATTERN = re.compile(r"^\s*del\s+items\s*\[\s*\d+\s*:\s*\]\s*$", re.MULTILINE)
# Guard that may precede del items[N:] — e.g. "if len(items) > 400:"
IF_GUARD_PATTERN = re.compile(r"^\s*if\s+len\s*\(\s*items\s*\)\s*[>]=?\s*\d+\s*:\s*$")
KEYWORD_FILTER = re.compile(
    r"if\s+any\s*\(\s*s\s+in\s+nodeid\s+for\s+s\s+in\s+\([^)]*"
    r"(?:tmux|interactive|libtmux|pexpect|test_pty)[^)]*\)\s*\)",
    re.IGNORECASE,
)

SEMANTIC_FILTER_BLOCK = """\
    def _is_tui_test(item):
        fpath = str(getattr(item, 'fspath', '') or '')
        tui_files = ('test_tui','test_tmux','test_pty','test_interactive',
                     'test_pexpect','test_curses')
        if any(p in fpath.lower() for p in tui_files):
            return True
        try:
            import ast, pathlib
            src = pathlib.Path(fpath).read_text(errors='replace')
            tree = ast.parse(src)
            tui_imports = {'pexpect','libtmux','curses','pty',
                           'termios','tty','blessed','urwid'}
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in getattr(node,'names',[])]
                    mod = getattr(node, 'module', '') or ''
                    if any(t in names or t in mod for t in tui_imports):
                        return True
        except Exception:
            pass
        return False
    keep = [item for item in items if not _is_tui_test(item)]
    items[:] = keep"""


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def load_config() -> dict:
    return json.loads(HETZNER_CONFIG.read_text())


def load_index() -> list[dict]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return []


def pending_tools() -> list[dict]:
    index = load_index()
    return [e for e in index if e["status"] == "pending_unlock"]


def find_tool_dir(slug: str) -> Path | None:
    for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300"):
        d = PENDING_BASE / pri / slug
        if d.exists():
            return d
    return None


def load_ticket(tool_dir: Path) -> dict:
    p = tool_dir / "unlock_ticket.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def ssh(
    node: dict, cmd: str, check: bool = True, timeout: int = 60, no_stdin: bool = False
) -> subprocess.CompletedProcess:
    key = str(Path(node["ssh_key"].replace("~", str(Path.home()))))
    base = [
        "ssh",
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={node.get('connect_timeout', 15)}",
    ]
    if no_stdin:
        base.append("-n")
    return subprocess.run(
        base + [f"{node['ssh_user']}@{node['ip']}", cmd],
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def scp_to(node: dict, local: Path, remote: str, timeout: int = 300) -> None:
    key = str(Path(node["ssh_key"].replace("~", str(Path.home()))))
    subprocess.run(
        [
            "scp",
            "-i",
            key,
            "-o",
            "StrictHostKeyChecking=no",
            str(local),
            f"{node['ssh_user']}@{node['ip']}:{remote}",
        ],
        check=True,
        timeout=timeout,
    )


def scp_from(node: dict, remote: str, local: Path, timeout: int = 300) -> None:
    key = str(Path(node["ssh_key"].replace("~", str(Path.home()))))
    local.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "scp",
            "-r",
            "-i",
            key,
            "-o",
            "StrictHostKeyChecking=no",
            f"{node['ssh_user']}@{node['ip']}:{remote}",
            str(local),
        ],
        check=True,
        timeout=timeout,
    )


# ──────────────────────────────────────────────────────────────────
# PHASE 1: PREFLIGHT
# ──────────────────────────────────────────────────────────────────


def apply_change_a(compile_sh: str) -> tuple[str, list[str]]:
    """Remove del items[N:] lines and any immediately preceding if len(items) > N: guard."""
    lines = compile_sh.splitlines(keepends=True)
    removed = []
    out: list[str] = []
    for line in lines:
        if CAP_PATTERN.match(line):
            removed.append(line.strip())
            # Also remove the immediately preceding guard if present
            if out and IF_GUARD_PATTERN.match(out[-1].rstrip("\r\n")):
                removed.append(out.pop().strip())
        else:
            out.append(line)
    return "".join(out), removed


def apply_change_b(compile_sh: str) -> tuple[str, bool]:
    """Replace keyword TUI filter with semantic classifier."""
    if not KEYWORD_FILTER.search(compile_sh):
        return compile_sh, False

    # Find the surrounding block: keep=[] ... items[:] = keep
    full_block = re.compile(
        r"(\n\s*keep\s*=\s*\[\]\s*\n"
        r"\s*for item in items:\s*\n"
        r"(?:[^\n]*\n)*?"
        r"\s*items\[:?\]\s*=\s*keep)",
        re.MULTILINE,
    )
    result, n = full_block.subn("\n" + SEMANTIC_FILTER_BLOCK, compile_sh)
    if n == 0:
        # Fallback: remove just the nodeid/if/continue lines
        result = re.sub(
            r"\s*nodeid\s*=\s*\([^\n]*\n\s*if any\(s in nodeid[^\n]+\):\s*\n\s*continue\s*\n",
            "\n",
            compile_sh,
            flags=re.MULTILINE,
        )
        # Append semantic filter before items[:] = keep line
        result = result.replace("    items[:] = keep", SEMANTIC_FILTER_BLOCK)
    return result, True


def apply_change_c(compile_sh: str) -> tuple[str, bool]:
    """Ensure timeout is set in pytest.ini section."""
    if "timeout" in compile_sh:
        return compile_sh, False  # already present
    # Inject into pytest.ini heredoc if present
    ini_block = re.compile(r"(cat\s*>\s*pytest\.ini[^\n]*\n(?:[^\n]*\n)*?EOF)", re.MULTILINE)
    if ini_block.search(compile_sh):
        result = ini_block.sub(
            lambda m: m.group(0).replace("[pytest]", "[pytest]\ntimeout = 30"),
            compile_sh,
        )
        changed = result != compile_sh
        return result, changed
    return compile_sh, False


def preflight_tool(slug: str) -> dict:
    """Apply A/B/C to a tool. Returns manifest dict."""
    tool_dir = find_tool_dir(slug)
    if tool_dir is None:
        return {"slug": slug, "ready_for_eval": False, "reason": "no tool dir found"}

    # Prefer existing uncapped tarball if already processed
    uncapped = tool_dir / "submission_uncapped.tar.gz"
    original = tool_dir / "submission.tar.gz"
    src_tarball = uncapped if uncapped.exists() else original

    if not src_tarball.exists():
        return {"slug": slug, "ready_for_eval": False, "reason": "no submission.tar.gz"}

    # Read tarball, extract compile.sh
    try:
        with tarfile.open(str(src_tarball), "r:gz") as tf:
            members = tf.getmembers()
            compile_member = next((m for m in members if m.name.endswith("compile.sh")), None)
            if compile_member is None:
                return {"slug": slug, "ready_for_eval": False, "reason": "no compile.sh in tarball"}
            _f = tf.extractfile(compile_member)
            if _f is None:
                return {
                    "slug": slug,
                    "ready_for_eval": False,
                    "reason": "compile.sh is not a regular file",
                }
            compile_sh = _f.read().decode("utf-8", errors="replace")
    except Exception as ex:
        return {"slug": slug, "ready_for_eval": False, "reason": f"tarball read error: {ex}"}

    changes: list[str] = []
    extra_changes: list[str] = []

    # A: Remove caps
    compile_sh, cap_lines = apply_change_a(compile_sh)
    if cap_lines:
        changes.append("removed_del_items_cap")

    # Verify no cap remains
    remaining = CAP_PATTERN.findall(compile_sh)
    if remaining:
        return {
            "slug": slug,
            "ready_for_eval": False,
            "reason": f"cap removal incomplete: {remaining}",
        }

    # B: Semantic TUI filter
    compile_sh, b_applied = apply_change_b(compile_sh)
    if b_applied:
        changes.append("semantic_tui_filter")

    # C: Timeout
    compile_sh, c_applied = apply_change_c(compile_sh)
    if c_applied:
        changes.append("timeout_set")

    if not changes:
        changes.append("no_changes_needed")

    # Repack tarball
    buf = io.BytesIO()
    with tarfile.open(str(src_tarball), "r:gz") as in_tf:
        with tarfile.open(fileobj=buf, mode="w:gz") as out_tf:
            for m in in_tf.getmembers():
                if m.name == compile_member.name:
                    encoded = compile_sh.encode("utf-8")
                    info = tarfile.TarInfo(name=m.name)
                    info.size = len(encoded)
                    info.mode = m.mode
                    info.mtime = m.mtime
                    out_tf.addfile(info, io.BytesIO(encoded))
                else:
                    f = in_tf.extractfile(m)
                    if f is not None:
                        out_tf.addfile(m, f)
                    else:
                        out_tf.addfile(m)

    dest = tool_dir / "submission_uncapped.tar.gz"
    dest.write_bytes(buf.getvalue())

    manifest = {
        "slug": slug,
        "original_tarball": str(original) if original.exists() else "",
        "uncapped_tarball": str(dest),
        "changes": changes,
        "cap_lines_removed": cap_lines,
        "extra_changes": extra_changes,
        "ready_for_eval": True,
    }
    (tool_dir / "uncap_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def phase_preflight(tools: list[dict]) -> tuple[list[dict], list[dict]]:
    ready = []
    not_ready = []
    print(f"\nPreflight: processing {len(tools)} tools...")
    for entry in tools:
        slug = entry["slug"]
        m = preflight_tool(slug)
        icon = "✓" if m["ready_for_eval"] else "✗"
        changes = ", ".join(m.get("changes", []))
        print(f"  {icon} {slug:30s} [{changes}]")
        if m["ready_for_eval"]:
            ready.append(entry)
        else:
            not_ready.append((slug, m.get("reason", "?")))

    print(
        f"\nPreflight complete: {len(ready)}/{len(tools)} ready for eval, "
        f"{len(not_ready)} not ready"
    )
    if not_ready:
        for slug, reason in not_ready:
            print(f"  NOT READY: {slug} — {reason}")
    return ready, not_ready


# ──────────────────────────────────────────────────────────────────
# PHASE 2: UPLOAD
# ──────────────────────────────────────────────────────────────────


def assign_tools_to_nodes(tools: list[dict], nodes: list[dict]) -> dict[str, list[dict]]:
    """
    Sort tools by total tests DESC, assign round-robin across nodes.
    Each node gets a mix of large and small suites.
    """
    sorted_tools = sorted(tools, key=lambda e: e.get("official_total", 0), reverse=True)
    assignment: dict[str, list[dict]] = {n["id"]: [] for n in nodes}
    node_ids = [n["id"] for n in nodes]
    for i, tool in enumerate(sorted_tools):
        assignment[node_ids[i % len(node_ids)]].append(tool)
    return assignment


def phase_upload(ready_tools: list[dict], nodes: list[dict]) -> dict[str, list[dict]]:
    assignment = assign_tools_to_nodes(ready_tools, nodes)

    for node in nodes:
        node_tools = assignment[node["id"]]
        print(f"\nNode {node['id']} ({node['ip']}): {len(node_tools)} tools")
        work_dir = node["work_dir"]

        # Create remote dirs
        ssh(node, f"mkdir -p {work_dir}/submissions {work_dir}/workspace {work_dir}/results")

        def _do_upload(progress=None, task_id=None):
            uploaded = 0
            for i, entry in enumerate(node_tools):
                slug = entry["slug"]
                tool_dir = find_tool_dir(slug)
                if tool_dir is None:
                    print(f"  SKIP {slug}: no tool dir")
                    continue
                tarball = tool_dir / "submission_uncapped.tar.gz"
                if not tarball.exists():
                    tarball = tool_dir / "submission.tar.gz"
                if not tarball.exists():
                    print(f"  SKIP {slug}: no tarball")
                    continue
                ticket = load_ticket(tool_dir)
                canonical = ticket.get("canonical_slug", slug)
                remote_path = f"{work_dir}/submissions/{canonical}.tar.gz"
                if progress and task_id is not None:
                    progress.update(task_id, advance=1, description=f"[cyan]Uploading {slug[:30]}")
                else:
                    print(f"  -> {slug} ({tarball.stat().st_size:,} bytes)...")
                scp_to(node, tarball, remote_path, timeout=120)
                uploaded += 1
            return uploaded

        if _rich:
            console = _get_console()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"[cyan]Uploading to {node['ip']}", total=len(node_tools))
                uploaded = _do_upload(progress=progress, task_id=task)
        else:
            uploaded = _do_upload()

        print(f"  Uploaded {uploaded} tarballs to {node['ip']}")

    return assignment


# ──────────────────────────────────────────────────────────────────
# PHASE 3: EXECUTE
# ──────────────────────────────────────────────────────────────────

HETZNER_EVAL_SCRIPT = """\
#!/bin/bash
set -uo pipefail
RESULTS_DIR={results_dir}
WORK_DIR={work_dir}
PB_BIN={pb_bin}
DOCKER_CPUS={docker_cpus}

mkdir -p "$RESULTS_DIR"

for tarball in {work_dir}/submissions/*.tar.gz; do
    fname=$(basename "$tarball")
    canonical="${{fname%.tar.gz}}"
    # canonical is author__tool.hash
    if [[ "$canonical" == *__* ]]; then
        author="${{canonical%%__*}}"
    else
        author="${{canonical%%.*}}"
    fi

    tool_dir="$WORK_DIR/workspace/$canonical"
    result_dir="$RESULTS_DIR/$canonical"
    log="$result_dir/eval.log"

    mkdir -p "$tool_dir" "$result_dir"

    echo "=== STARTING $canonical $(date -Iseconds) ==="
    cd "$tool_dir"
    cp "$tarball" submission.tar.gz

    # Run eval with timeout — allow non-zero exit (partial results still collected)
    set +e
    PYTHONUTF8=1 PROGRAMBENCH_DOCKER_CPUS=$DOCKER_CPUS \\
        timeout {eval_timeout} "$PB_BIN" eval "$WORK_DIR/workspace" \\
        --filter "$author" --force \\
        > "$log" 2>&1
    rc=$?
    set -e

    # Collect PB eval JSON (canonical.eval.json — ProgramBench's canonical output filename)
    find "$tool_dir" -name "*.eval.json" -exec cp {{}} "$result_dir/" \\;

    echo "=== FINISHED $canonical exit=$rc $(date -Iseconds) ===" | tee -a "$log"

    # Clean workspace to save disk
    rm -rf "$tool_dir"
done

echo "=== ALL_DONE $(date -Iseconds) ==="
"""


def phase_execute(assignment: dict[str, list[dict]], nodes: list[dict], config: dict) -> None:
    pb_config = config
    node_map = {n["id"]: n for n in nodes}

    for node_id, tools in assignment.items():
        if not tools:
            continue
        node = node_map[node_id]
        work_dir = node["work_dir"]
        results_dir = f"{work_dir}/results"
        pb_bin = node["pb_bin"]
        docker_cpus = node.get("docker_cpus", 4)
        eval_timeout = pb_config.get("eval_timeout_seconds", 600)

        script = HETZNER_EVAL_SCRIPT.format(
            results_dir=results_dir,
            work_dir=work_dir,
            pb_bin=pb_bin,
            docker_cpus=docker_cpus,
            eval_timeout=eval_timeout,
        )

        # Upload eval script
        script_remote = f"{work_dir}/run_all_evals.sh"
        log_remote = f"{work_dir}/batch_eval.log"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, newline="\n", encoding="utf-8"
        ) as f:
            f.write(script)
            script_local = Path(f.name)

        scp_to(node, script_local, script_remote)
        script_local.unlink(missing_ok=True)

        # Launch in background — </dev/null closes stdin so SSH exits cleanly
        launch_cmd = (
            f"chmod +x {script_remote} && "
            f"nohup bash {script_remote} > {log_remote} 2>&1 </dev/null & echo $!"
        )
        result = ssh(node, launch_cmd, timeout=30, no_stdin=True)
        pid = result.stdout.strip()
        print(f"Node {node_id}: launched eval (PID {pid}), log: {log_remote}")

        # Store PID for monitor phase
        pid_file = ROOT / "logs" / f"hetzner_{node_id}_pid.txt"
        pid_file.parent.mkdir(exist_ok=True)
        pid_file.write_text(pid)


# ──────────────────────────────────────────────────────────────────
# PHASE 4: MONITOR
# ──────────────────────────────────────────────────────────────────


def phase_monitor(assignment: dict[str, list[dict]], nodes: list[dict], config: dict) -> None:
    node_map = {n["id"]: n for n in nodes}
    poll_interval = config.get("poll_interval_seconds", 30)
    start_time = time.time()

    tool_status: dict[str, dict[str, str]] = {}
    for node_id, tools in assignment.items():
        tool_status[node_id] = {t["slug"]: "queued" for t in tools}

    all_done = False
    while not all_done:
        time.sleep(poll_interval)
        all_done = True
        elapsed = int(time.time() - start_time)

        print(f"\n[{elapsed}s elapsed] {datetime.now(UTC).strftime('%H:%M:%S UTC')}")

        for node_id, tools in assignment.items():
            if not tools:
                continue
            node = node_map[node_id]
            work_dir = node["work_dir"]
            results_dir = f"{work_dir}/results"
            log = f"{work_dir}/batch_eval.log"

            # Check which tools have results
            check = ssh(node, f"ls {results_dir}/ 2>/dev/null | head -100", check=False, timeout=15)
            completed_dirs = set(check.stdout.strip().split()) if check.stdout.strip() else set()

            # Check if all done
            done_check = ssh(
                node, f"grep -c 'ALL_DONE' {log} 2>/dev/null || echo 0", check=False, timeout=15
            )
            node_done = done_check.stdout.strip() != "0"

            # Get current tool from log tail
            tail = ssh(node, f"tail -3 {log} 2>/dev/null || echo ''", check=False, timeout=15)
            current = ""
            for line in tail.stdout.strip().splitlines():
                if "STARTING" in line or "FINISHED" in line:
                    current = line.split("===")[1].strip() if "===" in line else line

            # Update statuses
            for entry in tools:
                slug = entry["slug"]
                _td = find_tool_dir(slug)
                ticket = load_ticket(_td) if _td is not None else {}
                canonical = ticket.get("canonical_slug", slug)
                if any(canonical in d for d in completed_dirs):
                    tool_status[node_id][slug] = "done"
                elif "running" not in tool_status[node_id].get(slug, ""):
                    if current and slug in current:
                        tool_status[node_id][slug] = "running"

            done_count = sum(1 for s in tool_status[node_id].values() if s == "done")
            total_count = len(tools)
            print(
                f"  Node {node_id}: {done_count}/{total_count} done"
                f"{' [ALL DONE]' if node_done else ''}"
            )
            if current:
                print(f"    Current: {current}")

            if not node_done:
                all_done = False

    print("\nAll nodes complete!")


# ──────────────────────────────────────────────────────────────────
# PHASE 5: DOWNLOAD
# ──────────────────────────────────────────────────────────────────


def phase_download(assignment: dict[str, list[dict]], nodes: list[dict]) -> None:
    node_map = {n["id"]: n for n in nodes}

    for node_id, tools in assignment.items():
        if not tools:
            continue
        node = node_map[node_id]
        work_dir = node["work_dir"]
        results_dir = f"{work_dir}/results"

        print(f"\nDownloading results from {node['id']} ({node['ip']})...")

        # List what's available
        ls = ssh(node, f"ls {results_dir}/ 2>/dev/null", check=False)
        available = set(ls.stdout.strip().split()) if ls.stdout.strip() else set()
        print(f"  {len(available)} result directories found")

        for entry in tools:
            slug = entry["slug"]
            tool_dir = find_tool_dir(slug)
            if tool_dir is None:
                continue
            ticket = load_ticket(tool_dir)
            canonical = ticket.get("canonical_slug", slug)

            matching = [d for d in available if canonical in d or slug in d]
            if not matching:
                print(f"  MISSING: {slug} (canonical={canonical})")
                continue

            remote_result = f"{results_dir}/{matching[0]}"
            local_result = tool_dir / "hetzner_result"
            local_result.mkdir(exist_ok=True)

            scp_from(node, remote_result + "/*", local_result, timeout=60)
            print(f"  Downloaded: {slug}")

        # Clean remote
        print(f"  Cleaning remote {node['id']}...")
        ssh(
            node,
            f"rm -rf {work_dir}/submissions {work_dir}/workspace {work_dir}/results",
            check=False,
        )
        print("  Done.")


# ──────────────────────────────────────────────────────────────────
# PHASE 6: PROMOTE
# ──────────────────────────────────────────────────────────────────


def phase_promote(tools: list[dict]) -> dict:
    """Auto-promote strict locks and upstream-skip locks from Hetzner results."""
    sys.path.insert(0, str(ROOT / "scripts"))

    from pb_promote import promote_tool, validate_lock

    results = {
        "strict_lock": [],
        "upstream_skips": [],
        "partial": [],
        "regression": [],
        "error": [],
    }

    # Load current index to check for regressions
    index = load_index()
    prev_scores = {e["slug"]: e.get("official_passed", 0) for e in index}

    for entry in tools:
        slug = entry["slug"]
        tool_dir = find_tool_dir(slug)
        if tool_dir is None:
            results["error"].append(slug)
            continue

        hetzner_dir = tool_dir / "hetzner_result"
        if not hetzner_dir.exists():
            print(f"  {slug}: no hetzner_result/ dir")
            results["error"].append(slug)
            continue

        # Find eval JSON
        eval_jsons = list(hetzner_dir.rglob("*.eval.json"))
        if not eval_jsons:
            print(f"  {slug}: no eval.json in hetzner_result/")
            results["error"].append(slug)
            continue

        eval_data = json.loads(eval_jsons[0].read_text(encoding="utf-8", errors="replace"))

        ok, counts, errors = validate_lock(eval_data)

        prev = prev_scores.get(slug, 0)
        if counts["passed"] < prev:
            print(f"  REGRESSION: {slug} {prev} -> {counts['passed']}")
            results["regression"].append(slug)
            continue

        if ok:
            tarball = tool_dir / "submission_uncapped.tar.gz"
            if not tarball.exists():
                tarball = tool_dir / "submission.tar.gz"
            promote_tool(slug, eval_data, source="hetzner", tarball=tarball)
            if counts["skipped"] == 0:
                results["strict_lock"].append(slug)
            else:
                results["upstream_skips"].append(slug)
        else:
            results["partial"].append(slug)

    return results


# ──────────────────────────────────────────────────────────────────
# LOAD / SAVE ASSIGNMENT STATE
# ──────────────────────────────────────────────────────────────────

STATE_FILE = ROOT / "logs" / "hetzner_batch_state.json"


def save_state(assignment: dict, ready: list, not_ready: list) -> None:
    state = {
        "timestamp": datetime.now(UTC).isoformat(),
        "assignment": {nid: [e["slug"] for e in tools] for nid, tools in assignment.items()},
        "ready": [e["slug"] for e in ready],
        "not_ready": [slug for slug, _ in not_ready],
    }
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text())


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Hetzner ProgramBench batch eval")
    parser.add_argument(
        "--phase",
        default="all",
        choices=["all", "preflight", "upload", "execute", "monitor", "download", "promote"],
        help="Which phase to run",
    )
    parser.add_argument("--tools", nargs="*", help="Specific tool slugs (default: all pending)")
    args = parser.parse_args()

    if not HETZNER_CONFIG.exists():
        print(f"ERROR: {HETZNER_CONFIG} not found", file=sys.stderr)
        return 1

    config = load_config()
    nodes = config["nodes"]

    tools = pending_tools()
    if args.tools:
        tools = [e for e in tools if e["slug"] in args.tools]
    print(f"Tools: {len(tools)} pending_unlock entries")

    if args.phase in ("all", "preflight"):
        ready, not_ready = phase_preflight(tools)
    else:
        state = load_state()
        if state:
            ready_slugs = set(state.get("ready", []))
            ready = [e for e in tools if e["slug"] in ready_slugs]
        else:
            ready = tools
        not_ready = []

    if args.phase in ("all", "upload"):
        assignment = phase_upload(ready, nodes)
        save_state(assignment, ready, not_ready)
    else:
        state = load_state()
        assignment = {}
        if state:
            for node in nodes:
                slugs = state.get("assignment", {}).get(node["id"], [])
                assignment[node["id"]] = [e for e in tools if e["slug"] in slugs]

    if args.phase in ("all", "execute"):
        phase_execute(assignment, nodes, config)

    if args.phase in ("all", "monitor"):
        phase_monitor(assignment, nodes, config)

    if args.phase in ("all", "download"):
        phase_download(assignment, nodes)

    if args.phase in ("all", "promote"):
        all_tools = ready
        promote_results = phase_promote(all_tools)

        print("\n" + "=" * 65)
        print("PROMOTION RESULTS")
        print("=" * 65)
        for cat, tool_list in promote_results.items():
            if tool_list:
                print(f"  {cat.upper()}: {len(tool_list)} tools: {', '.join(tool_list)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
