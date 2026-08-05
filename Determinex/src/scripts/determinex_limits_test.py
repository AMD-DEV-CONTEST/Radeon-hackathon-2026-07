#!/usr/bin/env python3
"""
determinex_limits_test.py — Progressive stress test for the Determinex Hive Mind compiler loop.

Runs 6 levels of increasing complexity through the full Oracle→Architect→Builder→Monitor→
Compiler Oracle pipeline and reports timing, retry counts, and pass/fail per level.

Usage:
    python scripts/determinex_limits_test.py
    python scripts/determinex_limits_test.py --levels 1,2,3     # only specific levels
    python scripts/determinex_limits_test.py --lang python       # python instead of rust
    python scripts/determinex_limits_test.py --no-rosetta        # disable Rosetta bridge
    python scripts/determinex_limits_test.py --timeout 300       # per-level timeout (seconds)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Level definitions ─────────────────────────────────────────────────────────
LEVELS_RUST = [
    {
        "id": 1,
        "name": "Hello World",
        "desc": "Canonical baseline — single fn, no dependencies, trivial compile.",
        "spec": """# Hello Determinex

## Goal
Print "Hello, Determinex!" to stdout and exit 0.

## Language
rust

## Constraints
- No external crates
- Single source file

## Files
- `src/main.rs` — entry point
""",
    },
    {
        "id": 2,
        "name": "CLI Args",
        "desc": "Argument parsing with early exit — tests branching + std::env.",
        "spec": """# CLI Greeter

## Goal
Accept a single CLI argument (a name). Print "Hello, <name>!" and exit 0.
If no argument is provided, print "Usage: greeter <name>" to stderr and exit 1.

## Language
rust

## Constraints
- No external crates
- Use std::env::args()

## Files
- `src/main.rs` — entry point
""",
    },
    {
        "id": 3,
        "name": "File I/O",
        "desc": "Read/write a file — tests error handling + std::fs.",
        "spec": """# Line Counter

## Goal
Read a file path from the first CLI argument.
Count the number of lines in that file.
Print "Lines: <count>" to stdout.
Handle errors (file not found, permission denied) with a clear message to stderr and exit 1.

## Language
rust

## Constraints
- No external crates
- Use std::fs::read_to_string for file reading
- Must handle all IO errors gracefully

## Files
- `src/main.rs` — entry point
""",
    },
    {
        "id": 4,
        "name": "Structs + Impl",
        "desc": "Custom types with methods — tests struct definition, impl blocks, Display.",
        "spec": """# Task Manager

## Goal
Implement a simple in-memory task list.

## Language
rust

## Constraints
- No external crates
- Must implement std::fmt::Display for Task
- Must not use unwrap() — use proper error handling

## Files
- `src/lib.rs` — Task struct, TaskList struct, add/complete/display methods
- `src/main.rs` — create a TaskList, add 3 tasks, complete one, print the list

## Notes
Task has: id (u32), title (String), done (bool).
TaskList wraps Vec<Task> with add(title: &str) -> u32 and complete(id: u32) -> bool.
""",
    },
    {
        "id": 5,
        "name": "Concurrency",
        "desc": "Shared state across threads — tests Arc<Mutex<T>>, thread spawn, join.",
        "spec": """# Concurrent Counter

## Goal
Spawn 4 threads. Each thread increments a shared counter 250 times.
After all threads complete, print the final count (should be 1000).

## Language
rust

## Constraints
- No external crates
- Use Arc<Mutex<u64>> for the shared counter
- Must join all threads before printing
- No data races — must compile with no unsafe

## Files
- `src/main.rs` — spawn threads, share Arc<Mutex<u64>>, join, print result
""",
    },
    {
        "id": 6,
        "name": "Serde JSON",
        "desc": "External crate, serialisation round-trip — tests Cargo.toml generation + full crate build.",
        "spec": """# Config Loader

## Goal
Load a JSON config file from the first CLI argument.
The config has: name (string), version (string), max_retries (u32).
Print each field on its own line: "name: <value>", "version: <value>", "max_retries: <value>".
If parsing fails, print the error to stderr and exit 1.

## Language
rust

## Dependencies
- serde — serialization framework
- serde_json — JSON support

## Constraints
- Must use #[derive(Deserialize)] on the config struct
- Must handle file-not-found and JSON parse errors separately

