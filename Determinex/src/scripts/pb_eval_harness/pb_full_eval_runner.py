#!/usr/bin/env python3
import os
import sys

# Force UTF-8 output on Windows so box-drawing chars print cleanly
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
r"""
pb_full_eval_runner.py — Determinex ProgramBench Full Eval Harness
================================================================
Runs all ProgramBench evals sequentially, one at a time.
Monitors CPU/memory/Docker resource usage.
Places results into T:\determinex-programbench\full_evals_YYYYMMDD\
Updates corpus/programbench/eval_index.json after each run.

IMPORTANT: The 400-test cap has been removed. This runner always runs full suites.
All evals recorded here are post-cap-removal (post 2026-06-07).

Usage:
    python scripts/pb_eval_harness/pb_full_eval_runner.py [--dry-run] [--resume] [--filter SLUG]

Args:
    --dry-run       Print what would run, do nothing
    --resume        Skip tools that already have a completed entry in the run log
    --filter SLUG   Only run the tool matching this slug (partial match OK)
    --max N         Stop after N tools (default: all)
    --phase PHASE   Which phase to run: pending (default), board, all
    --start-from SLUG  Resume from a specific slug in the queue
"""

import argparse
import datetime
import json
import pathlib
import shutil
import subprocess
import sys
import threading
import time

# ------------------------------- PATHS ------------------------------- #
DETERMINEX_ROOT = pathlib.Path(__file__).parent.parent.parent.resolve()
INDEX_PATH = DETERMINEX_ROOT / "corpus" / "programbench" / "eval_index.json"
LOCKED_DIR = DETERMINEX_ROOT / "corpus" / "programbench" / "locked"
PB_HARNESS_DIR = pathlib.Path(r"T:\Dev\ProgramBench")
STAGING_ROOT = pathlib.Path(r"T:\determinex-programbench")
TODAY = datetime.date.today().strftime("%Y%m%d")
OUTPUT_ROOT = STAGING_ROOT / f"full_evals_{TODAY}"
LOG_FILE = OUTPUT_ROOT / "run_log.jsonl"
RESOURCE_LOG = OUTPUT_ROOT / "resource_log.jsonl"

# ------------------------------- TUNING ------------------------------- #
# Resource limits — we allow high utilization since user has spare CPU.
# Will pause if CPU > PAUSE_CPU_PCT for > PAUSE_HOLD_SECS
PAUSE_CPU_PCT = 88  # pause if CPU stays above this
PAUSE_HOLD_SECS = 30  # how many seconds it must stay above before pausing
RESUME_CPU_PCT = 70  # resume when CPU drops below this
RESOURCE_INTERVAL = 5  # seconds between resource samples

# How long to wait (seconds) for a single eval before declaring timeout
EVAL_TIMEOUT_SECS = 1800  # 30 minutes max per tool

# ------------------------------- LANGUAGE CORE DETECTION ---------------- #
# These language families are considered "base language core" —
# tools that build cleanly with standard compile.sh patterns.
# Tools outside this set need extra work and go to the bottom of the queue.
CORE_LANGUAGES = {
    "rust",  # cargo build --release
    "go",  # go build
    "python",  # py implementation, no native required
    "c",  # gcc/clang
    "cpp",  # g++/clang++
    "javascript",  # node
    "typescript",  # tsc + node
}

