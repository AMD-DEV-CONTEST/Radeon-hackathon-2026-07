#!/usr/bin/env python3
"""Corpus-first ProgramBench churn supervisor.

This is the unattended lane for Addendum H/I:

  corpus consult -> spec extraction -> native reimpl with a free local model
  -> local oracle -> official eval only after local green

It deliberately does one bounded action per tool per pass. That makes the loop
restartable, keeps failure evidence small, and prevents the old broad-eval
failure mode where a watch process could spend official evals before the corpus
or local oracle had approved the candidate.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"
EVAL_INDEX = PB / "eval_index.json"
OVERRIDES = PB / "per_tool_overrides"
SPECS = PB / "specs"
ORACLE_RESULTS = PB / "oracle_results"
LOG_DIR = ROOT / "logs"
STATE_PATH = LOG_DIR / "pb_churn_state.json"
EVENTS_PATH = LOG_DIR / "pb_churn_events.jsonl"
HANDBACK = ROOT / "CODEX_HANDBACK.md"
WATCH_LOCK_PATH = LOG_DIR / "pb_churn_watch.lock"


def _configured_secret(name: str) -> bool:
    if os.environ.get(name):
        return True
    env_path = ROOT / ".env"
    if not env_path.exists():
        return False
    prefix = f"{name}="
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
                continue
            return bool(stripped.split("=", 1)[1].strip().strip("'\""))
    except OSError:
        return False
    return False


def default_model_ladder() -> str:
    configured = os.environ.get("DETERMINEX_PB_CHURN_MODEL")
    if configured:
        return configured
    # 2026-07-02: default lane is local-only, EXCEPT for OpenRouter's free Qwen3-Coder-480B
    # lane, which -- unlike the free Gemini lane -- is well-provisioned for real k=8/rounds=3
    # amplification (20 req/min, 50-1000 req/day, 1M ctx; a full k=8/rounds=3 attempt issues
    # at most ~24 requests) and needs no --no-decompose/240s survival hacks (see
    # _uses_cloud_station_avoidance / _reimpl_timeout_s -- it does not match either, so it
    # gets the full local-grade timeout). Gated purely on key presence: no key configured,
    # no accidental use. The free Gemini lane still requires the explicit
    # DETERMINEX_PB_CHURN_ALLOW_CLOUD=1 opt-in -- it forces k=1/rounds=1 and a 240s timeout to
    # survive rate limits, which disables VerifiedSearch amplification entirely and was the
    # root cause of the churn loop's original 0-lock outcome.
    # Local lane (2026-07-02): the 7b->14b ESCALATION LADDER, not a flat single model.
    # The 7b (4.7GB) fits fully in a 6GB GPU (~100% GPU); the 14b (9-13GB) runs 70/30
    # CPU-bound. Router semantics: 7b clears the cheap bulk, 14b only the missed tail.
    local_ladder = "ollama/qwen2.5-coder:7b-instruct:1:1,ollama/qwen2.5-coder:14b-instruct:2:3"
    if _configured_secret("OPENROUTER_API_KEY"):
        return f"openrouter/qwen/qwen3-coder:free,{local_ladder}"
    if os.environ.get("DETERMINEX_PB_CHURN_ALLOW_CLOUD") == "1" and (
        _configured_secret("GEMINI_API_KEY") or _configured_secret("GOOGLE_API_KEY")
    ):
        return f"gemini-3.1-flash-lite,{local_ladder}"
    return local_ladder


DEFAULT_MODEL = default_model_ladder()
DEFAULT_WORKER = os.environ.get("DETERMINEX_WORKER", "codex-churn")
TERMINAL_STATUSES = {
    "strict_lock",
    "locked",
    "ceiling_certified",
    "ceiling_confirmed",
    "impossible_ceiling",
}
DEFAULT_COOLDOWN_SECONDS = int(os.environ.get("DETERMINEX_PB_CHURN_COOLDOWN_SECONDS", "86400"))
ALWAYS_COOLDOWN_ACTIONS = {"official-eval"}
NO_COMMAND_COOLDOWN_ACTIONS = {"consult-only", "hold-official-eval", "hold-low-roi-cloud-reimpl"}
DEFAULT_CLOUD_REIMPL_MAX_EXAMPLES = int(
    os.environ.get("DETERMINEX_PB_CLOUD_REIMPL_MAX_EXAMPLES", "80")
)


@dataclass(frozen=True)
class ChurnAction:
    name: str
    command: str
    reason: str
    official_eval: bool = False
    timeout_s: int = 1800


@dataclass(frozen=True)
class ChurnContext:
    slug: str
    route: Any
    model: str = DEFAULT_MODEL
    spec_path: str | None = None
    candidate_path: str | None = None
    allow_official: bool = False
    lang: str | None = None
    iters: int = 2
    fuzz: int = 20
    k: int = 2
    rounds: int = 1
    # ISO ts of the saved local-oracle verdict, if any (see load_oracle_result).
    # Lets next_action tell a candidate the oracle ALREADY judged red apart from
    # a fresh candidate written after that verdict.
    oracle_ts: str | None = None


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    # WINDOWS (2026-07-03): os.kill(pid, 0) on a DEAD pid raises SystemError
    # ("returned a result with an exception set"), not ProcessLookupError -- the
    # old except-list missed it, so _pid_running CRASHED on a stale lock instead of
    # returning False, and the supervisor could never reclaim its own watch lock
    # after a restart (every respawn died rc=1). Use OpenProcess + exit-code probe.
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return False  # no such process (or gone)
            try:
                code = wintypes.DWORD()
                if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == 259  # STILL_ACTIVE
                return True  # exists but couldn't read code -> assume alive
            finally:
                k32.CloseHandle(h)
        except Exception:
            return False  # can't prove it's alive -> treat as dead (lock reclaimable)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def acquire_watch_lock(path: Path = WATCH_LOCK_PATH) -> tuple[bool, int | None, str]:
    """Acquire the singleton watch-loop lock.

    Per-tool Redis leases stop two workers from acting on the same slug. They do
    not stop two detached --watch loops from taking turns across passes. This
    host-local lock is intentionally simple and stale-PID aware.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "ts": _now()}
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
            return True, fd, ""
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8", errors="replace") or "{}")
            except Exception:
                existing = {}
            try:
                pid = int(existing.get("pid") or 0)
            except Exception:
                pid = 0
            if pid and not _pid_running(pid):
                try:
                    path.unlink()
                    continue
                except FileNotFoundError:
                    continue
                except OSError as e:
                    return False, None, f"stale lock could not be removed: {e}"
            return False, None, f"watch lock held by pid={pid or 'unknown'}"