## Files
- `src/main.rs` — load args, read file, parse JSON, print fields

## Notes
Use serde = { version = "1", features = ["derive"] } in Cargo.toml.
""",
    },
]

LEVELS_PYTHON = [
    {
        "id": 1,
        "name": "Hello World",
        "desc": "Canonical baseline.",
        "spec": """# Hello Determinex

## Goal
Print "Hello, Determinex!" to stdout.

## Language
python

## Files
- `main.py` — entry point
""",
    },
    {
        "id": 2,
        "name": "CLI Args",
        "desc": "Argument parsing with argparse.",
        "spec": """# CLI Greeter

## Goal
Accept a single positional argument (name). Print "Hello, <name>!".
Use argparse. Exit code 0 on success.

## Language
python

## Files
- `main.py` — entry point
""",
    },
    {
        "id": 3,
        "name": "File I/O",
        "desc": "Read file, count lines, handle errors.",
        "spec": """# Line Counter

## Goal
Read a file path from sys.argv[1]. Count lines. Print "Lines: <count>".
Handle FileNotFoundError and PermissionError with clear stderr messages, sys.exit(1).

## Language
python

## Files
- `main.py` — entry point
""",
    },
    {
        "id": 4,
        "name": "Dataclass",
        "desc": "Typed dataclass with methods and __str__.",
        "spec": """# Task Manager

## Goal
Implement a simple in-memory task list using @dataclass.

## Language
python

## Files
- `task.py` — Task dataclass, TaskList class with add/complete/display
- `main.py` — create TaskList, add 3 tasks, complete one, print list
""",
    },
    {
        "id": 5,
        "name": "Threading",
        "desc": "Shared counter across threads with a Lock.",
        "spec": """# Concurrent Counter

## Goal
Spawn 4 threads. Each increments a shared counter 250 times (protected by threading.Lock).
After all threads join, print the final count (should be 1000).

## Language
python

## Files
- `main.py` — threads, Lock, join, print
""",
    },
    {
        "id": 6,
        "name": "JSON Config",
        "desc": "JSON round-trip with typed dataclass.",
        "spec": """# Config Loader

## Goal
Load a JSON config file from sys.argv[1].
Config fields: name (str), version (str), max_retries (int).
Print each field. Handle FileNotFoundError and json.JSONDecodeError separately.

## Language
python