# Known language for each slug (derived from locked/ source files and PB tasks)
# Format: slug_prefix -> language
SLUG_LANGUAGE_MAP = {
    # Rust
    "angle-grinder": "rust",
    "ascii-image-converter": "rust",
    "bore": "rust",
    "chroma": "rust",
    "clog-cli": "rust",
    "code-minimap": "rust",
    "curlie": "rust",
    "deadnix": "rust",
    "diffr": "rust",
    "elfcat": "rust",
    "entr": "c",
    "eva": "rust",
    "fblog": "rust",
    "flamelens": "rust",
    "fzf": "go",
    "genact": "rust",
    "git-trim": "go",
    "gping": "rust",
    "grex": "rust",
    "gron": "go",
    "hck": "rust",
    "hex": "rust",
    "htmlq": "rust",
    "hyperfine": "rust",
    "igrep": "rust",
    "i3-style": "python",
    "jplot": "go",
    "json-tui": "rust",
    "jq": "c",
    "keifu": "rust",
    "loop": "rust",
    "miniserve": "rust",
    "muffet": "go",
    "monolith": "rust",
    "ngrrram": "rust",
    "nomino": "rust",
    "nsh": "rust",
    "oha": "rust",
    "ov": "rust",
    "parqeye": "python",
    "pastel": "rust",
    "pier": "rust",
    "pingu": "rust",
    "quickjs": "c",
    "rhit": "rust",
    "richgo": "go",
    "ripgrep": "rust",
    "ripsecrets": "rust",
    "rnr": "rust",
    "rumdl": "rust",
    "run": "rust",
    "rustowl": "rust",
    "sd": "rust",
    "seqtk": "c",
    "shellharden": "rust",
    "tailspin": "rust",
    "tex-fmt": "rust",
    "thokr": "rust",
    "tparse": "go",
    "trdsql": "go",
    "tuc": "rust",
    "xsv": "rust",
    "xz": "c",
    "yj": "go",
    "yq": "go",
    "zip-password-finder": "rust",
    "zoxide": "rust",
    "argc": "rust",
    "dsq": "go",
    "dupl": "go",
    "fasttext": "cpp",
    "go-mod-outdated": "go",
    "cmatrix": "c",
    "csview": "rust",
    "xq": "rust",
    "stathissideris__ditaa": "java",
    "boyter__scc.515f91c": "go",
    "pier": "rust",
    "loop": "rust",
    "flamelens": "rust",
    "fblog": "rust",
}

NON_CORE_LANGS = {"java", "haskell", "nix", "lua", "ruby", "perl", "scala", "kotlin"}


def detect_language(slug: str) -> str:
    """Detect implementation language from slug or locked/ source files."""
    # Direct map first
    clean_slug = slug.split("__")[-1] if "__" in slug else slug
    for key, lang in SLUG_LANGUAGE_MAP.items():
        if key == clean_slug or key == slug:
            return lang
    # Try source files in locked dir
    locked_path = LOCKED_DIR / clean_slug / "source"
    if not locked_path.exists():
        locked_path = LOCKED_DIR / slug / "source"
    if locked_path.exists():
        files = list(locked_path.glob("**/*"))
        exts = [f.suffix for f in files if f.is_file()]
        if ".rs" in exts:
            return "rust"
        if ".go" in exts:
            return "go"
        if ".c" in exts:
            return "c"
        if ".cpp" in exts or ".cc" in exts:
            return "cpp"
        if ".py" in exts:
            return "python"
        if ".java" in exts:
            return "java"
        if ".hs" in exts:
            return "haskell"
    return "unknown"


def is_core_language(lang: str) -> bool:
    return lang in CORE_LANGUAGES


# ------------------------------- RESOURCE MONITOR ----------------------- #