def release_watch_lock(fd: int | None, path: Path = WATCH_LOCK_PATH) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        existing = json.loads(path.read_text(encoding="utf-8", errors="replace") or "{}")
        if int(existing.get("pid") or 0) == os.getpid():
            path.unlink()
    except Exception:
        pass


def _short(slug: str) -> str:
    s = slug.split("__", 1)[1] if "__" in slug else slug
    return s.split(".", 1)[0].replace("_native", "").replace("_model", "").lower()


def _cmd(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(p)) for p in parts)


def _script(name: str) -> str:
    return f"scripts/{name}"


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", slug)


def _slug_cooldown_keys(slug: str) -> set[str]:
    slug_text = str(slug or "").strip()
    if not slug_text:
        return set()
    short = slug_text.split("__")[-1].split(".")[0]
    keys = {slug_text, short}
    if "__" in slug_text and "." in slug_text:
        keys.add(slug_text.rsplit(".", 1)[0])
    return keys


def _parse_state_ts(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ts = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=_dt.UTC)
    return ts


def _run_rc(run: dict[str, Any]) -> int | None:
    result = run.get("result")
    if not isinstance(result, dict):
        return None
    rc = result.get("rc")
    if rc is None:
        return None
    try:
        return int(rc)
    except (TypeError, ValueError):
        return None


def should_cool_down_run(
    run: dict[str, Any],
    *,
    slug: str | None = None,
    now: _dt.datetime | None = None,
    cooldown_s: int = DEFAULT_COOLDOWN_SECONDS,
) -> bool:
    """Return true when a recent churn result should leave the slug alone.

    A timeout or failed bounded action should not keep the same high-score tool
    pinned at the front of the queue. A successful stage transition should stay
    eligible so the conveyor can move from spec extraction to reimpl to oracle.
    """
    if cooldown_s <= 0 or not isinstance(run, dict) or not run.get("executed"):
        return False
    ts = _parse_state_ts(run.get("ts"))
    if ts is None:
        return False
    now = now or _dt.datetime.now(_dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.UTC)
    if (now - ts).total_seconds() >= cooldown_s:
        return False

    action = run.get("action") if isinstance(run.get("action"), dict) else {}
    action_name = str((action or {}).get("name") or "")
    if action_name in ALWAYS_COOLDOWN_ACTIONS:
        return True

    rc = _run_rc(run)
    if rc is None:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        return action_name in NO_COMMAND_COOLDOWN_ACTIONS or bool(result.get("skipped"))
    if rc == 0:
        if action_name == "write-native-reimpl" and not run.get("candidate_path"):
            return True
        # EMPTY-HARVEST FIX (2026-07-10): pb_bulk_spec exits 0 even when a task's
        # test branches yield nothing harvestable (writes n_examples=0). Without
        # this, the slug re-selects extract-spec forever at rc=0 — never cooled,
        # never progressing (observed on quinn/jsonschema on the box).
        if action_name == "extract-spec" and slug and not _local_spec_path(slug):
            return True
        if action_name == "local-oracle":
            oracle = (
                run.get("oracle_result_saved")
                if isinstance(run.get("oracle_result_saved"), dict)
                else {}
            )
            try:
                total = int((oracle or {}).get("total") or 0)
            except (TypeError, ValueError):
                total = 0
            if total <= 0:
                return True
        return False
    return True


def cooldown_blocked_slugs(
    state: dict[str, Any] | None,
    *,
    now: _dt.datetime | None = None,
    cooldown_s: int = DEFAULT_COOLDOWN_SECONDS,
) -> set[str]:
    runs = (state or {}).get("runs", {})
    if not isinstance(runs, dict):
        return set()
    blocked: set[str] = set()
    for slug, run in runs.items():
        if should_cool_down_run(run, slug=str(slug), now=now, cooldown_s=cooldown_s):
            blocked.update(_slug_cooldown_keys(str(slug)))
    return blocked