## Files
- `main.py` — load file, parse JSON into dataclass, print fields
""",
    },
]


# ── Hive runner ───────────────────────────────────────────────────────────────


def run_hive_build(spec_content: str, lang: str, timeout: int) -> dict:
    """
    Full build via determinex_hive.py subcommands:
      1. new-session  → creates session dir + manifest, returns session_id
      2. generate-dag → Oracle + Architect populate step manifest
      3. run-session  → Builder + Monitor + Compiler Oracle execute all steps
    """
    import tempfile

    hive_script = REPO_ROOT / "scripts" / "determinex_hive.py"
    if not hive_script.exists():
        return {"ok": False, "error": f"determinex_hive.py not found at {hive_script}"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(spec_content)
        spec_path = f.name

    def run_cmd(args: list, step_timeout: int) -> tuple[int, str, str]:
        cmd = [sys.executable or "python", str(hive_script)] + args
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=step_timeout,
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "PYTHONUNBUFFERED": "1",
            },
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()

    def extract_session_id(stdout: str) -> str | None:
        # Look for JSON {"session_id": "..."} or plain "session_id: ..."
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    sid = data.get("session_id") or (data.get("data") or {}).get("session_id")
                    if sid:
                        return str(sid)
                except json.JSONDecodeError:
                    pass
            m = re.search(
                r'(?:session[_-]?id|session created|new session)["\s:=]+([a-zA-Z0-9_-]{8,})',
                line,
                re.I,
            )
            if m:
                return m.group(1)
        return None

    try:
        # ── Step 1: create session ─────────────────────────────────────────
        rc, out, err = run_cmd(
            ["new-session", "--spec", spec_path, "--lang", lang, "--budget", "0"],
            step_timeout=60,
        )
        session_id = extract_session_id(out) or extract_session_id(err)
        if rc != 0 or not session_id:
            return {
                "ok": False,
                "error": f"new-session failed (rc={rc})",
                "stdout": out[-1000:],
                "stderr": err[-500:],
            }

        # ── Step 2: generate DAG ──────────────────────────────────────────
        rc, out, err = run_cmd(
            ["generate-dag", "--session", session_id],
            step_timeout=min(timeout, 300),
        )
        if rc != 0:
            return {
                "ok": False,
                "error": f"generate-dag failed (rc={rc})",
                "session_id": session_id,
                "stdout": out[-1000:],
                "stderr": err[-500:],
            }

        # ── Step 3: run session ───────────────────────────────────────────
        rc, out, err = run_cmd(
            ["run-session", "--session", session_id],
            step_timeout=timeout,
        )

        # Read final manifest for step-level detail
        session_dir = REPO_ROOT / "sessions" / session_id
        manifest_path = session_dir / "manifest.json"
        steps = []
        final_status = "complete" if rc == 0 else "failed"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                steps = manifest.get("steps", [])
                final_status = manifest.get("status", final_status)
            except Exception:
                pass

        return {
            "ok": final_status == "complete",
            "session_id": session_id,
            "status": final_status,
            "steps": steps,
            "stdout": out[-1000:] if rc != 0 else "",
            "stderr": err[-500:] if rc != 0 else "",
        }

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        Path(spec_path).unlink(missing_ok=True)


def fallback_run(spec_content: str, lang: str, timeout: int, level_id: int) -> dict:
    """Try HTTP API first (if hive daemon is running), fall back to subprocess."""
    import urllib.request

    try:
        urllib.request.urlopen("http://localhost:8765/health", timeout=2)
        return _run_via_http(spec_content, lang, timeout, level_id)
    except Exception:
        pass
    return run_hive_build(spec_content, lang, timeout)


def _run_via_http(spec_content: str, lang: str, timeout: int, level_id: int) -> dict:
    import json as _json
    import tempfile
    import urllib.error
    import urllib.request

    base = "http://localhost:8765"
    headers = {"Content-Type": "application/json"}

    def post(path, body):
        data = _json.dumps(body).encode()
        req = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return _json.loads(r.read())

    def get(path):
        req = urllib.request.Request(f"{base}{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return _json.loads(r.read())

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(spec_content)
        spec_path = f.name

    try:
        sess = post("/session/create", {"spec_path": spec_path, "lang": lang, "budget": 5.0})
        session_id = sess["data"]["session_id"]

        post("/session/generate-dag", {"session_id": session_id})
        post("/session/run", {"session_id": session_id})

        deadline = time.time() + timeout
        while time.time() < deadline:
            status = get(f"/session/status/{session_id}")
            data = status.get("data", {})
            if data.get("status") in ("complete", "failed"):
                return {
                    "ok": data["status"] == "complete",
                    "session_id": session_id,
                    "steps": data.get("steps", []),
                    "status": data["status"],
                }
            time.sleep(3)

        return {"ok": False, "error": "Timeout waiting for session to complete"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        Path(spec_path).unlink(missing_ok=True)


# ── Report helpers ─────────────────────────────────────────────────────────────


def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def count_retries(result: dict) -> int:
    steps = result.get("steps", [])
    retries = 0
    for step in steps:
        retries += step.get("attempts", 1) - 1
    return retries


def print_header():
    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  Determinex Limits Test — Compiler Loop Stress Suite{RESET}")
    print(f"{CYAN}{'=' * 60}{RESET}\n")


def print_level_header(level: dict):
    print(f"{BOLD}Level {level['id']} — {level['name']}{RESET}")
    print(f"{DIM}  {level['desc']}{RESET}")


def print_result(level: dict, result: dict, elapsed: float):
    ok = result.get("ok", False)
    retries = count_retries(result)
    status_str = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    retry_str = f"{YELLOW}{retries} retries{RESET}" if retries > 0 else f"{DIM}0 retries{RESET}"
    print(f"  {status_str}  {fmt_time(elapsed)}  {retry_str}")

    if not ok:
        err = result.get("error") or "unknown error"
        print(f"  {RED}{err}{RESET}")

        # Also print the actual subprocess stderr if available
        stderr_out = result.get("stderr", "").strip()
        if stderr_out:
            print(f"\n  {RED}--- STDERR ---{RESET}")
            for line in stderr_out.splitlines()[-20:]:  # last 20 lines
                print(f"  {DIM}{line}{RESET}")
            print(f"  {RED}--------------{RESET}\n")

    steps = result.get("steps", [])
    if steps:
        for step in steps:
            sid = step.get("id", "?")
            st = step.get("status", "?")
            colour = GREEN if st == "complete" else RED if st == "failed" else YELLOW
            compiler = step.get("compiler_result", "")
            comp_str = f" [{compiler}]" if compiler else ""
            print(f"  {DIM}step {sid}: {colour}{st}{RESET}{DIM}{comp_str}{RESET}")


def print_summary(results: list[dict]):
    print(f"\n{BOLD}{CYAN}{'-' * 60}{RESET}")
    print(f"{BOLD}  Results Summary{RESET}\n")

    passed = sum(1 for r in results if r["result"].get("ok"))
    total = len(results)
    total_time = sum(r["elapsed"] for r in results)
    total_retries = sum(count_retries(r["result"]) for r in results)

    for r in results:
        ok = r["result"].get("ok", False)
        icon = f"{GREEN}[OK]{RESET}" if ok else f"{RED}[ERR]{RESET}"
        print(
            f"  {icon}  L{r['id']} {r['name']:<20} {fmt_time(r['elapsed']):<10} "
            f"{count_retries(r['result'])} retries"
        )

    print(
        f"\n  Passed: {GREEN}{passed}/{total}{RESET}  "
        f"Total time: {fmt_time(total_time)}  "
        f"Total retries: {total_retries}"
    )

    if passed == total:
        print(f"\n  {GREEN}{BOLD}All levels passed — compiler loop fully functional.{RESET}")
    elif passed >= 4:
        print(f"\n  {YELLOW}{BOLD}Core loop working. Higher-complexity levels struggling.{RESET}")
    elif passed >= 2:
        print(f"\n  {YELLOW}Partial function — investigate failing levels.{RESET}")
    else:
        print(f"\n  {RED}{BOLD}Compiler loop is not functional. Check model availability.{RESET}")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Determinex Hive Mind limits test")
    parser.add_argument(
        "--levels", default="1,2,3,4,5,6", help="Comma-separated level IDs to run (default: all)"
    )
    parser.add_argument(
        "--lang", choices=["rust", "python"], default="rust", help="Target language (default: rust)"
    )
    parser.add_argument(
        "--timeout", type=int, default=600, help="Per-level timeout in seconds (default: 600)"
    )
    parser.add_argument(
        "--no-rosetta", action="store_true", help="Disable Rosetta bridge for this run"
    )
    args = parser.parse_args()

    selected_ids = {int(x.strip()) for x in args.levels.split(",")}
    levels = LEVELS_RUST if args.lang == "rust" else LEVELS_PYTHON
    levels = [l for l in levels if l["id"] in selected_ids]

    if args.no_rosetta:
        os.environ["DETERMINEX_NO_ROSETTA"] = "1"

    print_header()
    print(
        f"  Language: {CYAN}{args.lang}{RESET}  "
        f"Levels: {CYAN}{args.levels}{RESET}  "
        f"Timeout: {CYAN}{args.timeout}s per level{RESET}"
    )
    if args.no_rosetta:
        print(f"  {YELLOW}Rosetta bridge: DISABLED{RESET}")
    print()

    all_results = []

    for level in levels:
        print_level_header(level)
        t0 = time.time()

        try:
            result = fallback_run(level["spec"], args.lang, args.timeout, level["id"])
        except KeyboardInterrupt:
            print(f"\n  {YELLOW}Interrupted at level {level['id']}{RESET}")
            break
        except Exception as e:
            result = {"ok": False, "error": str(e)}

        elapsed = time.time() - t0
        print_result(level, result, elapsed)
        print()

        all_results.append(
            {
                "id": level["id"],
                "name": level["name"],
                "result": result,
                "elapsed": elapsed,
            }
        )

        # Stop on catastrophic failure (level 1 or 2 failed — something is broken)
        if not result.get("ok") and level["id"] <= 2:
            print(f"  {RED}Stopping early — baseline level {level['id']} failed.{RESET}")
            print(
                f"  {DIM}Check: is Ollama running? Are models loaded? Is determinex_hive.py wired?{RESET}\n"
            )
            break

    if all_results:
        print_summary(all_results)

    # Write JSON report
    report_path = REPO_ROOT / "determinex_limits_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "lang": args.lang,
                "results": all_results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\n  {DIM}Report written to {report_path}{RESET}\n")


if __name__ == "__main__":
    main()