class ResourceMonitor:
    """Samples CPU/memory/Docker stats in a background thread."""

    def __init__(self, log_path: pathlib.Path):
        self.log_path = log_path
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._current = {"cpu_pct": 0.0, "mem_pct": 0.0, "docker_containers": 0}
        self._lock = threading.Lock()
        self._high_cpu_since = None  # type: Optional[float]

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=10)

    @property
    def current(self) -> dict:
        with self._lock:
            return dict(self._current)

    def should_pause(self) -> bool:
        """Return True if CPU has been consistently high for PAUSE_HOLD_SECS."""
        with self._lock:
            cpu = self._current.get("cpu_pct", 0)
        if cpu > PAUSE_CPU_PCT:
            if self._high_cpu_since is None:
                self._high_cpu_since = time.time()
            elif time.time() - self._high_cpu_since > PAUSE_HOLD_SECS:
                return True
        else:
            self._high_cpu_since = None
        return False

    def wait_for_headroom(self):
        """Block until CPU drops below RESUME_CPU_PCT."""
        while True:
            with self._lock:
                cpu = self._current.get("cpu_pct", 0)
            if cpu < RESUME_CPU_PCT:
                self._high_cpu_since = None
                return
            print(f"  [RESOURCE] CPU={cpu:.1f}% — waiting for headroom (<{RESUME_CPU_PCT}%)...")
            time.sleep(RESOURCE_INTERVAL)

    def _run(self):
        while not self._stop.is_set():
            sample = self._sample()
            with self._lock:
                self._current = sample
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.time(), **sample}) + "\n")
            except Exception:
                pass
            self._stop.wait(RESOURCE_INTERVAL)

    def _sample(self) -> dict:
        sample = {"ts": time.time()}
        # CPU & memory via psutil (fast, cross-platform)
        try:
            import psutil

            sample["cpu_pct"] = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            sample["mem_pct"] = mem.percent
            sample["mem_used_gb"] = round(mem.used / 1e9, 2)
            sample["mem_total_gb"] = round(mem.total / 1e9, 2)
            swap = psutil.swap_memory()
            sample["swap_pct"] = swap.percent
        except ImportError:
            # Fallback: wmic
            try:
                r = subprocess.run(
                    ["wmic", "cpu", "get", "loadpercentage", "/value"],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                for line in r.stdout.splitlines():
                    if "LoadPercentage=" in line:
                        sample["cpu_pct"] = float(line.split("=")[1].strip())
            except Exception:
                sample["cpu_pct"] = 0.0
            sample["mem_pct"] = 0.0

        # Docker container count
        try:
            r = subprocess.run(
                ["docker", "ps", "-q"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            sample["docker_containers"] = len([l for l in r.stdout.splitlines() if l.strip()])
        except Exception:
            sample["docker_containers"] = 0

        return sample


# ------------------------------- QUEUE BUILDER --------------------------- #


def build_eval_queue(phase: str = "pending") -> list[dict]:
    """
    Build the ordered eval queue.

    Order:
    1. pending_unlock tools (have submissions, need full re-eval) — sorted by score DESC
    2. board_cache_only tools with score > 0 — sorted by score DESC
    3. board_cache_only tools with score = 0
    4. All above sorted: core-language tools FIRST, non-core LAST

    Phase:
        pending  = only pending_unlock
        board    = only board_cache_only
        all      = everything (pending + board_cache)
    """
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    def enrich(d: dict) -> dict:
        lang = detect_language(d["slug"])
        d["detected_lang"] = lang
        d["is_core_lang"] = is_core_language(lang)
        ep = d.get("eval_report_path", "")
        if ep:
            p = pathlib.Path(ep).parent
            d["has_submission"] = (p / "submission.tar.gz").exists()
            d["locked_dir_path"] = str(p)
        else:
            d["has_submission"] = False
            d["locked_dir_path"] = ""
        return d

    pending = sorted(
        [enrich(d) for d in data if d["status"] == "pending_unlock"],
        key=lambda x: (-int(x["is_core_lang"]), -x.get("official_score_pct", 0)),
    )
    board_nonzero = sorted(
        [
            enrich(d)
            for d in data
            if d["status"] == "board_cache_only" and d.get("official_score_pct", 0) > 0
        ],
        key=lambda x: (-int(x["is_core_lang"]), -x.get("official_score_pct", 0)),
    )
    board_zero = [
        enrich(d)
        for d in data
        if d["status"] == "board_cache_only" and d.get("official_score_pct", 0) == 0
    ]

    if phase == "pending":
        return pending
    elif phase == "board":
        return board_nonzero + board_zero
    else:  # all
        return pending + board_nonzero + board_zero


# ------------------------------- SUBMISSION HELPER ----------------------- #


def find_submission_dir(tool: dict):
    """
    Find or create a staging directory on T: for this tool's submission.
    Returns a tuple of (submission_dir_path, instance_id).
    """
    slug = tool["slug"]

    # Search for the tarball in priority:
    # 1. pending_unlock priority subdirectories
    # 2. pending_unlock flat directory
    # 3. locked tier subdirectories
    # 4. locked flat legacy directory
    # For each, check for submission_uncapped.tar.gz first, then submission.tar.gz
    sub_tar = None
    search_dirs = [
        DETERMINEX_ROOT
        / "corpus"
        / "programbench"
        / "pending_unlock"
        / "priority_1_under100"
        / slug,
        DETERMINEX_ROOT
        / "corpus"
        / "programbench"
        / "pending_unlock"
        / "priority_2_under300"
        / slug,
        DETERMINEX_ROOT
        / "corpus"
        / "programbench"
        / "pending_unlock"
        / "priority_3_over300"
        / slug,
        DETERMINEX_ROOT / "corpus" / "programbench" / "pending_unlock" / slug,
        DETERMINEX_ROOT / "corpus" / "programbench" / "locked" / "tier_1_perfect" / slug,
        DETERMINEX_ROOT / "corpus" / "programbench" / "locked" / "tier_2_upstream_skips" / slug,
        DETERMINEX_ROOT / "corpus" / "programbench" / "locked" / slug,
    ]

    locked_dir_path = tool.get("locked_dir_path", "")
    if locked_dir_path:
        search_dirs.append(pathlib.Path(locked_dir_path))

    for sd in search_dirs:
        if sd.exists() and sd.is_dir():
            for name in ["submission_uncapped.tar.gz", "submission.tar.gz"]:
                p = sd / name
                if p.exists():
                    sub_tar = p
                    break
        if sub_tar:
            break

    if not sub_tar:
        print(f"  [ERROR] No submission tarball found for {slug}")
        return None

    # 1. Resolve instance_id by matching against ProgramBench data/tasks directory
    tasks_dir = PB_HARNESS_DIR / "src" / "programbench" / "data" / "tasks"
    if not tasks_dir.exists():
        print(f"  [ERROR] ProgramBench tasks directory not found at {tasks_dir}")
        return None

    task_dirs = [d.name for d in tasks_dir.iterdir() if d.is_dir()]
    instance_id = None
    clean_slug = slug.split("__")[-1] if "__" in slug else slug
    for td in task_dirs:
        parts = td.split("__")
        if len(parts) >= 2:
            name_part = parts[1].split(".")[0]
            if name_part == clean_slug or parts[1] == clean_slug or td == slug:
                instance_id = td
                break
        else:
            if td == slug or td.split(".")[0] == clean_slug:
                instance_id = td
                break

    if not instance_id:
        print(f"  [ERROR] Could not resolve instance_id for slug {slug}")
        return None

    dest = OUTPUT_ROOT / f"{slug}_submission"
    inst_dir = dest / instance_id
    inst_dir.mkdir(parents=True, exist_ok=True)

    target_tar = inst_dir / "submission.tar.gz"
    # Copy and overwrite to ensure fresh tarball (e.g. uncapped version is used)
    print(f"  Copying {sub_tar.name} -> {target_tar}")
    shutil.copy2(sub_tar, target_tar)

    return dest, instance_id


def clean_subprocess_env() -> dict:
    """Clean virtualenv variables from env so uv uses target virtualenv."""
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    path_val = env.get("PATH", "")
    if path_val:
        parts = path_val.split(os.pathsep)
        clean_parts = [p for p in parts if ".venv" not in p.lower()]
        env["PATH"] = os.pathsep.join(clean_parts)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ------------------------------- EVAL RUNNER --------------------------- #


def run_eval(
    tool: dict, submission_dir: pathlib.Path, instance_id: str, dry_run: bool = False
) -> dict:
    """
    Run `programbench eval` for one tool. Returns a result dict.
    """
    slug = tool["slug"]
    result_dir = OUTPUT_ROOT / f"{slug}_result"
    result_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "uv",
        "run",
        "programbench",
        "eval",
        str(submission_dir),
        "--filter",
        instance_id,
        "--force",
    ]

    print("\n" + "=" * 60)
    print(f"EVAL: {slug}")
    print(f"  Submission: {submission_dir}")
    print(f"  Result dir: {result_dir}")
    print(f"  Command:    {' '.join(cmd)}")
    print(
        f"  Lang:       {tool.get('detected_lang', '?')} (core={tool.get('is_core_lang', False)})"
    )
    print(
        f"  Old score:  {tool.get('official_score_pct', 0):.1f}% ({tool.get('official_passed', 0)}/{tool.get('official_total', 0)})"
    )
    print(
        f"  not_run:    {tool.get('official_not_run', 0)} (these were capped at 400, now running full suite)"
    )

    if dry_run:
        return {
            "slug": slug,
            "status": "dry_run",
            "ts": time.time(),
        }

    start_ts = time.time()
    stdout_lines = []
    stderr_lines = []

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PB_HARNESS_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            env=clean_subprocess_env(),
        )

        # Stream output while capturing it
        def stream_pipe(pipe, lines: list, prefix: str):
            for line in pipe:
                stripped = line.rstrip()
                lines.append(stripped)
                print(f"  {prefix} {stripped}")

        t_out = threading.Thread(target=stream_pipe, args=(proc.stdout, stdout_lines, "[PB]"))
        t_err = threading.Thread(target=stream_pipe, args=(proc.stderr, stderr_lines, "[ERR]"))
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=EVAL_TIMEOUT_SECS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return {
                "slug": slug,
                "status": "timeout",
                "elapsed_secs": round(time.time() - start_ts, 1),
                "ts": time.time(),
            }
        finally:
            t_out.join(timeout=10)
            t_err.join(timeout=10)

        elapsed = round(time.time() - start_ts, 1)
        returncode = proc.returncode

    except Exception as e:
        return {
            "slug": slug,
            "status": "error",
            "error": str(e),
            "elapsed_secs": round(time.time() - start_ts, 1),
            "ts": time.time(),
        }

    # Save raw output
    (result_dir / "stdout.txt").write_text("\n".join(stdout_lines), encoding="utf-8")
    (result_dir / "stderr.txt").write_text("\n".join(stderr_lines), encoding="utf-8")

    # Parse eval result directly from the output JSON if it exists
    eval_json_path = submission_dir / instance_id / f"{instance_id}.eval.json"
    eval_result = parse_eval_json(eval_json_path)
    if not eval_result:
        # Fallback to stdout/stderr parser if JSON is missing
        eval_result = parse_pb_output(stdout_lines, stderr_lines)
        if not eval_result.get("new_total"):
            # If stdout parsing also failed, set defaults
            eval_result = {
                "new_passed": 0,
                "new_failed": 0,
                "new_skipped": 0,
                "new_not_run": tool.get("official_not_run", 0),
                "new_total": tool.get("official_total", 0),
                "new_score_pct": 0.0,
                "new_status": "error",
                "eval_json_path": "",
            }

    result = {
        "slug": slug,
        "status": "completed",
        "returncode": returncode,
        "elapsed_secs": elapsed,
        "ts": time.time(),
        "result_dir": str(result_dir),
        "detected_lang": tool.get("detected_lang", "unknown"),
        "is_core_lang": tool.get("is_core_lang", False),
        "old_score_pct": tool.get("official_score_pct", 0),
        "old_passed": tool.get("official_passed", 0),
        "old_total": tool.get("official_total", 0),
        "old_not_run": tool.get("official_not_run", 0),
        **eval_result,
    }

    # Copy eval JSON from PB output location if it exists
    collect_eval_artifacts(slug, result_dir, eval_result)

    return result


def parse_eval_json(eval_json_path: pathlib.Path) -> dict:
    """Parse ProgramBench JSON eval results directly from the output file."""
    if not eval_json_path.exists():
        return {}
    try:
        data = json.loads(eval_json_path.read_text(encoding="utf-8"))
        test_results = data.get("test_results", [])

        passed = sum(1 for t in test_results if t.get("status") == "passed")
        failed = sum(1 for t in test_results if t.get("status") in ("failure", "error"))
        skipped = sum(1 for t in test_results if t.get("status") == "skipped")
        not_run = sum(1 for t in test_results if t.get("status") == "not_run")
        total = len(test_results)

        score_pct = 0.0
        new_status = "needs_work"
        if total > 0:
            score_pct = round(100.0 * passed / total, 4)
            if not_run == 0 and failed == 0:
                if skipped == 0:
                    new_status = "strict_lock"
                else:
                    new_status = "upstream_skips"
            elif score_pct >= 95.0:
                new_status = "near_lock"
            elif score_pct >= 70.0:
                new_status = "strong_candidate"

        return {
            "new_passed": passed,
            "new_failed": failed,
            "new_skipped": skipped,
            "new_not_run": not_run,
            "new_total": total,
            "new_score_pct": score_pct,
            "new_status": new_status,
            "eval_json_path": str(eval_json_path),
        }
    except Exception as e:
        print(f"  [ERROR] parsing JSON eval result {eval_json_path}: {e}")
        return {}


def parse_pb_output(stdout: list[str], stderr: list[str]) -> dict:
    """Parse ProgramBench eval output to extract pass/fail counts."""
    result = {
        "new_passed": 0,
        "new_failed": 0,
        "new_skipped": 0,
        "new_not_run": 0,
        "new_total": 0,
        "new_score_pct": 0.0,
        "new_status": "unknown",
        "eval_json_path": "",
    }

    all_lines = stdout + stderr
    for line in all_lines:
        # PB typically outputs: "passed=620 failed=0 skipped=1 not_run=0 total=671"
        # or a JSON summary at the end
        if "passed=" in line and "total=" in line:
            try:
                parts = {}
                for token in line.split():
                    if "=" in token:
                        k, v = token.split("=", 1)
                        parts[k.strip()] = int(v.strip())
                if "passed" in parts and "total" in parts:
                    result["new_passed"] = parts.get("passed", 0)
                    result["new_failed"] = parts.get("failed", 0)
                    result["new_skipped"] = parts.get("skipped", 0)
                    result["new_not_run"] = parts.get("not_run", 0)
                    result["new_total"] = parts.get("total", 0)
                    total = result["new_total"]
                    if total > 0:
                        result["new_score_pct"] = round(100.0 * result["new_passed"] / total, 4)
                    # Determine new status
                    if result["new_not_run"] == 0 and result["new_failed"] == 0:
                        if result["new_skipped"] == 0:
                            result["new_status"] = "strict_lock"
                        else:
                            result["new_status"] = "upstream_skips"
                    elif result["new_score_pct"] >= 95:
                        result["new_status"] = "near_lock"
                    elif result["new_score_pct"] >= 70:
                        result["new_status"] = "strong_candidate"
                    else:
                        result["new_status"] = "needs_work"
            except (ValueError, IndexError):
                pass

        # Look for JSON eval report path
        if "eval_report" in line.lower() and ".json" in line:
            for token in line.split():
                if ".json" in token and pathlib.Path(token.strip("\"'")).exists():
                    result["eval_json_path"] = token.strip("\"'")

    return result


def collect_eval_artifacts(slug: str, result_dir: pathlib.Path, eval_result: dict):
    r"""
    Copy or symlink the PB-generated eval artifacts into the result dir.
    PB writes to T:\determinex-programbench\<submission_dir>\ typically.
    """
    # Look for the most recently modified gate_result.json, eval_report.json, results.json or *.eval.json
    # in the current run's output root
    candidates = []
    for pattern in [
        "**/gate_result.json",
        "**/eval_report.json",
        "**/results.json",
        "**/*.eval.json",
    ]:
        candidates.extend(OUTPUT_ROOT.glob(pattern))

    if not candidates:
        return

    # Sort by modification time — most recent first
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Copy the most recent one that was modified in the last 10 minutes
    cutoff = time.time() - 600
    for c in candidates:
        if c.stat().st_mtime > cutoff and slug.lower() in str(c).lower():
            dest = result_dir / c.name
            shutil.copy2(str(c), str(dest))
            print(f"  [COLLECT] {c.name} -> {dest}")
            eval_result["eval_json_path"] = str(dest)
            break


# ------------------------------- INDEX UPDATER -------------------------- #


def update_index(result: dict):
    """Update eval_index.json with the new result for this tool."""
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        slug = result["slug"]
        for entry in data:
            if entry["slug"] == slug:
                new_passed = result.get("new_passed", 0)
                new_total = result.get("new_total", 0)
                new_not_run = result.get("new_not_run", 0)
                new_failed = result.get("new_failed", 0)
                new_skipped = result.get("new_skipped", 0)
                new_pct = result.get("new_score_pct", 0.0)
                new_status = result.get("new_status", "needs_work")

                entry["official_score_pct"] = new_pct
                entry["official_passed"] = new_passed
                entry["official_total"] = new_total
                entry["official_not_run"] = new_not_run
                entry["official_failed"] = new_failed
                entry["official_skipped"] = new_skipped
                entry["last_eval_source"] = "full_harness_post_uncap"
                entry["last_eval_time"] = datetime.datetime.utcnow().isoformat() + "+00:00"
                entry["detected_lang"] = result.get("detected_lang", "unknown")
                entry["is_core_lang"] = result.get("is_core_lang", False)

                # Reclassify status based on new strict rules
                if new_total > 0 and new_not_run == 0 and new_failed == 0:
                    if new_skipped == 0:
                        entry["status"] = "strict_lock"
                    else:
                        entry["status"] = "upstream_skips"
                elif new_total > 0:
                    entry["status"] = "board_cache_only"
                # else leave as-is if eval gave us nothing

                if result.get("result_dir"):
                    entry["result_dir_post_uncap"] = result["result_dir"]
                break

        # Atomic write
        tmp = INDEX_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(INDEX_PATH)
        print(f"  [INDEX] Updated {slug} -> {new_status} {new_pct:.1f}%")
    except Exception as e:
        print(f"  [INDEX] WARNING: failed to update index: {e}")


# ------------------------------- MAIN ---------------------------------- #


def main():
    parser = argparse.ArgumentParser(description="Determinex PB Full Eval Harness")
    parser.add_argument("--dry-run", action="store_true", help="Print queue, don't run")
    parser.add_argument("--resume", action="store_true", help="Skip already-completed tools")
    parser.add_argument("--filter", metavar="SLUG", help="Only run matching tool")
    parser.add_argument("--max", type=int, default=9999, help="Max tools to run")
    parser.add_argument(
        "--phase",
        choices=["pending", "board", "all"],
        default="pending",
        help="Which tools to run (default: pending)",
    )
    parser.add_argument("--start-from", metavar="SLUG", help="Start from this slug in queue")
    args = parser.parse_args()

    # Setup output dirs
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Build queue
    SEP = "=" * 60
    print(f"\n{SEP}")
    print("Determinex ProgramBench Full Eval Harness")
    print(f"Date:        {TODAY}")
    print(f"Phase:       {args.phase}")
    print(f"Output:      {OUTPUT_ROOT}")
    print(f"PB Harness:  {PB_HARNESS_DIR}")
    print(f"Dry run:     {args.dry_run}")
    print(f"{SEP}")

    queue = build_eval_queue(args.phase)

    # Apply filters
    if args.filter:
        queue = [t for t in queue if args.filter.lower() in t["slug"].lower()]

    if args.start_from:
        slugs = [t["slug"] for t in queue]
        if args.start_from in slugs:
            idx = slugs.index(args.start_from)
            queue = queue[idx:]

    # Load completed set if resuming
    completed_slugs = set()
    if args.resume and LOG_FILE.exists():
        for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if rec.get("status") == "completed":
                    completed_slugs.add(rec["slug"])
            except Exception:
                pass

    # Apply resume filter and max
    if args.resume:
        queue = [t for t in queue if t["slug"] not in completed_slugs]
    queue = queue[: args.max]

    # Summarize the queue with language core analysis
    core = [t for t in queue if t.get("is_core_lang", False)]
    non_core = [t for t in queue if not t.get("is_core_lang", False)]

    SEP2 = "-" * 60
    print(f"\n{SEP2}")
    print(f"QUEUE SUMMARY: {len(queue)} tools")
    print(f"  Core language (will run first): {len(core)}")
    print(f"  Non-core language (bottom of queue): {len(non_core)}")
    print(f"{SEP2}")

    # Print the full queue
    print("\nEVAL ORDER:")
    for i, t in enumerate(queue):
        core_flag = "Y" if t.get("is_core_lang") else "N"
        print(
            f"  {i + 1:3}. [{core_flag}] {t['slug']:<40} "
            f"{t.get('official_score_pct', 0):5.1f}%  "
            f"not_run={t.get('official_not_run', 0)}  "
            f"lang={t.get('detected_lang', '?')}"
        )

    if args.dry_run:
        print("\n[DRY RUN] No evals executed.")
        return

    # Pre-flight checks
    print("\n--- PRE-FLIGHT ---")
    # 1. Docker
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, encoding="utf-8", errors="replace", timeout=15
        )
        if r.returncode != 0:
            print("ERROR: Docker is not running. Start Docker Desktop and retry.")
            sys.exit(1)
        print("  [OK] Docker running")
    except Exception as e:
        print(f"ERROR: Cannot reach Docker: {e}")
        sys.exit(1)

    # 2. PB harness
    try:
        r = subprocess.run(
            ["uv", "run", "programbench", "--help"],
            cwd=str(PB_HARNESS_DIR),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=clean_subprocess_env(),
        )
        if r.returncode != 0:
            print(f"ERROR: ProgramBench harness not working at {PB_HARNESS_DIR}")
            print(r.stderr)
            sys.exit(1)
        print(f"  [OK] ProgramBench harness ready at {PB_HARNESS_DIR}")
    except Exception as e:
        print(f"ERROR: Cannot run ProgramBench harness: {e}")
        sys.exit(1)

    # 3. psutil (optional but recommended)
    try:
        import psutil

        print("  [OK] psutil available (accurate resource monitoring)")
    except ImportError:
        print("  [!] psutil not installed - using fallback CPU monitoring")
        print("      Install with: pip install psutil")

    # Start resource monitor
    monitor = ResourceMonitor(RESOURCE_LOG)
    monitor.start()
    print(f"  [OK] Resource monitor started (logging to {RESOURCE_LOG.name})")
    SEP = "=" * 60
    print(f"\n{SEP}")
    print("STARTING EVAL RUN")
    print(f"{SEP}\n")

    total_ran = 0
    total_promoted = 0
    total_regressed = 0
    summary_rows = []

    for i, tool in enumerate(queue):
        slug = tool["slug"]

        # Check resource headroom before each tool
        if monitor.should_pause():
            res = monitor.current
            print(
                f"\n[PAUSE] CPU={res.get('cpu_pct', 0):.1f}% has been high. Waiting for headroom..."
            )
            monitor.wait_for_headroom()
            print("[RESUME] CPU back to normal. Continuing.")

        print(f"\n[{i + 1}/{len(queue)}] Starting: {slug}")

        # Find or extract submission
        sub_info = find_submission_dir(tool)
        if sub_info is None:
            print(f"  [SKIP] No submission.tar.gz for {slug}")
            result = {
                "slug": slug,
                "status": "no_submission",
                "ts": time.time(),
            }
        else:
            submission_dir, instance_id = sub_info
            result = run_eval(tool, submission_dir, instance_id, dry_run=False)
            total_ran += 1

            # Track promotions/regressions
            old_pct = tool.get("official_score_pct", 0)
            new_pct = result.get("new_score_pct", 0)
            delta = new_pct - old_pct

            if result.get("new_status") in ("strict_lock", "upstream_skips"):
                total_promoted += 1
                print(f"  [PROMOTED] {slug} -> {result['new_status']} ({new_pct:.1f}%)")
            elif delta < -5:
                total_regressed += 1
                print(
                    f"  [⚠ REGRESSED] {slug}: {old_pct:.1f}% -> {new_pct:.1f}% (delta {delta:+.1f}%)"
                )
            else:
                print(f"  [→] {slug}: {old_pct:.1f}% -> {new_pct:.1f}% (delta {delta:+.1f}%)")

            # Update eval_index.json
            update_index(result)

        # Log result
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
        except Exception:
            pass

        summary_rows.append(
            {
                "slug": slug,
                "lang": tool.get("detected_lang", "?"),
                "core": tool.get("is_core_lang", False),
                "old_pct": tool.get("official_score_pct", 0),
                "new_pct": result.get("new_score_pct", 0),
                "new_status": result.get("new_status", result.get("status", "?")),
                "elapsed": result.get("elapsed_secs", 0),
            }
        )

        res = monitor.current
        print(
            f"  [RES] CPU={res.get('cpu_pct', 0):.1f}%  "
            f"MEM={res.get('mem_pct', 0):.1f}%  "
            f"Docker={res.get('docker_containers', 0)} containers"
        )

    # Stop monitor
    monitor.stop()

    # Write final summary
    summary_path = OUTPUT_ROOT / "summary.json"
    summary = {
        "run_date": TODAY,
        "phase": args.phase,
        "total_queued": len(queue),
        "total_ran": total_ran,
        "total_promoted_to_lock": total_promoted,
        "total_regressed": total_regressed,
        "results": summary_rows,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    SEP = "=" * 60
    print(f"\n{SEP}")
    print("RUN COMPLETE")
    print(f"{SEP}")
    print(f"  Tools queued:     {len(queue)}")
    print(f"  Tools ran:        {total_ran}")
    print(f"  New locks:        {total_promoted}")
    print(f"  Regressions:      {total_regressed}")
    print(f"  Summary:          {summary_path}")
    print(f"  Run log:          {LOG_FILE}")
    print(f"  Resource log:     {RESOURCE_LOG}")
    print(f"\nNext: Review {summary_path} for full results.")


if __name__ == "__main__":
    main()