def queue_from_eval_rows(
    rows: list[dict[str, Any]],
    state: dict[str, Any] | None = None,
    *,
    include_locked: bool = False,
    include_ceilings: bool = False,
    cooldown_s: int = DEFAULT_COOLDOWN_SECONDS,
    now: _dt.datetime | None = None,
) -> list[str]:
    """Return canonical non-alias ProgramBench rows ordered by likely payoff.

    PRODUCTIVE BIAS (2026-07-10): readiness is the primary key. A harvested spec,
    existing candidate, or green local oracle is paid-host work that can advance the
    conveyor; it must not sit behind hundreds of cold tools that only need another
    free spec harvest. Breadth/least-recently-touched remains a tie-breaker within
    the same readiness tier so the loop still avoids re-hammering one warm tool when
    several equally productive tools are available.
    """
    runs = (state or {}).get("runs", {}) if isinstance(state, dict) else {}
    runs = runs if isinstance(runs, dict) else {}

    # VARIANT-AWARE touch index (2026-07-03 fix): the queue yields SHORT slugs (`bore`)
    # but state records FULL slugs (`ekzhang__bore.8e059cd`), so a naive runs.get(slug)
    # saw every short-slug tool as never-touched and kept re-surfacing it at the front --
    # the exact "we keep doing the same tools" bug the breadth bias was meant to kill.
    # Map every run's slug variants ({full, short, author__repo}) -> its most-recent ts,
    # matching how the cooldown already resolves variants.
    touch_ts: dict[str, str] = {}
    for _rslug, _rec in runs.items():
        if not isinstance(_rec, dict):
            continue
        _ts = str(_rec.get("ts") or "")
        if not _ts:
            continue
        for _k in _slug_cooldown_keys(_rslug):
            if _ts > touch_ts.get(_k, ""):
                touch_ts[_k] = _ts

    def _touch_key(slug: str) -> tuple[int, str]:
        # Breadth: never-touched tools first (set up EVERY tool before deepening any),
        # then touched tools oldest-run-first (round-robin -- a tool that just ran goes
        # to the back, so the loop cannot sit on atlas/csview/walk). Resolves the queue
        # slug's OWN variants against the touch index so short/full forms agree.
        best = ""
        for _k in _slug_cooldown_keys(slug):
            _t = touch_ts.get(_k, "")
            if _t > best:
                best = _t
        return (0, "") if not best else (1, best)

    out: list[tuple[int, tuple[int, str], float, str]] = []
    seen: set[str] = set()
    blocked_slugs = cooldown_blocked_slugs(state, now=now, cooldown_s=cooldown_s)

    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or row.get("id") or "").strip()
        if not slug or slug in seen or slug in blocked_slugs:
            continue
        if _slug_cooldown_keys(slug) & blocked_slugs:
            continue
        if row.get("alias_of"):
            continue
        status = str(row.get("status") or "").strip().lower()
        if not include_locked and status in {"strict_lock", "locked"}:
            continue
        if not include_ceilings and status in TERMINAL_STATUSES - {"strict_lock", "locked"}:
            continue
        seen.add(slug)
        score = row.get("official_score_pct", row.get("score", 0.0))
        try:
            sort_score = float(score)
        except (TypeError, ValueError):
            sort_score = 0.0
        out.append((_readiness_priority(slug), _touch_key(slug), -sort_score, slug))
    return [slug for _, _, _, slug in sorted(out)]


def _load_eval_rows(path: Path = EVAL_INDEX) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [r for r in data.values() if isinstance(r, dict)]
    return []


