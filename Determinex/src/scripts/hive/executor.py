"""
scripts/hive/executor.py — Step execution engine and DAG run loop
==================================================================
Moved from determinex_hive.py (lines ~1819-2320).
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from hive.api_client import (
    RateLimitExhausted,
    _resolve_model,
    api_call,
    cleanup_session,
    load_role_assignments,
)
from hive.budget import (
    APPROX_TOKENS_PER_STEP,
    api_budget_preflight,
    queue_for_training,
    record_api_call_cost,
)
from hive.code_utils import _extract_code_block
from hive.compiler import (
    _atomic_write,
    _detect_brevity_cheat,
    _detect_ghost_imports,
    _detect_hardcode_cheat,
    _strip_internal_tracebacks,
    api_snapshots_differ,
    apply_step_output,
    check_toolchain_available,
    classify_training_quality,
    detect_compile_hack,
    ensure_sandbox_available,
    extract_public_api,
    hash_compiler_error,
    is_toolchain_error,
    run_correctness_tests,
    sanitize_compiler_output,
    validate_project,
    validate_scaffolding,
)
from hive.constants import (
    MAX_CHALLENGES_PER_STEP,
    MAX_ESCALATIONS_PER_STEP,
    MAX_LINES_BEFORE_FORCE_REPLACE,
    MAX_RETRIES_PER_STEP,
    MIN_CHALLENGE_DELTA,
    MONITOR_TIMEOUT_SECONDS,
    OSCILLATION_THRESHOLD,
)
from hive.dag import build_execution_waves, flag_stale_downstream, topological_sort
from hive.forge_daemon import start_forge_daemon, stop_forge_daemon
from hive.hardware import (
    adjudication_cosine,
    effective_adjudication_weights,
    get_free_vram_gb,
    get_hw_profile,
)
from hive.manifest import (
    ManifestSession,
    SessionWAL,
    StepRecord,
    _steps_dir,
    load_manifest,
    save_manifest,
    wal_complete,
    wal_fail,
    wal_queue_offline,
    wal_recover_pending,
    wal_write_pending,
)
from hive.prompt_builder import (
    _build_builder_messages,
    _build_monitor_messages,
    _parse_monitor_verdict,
)
from hive.rosetta_bridge import RosettaBridge, make_bridge
from hive.session_manager import release_session_lock
from hive.thermal import ThermalCriticalError, dynamic_ipc_timeout, thermal_hard_halt
from hive.workspace import (
    hash_workspace_files,
)

# ── Structured logging ────────────────────────────────────────────────────────
try:
    from hive._log import bind_session as _bind_log_session
    from hive._log import get_logger as _get_hive_logger

    log = _get_hive_logger("hive.executor")
    _LOG_BIND = _bind_log_session
except ImportError:
    import logging as _std_logging

    log = _std_logging.getLogger("hive")
    _LOG_BIND = lambda **_kw: None  # noqa: E731

# ── DSPy opt-in hook (DETERMINEX_USE_DSPY=1 enables prompt optimization) ────
import os as _os_dspy

_DSPY_ENABLED = _os_dspy.environ.get("DETERMINEX_USE_DSPY", "").strip() == "1"
if _DSPY_ENABLED:
    try:
        from hive.dspy_modules import DeterminexDAGPlanner, DeterminexMonitor  # noqa: F401

        log.info("dspy_enabled", monitor=True, dag_planner=True)
    except ImportError:
        _DSPY_ENABLED = False
        log.warning("dspy_import_failed", hint="pip install dspy-ai; DETERMINEX_USE_DSPY ignored")


#: Signals `run_correctness_tests` returns to mean "the tests did not run", as opposed to "the tests
#: passed". Every one is returned as `(True, signal)`, which is why both call sites have to test for
#: these BEFORE testing the boolean -- see the notes at those sites.
_CORRECTNESS_SKIP_PREFIXES = (
    "harness_not_found",
    "harness_read_error",  # carries ": {exception}"
    "lang_unsupported",
    "test_timeout",
    "runner_not_found",  # carries ": {exception}"
)


def _is_correctness_skip(output: str) -> bool:
    """Whether a run_correctness_tests result means the suite never ran.

    Prefix, not equality: two of the signals append an exception message, so exact membership
    silently missed them -- and `harness_read_error` was absent from the tuple that was being
    matched at all.
    """
    return str(output or "").startswith(_CORRECTNESS_SKIP_PREFIXES)


def _run_daemon_timeout(fn, timeout: float):
    """Run fn on a daemon thread and raise TimeoutError without waiting forever."""
    done = threading.Event()
    result: list[tuple[bool, object]] = []

    def _target() -> None:
        try:
            result.append((True, fn()))
        except BaseException as exc:
            result.append((False, exc))
        finally:
            done.set()

    thread = threading.Thread(target=_target, name="determinex-monitor-timeout", daemon=True)
    thread.start()
    if not done.wait(timeout):
        raise concurrent.futures.TimeoutError()
    ok, value = result[0]
    if ok:
        return value
    raise value


# Chrono-Daemon: optional Burnout Protocol monitor — graceful if chrono_daemon not on path
try:
    from chrono_daemon import ChronoDaemon as _ChronoDaemon
except ImportError:
    _ChronoDaemon = None  # type: ignore[assignment,misc]

# LatentRAG: optional semantic retrieval from previous builds.
# rosetta/ is at project root, not scripts/ — add root to path inside try block.
try:
    import sys as _sys

    _PROJ_ROOT = str(
        Path(os.environ["DETERMINEX_ROOT"]).resolve()
        if os.environ.get("DETERMINEX_ROOT")
        else Path(__file__).resolve().parent.parent.parent
    )
    if _PROJ_ROOT not in _sys.path:
        _sys.path.insert(0, _PROJ_ROOT)
    from rosetta.latent_rag import LatentRetriever as _LatentRetriever  # type: ignore[import]
except Exception:
    _LatentRetriever = None  # type: ignore[assignment,misc]


# VRAM keep-alive policy lives in ONE place: hive.api_client._ollama_extra.
#
# This module carried a byte-for-byte copy of it. When the tier-0 policy was corrected on
# 2026-07-31 -- the ~6GB rig cannot hold the builder and the observer at once, and pinning both
# stalled a session for 19 minutes -- the copy here would have kept the old behaviour on whichever
# call sites resolve through the executor, so the same session could evict the observer down one
# path and pin it down the other. That is the divergence this codebase's own AUDIT-BEFORE-BUILD
# rule exists to prevent, and re-deriving the answer is cheaper than keeping two copies honest.
# The import direction is safe: executor already imports api_client, which does not import back.
from hive.api_client import _ollama_extra  # noqa: E402  (kept beside its only consumer)


def _provider_extra_body(
    model_alias: str,
    role: str,
    hw_profile=None,
    *,
    force_evict: bool = False,
) -> dict:
    """Return provider-specific LiteLLM extra_body for a configured model alias."""
    real_model, _ = _resolve_model(model_alias)
    if not real_model.startswith("ollama/"):
        return {}
    body = _ollama_extra(real_model, role, hw_profile)
    if force_evict:
        body = {**body, "keep_alive": 0}
    return body


def _required_ollama_models(model_assignments: dict) -> dict[str, str]:
    """Resolve role assignments and return only aliases backed by Ollama."""
    required: dict[str, str] = {}
    for alias in {
        str(model_assignments.get("builder", "")).strip(),
        str(model_assignments.get("monitor", "")).strip(),
        str(model_assignments.get("oracle", "")).strip(),
        str(model_assignments.get("architect", "")).strip(),
    }:
        if not alias:
            continue
        real_model, _ = _resolve_model(alias)
        if real_model.startswith("ollama/"):
            required[alias] = real_model
    return required


def _ollama_model_installed(real_model: str, installed_models: set[str]) -> bool:
    """Return whether an Ollama model request matches installed tags exactly."""
    if not real_model.startswith("ollama/"):
        return True
    requested = real_model.removeprefix("ollama/")
    if ":" in requested:
        return requested in installed_models
    return requested in installed_models or f"{requested}:latest" in installed_models


def _missing_ollama_models(required: dict[str, str], installed_models: set[str]) -> list[str]:
    return [
        f"{alias} -> {real_model}"
        for alias, real_model in sorted(required.items())
        if not _ollama_model_installed(real_model, installed_models)
    ]


def _builder_fallback_aliases(primary_alias: str) -> list[str]:
    """Return configured Builder fallback aliases from litellm_config.yaml."""
    config_path = _EXECUTOR_ROOT / "litellm_config.yaml"
    if not primary_alias or not config_path.exists():
        return []
    try:
        import yaml

        with config_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as exc:
        log.debug("Builder fallback config unavailable: %s", exc)
        return []
    rows = (cfg.get("router_settings") or {}).get("fallbacks") or []
    for row in rows:
        if not isinstance(row, dict) or primary_alias not in row:
            continue
        values = row.get(primary_alias) or []
        if isinstance(values, list):
            return [str(v) for v in values if str(v).strip()]
    return []


def _response_text(resp) -> str:
    try:
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""


_HEALTH_OK_RE = re.compile(r"\bok\b", re.IGNORECASE)
_HEALTH_MAX_LEN = 2000


def _is_healthy_builder_response(text: str) -> bool:
    """A builder passes the health check if its response contains a
    standalone 'ok' token and isn't a runaway/garbage-length reply.

    Found live 2026-07-02: an exact-match `text.lower() == "ok"` check
    failed the production DSL-fine-tuned Builder (determinex-engineer-v11-dsl)
    100% of 3 independent live calls -- its fine-tuning trained it to
    always wrap even a trivial reply in structured formatting
    ("### Assistant\nok\n\n### Code:\n..."), so it can respond correctly
    and still never satisfy an exact string match. That's a real, working
    model being rejected by a check that tests formatting compliance, not
    actual health. A response with no standalone 'ok' token at all, or one
    that's absurdly long (suggesting runaway/looping generation), still
    correctly fails -- this is not a blanket loosening."""
    if not text:
        return False
    if len(text) > _HEALTH_MAX_LEN:
        return False
    return bool(_HEALTH_OK_RE.search(text))


def _preflight_builder_health(
    model_assignments: dict,
    *,
    fallback_aliases: list[str] | None = None,
    timeout: int | None = None,
) -> tuple[bool, str]:
    """Check that the selected Builder returns exactly 'ok', with local fallbacks."""
    import litellm

    primary = str(model_assignments.get("builder") or "").strip()
    if not primary:
        return False, "no builder model assigned"

    timeout = timeout or int(os.environ.get("DETERMINEX_BUILDER_HEALTH_TIMEOUT", "60"))
    candidates: list[str] = [primary]
    env_fallback = os.environ.get("DETERMINEX_BUILDER_FALLBACK_MODEL", "").strip()
    if env_fallback:
        candidates.append(env_fallback)
    for alias in (
        fallback_aliases if fallback_aliases is not None else _builder_fallback_aliases(primary)
    ):
        candidates.append(alias)

    unique_candidates: list[str] = []
    for alias in candidates:
        if alias and alias not in unique_candidates:
            unique_candidates.append(alias)

    failures: list[str] = []
    messages = [
        {"role": "system", "content": "Health check. Return exactly: ok"},
        {"role": "user", "content": "Return exactly: ok"},
    ]
    for alias in unique_candidates:
        try:
            extra_body = _provider_extra_body(
                alias,
                "builder",
                get_hw_profile(),
                force_evict=True,
            )
            call_kwargs = {
                "model": alias,
                "messages": messages,
                "session_id": "builder-health-preflight",
                "role": "builder",
                "estimated_tokens": 20,
                "timeout": timeout,
            }
            if extra_body:
                call_kwargs["extra_body"] = extra_body
            resp = api_call(litellm.completion, **call_kwargs)
            text = _response_text(resp)
            if _is_healthy_builder_response(text):
                if alias != primary:
                    model_assignments["builder"] = alias
                    return True, f"switched builder from {primary} to {alias}"
                return True, f"builder {alias} passed health preflight"
            failures.append(f"{alias}: returned {text[:80]!r}")
        except Exception as exc:
            failures.append(f"{alias}: {type(exc).__name__}: {str(exc)[:120]}")

    return False, "builder health preflight failed; " + "; ".join(failures)


log = logging.getLogger("hive")

# ── Build loop constants ──────────────────────────────────────────────────────
MAX_RETRIES_PER_STEP = 3
MAX_CHALLENGES_PER_STEP = 2
MIN_CHALLENGE_DELTA = 0.1
MAX_ESCALATIONS_PER_STEP = 1
MONITOR_TIMEOUT_SECONDS = 90
OSCILLATION_THRESHOLD = 3  # same file hash this many times = DAG cycle
MAX_LINES_BEFORE_FORCE_REPLACE = 300  # above this, force replace_file semantics

# ── Oscillation detection state (per session, in-memory) ─────────────────────
_file_hash_history: dict[str, dict[str, list[str]]] = {}

# ── G15: Structured metrics emission ─────────────────────────────────────────
import threading as _metrics_threading

_metrics_lock = _metrics_threading.Lock()
_EXECUTOR_ROOT = (
    Path(os.environ["DETERMINEX_ROOT"]).resolve()
    if os.environ.get("DETERMINEX_ROOT")
    else Path(__file__).resolve().parent.parent.parent
)
_METRICS_LOG = _EXECUTOR_ROOT / "logs" / "determinex_metrics.jsonl"


def _emit_metric(event: str, session_id: str, step_id: int, **kwargs) -> None:
    """G15: Append a JSON-lines metrics event to logs/determinex_metrics.jsonl.

    Fires at step start/complete/fail and monitor verdict so telemetry pipelines
    can reconstruct per-step timing and quality distributions without parsing logs.
    Non-fatal — a write failure never affects the build loop.
    """
    import time as _time_metrics

    record = {
        "ts": _time_metrics.time(),
        "event": event,
        "session_id": session_id,
        "step_id": step_id,
        **kwargs,
    }
    try:
        _METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _metrics_lock:
            with _METRICS_LOG.open("a", encoding="utf-8") as _mf:
                _mf.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _record_file_hash(session_id: str, workspace, target_file: str) -> bool:
    """Record current file hash and return True if oscillation detected."""
    path = workspace / target_file
    if not path.exists():
        return False
    try:
        h = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return False
    history = _file_hash_history.setdefault(session_id, {})
    hist = history.setdefault(target_file, [])
    hist.append(h)
    if len(hist) >= OSCILLATION_THRESHOLD and len(set(hist[-OSCILLATION_THRESHOLD:])) == 1:
        return True
    return False


# ── Escalation payload builder ────────────────────────────────────────────────


def build_escalation_payload(
    step: StepRecord, last_builder_output: str, last_compiler_error: str, monitor_notes: str
) -> dict:
    """Architect escalation payload."""
    return {
        "type": "step_replan",
        "step_id": step.id,
        "original_instruction": step.instruction,
        "dsl_context": step.dsl_context,
        "builder_final_attempt": last_builder_output[:1500],
        "compiler_errors": [last_compiler_error[:800]],
        "monitor_notes": monitor_notes,
        "attempts": step.retries,
        "escalation_number": step.escalations + 1,
    }


def _is_rust_missing_main_error(output: str) -> bool:
    return (
        "E0601" in output
        and "function not found" in output
        and ("main" in output or "`main`" in output)
    )


def _rust_package_name(workspace: Path) -> str:
    cargo_toml = workspace / "Cargo.toml"
    if cargo_toml.is_file():
        match = re.search(
            r'^name\s*=\s*"([^"]+)"', cargo_toml.read_text(encoding="utf-8"), re.MULTILINE
        )
        if match:
            return match.group(1)
    return ""


def _rust_missing_main_repair(workspace: Path, instruction: str) -> str:
    package_name = _rust_package_name(workspace)
    if "lane_d_message" in instruction and package_name:
        crate_name = package_name.replace("-", "_")
        return (
            f"use {crate_name}::lane_d_message;\n\n"
            "fn main() {\n"
            '    println!("{}", lane_d_message());\n'
            "}\n"
        )
    return 'fn main() {\n    println!("not implemented");\n}\n'


# ── Step execution engine ─────────────────────────────────────────────────────


def _correctness_allows_completion(
    session: ManifestSession,
    step: StepRecord,
    workspace: Path,
    code: str,
) -> tuple[bool, str]:
    """Return whether compile-passing code may complete the step."""
    if detect_compile_hack(code):
        step.correctness_result = "compile_hacked"
        step.quality = "compile_hacked"
        return (
            False,
            "[Static Hack Detected] Your implementation uses a stub pattern "
            "(unimplemented!(), todo!(), raise NotImplementedError, or empty body). "
            "You MUST write a real implementation.",
        )

    if not session.correctness_test_harness:
        return True, ""

    passed, output = run_correctness_tests(
        workspace,
        session.lang,
        session.correctness_test_harness,
    )
    # Skip first, by prefix -- see the long note at the other call site. Every skip signal is
    # returned as (True, signal), so testing `passed` first made this branch unreachable and a step
    # whose tests never ran was recorded as a correctness pass.
    if _is_correctness_skip(output):
        step.correctness_result = "skipped"
        return True, ""
    if passed:
        step.correctness_result = "pass"
        return True, ""

    step.correctness_result = "compile_hacked"
    step.quality = "compile_hacked"
    return (
        False,
        f"[Correctness Test FAIL] Your code compiled but the test suite failed.\n"
        f"Fix the implementation so all tests pass.\n\n"
        f"Test output:\n{output[:700]}",
    )


def execute_step(
    session: ManifestSession,
    step: StepRecord,
    model_assignments: dict,
    rosetta: RosettaBridge | None = None,
    compiler_lock: threading.Lock | None = None,
    manifest_lock: threading.Lock | None = None,
    chrono: _ChronoDaemon | None = None,
    rag: object | None = None,
) -> StepRecord:
    """
    Execute a single DAG step through the full Build Loop:

    1. Assemble Builder context → call Builder via api_call(litellm.completion)
       (or via RosettaBridge soft-prefix injection if bridge is active)
    2. Write output to workspace via apply_step_output()
    3. Call Compiler Oracle via validate_project()
    4. On PASS: WAL .pending → .complete, snapshot API, return
    5. On FAIL: retry up to MAX_RETRIES_PER_STEP with compiler error injected
    6. After 3 fails: escalate to Architect via build_escalation_payload()
    7. Call Monitor for verdict; if delta > MIN_CHALLENGE_DELTA, submit challenge
       Monitor hidden state is captured and projected to Builder space via Rosetta
       for the next retry attempt (if RosettaBridge is active).
    """
    import litellm

    workspace = Path(session.project_root)
    last_compiler_error = ""
    last_builder_output = ""
    monitor_notes = ""
    _rosetta_monitor_h = None  # Monitor hidden state for next-retry Rosetta injection

    # G10: wrap every save_manifest() call in this function with the optional lock
    # so concurrent wave threads don't interleave partial session writes.
    def _msave() -> None:
        _ctx = manifest_lock if manifest_lock is not None else contextlib.nullcontext()
        with _ctx:
            save_manifest(session)

    # ── Thermal guard: pause or abort before consuming GPU/CPU ───────────
    thermal_snap = None
    try:
        # #23: Hard thermal halt — GPU danger = immediate abort (not pause).
        # At 85°C the GPU thermally throttles and FP16 inference quality degrades.
        thermal_snap = thermal_hard_halt(session_id=session.session_id)
    except ThermalCriticalError as e:
        log.error("Thermal abort on step %d: %s", step.id, e)
        step.status = "failed"
        step.compiler_result = "thermal_abort"
        wal_fail(session.session_id, step.id, {"error": str(e)})
        _msave()
        return step

    # ── Mark in-progress ──────────────────────────────────────────────────
    step.status = "in_progress"
    wal_write_pending(session.session_id, step)
    _msave()
    _emit_metric(
        "step_start",
        session.session_id,
        step.id,
        target_file=step.target_file,
        instruction=step.instruction[:80],
    )

    log.info("═══ Step %d: %s", step.id, step.instruction[:80])

    # ── Chrono-Daemon: snapshot buffer state before Builder runs ──────────
    if chrono is not None and step.target_file:
        try:
            _target_path = workspace / step.target_file
            if _target_path.exists():
                chrono.update_buffer(
                    str(_target_path),
                    _target_path.read_text(encoding="utf-8", errors="backslashreplace"),
                    language=session.lang,
                )
        except Exception as _ce:
            log.debug("ChronoDaemon.update_buffer failed (non-fatal): %s", _ce)

    # ── Builder retry loop ────────────────────────────────────────────────
    for attempt in range(MAX_RETRIES_PER_STEP):
        step.retries = attempt

        # 1. Assemble Builder messages and call
        # For compiled languages (Rust/Go/Python+mypy), inject specific compiler errors — they are
        # line-and-type precise and the model can act on them.
        # Python now uses mypy for semantic type checking, making errors LLM-actionable.
        _inject_error = last_compiler_error and session.lang.lower() in ("rust", "go", "python")
        # #7 Attention-Aware Rollup: on attempt >= 2, prune accumulated context.
        # By attempt 3 the attention softmax is overwhelmingly biased toward the
        # most recent errors and the system prompt — the core spec in the middle
        # is forgotten. Hard-reset to spec + latest error only.
        _prune = attempt >= 2
        messages = _build_builder_messages(
            session,
            step,
            workspace,
            compiler_error=last_compiler_error if _inject_error else "",
            attempt=attempt,
            prune_context=_prune,
        )
        # Burnout check: if COMPILE_LOOP or TUNNEL_VISION threshold crossed,
        # prepend the intervention prompt to break the Builder out of a rut.
        _burnout_prefix = ""
        if chrono is not None and step.target_file:
            try:
                _bev = chrono.check_burnout()
                if _bev is not None:
                    log.warning(
                        "  [Chrono] Burnout event: %s — injecting intervention prompt",
                        _bev.event_type,
                    )
                    _burnout_prefix = _bev.intervention_prompt + "\n\n"
            except Exception as _be:
                log.debug("ChronoDaemon.check_burnout failed (non-fatal): %s", _be)

        log.info(
            "  Builder call (attempt %d/%d, model=%s)",
            attempt + 1,
            MAX_RETRIES_PER_STEP,
            model_assignments["builder"],
        )
        print(
            f"[DETERMINEX] Builder step {step.id} (attempt {attempt + 1}/{MAX_RETRIES_PER_STEP})...",
            flush=True,
        )

        # ── Rosetta soft-prefix injection (attempt >= 1 and Monitor hidden state available) ──
        # On the first retry after a Monitor verdict, we have _rosetta_monitor_h:
        # the Monitor's last-token hidden state projected to Builder arch space.
        # We use DeterminexInference directly (bypassing Ollama) so the soft prefix
        # is injected into the KV cache before text token decoding begins.
        # Inject burnout intervention into first user message when triggered
        if _burnout_prefix and messages:
            for _m in messages:
                if _m.get("role") == "user":
                    _m["content"] = _burnout_prefix + _m["content"]
                    break

        # LatentRAG: on the first attempt, append retrieved context from similar
        # past builds. On retries, the compiler error is more actionable.
        if rag is not None and attempt == 0:
            try:
                _hits = rag.retrieve_states(step.instruction, top_k=2)
                _previews = [
                    h["context_preview"]
                    for h in _hits
                    if h.get("context_preview") and h.get("similarity", 0) > 0.5
                ]
                if _previews:
                    _latent_ctx = "\n\nSimilar patterns from previous builds:\n" + "\n---\n".join(
                        _previews
                    )
                    for _m in messages:
                        if _m.get("role") == "user":
                            _m["content"] = _m["content"] + _latent_ctx
                            break
                    log.debug("  LatentRAG: injected %d retrieved context(s)", len(_previews))
            except Exception as _lre:
                log.debug("LatentRAG retrieve failed (non-fatal): %s", _lre)

        _rosetta_used = False
        response_text = None
        if (
            attempt >= 1
            and _rosetta_monitor_h is not None
            and rosetta is not None
            and rosetta.available
        ):
            # Flatten messages to a single prompt string for DeterminexInference
            _builder_prompt = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
            _rosetta_tokens = rosetta.build_soft_prefix(_rosetta_monitor_h, _builder_prompt)
            if _rosetta_tokens is not None:
                response_text = rosetta.decode_output(_rosetta_tokens)
                if response_text:
                    _rosetta_used = True
                    log.info("  [Rosetta] Soft-prefix injection ACTIVE on attempt %d", attempt + 1)
                    record_api_call_cost(
                        session, APPROX_TOKENS_PER_STEP, model="determinex/rosetta-local"
                    )  # local, no real cost

        # L1-A: VRAM headroom check — warn before dispatching to a GPU that's nearly full.
        # A freshly-loaded 7B model can consume 6+ GB; if another process has claimed VRAM
        # since startup, the Builder call will stall or OOM rather than giving a clean error.
        _hw = get_hw_profile()
        if _hw.vram_gb > 0:
            _free_gb = get_free_vram_gb()
            if 0.0 < _free_gb < 1.0:
                log.warning(
                    "[L1-A] LOW VRAM HEADROOM: %.2f GB free on step %d attempt %d — "
                    "Builder dispatch may stall. Close other GPU processes if inference hangs.",
                    _free_gb,
                    step.id,
                    attempt + 1,
                )

        if not _rosetta_used:
            # Standard path: call Builder via Ollama → litellm
            try:
                builder_resp = api_call(
                    litellm.completion,
                    model=model_assignments["builder"],
                    messages=messages,
                    session_id=session.session_id,
                    extra_body=_provider_extra_body(
                        model_assignments["builder"],
                        "builder",
                        get_hw_profile(),
                    ),
                )
            except RateLimitExhausted as e:
                log.error("  Rate limit exhausted during Builder call: %s", e)
                step.status = "failed"
                step.compiler_result = "rate_limit_exhausted"
                wal_fail(session.session_id, step.id, {"error": str(e)})
                _msave()
                return step

            usage = getattr(builder_resp, "usage", None)
            tokens = getattr(usage, "total_tokens", 0) if usage else APPROX_TOKENS_PER_STEP
            record_api_call_cost(
                session,
                tokens,
                model=model_assignments["builder"],
                prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            )

            # finish_reason truncation guard (only applies to api_call path)
            finish_reason = getattr(builder_resp.choices[0], "finish_reason", None)
            if finish_reason == "length":
                log.warning(
                    "  Builder output truncated (finish_reason='length') on attempt %d — "
                    "increase max_tokens or shorten context. Skipping this attempt.",
                    attempt + 1,
                )
                # G11: do NOT recycle the truncation message as last_compiler_error —
                # that would inject a fake "compiler error" on the next retry, confusing
                # the Builder into thinking the truncation was a compilation failure.
                continue

            response_text = builder_resp.choices[0].message.content or ""

        code = _extract_code_block(response_text or "")
        last_builder_output = code

        # Shared by both opt-in paths below: apply a candidate and let the SAME
        # Compiler Oracle judge it. Hoisted out of the amplifier block so the
        # router can reuse the identical verifier -- routing must never change
        # what "passes" means, only who gets to attempt it.
        def _apply_validate(_code: str) -> tuple[bool, str]:
            if not apply_step_output(workspace, step, _code):
                return False, "apply_step_output failed"
            _lc = compiler_lock if compiler_lock is not None else contextlib.nullcontext()
            with _lc:
                return validate_project(workspace, session.lang)

        # Per-call telemetry for the generations the router/amplifier make. Two gaps
        # this closes, both recorded as unprobed in the 2026-07-28 probe notes:
        #   * LATENCY had no home anywhere -- the ledger tracks tokens and dollars,
        #     never milliseconds -- while routing measurably cost 27% and 31% more wall
        #     clock than always-frontier. A cost with no instrument is a cost that gets
        #     argued about instead of measured.
        #   * PER-CALL TOKENS were not captured, only per-session totals, so cost could
        #     not be attributed to a rung. That is exactly why the paid A/B has an
        #     unexplained gap: routed made 2 paid calls where baseline made 3, which
        #     predicts ~33% saving, and 1.6% was observed.
        _gen_calls: list[dict] = []

        def _gen_with(_model: str, _temp: float) -> str:
            _t0 = time.time()
            _r = api_call(
                litellm.completion,
                model=_model,
                messages=messages,
                session_id=session.session_id,
                temperature=_temp,
                extra_body=_provider_extra_body(_model, "builder", get_hw_profile()),
            )
            # EVERY extra generation is billed. The single builder call above records
            # its own cost (see `usage = getattr(builder_resp, ...)`), but the router
            # and the amplifier make ADDITIONAL calls through this closure and none of
            # them were counted -- so with DETERMINEX_AMPLIFY=1 and K=6 against a paid
            # model, six calls happened and one was billed, and the budget guard
            # under-counted by ~6x. The routed A/B made this visible: its manifests
            # showed api_cost_usd=0.0 for sessions that demonstrably called DeepSeek.
            #
            # Fixed here rather than in each bridge because both now share this
            # closure, so one accounting point covers both paths.
            _u = getattr(_r, "usage", None)
            record_api_call_cost(
                session,
                getattr(_u, "total_tokens", 0) if _u else APPROX_TOKENS_PER_STEP,
                model=_model,
                prompt_tokens=getattr(_u, "prompt_tokens", None) if _u else None,
                completion_tokens=getattr(_u, "completion_tokens", None) if _u else None,
            )
            _gen_calls.append(
                {
                    "model": _model,
                    "temp": round(float(_temp), 2),
                    "ms": int((time.time() - _t0) * 1000),
                    "tokens_in": int(getattr(_u, "prompt_tokens", 0) or 0) if _u else 0,
                    "tokens_out": int(getattr(_u, "completion_tokens", 0) or 0) if _u else 0,
                }
            )
            return _extract_code_block(_r.choices[0].message.content or "")

        # ── Model Router (DETERMINEX_ROUTE; default derived, see route_decision) ──
        # Walk a configured ladder of builder models cheapest-first, escalating
        # only when verified search on the cheap tier exhausts. A step the local
        # 1.5B can clear costs nothing; one it cannot escalates carrying its own
        # error trace. A no-op unless a ladder of 2+ models is configured
        # (determinex.builder_ladder / DETERMINEX_ROUTE_LADDER).
        _routed = None
        try:
            from hive.router_bridge import load_ladder, route_decision, routed_build

            _route_on, _route_why = route_decision()
            # Logged either way. A derived default that stays silent is indistinguishable
            # from a feature that is broken, and the reason is the whole value of deriving
            # it -- "off because your ladder has a paid rung" is actionable, "off" is not.
            log.info("  [ROUTE] %s -- %s", "on" if _route_on else "off", _route_why)
            if _route_on and not _rosetta_used:
                _ladder = load_ladder()
                _routed = routed_build(
                    lambda _m: lambda _p, _t: _gen_with(_m, _t),
                    _apply_validate,
                    _ladder,
                )
                if _routed is None:
                    log.info(
                        "  [ROUTE] enabled but no 2+ model ladder configured "
                        "(determinex.builder_ladder / DETERMINEX_ROUTE_LADDER) "
                        "-- falling through to the single builder"
                    )
                elif _routed.code:
                    code = _routed.code
                    last_builder_output = code
                    log.info(
                        "  [ROUTE] %s via %s (tier %d, %d escalation(s), "
                        "%d samples, est cost %.3f)",
                        "PASS" if _routed.passed else "best-partial",
                        _routed.model_used,
                        _routed.tier_used,
                        _routed.escalations,
                        _routed.samples,
                        _routed.est_cost,
                    )
                    # Persist WHICH rung produced this, both places. A logged-only
                    # result cannot be measured after the fact, so "routing saved X"
                    # would have no evidence behind it.
                    from hive.router_bridge import (
                        provenance_dict,
                        record_route_decision,
                    )

                    step.route_provenance = provenance_dict(_routed, _gen_calls)
                    record_route_decision(session.session_id, step.id, _routed, _gen_calls)
        except Exception as _route_e:  # never let routing break the build loop
            # WARNING, not debug: the operator explicitly asked for routing via
            # DETERMINEX_ROUTE=1. Swallowing the reason at debug level meant an
            # enabled feature could silently not run, which is indistinguishable
            # from it running and finding nothing to do.
            log.warning("  [ROUTE] skipped (%s): %s", type(_route_e).__name__, _route_e)
            _routed = None

        # ── Correctness Amplifier (opt-in: DETERMINEX_AMPLIFY=1) ──────────────
        # Replace this single candidate with a verified-search winner: sample K
        # builder candidates at varied temperature, apply+validate each against
        # the SAME Compiler Oracle, keep the first that PASSES. Lets a weak local
        # builder converge on steps it could not one-shot. Off by default.
        #
        # Skipped when the router already ran: the router does verified search at
        # every tier it visits, so amplifying afterwards would re-sample a model
        # the oracle has already exhausted -- paying twice for the same evidence.
        try:
            from hive.amplifier_bridge import amplified_build, amplify_enabled

            if amplify_enabled() and not _rosetta_used and _routed is None:

                def _gen_at_temp(_temp: float) -> str:
                    return _gen_with(model_assignments["builder"], _temp)

                _amp = amplified_build(_gen_at_temp, _apply_validate)
                if _amp.code:
                    code = _amp.code
                    last_builder_output = code
                    log.info(
                        "  [AMPLIFY] verified search: %s after %d samples",
                        "PASS" if _amp.passed else "best-partial",
                        _amp.samples,
                    )
        except Exception as _amp_e:  # never let amplification break the build loop
            # Same reasoning as [ROUTE] above: an explicitly-enabled feature that
            # fails must say so.
            log.warning("  [AMPLIFY] skipped (%s): %s", type(_amp_e).__name__, _amp_e)

        # Save builder output to step dir for traceability
        step_output_dir = _steps_dir(session.session_id) / f"step_{step.id:04d}_outputs"
        step_output_dir.mkdir(parents=True, exist_ok=True)
        out_file = step_output_dir / f"attempt_{attempt}.txt"
        _atomic_write(
            out_file, code
        )  # G8: atomic write prevents partial reads by concurrent threads
        step.builder_output_path = str(out_file)

        # L10-B: Preserve Builder reasoning prose — the text before the first
        # ``` fence is the model's chain-of-thought.  Stripping it severs the
        # alignment between reasoning and the generated fix; saving it allows
        # training pipelines to use it for reasoning-trace fine-tuning.
        _fence_idx = (response_text or "").find("```")
        _reasoning = response_text[:_fence_idx].strip() if _fence_idx > 0 else ""
        if _reasoning:
            (step_output_dir / f"attempt_{attempt}.reasoning").write_text(
                _reasoning, encoding="utf-8"
            )

        # 2. Apply to workspace
        if not apply_step_output(workspace, step, code):
            log.error("  apply_step_output failed for step %d", step.id)
            continue

        # #26 Oscillation check — must happen after write, before compile.
        # If this file has seen the same hash > OSCILLATION_THRESHOLD times
        # already, the DAG is cycling. Halt immediately.
        if step.target_file and _record_file_hash(session.session_id, workspace, step.target_file):
            log.error(
                "  [DETERMINEX] OSCILLATION_DETECTED on step %d — "
                "DAG plan is globally incoherent. Halting to prevent infinite API burn.",
                step.id,
            )
            print(
                f"\n[DETERMINEX] ⚠ REFACTOR CONFLICT DETECTED on step {step.id}.\n"
                f"  File '{step.target_file}' has reverted to an identical state "
                f"more than {OSCILLATION_THRESHOLD} times.\n"
                "  The Architect's plan has a cross-file dependency conflict it cannot\n"
                "  resolve step-by-step. Please re-plan with explicit multi-file\n"
                "  dependency ordering."
            )
            step.status = "failed"
            step.compiler_result = "oscillation_abort"
            wal_fail(session.session_id, step.id, {"error": "oscillation_abort"})
            _msave()
            return step

        # 3. Compiler Oracle
        # #30 Linter mutation guard: record file hash BEFORE compilation.
        # Auto-formatters triggered by the compiler toolchain (rustfmt, black,
        # gofmt) may mutate the file on disk silently. If we don't track this,
        # the Orchestrator hashes the file, sees it differs from what it wrote,
        # and incorrectly treats it as a tamper event, rolling back valid code.
        _pre_compile_hash = None
        if step.target_file:
            _target_p = workspace / step.target_file
            if _target_p.exists():
                try:
                    _pre_compile_hash = hashlib.sha256(_target_p.read_bytes()).hexdigest()[:16]
                except OSError:
                    pass

        # Serialise concurrent cargo/go/python builds on the same workspace.
        # compiler_lock is None in sequential mode (no-op); a threading.Lock
        # is injected by run_session() when wave items execute in parallel.
        _lock_ctx = compiler_lock if compiler_lock is not None else contextlib.nullcontext()
        with _lock_ctx:
            passed, compiler_output = validate_project(workspace, session.lang)

        # Safety net: if the ONLY compile error is E0601 (no fn main), inject a stub.
        # This fires when the Builder correctly writes helper functions but forgets the
        # entry point — a common 1.5B model failure for the first step of a binary crate.
        if not passed and session.lang == "rust" and _is_rust_missing_main_error(compiler_output):
            error_lines = [l for l in compiler_output.splitlines() if "error[" in l]
            if len(error_lines) <= 1 and step.target_file and "main.rs" in step.target_file:
                _main_path = workspace / step.target_file
                if _main_path.exists():
                    _existing = _main_path.read_text(encoding="utf-8")
                    if "fn main()" not in _existing:
                        log.info(
                            "  [safety-net] E0601 sole error — injecting fn main() stub "
                            "into %s and retrying compilation",
                            step.target_file,
                        )
                        # G3: use atomic write (temp→rename) — bare write_text on a
                        # shared workspace file risks a partial read by the compiler
                        # if the process is interrupted mid-write.
                        _atomic_write(
                            _main_path,
                            _rust_missing_main_repair(workspace, step.instruction),
                        )
                        passed, compiler_output = validate_project(workspace, session.lang)
                        if passed:
                            log.info("  [safety-net] fn main() stub resolved E0601")
                            # G14: stub was injected by Determinex — mark inconclusive so
                            # Determinex-authored code doesn't auto-ingest into training.
                            step.quality = "inconclusive"

        # Safety net: E0277 serde::Deserialize — the 1.5B engineer consistently
        # imports serde traits but omits #[derive(Deserialize, Serialize)] on the
        # target struct.  Detect the pattern, patch the derive in-place, and
        # re-run the compiler rather than burning retries on an identical error.
        if (
            not passed
            and session.lang == "rust"
            and "E0277" in compiler_output
            and "serde::Deserialize" in compiler_output
            and step.target_file
        ):
            _e0277_m = re.search(r"the trait bound `(\w+): serde::Deserialize", compiler_output)
            if _e0277_m:
                _serde_struct = _e0277_m.group(1)
                _target_p = workspace / step.target_file
                if _target_p.exists():
                    _src = _target_p.read_text(encoding="utf-8")
                    _lines = _src.splitlines()
                    _patched = False
                    for _li, _ln in enumerate(_lines):
                        if re.match(r"\s*(?:pub\s+)?struct\s+" + _serde_struct + r"\b", _ln):
                            for _di in range(_li - 1, max(-1, _li - 6), -1):
                                _dl = _lines[_di]
                                if _dl.strip().startswith("#[derive("):
                                    if "Deserialize" not in _dl:
                                        _close = _dl.rfind(")")
                                        if _close >= 0:
                                            _extra = (
                                                "Deserialize, Serialize"
                                                if "Serialize" not in _dl
                                                else "Deserialize"
                                            )
                                            _lines[_di] = (
                                                _dl[:_close] + f", {_extra}" + _dl[_close:]
                                            )
                                            _patched = True
                                    break
                                elif _dl.strip() and not _dl.strip().startswith("#["):
                                    break
                            if not _patched:
                                # No existing derive — insert one before the struct
                                _ind = re.match(r"^(\s*)", _ln).group(1)
                                _lines.insert(_li, f"{_ind}#[derive(Deserialize, Serialize)]")
                                _patched = True
                            break
                    if _patched:
                        _atomic_write(
                            _target_p,
                            "\n".join(_lines) + ("\n" if _src.endswith("\n") else ""),
                        )
                        log.info(
                            "  [safety-net] E0277 serde — added Deserialize/Serialize "
                            "derive to struct %s, retrying compilation",
                            _serde_struct,
                        )
                        passed, compiler_output = validate_project(workspace, session.lang)
                        if passed:
                            log.info(
                                "  [safety-net] E0277 serde resolve confirmed for %s",
                                _serde_struct,
                            )
                            # G13: re-read patched file so detect_compile_hack() below
                            # operates on the actual compiled content, not the pre-patch LLM output.
                            try:
                                code = _target_p.read_text(
                                    encoding="utf-8", errors="backslashreplace"
                                )
                            except OSError:
                                pass
                            # G14: serde-patched code was authored by Determinex, not the model —
                            # mark inconclusive to prevent it auto-ingesting into training.
                            step.quality = "inconclusive"

        step.compiler_result = "pass" if passed else "fail"
        step.compiler_output = compiler_output[:1000]

        # Chrono-Daemon: record compile result for COMPILE_LOOP burnout detection.
        if chrono is not None and step.target_file:
            try:
                chrono.record_compile_result(
                    buffer_path=str(workspace / step.target_file),
                    function_signature=step.instruction[:120],
                    failed=not passed,
                )
            except Exception as _cre:
                log.debug("ChronoDaemon.record_compile_result failed (non-fatal): %s", _cre)

        # #30: If the file was mutated by a formatter during compilation,
        # update our internal state tracker to the new hash so the Orchestrator
        # doesn't treat the formatter's changes as an integrity violation.
        if passed and step.target_file and _pre_compile_hash is not None:
            _target_p = workspace / step.target_file
            if _target_p.exists():
                try:
                    _post_compile_hash = hashlib.sha256(_target_p.read_bytes()).hexdigest()[:16]
                    if _post_compile_hash != _pre_compile_hash:
                        log.info(
                            "  #30 Linter mutation detected on '%s': "
                            "hash %s → %s (formatter ran — state tracker updated)",
                            step.target_file,
                            _pre_compile_hash,
                            _post_compile_hash,
                        )
                        # Update the hash history so oscillation detection
                        # uses the formatter-normalized hash as the baseline.
                        history = _file_hash_history.get(session.session_id, {})
                        file_hist = history.get(step.target_file, [])
                        if file_hist:
                            file_hist[-1] = _post_compile_hash
                except OSError:
                    pass

        if not passed:
            # #43 OS error intercept: toolchain-missing errors are an environment
            # problem, not a code problem. Feeding them to the Builder as compiler
            # errors burns all retries and poisons the training vault with failures
            # that have nothing to do with model output quality.
            if is_toolchain_error(compiler_output):
                log.error(
                    "  Toolchain error from Compiler Oracle — OS/environment problem, "
                    "not a code error. Aborting step to protect Builder retry loop.\n%s",
                    compiler_output[:400],
                )
                step.status = "failed"
                step.compiler_result = "toolchain_error"
                step.compiler_output = compiler_output[:500]
                wal_fail(
                    session.session_id,
                    step.id,
                    {"error": "toolchain_error", "detail": compiler_output[:300]},
                )
                _msave()
                return step

            sanitized = sanitize_compiler_output(compiler_output, workspace)
            sanitized = _strip_internal_tracebacks(sanitized)  # L14-A
            error_hash = hash_compiler_error(compiler_output, workspace)
            step.compiler_error_hashes.append(error_hash)
            last_compiler_error = sanitized[:1500]  # L13-A: was 800
            log.warning("  Compiler FAIL (attempt %d, hash=%s)", attempt + 1, error_hash)
            continue  # retry with error injected

        # ── Compiler PASS ─────────────────────────────────────────────────
        log.info("  Compiler PASS on attempt %d", attempt + 1)
        last_compiler_error = ""

        # Snapshot public API
        if step.target_file:
            target = workspace / step.target_file
            step.public_api_snapshot = extract_public_api(target, session.lang)

        # Plan A: Correctness Oracle — Enterprise Semantic Guarantee.
        # Two-stage: static hack detection first (free), then test runner if harness exists.
        #
        # GATE SEMANTICS (TDD mode):
        #   - Static hack detected → label compile_hacked, continue retry loop.
        #   - Test harness FAIL → inject test output into Builder as error, continue retry loop.
        #     A step is NOT complete until it both compiles AND its tests pass.
        #   - Test harness SKIP signals (timeout/not-found) → fall through to completion.
        #     Avoids blocking sessions where no harness was generated yet.
        #
        # "Who tests the tests?" limitation: Architect generates from MD spec, not Builder output
        # — genuinely different failure mode coverage. Documented, not hidden.
        _hack_flagged = detect_compile_hack(code)
        if _hack_flagged:
            log.warning(
                "  Static hack detection: unimplemented!()/todo!()/stub pattern found "
                "in step %d — re-entering retry loop.",
                step.id,
            )
            step.correctness_result = "compile_hacked"
            step.quality = "compile_hacked"
            last_compiler_error = (
                "[Static Hack Detected] Your implementation uses a stub pattern "
                "(unimplemented!(), todo!(), raise NotImplementedError, or empty body). "
                "You MUST write a real implementation."
            )
            continue  # re-enter Builder retry loop with hack message injected

        if not _hack_flagged and session.correctness_test_harness:
            _ct_passed, _ct_output = run_correctness_tests(
                workspace,
                session.lang,
                session.correctness_test_harness,
            )
            # SKIP IS CHECKED FIRST, and by prefix. Fixed 2026-07-30.
            #
            # run_correctness_tests returns (True, <signal>) for all five of its skip signals, so
            # `if _ct_passed:` matched first and the `elif` below was UNREACHABLE: a step whose
            # tests never ran was recorded as correctness_result="pass". That fed
            # `_tests_passed` (crediting the gamma channel of the adjudication score) and the dspy
            # trainset (compiler_result=PASS, score=1.0) with a verification that had not happened.
            #
            # Triggers are ordinary, not exotic: the Architect declared a harness path the Builder
            # never wrote; the language is not rust/go/python (TypeScript included, which
            # validate_project now genuinely verifies -- so a whole TS session recorded every step's
            # tests as "pass"); the run timed out; the runner binary is missing.
            #
            # Prefix matching because two signals carry a suffix -- "harness_read_error: {e}" and
            # "runner_not_found: {e}" -- so exact membership missed them, and harness_read_error was
            # not even in the tuple.
            if _is_correctness_skip(_ct_output):
                step.correctness_result = "skipped"
                log.info("  Correctness tests: SKIPPED (%s)", _ct_output)
            elif _ct_passed:
                step.correctness_result = "pass"
                log.info("  Correctness tests: PASS — Semantic Guarantee satisfied.")
            else:
                # GATE: inject test failure back into Builder retry loop.
                # This is the core TDD enforcement: compiler PASS is necessary but
                # not sufficient. The step only completes when tests also pass.
                step.correctness_result = "compile_hacked"
                step.quality = "compile_hacked"
                log.warning(
                    "  Correctness tests FAILED after compiler PASS on step %d — "
                    "re-entering Builder retry loop with test output.\n%s",
                    step.id,
                    _ct_output[:400],
                )
                last_compiler_error = (
                    f"[Correctness Test FAIL] Your code compiled but the test suite failed.\n"
                    f"Fix the implementation so all tests pass.\n\n"
                    f"Test output:\n{_ct_output[:700]}"
                )
                continue  # re-enter Builder retry loop with test failure injected

        # 4. Monitor verdict (if budget allows and model is assigned)
        # Plan B — fast mode: skip live Monitor to reduce build latency.
        # Queue the step for async offline Monitor evaluation when GPU is idle.
        # Without this queue, --fast sessions never generate DPO comparison pairs
        # and the training flywheel stalls (training starvation problem).
        if session.fast_mode:
            log.info(
                "  Fast mode: Monitor skipped — queuing step %d for offline observation", step.id
            )
            step.offline_observation_pending = True
            step.offline_observation_result = "pending"
            wal_queue_offline(session.session_id, step)

        # #44 Circular Monitor guard: on extreme Tier 0 the same model may be assigned
        # to both Builder and Monitor. A model evaluating its own output is useless —
        # it will reproduce the same reasoning errors it just made.
        _monitor_model = None if session.fast_mode else model_assignments.get("monitor")
        if _monitor_model and _monitor_model == model_assignments.get("builder"):
            log.warning(
                "  Monitor skipped: assigned model (%s) is same as Builder — "
                "circular self-evaluation is not useful on this tier.",
                _monitor_model,
            )
            step.monitor_verdict = "monitor_skipped:same_model_as_builder"
            step.adjudication_score = 0.5
            _monitor_model = None  # disable Monitor block below

        # VRAM guard: on Tier -1 hardware (< 4GB VRAM / CPU-only), local Ollama
        # models cannot fit in VRAM and will thrash the OS page file — a 3B model
        # that takes seconds on Tier 0 can take hours on Tier -1 via CPU swap.
        # Local model aliases are prefixed with "determinex/", "local/", or "ollama/".
        if _monitor_model:
            _hw = get_hw_profile()
            _is_local_monitor = any(
                _monitor_model.startswith(p) for p in ("determinex/", "local/", "ollama/")
            )
            if _hw.tier < 0 and _is_local_monitor:
                log.warning(
                    "  Monitor skipped: local model '%s' cannot fit in VRAM on "
                    "Tier -1 hardware (%.1f GB detected). Assign monitor to an "
                    "API model (e.g. cloud/claude-fast) to enable critique on "
                    "this machine.",
                    _monitor_model,
                    _hw.vram_gb,
                )
                step.monitor_verdict = "monitor_skipped:insufficient_vram"
                step.adjudication_score = 0.5
                _monitor_model = None

        if not session.budget_exhausted and _monitor_model:
            try:
                monitor_msgs = _build_monitor_messages(session, step, code, passed)
                monitor_model = _monitor_model
                monitor_extra = _provider_extra_body(monitor_model, "monitor", get_hw_profile())

                def _run_monitor():
                    return api_call(
                        litellm.completion,
                        model=monitor_model,
                        messages=monitor_msgs,
                        session_id=session.session_id,
                        extra_body=monitor_extra,
                    )

                # #39 dynamic IPC timeout: scale by thermal throttle factor so
                # thermally throttled hardware doesn't produce spurious timeouts.
                _monitor_timeout = dynamic_ipc_timeout(MONITOR_TIMEOUT_SECONDS, thermal_snap)
                try:
                    monitor_resp = _run_daemon_timeout(_run_monitor, _monitor_timeout)
                except concurrent.futures.TimeoutError:
                    log.warning(
                        "  Monitor timed out after %.0fs — skipping verdict", _monitor_timeout
                    )
                    step.monitor_verdict = f"monitor_timeout:{_monitor_timeout:.0f}s"
                    step.adjudication_score = 0.5
                    monitor_notes = step.monitor_verdict
                    raise  # caught below

                m_usage = getattr(monitor_resp, "usage", None)
                m_tokens = getattr(m_usage, "total_tokens", 0) if m_usage else 500
                record_api_call_cost(
                    session,
                    m_tokens,
                    model=monitor_model,
                    prompt_tokens=getattr(m_usage, "prompt_tokens", None) if m_usage else None,
                    completion_tokens=getattr(m_usage, "completion_tokens", None)
                    if m_usage
                    else None,
                )

                m_text = monitor_resp.choices[0].message.content or ""
                m_score, m_verdict = _parse_monitor_verdict(m_text)
                step.monitor_verdict = m_verdict
                step.adjudication_score = m_score
                monitor_notes = m_verdict
                log.info("  Monitor score=%.2f: %s", m_score, m_verdict[:80])
                _emit_metric(
                    "monitor_verdict",
                    session.session_id,
                    step.id,
                    score=m_score,
                    verdict=m_verdict[:120],
                )

                # L9-A: Observer veto — when Monitor is very confident the fix
                # is wrong (score < 0.3), demote to human review even if the
                # compiler passes.  The Compiler is not the final arbiter of
                # semantic correctness; a hardcoded or stub solution can pass
                # compilation while failing every real-world invariant.
                if m_score < 0.3:
                    log.warning(
                        "  [L9-A] Observer veto: Monitor score %.2f < 0.3 — "
                        "step %d will be routed to human review despite compiler PASS.",
                        m_score,
                        step.id,
                    )
                    step.quality = "inconclusive"

                # ── Rosetta: capture Monitor hidden state for next Builder retry ──
                # If the Monitor found issues (score < threshold), extract its
                # last-token hidden state. On the next Builder retry, this is
                # projected to Builder arch space and injected as a soft prefix
                # so the Builder's generation is semantically steered by what
                # the Monitor identified as wrong.
                if (
                    rosetta is not None
                    and rosetta.available
                    and m_score < (1.0 - MIN_CHALLENGE_DELTA)
                    and m_text
                ):
                    _h = rosetta.extract_monitor_hidden(m_text)
                    if _h is not None:
                        _rosetta_monitor_h = _h
                        log.info(
                            "  [Rosetta] Monitor hidden state captured (score=%.2f) "
                            "→ will inject as soft prefix on next Builder retry",
                            m_score,
                        )

                # Challenge protocol
                if (
                    step.challenges < MAX_CHALLENGES_PER_STEP
                    and m_score < (1.0 - MIN_CHALLENGE_DELTA)
                    and not session.budget_exhausted
                ):
                    log.info(
                        "  Challenge opportunity (score=%.2f < threshold=%.1f)",
                        m_score,
                        1.0 - MIN_CHALLENGE_DELTA,
                    )
                    step.challenges += 1
            except (RateLimitExhausted, concurrent.futures.TimeoutError):
                pass  # timeout already logged and defaults set above
            except Exception as e:
                log.warning("  Monitor call failed (non-fatal): %s", e)
                step.monitor_verdict = f"monitor_unavailable: {e}"
                step.adjudication_score = 0.5

        # Compute adjudication score using nomic-embed-text.
        # tests_exist=True when we actually ran the correctness suite AND it passed,
        # enabling the test-weight (gamma) channel in the adjudication formula.
        if step.instruction and code:
            semantic_sim = adjudication_cosine(step.instruction, code)
            _tests_passed = getattr(step, "correctness_result", "skipped") == "pass"
            weights = effective_adjudication_weights(tests_exist=_tests_passed, lang=session.lang)
            compile_score = 1.0 if passed else 0.0
            test_score = 1.0 if _tests_passed else 0.0
            step.adjudication_score = (
                weights["alpha"] * compile_score
                + weights["beta"] * semantic_sim
                + weights.get("gamma", 0.0) * test_score
                + weights["delta"] * max(0.0, 1.0 - len(code) / 10000)
            )

        # ── SUCCESS: WAL .pending → .complete ─────────────────────────────
        step.status = "complete"
        wal_complete(session.session_id, step.id)
        _emit_metric(
            "step_complete",
            session.session_id,
            step.id,
            retries=step.retries,
            adj_score=step.adjudication_score,
            quality=step.quality,
        )

        # P2 integrity checks — demote to human review if code is suspicious.
        # These run only on compiler-pass steps so we don't penalise failed attempts.
        if code:
            _integrity_flags: list[str] = []
            _integrity_flags.extend(_detect_hardcode_cheat(code))  # L12-A
            _integrity_flags.extend(_detect_brevity_cheat(code))  # Mole-113
            _integrity_flags.extend(_detect_ghost_imports(code, session.lang))  # Mole-114
            if _integrity_flags:
                log.warning(
                    "  [P2 integrity] Step %d flagged — routing to human review: %s",
                    step.id,
                    "; ".join(_integrity_flags),
                )
                step.quality = "inconclusive"  # overrides classify_training_quality

        # ── Provenance check (fire-and-forget) ────────────────────────────────
        # Run after P2 integrity and before training queue so provenance tags
        # are logged alongside every compiler-pass step. Never blocks.
        if code:
            try:
                from determinex_copyright_guard import get_guard as _get_pguard

                _pguard = _get_pguard()
                _task_id = f"{session.session_id}_step{step.id}"
                _preport = _pguard.check_provenance(code, task_id=_task_id)
                if _preport.has_copyright_violation:
                    log.warning(
                        "  [provenance] COPYRIGHT ALERT step %d: %s",
                        step.id,
                        ", ".join(a.work_label for a in _preport.copyright_alerts),
                    )
                if _preport.has_attributions:
                    _tags = [
                        t
                        for t in _preport.attribution_tags
                        if t.match_type != "verbatim_reproduction"
                    ]
                    if _tags:
                        log.info(
                            "  [provenance] attribution: %s",
                            ", ".join(t.source_label for t in _tags[:5]),
                        )
                _pguard.log_attribution(_preport)
            except Exception as _pe:
                log.debug("  [provenance] check failed (non-fatal): %s", _pe)

        session.workspace_file_hashes = hash_workspace_files(workspace, session.lang)
        _msave()

        queue_for_training(session, step)

        log.info("  ✓ Step %d COMPLETE (adj=%.3f)", step.id, step.adjudication_score)
        return step

    # ── All retries exhausted — Architect escalation ──────────────────────
    log.warning(
        "  Step %d: %d/%d retries exhausted — escalating to Architect",
        step.id,
        MAX_RETRIES_PER_STEP,
        MAX_RETRIES_PER_STEP,
    )

    if step.escalations < MAX_ESCALATIONS_PER_STEP:
        step.escalations += 1
        payload = build_escalation_payload(
            step,
            last_builder_output,
            last_compiler_error,
            monitor_notes,
        )

        log.info(
            "  Architect escalation #%d (model=%s)",
            step.escalations,
            model_assignments.get("architect", "N/A"),
        )

        try:
            import litellm

            esc_messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are the Architect for a {session.lang.capitalize()} project. "
                        f"A build step has failed {MAX_RETRIES_PER_STEP} times. "
                        "Analyze the failure and provide a revised step instruction. "
                        "Reply with ONLY the new instruction text — no code, no explanation."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, indent=2)},
            ]

            _arch_model = model_assignments.get("architect") or model_assignments["builder"]
            arch_resp = api_call(
                litellm.completion,
                model=_arch_model,
                messages=esc_messages,
                session_id=session.session_id,
                extra_body=_provider_extra_body(_arch_model, "architect", get_hw_profile()),
            )
            a_usage = getattr(arch_resp, "usage", None)
            a_tokens = getattr(a_usage, "total_tokens", 0) if a_usage else 1000
            record_api_call_cost(
                session,
                a_tokens,
                model=_arch_model,
                prompt_tokens=getattr(a_usage, "prompt_tokens", None) if a_usage else None,
                completion_tokens=getattr(a_usage, "completion_tokens", None) if a_usage else None,
            )

            revised = (arch_resp.choices[0].message.content or "").strip()
            # Guard: Architect sometimes returns code instead of an instruction.
            # Detect by looking for code markers — if found, discard and keep original.
            _code_markers = (
                "```",
                "use std::",
                "fn main",
                "func main",
                "def main",
                "import ",
                "#include",
                "package main",
            )
            if revised and not any(
                revised.startswith(m) or (m in revised[:80]) for m in _code_markers
            ):
                step.instruction = revised[:500]
            else:
                # Architect returned code — use a simplified fallback instruction
                step.instruction = (
                    f"Write the COMPLETE, compilable {session.lang} implementation "
                    f"for {step.target_file}. "
                    "Write minimal, correct code. No imports that are not in Cargo.toml. "
                    "Include fn main() if this is src/main.rs."
                )
                log.warning("  Architect returned code instead of instruction — using fallback")
            log.info("  Architect revised instruction: %s", step.instruction[:80])

            # Check for API drift
            if step.target_file:
                old_snapshot = step.public_api_snapshot or {}

            # One more Builder attempt with revised instruction
            step.retries = 0
            last_compiler_error = ""
            messages = _build_builder_messages(session, step, workspace)

            esc_resp = api_call(
                litellm.completion,
                model=model_assignments["builder"],
                messages=messages,
                session_id=session.session_id,
                extra_body=_provider_extra_body(
                    model_assignments["builder"],
                    "builder",
                    get_hw_profile(),
                ),
            )
            e_usage = getattr(esc_resp, "usage", None)
            e_tokens = getattr(e_usage, "total_tokens", 0) if e_usage else APPROX_TOKENS_PER_STEP
            record_api_call_cost(
                session,
                e_tokens,
                model=model_assignments["builder"],
                prompt_tokens=getattr(e_usage, "prompt_tokens", None) if e_usage else None,
                completion_tokens=getattr(e_usage, "completion_tokens", None) if e_usage else None,
            )

            esc_code = _extract_code_block(esc_resp.choices[0].message.content or "")
            # G8: save escalation builder output atomically for traceability
            _esc_out_dir = _steps_dir(session.session_id) / f"step_{step.id:04d}_outputs"
            _esc_out_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(_esc_out_dir / "escalation.txt", esc_code)
            apply_step_output(workspace, step, esc_code)
            _lock_ctx = compiler_lock if compiler_lock is not None else contextlib.nullcontext()
            with _lock_ctx:
                passed, output = validate_project(workspace, session.lang)

            if passed:
                correctness_ok, correctness_error = _correctness_allows_completion(
                    session,
                    step,
                    workspace,
                    esc_code,
                )
                if not correctness_ok:
                    step.compiler_result = "correctness_fail"
                    step.compiler_output = correctness_error[:500]
                    last_compiler_error = correctness_error
                    log.warning(
                        "  Escalation compile passed but correctness gate failed on step %d",
                        step.id,
                    )
                    raise RuntimeError(correctness_error[:500])

                step.status = "complete"
                step.compiler_result = "pass"
                if step.target_file:
                    new_snapshot = extract_public_api(workspace / step.target_file, session.lang)
                    step.public_api_snapshot = new_snapshot
                    if old_snapshot and api_snapshots_differ(old_snapshot, new_snapshot):
                        flagged = flag_stale_downstream(session, step.id)
                        log.warning(
                            "  API drift detected — %d downstream steps flagged stale", flagged
                        )

                wal_complete(session.session_id, step.id)
                session.workspace_file_hashes = hash_workspace_files(workspace, session.lang)
                _msave()
                queue_for_training(session, step)
                log.info("  ✓ Step %d COMPLETE after escalation", step.id)
                return step
            else:
                step.compiler_error_hashes.append(hash_compiler_error(output, workspace))
                log.warning("  Escalation attempt also failed to compile")

        except (RateLimitExhausted, Exception) as e:
            log.error("  Architect escalation failed: %s", e)

    # ── Final failure ─────────────────────────────────────────────────────
    step.status = "failed"
    step.quality = classify_training_quality(step)
    wal_fail(
        session.session_id,
        step.id,
        {
            "final_compiler_error": last_compiler_error[:500],
            "monitor_notes": monitor_notes[:300],
        },
    )
    _msave()
    _emit_metric(
        "step_fail",
        session.session_id,
        step.id,
        retries=step.retries,
        quality=step.quality,
        escalations=step.escalations,
    )
    queue_for_training(session, step)
    log.error("  ✗ Step %d FAILED (exhausted retries + escalation)", step.id)
    return step


def run_session(
    session_id: str,
    model_assignments: dict | None = None,
    fast_mode: bool = False,
) -> ManifestSession:
    """
    Run the full DAG execution loop for a session.
    """
    # G2: crash-recovery — reset orphaned in_progress steps from any prior run
    _recovered = SessionWAL.recover_stale()
    if _recovered:
        log.info("[SessionWAL] Recovered %d orphaned session(s): %s", len(_recovered), _recovered)

    session = load_manifest(session_id)
    workspace = Path(session.project_root)

    if fast_mode and not session.fast_mode:
        session.fast_mode = True
        save_manifest(session)
        log.info(
            "Fast mode enabled — Monitor will be skipped; steps queued for offline observation"
        )

    if model_assignments is None:
        model_assignments = load_role_assignments()
    log.info("Model assignments: %s (fast_mode=%s)", model_assignments, session.fast_mode)

    # G1: session-level WAL — write PID + intent before any work begins so a
    # crash leaves a recoverable record (picked up by recover_stale() on next boot).
    _session_wal = SessionWAL(session, "run_session")
    _session_wal.__enter__()

    # ── SEC-2: verify Job Object sandbox is available before first compile ──
    # Raises SandboxUnavailableError with instructions if unavailable and
    # DETERMINEX_ALLOW_UNSANDBOXED=1 is not set. On non-Windows this is a no-op.
    ensure_sandbox_available()

    # ── ForgeDaemon: start autonomous telemetry flywheel ─────────────────
    forge_daemon = start_forge_daemon()
    log.info("ForgeDaemon: %s", forge_daemon.status())

    # ── ChronoDaemon: Burnout Protocol / Synthetic Peer monitor ──────────
    _chrono_inst = None
    if _ChronoDaemon is not None:
        try:
            _chrono_inst = _ChronoDaemon(session_id=session.session_id)
            _chrono_inst.start()
            log.info("ChronoDaemon started (burnout monitor active)")
        except Exception as _cde:
            log.warning("ChronoDaemon failed to start (non-fatal): %s", _cde)
            _chrono_inst = None

    # ── WAL recovery ──────────────────────────────────────────────────────
    pending_recovery = wal_recover_pending(session_id)
    if pending_recovery:
        for sid in pending_recovery:
            for step in session.steps:
                if step.id == sid:
                    step.status = "pending"
                    step.retries = 0
        save_manifest(session)
        log.info("WAL recovery: reset %d incomplete steps to pending", len(pending_recovery))

    if not session.steps:
        log.error("Session has no steps — run Architect first to populate the DAG")
        return session

    # ── Disk space pre-flight ─────────────────────────────────────────────
    # Catch the disk-full case before any compilation touches the workspace.
    # A full /tmp causes cargo/go to silently produce corrupt binaries or
    # confusing "No space left on device" errors buried in compiler output.
    try:
        import shutil as _shutil

        _free_gb = _shutil.disk_usage(workspace).free / (1024**3)
        if _free_gb < 0.5:
            log.error(
                "Disk space pre-flight FAIL: %.2fGB free (need ≥0.5GB) in %s", _free_gb, workspace
            )
            print(
                f"\n[DETERMINEX] Insufficient disk space: {_free_gb:.2f}GB free. "
                f"Need at least 500MB. Free space in: {workspace}"
            )
            return session
        log.info("Disk space pre-flight: %.2fGB free — OK", _free_gb)
    except Exception as _e:
        log.warning("Disk space check failed (non-fatal): %s", _e)

    # ── Toolchain pre-flight ──────────────────────────────────────────────
    # Check the compiler/runtime BEFORE the DAG starts. A missing Go install
    # (or cargo, or python) causes every step to fail with an OS error that
    # the Builder cannot fix — it has no concept of the host environment.
    # Catching this here produces one clear user-facing message instead of
    # 3 × N_STEPS × confusing "command not found" entries in the training vault.
    _tc_ok, _tc_err = check_toolchain_available(session.lang)
    if not _tc_ok:
        log.error("Toolchain pre-flight FAIL for lang='%s': %s", session.lang, _tc_err)
        print(f"\n[DETERMINEX] Required toolchain for '{session.lang}' is not installed.")
        print(f"  {_tc_err}")
        print("  Install the toolchain, then re-run this session.")
        return session

    try:
        _required_ollama = _required_ollama_models(
            {
                "monitor": model_assignments.get("monitor", ""),
                "oracle": model_assignments.get("oracle", ""),
                "architect": model_assignments.get("architect", ""),
            }
        )
    except Exception as _model_resolve_err:
        log.error("Model assignment pre-flight FAIL: %s", _model_resolve_err)
        print("\n[DETERMINEX] Model assignment pre-flight failed.")
        print(f"  {_model_resolve_err}")
        print("  Check litellm_config.yaml and provider opt-in settings, then re-run this session.")
        return session

    # ── Ollama pre-flight: is Ollama serving? ─────────────────────────────
    # The Tauri setup wizard handles Ollama install and start on first boot.
    # But when running the Python sidecar directly (CI, CLI, headless),
    # Ollama may be absent. A missing Ollama causes a 150-second silent
    # timeout per API call — this check fails immediately with a clear message.
    if _required_ollama:
        try:
            import urllib.request as _urllib_req

            _ollama_req = _urllib_req.urlopen("http://localhost:11434/api/tags", timeout=3)
            _ollama_req.close()
            log.info("Ollama pre-flight: serving OK at http://localhost:11434")
        except Exception as _ollama_err:
            log.error("Ollama pre-flight FAIL: %s", _ollama_err)
            print("\n[DETERMINEX] Ollama is not running or not reachable on http://localhost:11434")
            print("  At least one configured role is backed by an Ollama model:")
            for _alias, _real in sorted(_required_ollama.items()):
                print(f"  - {_alias} -> {_real}")
            print("  Fix: Start Ollama, change those roles to non-Ollama model aliases,")
            print("  or enable an intended cloud fallback, then re-run this session.")
            print("       Windows: open 'Ollama' from the Start Menu or system tray.")
            print("       Linux:   systemctl start ollama  OR  ollama serve &")
            print("       macOS:   open -a Ollama")
            return session
    else:
        log.info(
            "Model provider pre-flight: no non-Builder Ollama-backed roles before Builder health"
        )

    # ── Ollama model registration pre-flight ──────────────────────────────
    # Even with Ollama running, the determinex DSL models must be registered.
    # A missing model returns a 404 from Ollama and produces the same
    # confusing timeout behaviour as a missing Ollama instance.
    # Builder health pre-flight: a model can be registered and still unusable
    # for code generation. Check a bounded exact-response prompt before any
    # step can burn the full Builder timeout.
    _builder_ok, _builder_reason = _preflight_builder_health(model_assignments)
    if not _builder_ok:
        log.error("Builder health pre-flight FAIL: %s", _builder_reason)
        print("\n[DETERMINEX] Builder model failed the exact health pre-flight.")
        print(f"  {_builder_reason}")
        print("  Set DETERMINEX_BUILDER_FALLBACK_MODEL to a stable local model,")
        print("  or repair/register the configured Builder model, then re-run this session.")
        return session
    log.info("Builder health pre-flight OK: %s", _builder_reason)
    if "switched builder" in _builder_reason:
        print(f"[DETERMINEX] {_builder_reason}", flush=True)

    try:
        _required_ollama = _required_ollama_models(model_assignments)
    except Exception as _model_resolve_err:
        log.error("Model assignment pre-flight FAIL: %s", _model_resolve_err)
        print("\n[DETERMINEX] Model assignment pre-flight failed.")
        print(f"  {_model_resolve_err}")
        print("  Check litellm_config.yaml and provider opt-in settings, then re-run this session.")
        return session

    try:
        import json as _json_pf
        import urllib.request as _urllib_req

        _tags_req = _urllib_req.urlopen("http://localhost:11434/api/tags", timeout=5)
        _tags_data = _json_pf.loads(_tags_req.read())
        _tags_req.close()
        _installed_ollama = {
            value
            for m in _tags_data.get("models", [])
            for value in (m.get("name"), m.get("model"))
            if value
        }
        # Resolve aliases to bare ollama model names for comparison
        _missing_models = _missing_ollama_models(_required_ollama, _installed_ollama)
        _required_models: set[str] = set()
        for _alias in _required_models:
            if not _alias:
                continue
            try:
                _real, _ = _resolve_model(_alias)  # from api_client
            except Exception:
                _real = _alias
            if _real.startswith("ollama/"):
                _bare = _real.removeprefix("ollama/").split(":")[0]
                if _bare not in _installed_ollama:
                    _missing_models.append(f"{_alias} → {_real}")
        if _missing_models:
            log.error("Ollama model pre-flight FAIL: missing models: %s", _missing_models)
            print("\n[DETERMINEX] Required Ollama models are not registered:")
            for _m in _missing_models:
                print(f"  ✗ {_m}")
            print("\n  To register the determinex DSL models, run:")
            print("    ollama create determinex-engineer-v10-dsl -f Modelfile.engineer.v10")
            print("    ollama create determinex-observer-v5-dsl  -f Modelfile.observer.v5")
            print("    ollama create determinex-sentinel-v3      -f Modelfile.sentinel")
            print(
                "  Or use the Determinex Setup Wizard (Tauri IDE) which registers them automatically."
            )
            return session
        log.info("Ollama model pre-flight: all required models registered — OK")
    except Exception as _model_pf_err:
        # Non-fatal: don't block the session if the tags API is temporarily unreadable
        log.warning(
            "Ollama model pre-flight check failed (non-fatal, continuing): %s", _model_pf_err
        )

    # ── Scaffolding validation ────────────────────────────────────────────
    if not session.scaffolding_validated:
        passed, err = validate_scaffolding(workspace, session.lang)
        if not passed:
            log.error("Scaffolding validation failed: %s", err)
            log.error(
                "Fix the scaffolding and re-run, or use: "
                "python determinex_hive.py validate-scaffolding --session %s",
                session_id,
            )
            return session
        session.scaffolding_validated = True
        save_manifest(session)

    # ── API budget pre-flight ─────────────────────────────────────────────
    budget_ok, estimated, remaining = api_budget_preflight(session)
    log.info(
        "Budget pre-flight: estimated=$%.3f, remaining=$%.3f, ok=%s",
        estimated,
        remaining,
        budget_ok,
    )
    if not budget_ok:
        log.warning(
            "Estimated cost ($%.3f) exceeds remaining budget ($%.3f) — "
            "proceeding with budget warnings enabled",
            estimated,
            remaining,
        )

    # ── Topological sort ──────────────────────────────────────────────────
    execution_order, cycle_groups = topological_sort(session.steps)
    steps_by_id = {s.id: s for s in session.steps}

    total_steps = len(session.steps)
    completed_pre = sum(1 for s in session.steps if s.status == "complete")
    log.info(
        "DAG: %d steps total, %d already complete, %d cycle groups",
        total_steps,
        completed_pre,
        len(cycle_groups),
    )

    # ── Rosetta bridge: one instance per session, shared across all steps ────
    # The bridge loads DeterminexInference for builder + monitor once, then serves
    # all steps. Loading is deferred (lazy) and the object is always created —
    # bridge.available == False means it will silently no-op on every call.
    _builder_m = model_assignments.get("builder", "")
    _monitor_m = model_assignments.get("monitor", "")
    rosetta = make_bridge(_builder_m, _monitor_m)
    log.info(
        "Rosetta bridge: available=%s (builder=%s, monitor=%s)",
        rosetta.available,
        _builder_m,
        _monitor_m,
    )

    # ── LatentRAG: optional semantic retrieval from past builds ──────────
    _rag_inst = None
    if _LatentRetriever is not None:
        try:
            _rag_db = _EXECUTOR_ROOT / "sessions" / "latent_rag.db"
            _rag_inst = _LatentRetriever(db_path=_rag_db)
            log.info("LatentRAG active (db=%s)", _rag_db)
        except Exception as _re:
            log.debug("LatentRAG init failed (non-fatal): %s", _re)

    # ── Parallel wave setup ───────────────────────────────────────────────
    waves = build_execution_waves(session.steps, execution_order)
    max_parallel = get_hw_profile().max_parallel_steps
    log.info("Execution plan: %d waves, max_parallel=%d", len(waves), max_parallel)

    # One lock per session serialises all cargo/go/python compiler invocations.
    # Builder LLM calls (the fast path) remain concurrent within a wave.
    _compiler_lock = threading.Lock()
    # Protects save_manifest() from concurrent writes when max_parallel > 1.
    _manifest_lock = threading.Lock()

    def _run_wave_item(item: int | list[int]) -> None:
        """Execute one item (single step or co-dependent group) from a wave."""
        if isinstance(item, list):
            group_steps = [steps_by_id[sid] for sid in item if sid in steps_by_id]
            if all(s.status == "complete" for s in group_steps):
                return
            log.info("── Co-dependent group %s (compiles atomically)", item)
            for gs in group_steps:
                if gs.status == "complete" or session.budget_exhausted:
                    continue
                execute_step(
                    session,
                    gs,
                    model_assignments,
                    rosetta=rosetta,
                    compiler_lock=_compiler_lock,
                    manifest_lock=_manifest_lock,
                    chrono=_chrono_inst,
                    rag=_rag_inst,
                )
        else:
            step = steps_by_id.get(item)
            if step is None or step.status == "complete":
                return
            if step.status == "stale_instruction":
                log.info("── Step %d is stale_instruction — re-executing", item)
                step.status = "pending"
                step.retries = 0
                step.compiler_error_hashes = []
            unmet = [
                d
                for d in step.depends_on
                if d in steps_by_id and steps_by_id[d].status != "complete"
            ]
            if unmet:
                log.warning("  Step %d has unmet deps %s — skipping", item, unmet)
                return
            execute_step(
                session,
                step,
                model_assignments,
                rosetta=rosetta,
                compiler_lock=_compiler_lock,
                manifest_lock=_manifest_lock,
                chrono=_chrono_inst,
                rag=_rag_inst,
            )

        with _manifest_lock:
            save_manifest(session)

    # ── Execution loop (wavefront) ────────────────────────────────────────
    for wave_idx, wave in enumerate(waves):
        if session.budget_exhausted:
            log.warning("Budget exhausted — skipping remaining waves")
            break

        def _is_complete(sid) -> bool:
            s = steps_by_id.get(sid)
            return s is not None and s.status == "complete"

        pending_in_wave = [
            item
            for item in wave
            if not (isinstance(item, list) and all(_is_complete(sid) for sid in item))
            and not (not isinstance(item, list) and _is_complete(item))
        ]
        if not pending_in_wave:
            continue

        log.info(
            "── Wave %d/%d: %d items (max_parallel=%d)",
            wave_idx + 1,
            len(waves),
            len(pending_in_wave),
            max_parallel,
        )

        if max_parallel <= 1 or len(pending_in_wave) == 1:
            # Sequential path — identical behaviour to the previous loop.
            for item in pending_in_wave:
                if session.budget_exhausted:
                    break
                _run_wave_item(item)
        else:
            # Parallel path (Tier 1+): Builder LLM calls run concurrently;
            # Compiler Oracle calls are serialised by _compiler_lock.
            workers = min(max_parallel, len(pending_in_wave))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(_run_wave_item, item): item for item in pending_in_wave}
                for fut in concurrent.futures.as_completed(futs):
                    exc = fut.exception()
                    if exc:
                        item = futs[fut]
                        log.error("Wave %d item %s raised: %s", wave_idx + 1, item, exc)

    # ── ForgeDaemon: stop background watcher, do one final check ─────────
    forge_daemon.check_and_trigger()  # flush any remaining .enc files
    stop_forge_daemon()
    log.info("ForgeDaemon final status: %s", forge_daemon.status())

    # ── ChronoDaemon: stop burnout monitor ───────────────────────────────
    if _chrono_inst is not None:
        try:
            _chrono_inst.stop()
            log.info("ChronoDaemon stopped")
        except Exception as _cds:
            log.debug("ChronoDaemon.stop failed (non-fatal): %s", _cds)

    # ── Offline Observer: spawn background Monitor for fast-mode steps ───
    # If any steps have .offline_pending markers (queued during fast-mode),
    # start the offline observer as a background subprocess so the Monitor
    # runs while the GPU is idle between sessions.
    # Set DETERMINEX_OFFLINE_OBSERVER=0 to disable auto-spawn.
    import os as _os
    import subprocess as _subprocess
    import sys as _sys

    if _os.environ.get("DETERMINEX_OFFLINE_OBSERVER", "1") != "0":
        try:
            from hive.manifest import find_offline_pending

            _pending_markers = find_offline_pending()
            if _pending_markers:
                log.info(
                    "Offline Observer: %d step(s) pending — spawning background process",
                    len(_pending_markers),
                )
                # G4: pass a hard timeout so the observer doesn't run forever,
                # and write its PID to a WAL file for crash-recovery detection.
                _obs_timeout = str(_os.environ.get("DETERMINEX_OBSERVER_TIMEOUT", "7200"))
                _obs_proc = _subprocess.Popen(
                    [_sys.executable, "-m", "hive.offline_observer", "--timeout", _obs_timeout],
                    cwd=str(_EXECUTOR_ROOT / "scripts"),
                    stdout=_subprocess.DEVNULL,
                    stderr=_subprocess.DEVNULL,
                    close_fds=True,
                )
                _obs_pid_path = _EXECUTOR_ROOT / "sessions" / "observer.pid"
                try:
                    _obs_pid_path.write_text(str(_obs_proc.pid), encoding="utf-8")
                except OSError:
                    pass
            else:
                log.debug("Offline Observer: no pending markers — skipping spawn")
        except Exception as _ooe:
            log.debug("Offline Observer spawn failed (non-fatal): %s", _ooe)

    # ── Summary ───────────────────────────────────────────────────────────
    completed = sum(1 for s in session.steps if s.status == "complete")
    failed = sum(1 for s in session.steps if s.status == "failed")
    pending = sum(1 for s in session.steps if s.status in ("pending", "stale_instruction"))

    print(f"\n{'═' * 60}")
    print(f"SESSION COMPLETE: {session.session_id}")
    print(f"{'═' * 60}")
    print(f"  Steps:     {completed}/{total_steps} complete, {failed} failed, {pending} pending")
    print(f"  API cost:  ${session.api_cost_usd:.4f} / ${session.session_budget_usd:.2f}")
    print(f"  Workspace: {workspace}")
    if failed:
        print("\n  Failed steps:")
        for s in session.steps:
            if s.status == "failed":
                print(f"    [{s.id:03d}] {s.instruction[:60]}")
    print()

    # G5: prune oscillation-detection history to prevent unbounded memory growth
    _file_hash_history.pop(session.session_id, None)

    # G16: prune step output dirs older than 30 days to prevent unbounded disk growth
    try:
        import time as _time_g16

        _g16_cutoff = _time_g16.time() - 30 * 86400
        _g16_steps_root = _steps_dir(session.session_id)  # sessions/<id>/steps/
        if _g16_steps_root.exists():
            for _g16_dir in _g16_steps_root.iterdir():
                if _g16_dir.is_dir() and _g16_dir.name.endswith("_outputs"):
                    try:
                        if _g16_dir.stat().st_mtime < _g16_cutoff:
                            import shutil as _shutil_g16

                            _shutil_g16.rmtree(_g16_dir, ignore_errors=True)
                            log.debug("G16: pruned old step output dir: %s", _g16_dir.name)
                    except OSError:
                        pass
    except Exception as _g16_err:
        log.debug("G16 artifact TTL prune failed (non-fatal): %s", _g16_err)

    # G21/G30: release workspace lock acquired during session creation
    release_session_lock(session.session_id)

    # G19: purge per-session KV namespace UUID and epoch state
    cleanup_session(session.session_id)

    # G1: commit the session WAL (marks session as cleanly completed)
    _session_wal.__exit__(None, None, None)

    return session
