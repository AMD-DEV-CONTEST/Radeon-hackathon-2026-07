"""
scripts/determinex_flywheel.py — Autonomous Training Data Flywheel
===============================================================
Listens for successful SWE-bench solves. Captures (issue → verified_patch)
pairs as JSONL training data.

Sprint 4 (2026-05-15) adds **auto-retrain orchestration**: when the corpus
crosses `DETERMINEX_FLYWHEEL_RETRAIN_THRESHOLD` new pairs since the last training
run, the flywheel can spawn a background dsl_finetune job, run micro_eval
against the resulting adapter, and promote it to the active Ollama tag ONLY
when the delta meets `DETERMINEX_FLYWHEEL_PROMOTE_DELTA_PP` (default +1.0pp on
the 45-probe set).

Safety guard rails:
  - Opt-in: requires DETERMINEX_FLYWHEEL_AUTO=1 (default OFF — never retrains
    unattended unless explicitly enabled).
  - Concurrency lock: pid+timestamp file in flywheel state dir; a stale lock
    older than DETERMINEX_FLYWHEEL_LOCK_TTL_S seconds is reclaimed.
  - Promotion is reversible: previous adapter manifest snapshot stays on disk.

Usage:
    from determinex_flywheel import capture_successful_epoch
    # `verification` is required: it is what the compile gate actually established.
    count = capture_successful_epoch(issue_text, patch, instance_id, repo_name,
                                     verification="compiled+tested")
    # Optional: poll auto-retrain status / trigger
    from determinex_flywheel import maybe_trigger_auto_retrain
    maybe_trigger_auto_retrain()
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("determinex_flywheel")

_ROOT = Path(__file__).resolve().parent.parent

FLYWHEEL_PATH = Path(os.getenv("DETERMINEX_FLYWHEEL_PATH", str(_ROOT / "auto_curriculum.jsonl")))
FLYWHEEL_NOTIFY_THRESHOLD = int(os.getenv("DETERMINEX_FLYWHEEL_THRESHOLD", "50"))

# ── Sprint 4: auto-retrain orchestration config ───────────────────────────────
_FLYWHEEL_STATE_DIR = _ROOT / ".flywheel"
_FLYWHEEL_STATE_FILE = _FLYWHEEL_STATE_DIR / "state.json"
_FLYWHEEL_LOCK_FILE = _FLYWHEEL_STATE_DIR / "retrain.lock"
_FLYWHEEL_LOG_DIR = _ROOT / "logs" / "flywheel"

AUTO_RETRAIN_ENABLED = os.getenv("DETERMINEX_FLYWHEEL_AUTO", "0") == "1"
RETRAIN_THRESHOLD = int(os.getenv("DETERMINEX_FLYWHEEL_RETRAIN_THRESHOLD", "500"))
PROMOTE_DELTA_PP = float(os.getenv("DETERMINEX_FLYWHEEL_PROMOTE_DELTA_PP", "1.0"))
LOCK_TTL_S = int(os.getenv("DETERMINEX_FLYWHEEL_LOCK_TTL_S", "21600"))  # 6h
RETRAIN_BASE_MODEL = os.getenv("DETERMINEX_FLYWHEEL_BASE_MODEL", "determinex-engineer-v11-dsl")
TRAIN_DRIVER = os.getenv(
    "DETERMINEX_FLYWHEEL_TRAIN_DRIVER",
    str(_ROOT / "determinex_trainer" / "dsl_finetune.py"),
)
MICRO_EVAL_SCRIPT = os.getenv(
    "DETERMINEX_FLYWHEEL_MICRO_EVAL",
    str(_ROOT / "scripts" / "micro_eval.py"),
)


@dataclass
class FlywheelState:
    """Persistent state across flywheel auto-retrain runs."""

    last_trigger_count: int = 0  # entry count at last retrain trigger
    last_promotion_count: int = 0  # entry count at last successful promotion
    last_promoted_adapter: str = ""  # tag of last promoted adapter
    last_baseline_score: float = 0.0  # micro_eval score at last promotion (0-100)
    last_attempt_ts: str = ""  # ISO timestamp of last retrain attempt
    last_attempt_outcome: str = ""  # "promoted" | "rejected" | "failed" | "skipped"
    last_attempt_detail: str = ""  # short string explanation

    @classmethod
    def load(cls) -> FlywheelState:
        if _FLYWHEEL_STATE_FILE.exists():
            try:
                data = json.loads(_FLYWHEEL_STATE_FILE.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
            except (OSError, json.JSONDecodeError) as e:
                log.warning("Flywheel state file unreadable, resetting: %s", e)
        return cls()

    def save(self) -> None:
        _FLYWHEEL_STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _FLYWHEEL_STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(_FLYWHEEL_STATE_FILE)


#: Gate outcomes that genuinely clear CLAUDE.md's "all training data must be compiler-validated
#: before entering corpus" bar. Compile-only qualifies: a compiler really ran and really passed.
#: Anything else does not, however plausible the patch looks.
VERIFIED_GATE_KINDS = frozenset({"compiled+tested", "compiled_only"})


def capture_successful_epoch(
    issue_text: str,
    patch: str,
    instance_id: str = "unknown",
    repo_name: str = "",
    *,
    verification: str,
) -> int:
    """
    Append a compiler-validated (issue → patch) pair to auto_curriculum.jsonl.

    `verification` is required and keyword-only on purpose. This function's docstring used to say
    "Called only when: targeted tests PASS AND regression sweep PASSES", and that was simply not
    true: it wrote `"verified": True` for whatever it was handed, and the caller handed it any
    patch the compile gate returned PASS for. The gate returned PASS without compiling anything
    whenever the baseline compile failed, the toolchain was absent, the language was unsupported,
    or no build file existed -- so unverified patches entered the corpus labelled verified and
    became training data for the next LoRA retrain.

    An unverified patch is now NOT written at all, rather than written with verified=False. The
    corpus stays clean regardless of whether a downstream consumer remembers to filter, which is
    the same reason the oracle fails closed instead of returning a soft pass.

    Returns current total entry count in flywheel file.
    Logs a notification when FLYWHEEL_NOTIFY_THRESHOLD is crossed.
    """
    if not patch or not patch.strip():
        log.debug("Flywheel: empty patch — skipping capture for %s", instance_id)
        return _count_entries()

    if verification not in VERIFIED_GATE_KINDS:
        log.warning(
            "Flywheel: NOT capturing %s — verification=%r is not compiler-validated, so it is "
            "not training data. Corpus unchanged.",
            instance_id,
            verification,
        )
        return _count_entries()

    entry = {
        "instruction": (
            f"You are an expert software engineer. Fix the following GitHub issue "
            f"by producing a unified diff patch.\n\nIssue:\n{issue_text.strip()}"
        ),
        "output": patch.strip(),
        "instance_id": instance_id,
        "repo": repo_name,
        "timestamp": datetime.now(UTC).isoformat(),
        "verified": True,
        # Provenance, so a future reader can tell a compile-only sample from a tested one
        # without re-deriving it from run logs.
        "verification": verification,
        "source": "determinex_swe_flywheel",
    }

    FLYWHEEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FLYWHEEL_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    total = _count_entries()
    log.info("Flywheel: %d verified patches captured → %s", total, FLYWHEEL_PATH.name)

    if total > 0 and total % FLYWHEEL_NOTIFY_THRESHOLD == 0:
        log.info(
            "\n" + "=" * 60 + "\nFLYWHEEL THRESHOLD: %d verified patches in auto_curriculum.jsonl\n"
            "Ready for LoRA fine-tune. Trigger manually:\n"
            "  python determinex_trainer/dsl_finetune.py --data auto_curriculum.jsonl\n"
            "  python determinex_trainer/train_unsloth.py --data auto_curriculum.jsonl\n"
            + "="
            * 60,
            total,
        )

    # Sprint 4: opportunistic auto-retrain check (opt-in via DETERMINEX_FLYWHEEL_AUTO=1)
    if AUTO_RETRAIN_ENABLED:
        try:
            maybe_trigger_auto_retrain(current_count=total)
        except Exception as e:  # pylint: disable=broad-except
            log.warning("auto-retrain check failed: %s", e)

    return total


def _count_entries() -> int:
    try:
        with open(FLYWHEEL_PATH, encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except FileNotFoundError:
        return 0


def flywheel_status() -> dict:
    """Return current flywheel stats for dashboard / reporting."""
    count = _count_entries()
    state = FlywheelState.load()
    pending = max(0, count - state.last_trigger_count)
    return {
        "path": str(FLYWHEEL_PATH),
        "entries": count,
        "notify_threshold": FLYWHEEL_NOTIFY_THRESHOLD,
        "pct_to_threshold": round(
            (count % FLYWHEEL_NOTIFY_THRESHOLD) / FLYWHEEL_NOTIFY_THRESHOLD * 100, 1
        ),
        "auto_retrain": {
            "enabled": AUTO_RETRAIN_ENABLED,
            "retrain_threshold": RETRAIN_THRESHOLD,
            "pending_since_train": pending,
            "pct_to_retrain": round(min(pending / max(RETRAIN_THRESHOLD, 1), 1.0) * 100, 1),
            "last_trigger_count": state.last_trigger_count,
            "last_promoted": state.last_promoted_adapter,
            "last_baseline": state.last_baseline_score,
            "last_attempt": state.last_attempt_ts,
            "last_outcome": state.last_attempt_outcome,
            "last_detail": state.last_attempt_detail,
        },
    }


# ── Sprint 4: auto-retrain orchestration ──────────────────────────────────────


def _acquire_retrain_lock() -> bool:
    """Return True if we got the lock. Reclaim stale locks older than LOCK_TTL_S."""
    _FLYWHEEL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if _FLYWHEEL_LOCK_FILE.exists():
        try:
            payload = json.loads(_FLYWHEEL_LOCK_FILE.read_text(encoding="utf-8"))
            held_at = float(payload.get("ts", 0))
            held_by = payload.get("pid", "?")
            age_s = time.time() - held_at
            if age_s < LOCK_TTL_S:
                log.info(
                    "retrain lock held by pid %s, age %.0fs (< %ds) — skipping",
                    held_by,
                    age_s,
                    LOCK_TTL_S,
                )
                return False
            log.warning("stale retrain lock (age %.0fs) — reclaiming", age_s)
        except (OSError, json.JSONDecodeError):
            log.warning("retrain lock unparseable — reclaiming")
    _FLYWHEEL_LOCK_FILE.write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8"
    )
    return True


def _release_retrain_lock() -> None:
    try:
        _FLYWHEEL_LOCK_FILE.unlink(missing_ok=True)
    except OSError as e:
        log.warning("could not release retrain lock: %s", e)


def _run_subprocess_logged(cmd: list[str], log_path: Path, timeout_s: int = 7200) -> int:
    """Run subprocess, stream stdout+stderr to log_path, return rc. Never raises."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("→ %s  (log: %s)", " ".join(cmd), log_path.name)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"\n========== {datetime.now(UTC).isoformat()} ==========\n")
        fh.write(" ".join(cmd) + "\n\n")
        fh.flush()
        try:
            return subprocess.run(
                cmd,
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            fh.write(f"\n[TIMEOUT after {timeout_s}s]\n")
            return 124
        except FileNotFoundError as e:
            fh.write(f"\n[NOT_FOUND] {e}\n")
            return 127


def _parse_micro_eval_score(log_path: Path) -> float:
    """Extract pct score from a micro_eval log. Returns -1.0 if not found."""
    if not log_path.exists():
        return -1.0
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return -1.0
    import re as _re

    # micro_eval typically emits a line like: "Score: 89.0% (40/45)" or similar
    for line in reversed(text.splitlines()):
        m = _re.search(r"(?:Score|TOTAL|RESULT)\D+([0-9]+(?:\.[0-9]+)?)\s*%", line, _re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return -1.0


def maybe_trigger_auto_retrain(current_count: int | None = None) -> dict:
    """
    Sprint 4 entry point. Returns a dict describing the action taken.

    Flow (all gated behind DETERMINEX_FLYWHEEL_AUTO=1):
      1. Check pending delta against RETRAIN_THRESHOLD.
      2. Acquire lock; abort if held.
      3. Run dsl_finetune driver on auto_curriculum.jsonl.
      4. Run micro_eval against the new adapter; compare to baseline.
      5. If delta >= PROMOTE_DELTA_PP, swap the active Ollama tag. Otherwise reject.
      6. Persist state for next decision and release lock.

    Returns dict with keys: status, count_at_trigger, baseline, new_score, action.
    Status one of: "skipped" | "promoted" | "rejected" | "failed".
    """
    if not AUTO_RETRAIN_ENABLED:
        return {"status": "skipped", "reason": "DETERMINEX_FLYWHEEL_AUTO != 1"}

    if current_count is None:
        current_count = _count_entries()

    state = FlywheelState.load()
    pending = current_count - state.last_trigger_count
    if pending < RETRAIN_THRESHOLD:
        return {
            "status": "skipped",
            "reason": f"pending={pending} < threshold={RETRAIN_THRESHOLD}",
            "pending": pending,
        }

    if not _acquire_retrain_lock():
        return {"status": "skipped", "reason": "lock held by another flywheel process"}

    _FLYWHEEL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_dir = _FLYWHEEL_LOG_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    train_log = run_dir / "dsl_finetune.log"
    eval_log = run_dir / "micro_eval.log"

    state.last_attempt_ts = datetime.now(UTC).isoformat()

    try:
        # Step 1: training
        python_exe = sys.executable
        train_rc = _run_subprocess_logged(
            [
                python_exe,
                TRAIN_DRIVER,
                "--data",
                str(FLYWHEEL_PATH),
                "--base-model",
                RETRAIN_BASE_MODEL,
                "--output-tag",
                f"{RETRAIN_BASE_MODEL}-auto-{ts}",
            ],
            train_log,
            timeout_s=int(os.getenv("DETERMINEX_FLYWHEEL_TRAIN_TIMEOUT_S", "10800")),
        )
        if train_rc != 0:
            state.last_attempt_outcome = "failed"
            state.last_attempt_detail = f"dsl_finetune rc={train_rc} — see {train_log}"
            state.save()
            return {"status": "failed", "stage": "train", "rc": train_rc, "log": str(train_log)}

        # Step 2: micro_eval the new adapter
        new_tag = f"{RETRAIN_BASE_MODEL}-auto-{ts}"
        eval_rc = _run_subprocess_logged(
            [python_exe, MICRO_EVAL_SCRIPT, "--model", new_tag],
            eval_log,
            timeout_s=int(os.getenv("DETERMINEX_FLYWHEEL_EVAL_TIMEOUT_S", "1800")),
        )
        if eval_rc != 0:
            state.last_attempt_outcome = "failed"
            state.last_attempt_detail = f"micro_eval rc={eval_rc} — see {eval_log}"
            state.save()
            return {"status": "failed", "stage": "eval", "rc": eval_rc, "log": str(eval_log)}

        new_score = _parse_micro_eval_score(eval_log)
        baseline = state.last_baseline_score
        delta_pp = new_score - baseline

        # Step 3: promotion gate
        if new_score < 0:
            state.last_attempt_outcome = "rejected"
            state.last_attempt_detail = "could not parse score from micro_eval log"
            state.save()
            return {"status": "rejected", "reason": "unparseable_score", "log": str(eval_log)}

        if delta_pp < PROMOTE_DELTA_PP and baseline > 0:
            state.last_attempt_outcome = "rejected"
            state.last_attempt_detail = (
                f"new_score={new_score:.2f}%, baseline={baseline:.2f}%, "
                f"delta={delta_pp:+.2f}pp < required={PROMOTE_DELTA_PP:+.2f}pp"
            )
            state.last_trigger_count = current_count  # so we don't loop on the same data
            state.save()
            return {
                "status": "rejected",
                "baseline": baseline,
                "new_score": new_score,
                "delta_pp": delta_pp,
                "required_pp": PROMOTE_DELTA_PP,
            }

        # Step 4: promote — point the canonical tag at the new adapter
        promote_rc = _ollama_hot_swap(
            target_alias=RETRAIN_BASE_MODEL, new_model=new_tag, run_dir=run_dir
        )
        if promote_rc != 0:
            state.last_attempt_outcome = "failed"
            state.last_attempt_detail = f"ollama hot-swap failed rc={promote_rc}"
            state.save()
            return {"status": "failed", "stage": "promote", "rc": promote_rc}

        state.last_promotion_count = current_count
        state.last_trigger_count = current_count
        state.last_promoted_adapter = new_tag
        state.last_baseline_score = new_score
        state.last_attempt_outcome = "promoted"
        state.last_attempt_detail = (
            f"{new_tag} → {new_score:.2f}% (delta {delta_pp:+.2f}pp from baseline {baseline:.2f}%)"
        )
        state.save()
        return {
            "status": "promoted",
            "tag": new_tag,
            "baseline": baseline,
            "new_score": new_score,
            "delta_pp": delta_pp,
        }
    finally:
        _release_retrain_lock()


def _ollama_hot_swap(target_alias: str, new_model: str, run_dir: Path) -> int:
    """
    Swap the active Ollama tag. We create a thin alias Modelfile (`FROM new_model`)
    and run `ollama create target_alias -f <modelfile>` to point the canonical name
    at the freshly-trained adapter without restarting Ollama.

    Returns 0 on success, non-zero rc on failure.
    """
    ollama = shutil.which("ollama") or shutil.which("ollama.exe")
    if not ollama:
        log.error("ollama not on PATH — cannot hot-swap")
        return 127

    modelfile = run_dir / f"swap_{target_alias}.modelfile"
    modelfile.write_text(
        f"FROM {new_model}\n"
        f"# Auto-generated by determinex_flywheel.py Sprint 4 promotion gate\n"
        f"# Timestamp: {datetime.now(UTC).isoformat()}\n",
        encoding="utf-8",
    )
    swap_log = run_dir / "ollama_swap.log"
    return _run_subprocess_logged(
        [ollama, "create", target_alias, "-f", str(modelfile)],
        swap_log,
        timeout_s=300,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "trigger":
        # Manual trigger: explicit invocation honoring all guards.
        result = maybe_trigger_auto_retrain()
        print(json.dumps(result, indent=2, default=str))
        sys.exit(0 if result.get("status") in {"promoted", "rejected", "skipped"} else 1)

    status = flywheel_status()
    print(f"Flywheel path        : {status['path']}")
    print(f"Entries captured     : {status['entries']}")
    print(f"Notify threshold     : {status['notify_threshold']}")
    print(f"Progress (notify)    : {status['pct_to_threshold']}% to next notification")
    print()
    ar = status["auto_retrain"]
    print(f"Auto-retrain enabled : {ar['enabled']}")
    print(f"Retrain threshold    : {ar['retrain_threshold']}")
    print(f"Pending since train  : {ar['pending_since_train']} ({ar['pct_to_retrain']}%)")
    print(f"Last promoted tag    : {ar['last_promoted'] or '(none)'}")
    print(f"Last baseline score  : {ar['last_baseline']:.2f}%")
    print(f"Last attempt         : {ar['last_attempt'] or '(none)'} -> {ar['last_outcome'] or '-'}")
    if ar["last_detail"]:
        print(f"  detail: {ar['last_detail']}")
    sys.exit(0)