def _spec_is_empty_harvest(path: Path) -> bool:
    """True when a spec file records a CONFIRMED zero-example harvest.

    pb_bulk_spec writes {"n_examples": 0, "examples": []} when a task's test
    branches yield nothing harvestable; treating that as a usable spec advances
    the conveyor to reimpl passes with no oracle signal behind them. Only an
    explicit zero counts — a placeholder or foreign spec without the field is
    NOT empty (unknown != empty), so pre-existing minimal specs stay usable.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or "n_examples" not in data:
        return False
    try:
        return int(data.get("n_examples") or 0) <= 0
    except (TypeError, ValueError):
        return False


def _local_spec_path(slug: str, answer: dict[str, Any] | None = None) -> str | None:
    spec = (answer or {}).get("spec") if isinstance(answer, dict) else None
    if isinstance(spec, dict) and spec.get("path"):
        return str(spec["path"])
    for name in (slug, _short(slug)):
        p = SPECS / f"{name}.json"
        if p.exists() and not _spec_is_empty_harvest(p):
            return str(p)
        matches = sorted(
            SPECS.glob(f"{name}.*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        )
        for m in matches:
            if not _spec_is_empty_harvest(m):
                return str(m)
    return None


def _readiness_priority(slug: str) -> int:
    """Lower is better: spend passes on already-promotable evidence before cold generation."""
    oracle = load_oracle_result(slug)
    spec_path = _local_spec_path(slug)
    candidate = _candidate_for(slug)
    if oracle and int(oracle.get("total") or 0) > 0 and oracle.get("passed") == oracle.get("total"):
        return 0
    if spec_path and candidate:
        return 1
    if spec_path:
        examples = _spec_example_count(spec_path)
        if examples is not None:
            max_examples = int(
                os.environ.get(
                    "DETERMINEX_PB_CLOUD_REIMPL_MAX_EXAMPLES",
                    str(DEFAULT_CLOUD_REIMPL_MAX_EXAMPLES),
                )
            )
            if examples > max_examples:
                return 5
        return 2
    if candidate:
        return 3
    return 4


def _lang_from_spec(spec_path: str | None) -> str | None:
    if not spec_path:
        return None
    try:
        data = json.loads(
            (ROOT / spec_path if not Path(spec_path).is_absolute() else Path(spec_path)).read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None
    lang = str(data.get("language") or "").strip().lower()
    return lang or None


def _spec_example_count(spec_path: str | None) -> int | None:
    if not spec_path:
        return None
    try:
        data = json.loads(
            (ROOT / spec_path if not Path(spec_path).is_absolute() else Path(spec_path)).read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "n_examples" in data:
        try:
            return int(data.get("n_examples") or 0)
        except (TypeError, ValueError):
            return None
    examples = data.get("examples")
    return len(examples) if isinstance(examples, list) else None


_NATIVE_SOURCE = {
    "rust": ("main.rs", "rustc -O -o executable main.rs"),
    # go build in module mode (1.16+) needs a go.mod IN THE CANDIDATE DIR, else it
    # walks up and fails on the repo's own .git ("cannot find main module, but found
    # .git/config in <repo>/") -- which silently red'd EVERY go tool's local
    # oracle. The in-search compile (observe._compile_native) and the official eval
    # template already `go mod init` first; this path was the lone straggler. Match
    # them (GOPROXY=off = offline, stdlib resolves from GOROOT). Fixed 2026-07-03.
    "go": (
        "main.go",
        "export GO111MODULE=on GOFLAGS=-mod=mod GOPROXY=off\n"
        "go mod init m 2>/dev/null || true\ngo build -o executable .",
    ),
    "c": (
        "main.c",
        "{ command -v cc >/dev/null && cc -O2 -o executable main.c; } || gcc -O2 -o executable main.c",
    ),
    "cpp": (
        "main.cpp",
        "{ command -v c++ >/dev/null && c++ -O2 -std=c++17 -o executable main.cpp; } || g++ -O2 -std=c++17 -o executable main.cpp",
    ),
    "haskell": ("main.hs", "ghc -O2 -o executable main.hs"),
}


def _infer_candidate_lang(path: Path, preferred: str | None = None) -> str:
    preferred = (preferred or "").lower()
    if preferred in _NATIVE_SOURCE or preferred == "python":
        return preferred
    suffix_map = {
        ".rs": "rust",
        ".go": "go",
        ".c": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".hs": "haskell",
    }
    if path.suffix.lower() in suffix_map:
        return suffix_map[path.suffix.lower()]
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return preferred or "python"
    if "use std::" in head or "fn main" in head:
        return "rust"
    if re.search(r"(?m)^\s*package\s+main\b", head):
        return "go"
    if "#include" in head and ("int main" in head or " main(" in head):
        return (
            "cpp"
            if any(tok in head for tok in ("std::", "#include <iostream>", "using namespace std"))
            else "c"
        )
    return preferred or "python"


def _candidate_for_oracle(candidate: str | None, lang: str | None, slug: str) -> str | None:
    """Stage native single-file candidates so determinex_local_oracle compiles them.

    Some reimpl runs historically wrote native source into a ``*_drive.py`` file.
    Passing that directly to the local oracle executes Rust/Go/C as Python. The
    local oracle already supports native compile directories, so create one.
    """
    if not candidate:
        return None
    p = Path(candidate)
    if not p.is_absolute():
        p = ROOT / p
    if p.is_dir():
        return str(p)
    if not p.exists():
        return candidate
    inferred = _infer_candidate_lang(p, lang)
    if inferred == "python" and p.suffix.lower() == ".py":
        return str(p)
    if inferred not in _NATIVE_SOURCE:
        return str(p)
    src_name, compile_cmd = _NATIVE_SOURCE[inferred]
    out = ROOT / "logs" / "reimpl_native" / _safe_slug(slug)
    out.mkdir(parents=True, exist_ok=True)
    (out / src_name).write_text(
        p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8", newline="\n"
    )
    compile_sh = out / "compile.sh"
    compile_sh.write_text(
        f'#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\n{compile_cmd}\n', encoding="utf-8", newline="\n"
    )
    try:
        compile_sh.chmod(0o755)
    except OSError:
        pass
    return str(out)


def _candidate_for_official(candidate: str | None, lang: str | None) -> str | None:
    if not candidate:
        return None
    p = Path(candidate)
    if not p.is_absolute():
        p = ROOT / p
    if not p.is_dir():
        return str(p)
    src_name = _NATIVE_SOURCE.get((lang or "").lower(), ("main.py", ""))[0]
    src = p / src_name
    return str(src) if src.exists() else str(p)


def _candidate_for(slug: str, answer: dict[str, Any] | None = None) -> str | None:
    """Find the safest current candidate for local oracle.

    Upstream-source override dirs are intentionally not used as candidates.
    """
    shape = ((answer or {}).get("source_shape") or {}) if isinstance(answer, dict) else {}
    short = _short(slug)
    candidates: list[Path] = []
    reimpl_dir = ROOT / "logs" / "reimpl"
    if reimpl_dir.is_dir():
        candidates.extend(
            sorted(
                reimpl_dir.glob(f"{short}_drive.*"), key=lambda p: p.stat().st_mtime, reverse=True
            )
        )
        candidates.extend(
            sorted(reimpl_dir.glob(f"{short}_*.py"), key=lambda p: p.stat().st_mtime, reverse=True)
        )
    if shape.get("class") == "reimpl-candidate":
        d = OVERRIDES / slug
        if (d / "compile.sh").exists():
            candidates.append(d)
    for p in candidates:
        if p.exists() and not _candidate_is_generation_error(p):
            return str(p)
    return None


def _candidate_is_generation_error(path: Path) -> bool:
    if path.is_dir():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:512].lower()
    except OSError:
        return False
    return "__generation_error" in head or "generation_error" in head


def _oracle_result_path(slug: str) -> Path:
    return ORACLE_RESULTS / f"{_safe_slug(slug)}.json"


def load_oracle_result(slug: str) -> dict[str, Any] | None:
    p = _oracle_result_path(slug)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if "passed" in data and "total" in data:
        return data
    return None


def parse_local_oracle_counts(text: str) -> tuple[int, int] | None:
    m = re.search(r"(?m)\b(\d+)/(\d+)\s+local examples pass\b", text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def save_oracle_result(slug: str, *, rc: int, stdout: str, stderr: str) -> dict[str, Any] | None:
    parsed = parse_local_oracle_counts(stdout)
    if not parsed:
        return None
    passed, total = parsed
    ORACLE_RESULTS.mkdir(parents=True, exist_ok=True)
    data = {
        "slug": slug,
        "passed": passed,
        "total": total,
        "rc": rc,
        "ts": _now(),
        "stdout_tail": stdout[-3000:],
        "stderr_tail": stderr[-1200:],
    }
    _oracle_result_path(slug).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return data


def _candidate_newer_than(candidate: str, oracle_ts: str | None) -> bool:
    """True iff the candidate file/dir was modified AFTER the saved oracle verdict.
    Unknown timestamps -> False (treat the candidate as already-judged, so a red
    verdict routes to reimpl rather than re-judging forever)."""
    if not oracle_ts:
        return False
    try:
        p = Path(candidate)
        if not p.is_absolute():
            p = ROOT / candidate
        mtime = _dt.datetime.fromtimestamp(p.stat().st_mtime, _dt.UTC)
        verdict_ts = _dt.datetime.fromisoformat(oracle_ts)
        if verdict_ts.tzinfo is None:
            verdict_ts = verdict_ts.replace(tzinfo=_dt.UTC)
        return mtime > verdict_ts
    except Exception:
        return False


def _uses_cloud_station_avoidance(model: str) -> bool:
    return any(
        part.strip().lower().startswith(("gemini-", "gemini/"))
        for part in str(model or "").split(",")
    )


def _uses_paid_cloud_model(model: str) -> bool:
    for part in str(model or "").split(","):
        name = part.strip().split(":", 1)[0].lower()
        if not name:
            continue
        if name.startswith(("local/", "ollama/", "tiny/")):
            continue
        if name.startswith(
            ("huggingface/", "openrouter/", "gemini-", "gemini/", "deepseek", "anthropic", "claude")
        ):
            return True
    return False


def _low_roi_cloud_hold_reason(ctx: ChurnContext, spec_path: str | None) -> str | None:
    if os.environ.get("DETERMINEX_PB_CHURN_ALLOW_BROAD_CLOUD") == "1":
        return None
    if not _uses_paid_cloud_model(ctx.model):
        return None
    examples = _spec_example_count(spec_path)
    if examples is None:
        return None
    max_examples = int(
        os.environ.get(
            "DETERMINEX_PB_CLOUD_REIMPL_MAX_EXAMPLES", str(DEFAULT_CLOUD_REIMPL_MAX_EXAMPLES)
        )
    )
    if examples <= max_examples:
        return None
    return (
        f"paid cloud reimpl held: spec has {examples} examples, above "
        f"DETERMINEX_PB_CLOUD_REIMPL_MAX_EXAMPLES={max_examples}; "
        "raise the cap or set DETERMINEX_PB_CHURN_ALLOW_BROAD_CLOUD=1 only for a deliberate spend"
    )


def _reimpl_drive_command(ctx: ChurnContext, lang: str) -> str:
    cmd = [
        "python3",
        _script("determinex_reimpl_drive.py"),
        ctx.slug,
        "--models",
        ctx.model,
        "--iters",
        str(ctx.iters),
        "--fuzz",
        str(ctx.fuzz),
        "--k",
        str(ctx.k),
        "--rounds",
        str(ctx.rounds),
        "--lang",
        lang,
        "--no-official",
    ]
    if _uses_cloud_station_avoidance(ctx.model):
        cmd.append("--no-decompose")
    return _cmd(cmd)


def _reimpl_timeout_s(model: str) -> int:
    if _uses_cloud_station_avoidance(model):
        return int(os.environ.get("DETERMINEX_PB_CLOUD_REIMPL_TIMEOUT", "240"))
    # 2026-07-02: real VerifiedSearch attempts at k=8/rounds=3 on a local model take
    # 1-2+ hours per tool (observed via logs/reimpl/gron_*.py candidate timestamps).
    # 3600s was killing attempts before a single real pass completed.
    # NOTE: with the observation cache + station checkpoint now in determinex_pb_reimpl,
    # hitting this timeout is no longer catastrophic -- the next churn pass on the same
    # tool RESUMES from the checkpointed station instead of restarting from zero, so a
    # decompose run that legitimately needs longer than one budget window completes
    # across passes.
    if _uses_paid_cloud_model(model):
        return int(os.environ.get("DETERMINEX_PB_CLOUD_REIMPL_TIMEOUT", "3600"))
    return int(os.environ.get("DETERMINEX_PB_LOCAL_REIMPL_TIMEOUT", "7200"))


def _reimpl_action_or_roi_hold(ctx: ChurnContext, lang: str, reason: str) -> ChurnAction:
    hold_reason = _low_roi_cloud_hold_reason(ctx, ctx.spec_path)
    if hold_reason:
        return ChurnAction(
            name="hold-low-roi-cloud-reimpl",
            command="",
            reason=hold_reason,
        )
    return ChurnAction(
        name="write-native-reimpl",
        command=_reimpl_drive_command(ctx, lang),
        reason=reason,
        timeout_s=_reimpl_timeout_s(ctx.model),
    )


def next_action(ctx: ChurnContext) -> ChurnAction:
    route = ctx.route
    verdict = str(getattr(route, "verdict", ""))
    spec_path = ctx.spec_path
    candidate = ctx.candidate_path
    lang = (ctx.lang or _lang_from_spec(spec_path) or "python").lower()

    if verdict in {"needs-spec-extraction", "corpus-route-unknown"}:
        if spec_path and candidate:
            return ChurnAction(
                name="local-oracle",
                command=_cmd(
                    [
                        "python3",
                        _script("determinex_local_oracle.py"),
                        candidate,
                        "--spec",
                        spec_path,
                    ]
                ),
                reason="spec and candidate already exist despite stale extraction route",
                timeout_s=900,
            )
        if spec_path:
            return _reimpl_action_or_roi_hold(
                ctx,
                lang,
                "spec already exists despite stale extraction route",
            )
        return ChurnAction(
            name="extract-spec",
            command=_cmd(["python3", _script("pb_bulk_spec.py"), "--only", ctx.slug]),
            reason="corpus has no harvested I/O spec yet",
            timeout_s=1800,
        )

    if verdict == "needs-native-reimpl":
        if not spec_path:
            return ChurnAction(
                name="extract-spec",
                command=_cmd(["python3", _script("pb_bulk_spec.py"), "--only", ctx.slug]),
                reason="upstream-source override is prohibited; harvest the spec before reimpl",
                timeout_s=1800,
            )
        if candidate:
            return ChurnAction(
                name="local-oracle",
                command=_cmd(
                    [
                        "python3",
                        _script("determinex_local_oracle.py"),
                        candidate,
                        "--spec",
                        spec_path,
                    ]
                ),
                reason="native reimpl candidate exists; validate it before spending another model pass",
                timeout_s=900,
            )
        return _reimpl_action_or_roi_hold(
            ctx,
            lang,
            "Addendum H/I requires a few-file native reimpl, not upstream-source build",
        )

    if verdict in {"needs-local-oracle", "needs-local-oracle-tail", "oracle-red-needs-tail"}:
        if not spec_path:
            return ChurnAction(
                name="extract-spec",
                command=_cmd(["python3", _script("pb_bulk_spec.py"), "--only", ctx.slug]),
                reason="local oracle needs a harvested I/O spec",
                timeout_s=1800,
            )
        # RED-LOOP FIX (2026-07-03, first unattended night): "candidate exists ->
        # re-run local-oracle" looped forever on a red verdict -- the oracle kept
        # re-judging the SAME stale candidate and write-native-reimpl (the only
        # action that invokes the model) was unreachable while any candidate file
        # existed. On a red verdict, only re-validate a candidate WRITTEN AFTER
        # that verdict; otherwise spend the pass on reimpl to produce a new one.
        if (
            candidate
            and verdict == "oracle-red-needs-tail"
            and not _candidate_newer_than(candidate, ctx.oracle_ts)
        ):
            return _reimpl_action_or_roi_hold(
                ctx,
                lang,
                "local oracle already judged this candidate red; regenerate, don't re-judge",
            )
        if candidate:
            return ChurnAction(
                name="local-oracle",
                command=_cmd(
                    [
                        "python3",
                        _script("determinex_local_oracle.py"),
                        candidate,
                        "--spec",
                        spec_path,
                    ]
                ),
                reason="validate every local example before official eval",
                timeout_s=900,
            )
        return _reimpl_action_or_roi_hold(
            ctx,
            lang,
            "corpus requires an oracle-gated candidate, but no candidate exists yet",
        )

    if verdict == "oracle-green-ready-for-official":
        if not ctx.allow_official:
            return ChurnAction(
                name="hold-official-eval",
                command="",
                reason="local oracle is green; rerun with --allow-official to spend the official eval",
            )
        if not candidate:
            return ChurnAction(
                name="hold-official-eval",
                command="",
                reason="local oracle is green but no candidate file was found",
            )
        official_candidate = _candidate_for_official(candidate, lang) or candidate
        return ChurnAction(
            name="official-eval",
            command=_cmd(
                [
                    "python3",
                    _script("determinex_pb_official_eval.py"),
                    ctx.slug,
                    official_candidate,
                    "--lang",
                    lang,
                ]
            ),
            reason="local oracle is green; official eval may measure the candidate",
            official_eval=True,
            timeout_s=5400,
        )

    return ChurnAction(
        name="consult-only",
        command="",
        reason=f"no executable churn action for route verdict={verdict!r}",
    )


def record_run_in_state(state: dict[str, Any], slug: str, result: dict[str, Any]) -> bool:
    """Record executed runs, without letting plan-only probes erase cooldown data."""
    runs = state.setdefault("runs", {})
    previous = runs.get(slug)
    if not result.get("executed"):
        return False
    runs[slug] = result
    return previous != result


def merge_executed_events_into_state(state: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    changed = False
    for event in events:
        if not isinstance(event, dict) or not event.get("executed"):
            continue
        slug = str(event.get("slug") or "").strip()
        if not slug:
            continue
        changed = record_run_in_state(state, slug, event) or changed
    return changed


def _load_event_records(path: Path = EVENTS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
    except OSError:
        return []
    return out


def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merge_executed_events_into_state(data, _load_event_records())
                return data
        except Exception:
            pass
    state = {"schema": "determinex-pb-churn-v1", "runs": {}}
    merge_executed_events_into_state(state, _load_event_records())
    return state


def _save_state(state: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
            default=lambda o: (
                o.decode("utf-8", errors="replace") if isinstance(o, bytes) else str(o)
            ),
        )
        + "\n",
        encoding="utf-8",
    )


def _append_event(event: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def format_handoff_event(slug: str, action: ChurnAction, *, rc: int | None, log_path: str) -> str:
    rc_text = "not-run" if rc is None else str(rc)
    command = action.command.replace("\n", " ").strip()
    return (
        f"- ts={_now()} slug={slug} action={action.name} rc={rc_text} "
        f"official_eval={str(action.official_eval).lower()} log={log_path} "
        f"reason={action.reason}; command={command or '<none>'}\n"
    )


def append_handback(slug: str, action: ChurnAction, *, rc: int | None, log_path: str) -> None:
    with HANDBACK.open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n### Codex PB churn raw evidence\n")
        f.write(format_handoff_event(slug, action, rc=rc, log_path=log_path))


def _argv_from_command(command: str) -> list[str]:
    # ALWAYS posix=True (2026-07-03): every ChurnAction command is built by _cmd()
    # with shlex.quote (POSIX single quotes), and only posix-mode split strips them.
    # posix=False on Windows kept the quotes LITERAL in each argument, so every
    # subprocess got paths like "'C:\\...\\spec.json'" (quotes included) and crashed
    # instantly with OSError 22 -- all nine first-night local-oracle "rc=1" results
    # were this crash, not real verdicts. Backslashes are safe: shlex.quote wraps
    # any arg containing them in single quotes, and posix split treats single-quoted
    # content literally.
    if not command:
        return []
    return shlex.split(command, posix=True)


def execute_action(action: ChurnAction) -> dict[str, Any]:
    if not action.command:
        return {"rc": None, "stdout": "", "stderr": "", "skipped": True}
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    for p in (str(Path.home() / ".local" / "bin"), "/root/.local/bin", "/usr/local/go/bin"):
        if Path(p).is_dir() and p not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = p + os.pathsep + env.get("PATH", "")
    argv = _argv_from_command(action.command)
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, stderr = proc.communicate(timeout=action.timeout_s)
        return {
            "rc": proc.returncode,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "skipped": False,
        }
    except subprocess.TimeoutExpired:
        if proc:
            import signal

            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)  # posix; AttributeError on nt
            except Exception:
                proc.kill()
            # Bounded drain (2026-07-03): on Windows proc.kill() leaves grandchildren
            # (compilers, docker clients) that can hold the stdout pipe open -- an
            # unbounded communicate() here wedges the whole churn lane (corpus class:
            # eval_orphan_pipe_hang). Give it 30s, then abandon the pipes.
            try:
                stdout, stderr = proc.communicate(timeout=30)
            except Exception:
                stdout, stderr = "", "<timeout: output pipes abandoned (orphan grandchild)>"
            return {"rc": 124, "stdout": stdout or "", "stderr": stderr or "", "skipped": False}
        # proc is always truthy here (Popen assigned it), but guarantee a return
        # so a timeout can never fall through to None and desync the churn loop.
        return {"rc": 124, "stdout": "", "stderr": "timeout", "skipped": False}
    except Exception as e:
        return {"rc": 1, "stdout": "", "stderr": str(e), "skipped": False}


def _redis_client():
    url = os.environ.get("QUEUE_URL")
    if not url:
        return None
    try:
        import redis  # type: ignore[import-not-found]

        return redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
    except Exception:
        return None


def acquire_lease(slug: str, worker: str, ttl_s: int) -> tuple[bool, Any]:
    r = _redis_client()
    if r is None:
        return True, None
    try:
        tool = r.hgetall(f"determinex:tool:{slug}") or {}
        if tool.get("status") == "claimed" and tool.get("claimed_by") not in {"", worker, None}:
            return False, r
        ok = r.set(f"determinex:churn:lease:{slug}", worker, nx=True, ex=ttl_s)
        return bool(ok), r
    except Exception:
        return True, None


def release_lease(slug: str, worker: str, client: Any) -> None:
    if client is None:
        return
    try:
        key = f"determinex:churn:lease:{slug}"
        if client.get(key) == worker:
            client.delete(key)
    except Exception:
        pass


def run_slug(
    slug: str,
    *,
    execute: bool,
    model: str,
    allow_official: bool,
    append_to_handback: bool,
    worker: str,
    lease_ttl_s: int,
    iters: int,
    fuzz: int,
    k: int,
    rounds: int,
) -> dict[str, Any]:
    leased, redis_client = acquire_lease(slug, worker, lease_ttl_s)
    if not leased:
        return {"slug": slug, "ts": _now(), "skipped": "claimed-by-other"}
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import determinex_pb_ask_corpus as ask
        import determinex_pb_corpus_router as router

        answer = ask.ask_corpus(slug)
        full = str(answer.get("slug") or slug)
        oracle = load_oracle_result(full)
        route = router.route_from_corpus(answer, oracle_result=oracle)
        spec_path = _local_spec_path(full, answer)
        raw_candidate = _candidate_for(full, answer)
        lang = _lang_from_spec(spec_path)
        candidate = _candidate_for_oracle(raw_candidate, lang, full)
        action = next_action(
            ChurnContext(
                slug=full,
                route=route,
                model=model,
                spec_path=spec_path,
                candidate_path=candidate,
                allow_official=allow_official,
                lang=lang,
                iters=iters,
                fuzz=fuzz,
                k=k,
                rounds=rounds,
                oracle_ts=(oracle or {}).get("ts"),
            )
        )

        result: dict[str, Any] = {
            "slug": full,
            "ts": _now(),
            "route": route.to_dict(),
            "spec_path": spec_path,
            "candidate_path": candidate,
            "action": asdict(action),
            "executed": execute,
        }
        if execute:
            try:
                ex = execute_action(action)
            except subprocess.TimeoutExpired as e:

                def _dec(v: Any) -> str:
                    if isinstance(v, bytes):
                        return v.decode("utf-8", errors="replace")
                    return str(v) if v is not None else ""

                ex = {
                    "rc": 124,
                    "stdout": _dec(e.stdout),
                    "stderr": _dec(e.stderr) or "timeout",
                    "skipped": False,
                }
            result["result"] = {
                k2: (v[-4000:] if isinstance(v, str) else v) for k2, v in ex.items()
            }
            # Cooldown measures from COMPLETION, not start (2026-07-03): a reimpl runs up
            # to 2h -- longer than the 90-min cooldown -- so a start-stamped ts is already
            # past cooldown the instant the run ends, and a always-times-out hard tool
            # (atlas) never actually yields. Re-stamp to the end so the 90-min yield is real.
            result["ts"] = _now()
            if action.name == "write-native-reimpl":
                result["candidate_path"] = _candidate_for(full, answer)
            if action.name == "local-oracle":
                saved = save_oracle_result(
                    full,
                    rc=int(ex.get("rc") or 0),
                    stdout=str(ex.get("stdout") or ""),
                    stderr=str(ex.get("stderr") or ""),
                )
                result["oracle_result_saved"] = saved
            if append_to_handback:
                append_handback(full, action, rc=ex.get("rc"), log_path=str(EVENTS_PATH))
        elif append_to_handback:
            append_handback(full, action, rc=None, log_path=str(EVENTS_PATH))

        state = _load_state()
        if record_run_in_state(state, full, result):
            _save_state(state)
        _append_event(result)
        return result
    finally:
        release_lease(slug, worker, redis_client)


def _resolve_queue(args: argparse.Namespace) -> list[str]:
    if args.slugs:
        return [s.strip() for s in args.slugs.split(",") if s.strip()]
    if args.all:
        return queue_from_eval_rows(
            _load_eval_rows(),
            _load_state(),
            include_locked=args.include_locked,
            include_ceilings=args.include_ceilings,
            cooldown_s=args.cooldown_seconds,
        )
    raise SystemExit("specify --slugs or --all")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--slugs", help="comma-separated slugs")
    group.add_argument(
        "--all", action="store_true", help="churn every non-terminal eval_index tool"
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="actually run the planned action; default is plan-only",
    )
    ap.add_argument(
        "--allow-official",
        action="store_true",
        help="allow official eval after local oracle is green",
    )
    ap.add_argument(
        "--append-handback",
        action="store_true",
        help="append raw action evidence to CODEX_HANDBACK.md",
    )
    ap.add_argument("--watch", action="store_true", help="loop forever")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--max-tools-per-pass", type=int, default=1)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--worker", default=DEFAULT_WORKER)
    ap.add_argument("--lease-ttl", type=int, default=7200)
    ap.add_argument(
        "--cooldown-seconds",
        type=int,
        default=DEFAULT_COOLDOWN_SECONDS,
        help="seconds to suppress recently failed/no-progress tools from --all queue",
    )
    ap.add_argument("--include-locked", action="store_true")
    ap.add_argument("--include-ceilings", action="store_true")
    ap.add_argument("--iters", type=int, default=2)
    ap.add_argument("--fuzz", type=int, default=20)
    # 2026-07-02: match determinex_pb_reimpl.py's own sound defaults (k=8, rounds=3).
    # The old k=2/rounds=1 defaults disabled most of VerifiedSearch's amplification.
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args(argv)

    watch_lock_fd: int | None = None
    if args.watch:
        locked, watch_lock_fd, reason = acquire_watch_lock()
        if not locked:
            print(f"[pb-churn] refusing second watch loop: {reason}", flush=True)
            return 2

    pass_no = 1
    try:
        while True:
            queue = _resolve_queue(args)
            todo = queue[: max(1, args.max_tools_per_pass)]
            print(
                f"[pb-churn] pass={pass_no} queue={len(queue)} todo={len(todo)} execute={args.execute} model={args.model}",
                flush=True,
            )
            for slug in todo:
                event = run_slug(
                    slug,
                    execute=args.execute,
                    model=args.model,
                    allow_official=args.allow_official,
                    append_to_handback=args.append_handback,
                    worker=args.worker,
                    lease_ttl_s=args.lease_ttl,
                    iters=args.iters,
                    fuzz=args.fuzz,
                    k=args.k,
                    rounds=args.rounds,
                )
                action = (event.get("action") or {}).get("name")
                route = (event.get("route") or {}).get("verdict")
                rc = (
                    (event.get("result") or {}).get("rc")
                    if isinstance(event.get("result"), dict)
                    else None
                )
                print(
                    f"[pb-churn] {event.get('slug', slug)} route={route} action={action} rc={rc}",
                    flush=True,
                )
            if not args.watch:
                return 0
            pass_no += 1
            time.sleep(args.interval)
    finally:
        release_watch_lock(watch_lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
