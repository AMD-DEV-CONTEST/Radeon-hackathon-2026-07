"""
Isolated vte-server Instance Manager for the Kernel Optimizer.
Spins up separate vte-server subprocesses, each pointed at its own temp copy of the templates directory (one unmodified 'official' copy, one with a single kernel's template swapped for a candidate), so a kernel optimization candidate can be measured and validated without ever touching the templates directory or the process the production vte-server (core/utils/vte_bridge.py) is serving real chat traffic from.

Reference model is fixed and small (REFERENCE_MODEL below) rather than
whatever model the user's real chat session happens to be running --
an isolated instance is still a full model load, and using a tiny,
already-measured model keeps that load fast and its VRAM footprint
small enough to plausibly coexist with the production model already
resident.

VRAM headroom is enforced by vte-server's OWN --vram-limit-pct preflight
check (vte/server/http_server.py's _check_vram_preflight, a real
hipMemGetInfo probe done inside that subprocess before it commits to
loading) on EACH spawned instance -- this module does not reimplement
that check or query VRAM itself, it just surfaces a failed/non-ready
spawn as IsolatedInstanceError ("not enough room right now") rather than
retrying or forcing it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

from core.optimizer.sandbox import TemplateSandbox

# Already exercises gemv_q4k and loads in seconds; measured VRAM footprint
# post-fix is ~1.5GB (see memory note on the batched-prefill over-
# reservation fix), small enough for two instances (official + candidate)
# to plausibly coexist with a production model already resident.
REFERENCE_MODEL = "qwen2.5:1.5b-q4_k_m"

_OFFICIAL_PORT = 8031
_CANDIDATE_PORT = 8032

# Small reference model -- no need for vte_bridge's 240s cold-start
# allowance (sized for models up to ~70B).
_READY_TIMEOUT_SECONDS = 90.0

# Two small reference-model instances need to coexist with whatever the
# production vte-server already has resident. vte-server's own default
# (80%) is tuned for the single-large-model production case and would
# reject this combination on most GPUs whenever a real chat model is
# loaded. 25% free is still a real, GPU-wide, driver-measured floor (not
# a bypass) -- just calibrated for two known-small instances instead of
# an arbitrary one.
_DEFAULT_VRAM_LIMIT_PCT = 25.0


class IsolatedInstanceError(RuntimeError):
    """Raised when an isolated vte-server instance fails to become ready:
    VRAM preflight rejection, port conflict, or a genuine load failure."""


def generate_at(
    base_url: str,
    model_name: str,
    messages: list,
    temperature: float = 0.0,
    max_tokens: int = 64,
) -> dict:
    """Synchronous, non-streaming generation against an explicit vte-server
    base_url -- unlike core.utils.vte_bridge.generate_once, which always
    targets the shared PRODUCTION server through its own ensure_server()/
    global process state, this hits whichever isolated instance base_url
    the caller passes (IsolatedInstancePair.official_base_url /
    .candidate_base_url).

    Returns the full OpenAI-shaped response dict, not just the text: the
    non-streaming /v1/chat/completions handler (vte/server/http_server.py)
    always populates usage.decoding_speed_tps/usage.prefill_duration_ttft
    with real, GPU-measured numbers, and validator.py/benchmark.py want
    those directly instead of re-deriving a rate from client-side wall-
    clock timing (which would include this HTTP round trip and process
    scheduling noise on top of the actual decode)."""
    resp = httpx.post(
        f"{base_url}/v1/chat/completions",
        json={
            "model": model_name, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens, "stream": False,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def _resolve_reference_gguf_path() -> str:
    from core.utils.vte_bridge import _resolve_gguf_path
    return _resolve_gguf_path(REFERENCE_MODEL)


def _wait_until_ready(base_url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2.0)
            if resp.status_code == 200 and resp.json().get("status") == "ready":
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def _make_templates_copy(
    vte_templates_dir: Path,
    dest_dir: Path,
    kernel_name: Optional[str] = None,
    candidate_code: Optional[str] = None,
) -> Path:
    """Copies the whole templates dir (every kernel a generation might
    touch, not just the one under test -- render_template() reads whatever
    kernel name a request needs) into dest_dir, then optionally overwrites
    one kernel's template with candidate_code (the full, ready-to-render
    .hip.template content -- e.g. TransformationApplier.apply()'s return
    value, which patches the same literal values the original file has,
    not a different format)."""
    shutil.copytree(vte_templates_dir, dest_dir, dirs_exist_ok=True)
    if kernel_name is not None and candidate_code is not None:
        target = dest_dir / f"{kernel_name}.hip.template"
        target.write_text(candidate_code, encoding="utf-8")
    return dest_dir


def _compiled_sources(work_dir: Path, kernel_name: str) -> set:
    """The set of distinct rendered C++ sources this instance actually
    compiled for `kernel_name`.

    CodegenEngine.compile_kernel writes every rendered source it compiles
    to `logs/Codegen/<template_name>_<code_hash>.hip` before invoking
    hipcc, so this reads what the GPU really ran, not what we intended it
    to run."""
    codegen_logs = work_dir / "logs" / "Codegen"
    if not codegen_logs.is_dir():
        return set()
    return {
        p.read_text(encoding="utf-8", errors="replace")
        for p in codegen_logs.glob(f"{kernel_name}_*.hip")
    }


def verify_engagement(
    official_work_dir: Path, candidate_work_dir: Path, kernel_name: str
) -> Tuple[bool, str]:
    """Did the candidate kernel actually reach the GPU? (trust, not policy)

    Distinguishes a genuine "this change is worth ~0%" result from "the
    change never ran at all", which otherwise look identical in the
    benchmark numbers. Two real ways VTE can silently not run a candidate,
    both of which produce a perfectly normal-looking tok/s figure:

    * `CodegenEngine.render_template` only logs a warning and returns ""
      when the template file is missing, and `compile_kernel` then falls
      back to `mock_code` / `str(kwargs)` rather than failing.
    * `load_kernel_safe` failing is caught by the graph executor, which
      logs "Nó ignorado na captura" and simply SKIPS the node, leaving the
      rest of the model to answer normally.

    Modelled on Hyperloom's `_engagement_proof` (see
    agents/kernel/tools/apply_and_bench.py), but stronger: Hyperloom greps
    the server log for rebuild markers, while this compares the actual
    rendered C++ each instance compiled.

    Returns (engaged, reason)."""
    official_sources = _compiled_sources(official_work_dir, kernel_name)
    candidate_sources = _compiled_sources(candidate_work_dir, kernel_name)

    if not candidate_sources:
        return False, (
            f"NOT_ENGAGED: the candidate instance never compiled '{kernel_name}' at all "
            f"(missing template, render fallback, or the node was skipped)."
        )
    if not official_sources:
        return False, (
            f"NOT_ENGAGED: the official instance never compiled '{kernel_name}', so there is "
            f"no baseline to attribute any difference to."
        )
    if candidate_sources == official_sources:
        return False, (
            f"NOT_ENGAGED: both instances compiled byte-identical source for '{kernel_name}', "
            f"so the transformation changed nothing the GPU actually ran."
        )
    return True, (
        f"ENGAGED: candidate compiled {len(candidate_sources)} distinct source(s) for "
        f"'{kernel_name}', differing from the official instance's."
    )


class _IsolatedServer:
    """One isolated vte-server subprocess bound to its own templates dir
    and port. Internal building block -- see IsolatedInstancePair below
    for the pair most callers actually want."""

    def __init__(self, port: int, templates_dir: Path, gguf_path: str, vram_limit_pct: float, work_dir: Path):
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self._templates_dir = templates_dir
        self._gguf_path = gguf_path
        self._vram_limit_pct = vram_limit_pct
        # Own cwd per instance: CodegenEngine resolves both its kernel cache
        # (`cache/kernels`) and its rendered-source log dir (`logs/Codegen`)
        # RELATIVE to cwd. Giving each instance its own means (a) neither can
        # serve the other a cached .hsaco, so both compile their own kernel
        # fresh and the comparison is honest, and (b) the rendered C++ each
        # one actually compiled is recoverable afterwards, which is what
        # verify_engagement() reads. Safe because --gguf-path is already
        # absolute, so nothing else here depends on cwd.
        self.work_dir = work_dir
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            [
                sys.executable, "-m", "vte.server.http_server",
                "--gguf-path", self._gguf_path,
                "--port", str(self.port),
                "--host", "127.0.0.1",
                # This module owns the instance's whole lifecycle explicitly
                # (start()/stop()); vte-server's own idle-unload timer would
                # fight that.
                "--idle-timeout", "0",
                # If this process dies without a clean shutdown, vte-server's
                # own parent-watchdog notices and frees the VRAM instead of
                # leaking an orphaned process.
                "--parent-pid", str(os.getpid()),
                "--vram-limit-pct", str(self._vram_limit_pct),
                "--templates-dir", str(self._templates_dir),
            ],
            cwd=str(self.work_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        if not _wait_until_ready(self.base_url, _READY_TIMEOUT_SECONDS):
            self.stop()
            raise IsolatedInstanceError(
                f"Isolated vte-server on port {self.port} did not become ready in "
                f"{_READY_TIMEOUT_SECONDS:.0f}s -- likely a VRAM headroom rejection "
                f"(see vte-server's own log line) or a load failure."
            )

    def stop(self) -> None:
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


class IsolatedInstancePair:
    """Context manager: brings up TWO isolated vte-server instances --
    an unmodified 'official' copy of the templates dir and a 'candidate'
    copy with one kernel's template swapped for the text under test --
    both running REFERENCE_MODEL on their own ports, distinct from the
    production vte-server's port (core/utils/vte_bridge.py's
    _SERVER_PORT). Tears both down (processes + temp dirs) on exit,
    including on an exception, so a crash mid-benchmark never leaves a
    stray GPU-resident process or temp directory behind.

    Usage:
        with IsolatedInstancePair("gemv_q4k", candidate_code) as pair:
            ...  # pair.official_base_url / pair.candidate_base_url
    """

    def __init__(
        self,
        kernel_name: str,
        candidate_code: str,
        vram_limit_pct: float = _DEFAULT_VRAM_LIMIT_PCT,
    ):
        self.kernel_name = kernel_name
        self.candidate_code = candidate_code
        self.vram_limit_pct = vram_limit_pct
        self._tmp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._official: Optional[_IsolatedServer] = None
        self._candidate: Optional[_IsolatedServer] = None

    @property
    def official_base_url(self) -> str:
        return self._official.base_url

    @property
    def candidate_base_url(self) -> str:
        return self._candidate.base_url

    def verify_engagement(self) -> Tuple[bool, str]:
        """Did the candidate kernel actually reach the GPU? Call this AFTER
        at least one generation has run against both instances, since the
        rendered sources it inspects are only written when a kernel is
        first compiled. See the module-level verify_engagement()."""
        return verify_engagement(self._official.work_dir, self._candidate.work_dir, self.kernel_name)

    def __enter__(self) -> "IsolatedInstancePair":
        vte_templates_dir = TemplateSandbox().vte_templates_dir
        gguf_path = _resolve_reference_gguf_path()

        # ignore_cleanup_errors: each instance's kernel cache now lives under
        # this temp root (see _IsolatedServer.work_dir), and on Windows the
        # just-terminated subprocess can still hold an open handle to its
        # own .hsaco when cleanup runs, raising PermissionError (WinError 32)
        # out of an otherwise-successful optimizer run. Reproduced directly.
        # Leaving a temp directory for the OS to reap is strictly better than
        # failing the run over it.
        self._tmp_dir = tempfile.TemporaryDirectory(
            prefix="aetheris_optimizer_", ignore_cleanup_errors=True,
        )
        tmp_root = Path(self._tmp_dir.name)
        official_dir = _make_templates_copy(vte_templates_dir, tmp_root / "official")
        candidate_dir = _make_templates_copy(
            vte_templates_dir, tmp_root / "candidate",
            kernel_name=self.kernel_name, candidate_code=self.candidate_code,
        )

        self._official = _IsolatedServer(
            _OFFICIAL_PORT, official_dir, gguf_path, self.vram_limit_pct, tmp_root / "official_work",
        )
        self._candidate = _IsolatedServer(
            _CANDIDATE_PORT, candidate_dir, gguf_path, self.vram_limit_pct, tmp_root / "candidate_work",
        )
        try:
            self._official.start()
            self._candidate.start()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._official is not None:
            self._official.stop()
        if self._candidate is not None:
            self._candidate.stop()
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
