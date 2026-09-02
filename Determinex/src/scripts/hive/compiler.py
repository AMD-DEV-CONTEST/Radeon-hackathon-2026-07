"""
scripts/hive/compiler.py — Scaffolding validation, Compiler Oracle, write modes, public API
============================================================================================
Moved from determinex_hive.py (lines ~791-1043, ~1232-1293).
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
from pathlib import Path

import psutil

from hive.manifest import StepRecord

try:
    from hive._log import bind_session as _bind_session
    from hive._log import get_logger as _get_logger  # noqa: F401

    log = _get_logger("hive.compiler")
except ImportError:
    log = logging.getLogger("hive")

# ── Compile timeout ────────────────────────────────────────────────────────────
COMPILE_TIMEOUT = 60

# ── Build loop constants ──────────────────────────────────────────────────────
MAX_ESCALATIONS_PER_STEP = 1

# ── Root path (for Tauri binary lookup) ───────────────────────────────────────
_ROOT = (
    Path(os.environ["DETERMINEX_ROOT"]).resolve()
    if os.environ.get("DETERMINEX_ROOT")
    else Path(__file__).resolve().parent.parent.parent
)


# ── #21 Unicode Normalization Filter ────────────────────────────────────────────
# LLMs using different tokenizers (SentencePiece vs. Tiktoken BPE) output the
# same visible glyphs in different Unicode normalization forms (NFC vs NFD).
# This silently breaks regex/AST diff patchers because the raw bytes differ
# even when the rendered characters look identical.
# Additionally, LLMs frequently hallucinate zero-width spaces (\u200B) and
# non-breaking spaces (\u00A0) that produce invisible syntax errors in compilers.

_INVISIBLE_CHARS = re.compile(r"[\u200B\u200C\u200D\u00A0\u2028\u2029\uFEFF]")

# Typographic chars that LLMs emit but compilers reject as syntax errors.
# These look like normal punctuation but cause rustc/go/python to emit
# "unknown start of token" (e.g. em dash in Rust source).
_TYPO_REPLACEMENTS: list[tuple[str, str]] = [
    ("‘", "'"),  # left single quotation mark
    ("’", "'"),  # right single quotation mark (most common culprit)
    ("“", '"'),  # left double quotation mark
    ("”", '"'),  # right double quotation mark
    ("—", "--"),  # em dash
    ("–", "-"),  # en dash
    ("‒", "-"),  # figure dash
    ("‐", "-"),  # hyphen (Unicode)
    ("‑", "-"),  # non-breaking hyphen
    ("´", "'"),  # acute accent
]


def normalize_code_text(text: str) -> str:
    """#21: Normalize Unicode and strip invisible characters from LLM output.

    Must be applied to ALL LLM outputs before they are written to disk or
    passed through any regex/AST patcher. Ensures consistent byte sequences
    regardless of which tokenizer the sending model used.
    """
    # NFC: composed form — 'é' as one codepoint, not 'e' + combining accent
    normalized = unicodedata.normalize("NFC", text)
    # Replace typographic punctuation with ASCII equivalents (smart quotes, dashes, etc.)
    for typo_char, ascii_equiv in _TYPO_REPLACEMENTS:
        normalized = normalized.replace(typo_char, ascii_equiv)
    # Strip remaining invisible characters that compile as syntax errors
    scrubbed = _INVISIBLE_CHARS.sub(" ", normalized)
    return scrubbed


# ── Toolchain availability ────────────────────────────────────────────────────

# Patterns that identify OS-level missing-tool errors vs. code errors.
# These must NEVER be fed to the Builder as compiler errors — the model
# has no concept of the host OS environment and will waste all retries
# trying to rewrite code that didn't cause the problem.
_TOOLCHAIN_MISSING_PATTERNS = [
    r"command not found",
    r"is not recognized as an internal or external command",
    r"No such file or directory",
    r"cannot find the file specified",
    r"not found in PATH",
    r"Toolchain not found",
    r"go: command not found",
    r"cargo: command not found",
    r"rustc: command not found",
    r"python.*not found",
]
_TOOLCHAIN_MISSING_RE = re.compile("|".join(_TOOLCHAIN_MISSING_PATTERNS), re.IGNORECASE)
_WSL_TOOLCHAIN_UNAVAILABLE_RE = re.compile(
    r"env:\s*.{0,40}(cargo|go|python3?|rustc).{0,80}No such file or directory"
    r"|(cargo|go|python3?|rustc): command not found"
    r"|(cargo|go|python3?|rustc).*not found in PATH"
    r"|Windows Subsystem for Linux has no installed distributions",
    re.IGNORECASE,
)


def is_toolchain_error(output: str) -> bool:
    """
    Return True if the compiler output indicates a missing OS tool,
    not a code-level error. Used to prevent feeding environment errors
    to the Builder retry loop.
    """
    return bool(_TOOLCHAIN_MISSING_RE.search(output))


def _is_wsl_toolchain_unavailable(output: str) -> bool:
    """Return True for WSL2 env/PATH failures that should fall back to direct."""
    return bool(_WSL_TOOLCHAIN_UNAVAILABLE_RE.search(output))


# ── L2-B / Mole-125: Credential-safe subprocess environment ─────────────────
# os.environ.copy() passes HF_TOKEN, ANTHROPIC_API_KEY, and every other secret
# to every compiler subprocess. C-extensions that call os.putenv() also mutate
# the underlying C runtime env block, bleeding credentials across evaluations
# sharing the same process.  _make_safe_env() strips credential-bearing keys
# before handing the env dict to any Popen call.

_CREDENTIAL_STRIP_RE = re.compile(
    r"(HF_TOKEN|HUGGING_?FACE|ANTHROPIC|OPENAI|AZURE|GCP_|GOOGLE_API_"
    r"|AWS_SECRET|AWS_ACCESS|GITHUB_TOKEN|GITLAB_TOKEN|NPM_TOKEN"
    r"|PYPI_TOKEN|DOCKER_PASS|DATABASE_URL|REDIS_URL"
    r"|SK[-_]|API[-_]KEY|SECRET[-_]KEY|AUTH[-_]TOKEN"
    r"|PRIVATE[-_]KEY|PASSWORD$|PASSWD$|CREDENTIALS?)",
    re.IGNORECASE,
)

# L6-A / L6-B: Strip environment isolation variables so compiler subprocesses
# don't inherit the host PYTHONPATH or virtual-env overlays.  A test that passes
# because the host has a library the project's requirements.txt omits is a false
# positive — and it will silently poison the training curriculum.
_ENV_POLLUTION_KEYS: frozenset[str] = frozenset(
    {
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
        "VIRTUAL_ENV_PROMPT",
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        "CONDA_EXE",
        "CONDA_SHLVL",
    }
)


def _with_standard_user_toolchain_bins(path_value: str) -> str:
    """Preserve common per-user compiler locations after credential stripping."""
    entries = [p for p in path_value.split(os.pathsep) if p]
    seen = {str(Path(p)).lower() for p in entries}
    candidates: list[Path] = []

    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if home:
        candidates.extend(
            [
                Path(home) / ".cargo" / "bin",
                Path(home) / "go" / "bin",
            ]
        )

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        programs = Path(local_appdata) / "Programs" / "Python"
        if programs.is_dir():
            candidates.extend(p / "Scripts" for p in sorted(programs.glob("Python*")) if p.is_dir())

    for candidate in candidates:
        key = str(candidate).lower()
        if candidate.is_dir() and key not in seen:
            entries.append(str(candidate))
            seen.add(key)
    return os.pathsep.join(entries)


def _make_safe_env(extra: dict | None = None) -> dict[str, str]:
    """Return os.environ copy with credential-bearing and env-pollution keys stripped."""
    safe = {
        k: v
        for k, v in os.environ.items()
        if not _CREDENTIAL_STRIP_RE.search(k) and k not in _ENV_POLLUTION_KEYS
    }
    safe["PATH"] = _with_standard_user_toolchain_bins(safe.get("PATH", ""))
    # L4-A: suppress HuggingFace background analytics during model downloads
    safe["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if extra:
        safe.update(extra)
    return safe


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".determinex-write-probe-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _select_cargo_target_dir() -> Path:
    """Choose a writable Cargo target dir for direct compiler execution."""
    candidates: list[Path] = []
    override = os.environ.get("DETERMINEX_HIVE_CARGO_TARGET_DIR")
    if override:
        candidates.append(Path(override))
    candidates.extend(
        [
            Path("T:/determinex-target/hive"),
            Path(tempfile.gettempdir()) / "determinex-target" / "hive",
        ]
    )
    for candidate in candidates:
        try:
            if candidate == Path("T:/determinex-target/hive"):
                candidate.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(candidate).free < 512 * 1024 * 1024:
                    continue
            if _is_writable_dir(candidate):
                return candidate
        except OSError:
            continue
    fallback = Path.cwd() / ".tmp" / "determinex-target" / "hive"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


# L5-B: Toolchain version cache.  Populated by check_toolchain_available() on
# first call and reused for the rest of the daemon lifetime.  Injected into the
# Builder's context window so the LLM targets the ACTUAL installed compiler
# version instead of guessing from its training cutoff (which may be 2+ years stale).
_TOOLCHAIN_VERSION: dict[str, str] = {}


def get_toolchain_version(lang: str) -> str:
    """Return the cached toolchain version string, or '' if not yet checked."""
    return _TOOLCHAIN_VERSION.get(lang.lower(), "")


def check_toolchain_available(lang: str) -> tuple[bool, str]:
    """
    Verify the local toolchain (cargo, go, python) is on PATH.
    Sidecar mode: Docker is not required — Determinex runs compilers directly.
    Returns (available, error_message_for_user).
    Side-effect: caches the version string in _TOOLCHAIN_VERSION[lang].
    """
    lang = lang.lower()
    try:
        if "rust" in lang:
            r = subprocess.run(["cargo", "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                _TOOLCHAIN_VERSION["rust"] = r.stdout.strip()  # L5-B
                log.info("Toolchain check: cargo OK (%s)", r.stdout.strip())
                return True, ""
            return False, "cargo returned an error. Check your Rust installation."
        elif "go" in lang:
            r = subprocess.run(["go", "version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                _TOOLCHAIN_VERSION["go"] = r.stdout.strip()  # L5-B
                log.info("Toolchain check: go OK (%s)", r.stdout.strip())
                return True, ""
            return False, "go returned an error. Check your Go installation."
        elif "python" in lang:
            for cmd in [["python", "--version"], ["python3", "--version"]]:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if r.returncode == 0:
                        ver = (r.stdout or r.stderr).strip()
                        _TOOLCHAIN_VERSION["python"] = ver  # L5-B
                        log.info("Toolchain check: python OK (%s)", ver)
                        return True, ""
                except FileNotFoundError:
                    continue
            return False, "python/python3 not found on PATH."
        else:
            log.info("Toolchain check: unknown lang '%s' — lenient pass", lang)
            return True, ""
    except FileNotFoundError:
        names = {"rust": "cargo (rustup)", "go": "go", "python": "python"}
        return False, f"{names.get(lang, lang)} is not installed or not on PATH."
    except subprocess.TimeoutExpired:
        return False, f"Toolchain check timed out for '{lang}'."


class SandboxUnavailableError(RuntimeError):
    """Raised when SEC-2 Job Object sandbox cannot be established and
    DETERMINEX_ALLOW_UNSANDBOXED is not set in the environment."""


# Cached result of the one-time Job Object availability probe.
# None = not yet checked.  True/False = probe result.
_JOB_OBJECT_AVAILABLE: bool | None = None


# ── L1-C: Daemon-lifetime Job Object with KillOnJobClose ─────────────────────
# The per-call Job Objects in _apply_job_object_restrictions() close their handle
# immediately after assignment, making KillOnJobClose incompatible (it would kill
# the child the moment the handle closes).  The fix is a module-level handle kept
# open for the entire Determinex process lifetime.  When Determinex exits or crashes,
# the OS closes all open handles, triggering KillOnJobClose on every assigned
# compiler subprocess — no zombie processes survive a daemon crash.

_DAEMON_JOB_HANDLE: int | None = None
_daemon_job_lock = threading.Lock()


def _get_daemon_job_handle() -> int | None:
    """Return (creating if needed) the module-level KillOnJobClose Job Object handle."""
    global _DAEMON_JOB_HANDLE
    if not sys.platform.startswith("win"):
        return None
    if _DAEMON_JOB_HANDLE is not None:
        return _DAEMON_JOB_HANDLE
    with _daemon_job_lock:
        if _DAEMON_JOB_HANDLE is not None:
            return _DAEMON_JOB_HANDLE
        try:
            import ctypes

            k32 = ctypes.windll.kernel32
            h = k32.CreateJobObjectW(None, None)
            if not h:
                return None

            class _LargeInt(ctypes.Structure):
                _fields_ = [("QuadPart", ctypes.c_longlong)]

            class _BasicLimit(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", _LargeInt),
                    ("PerJobUserTimeLimit", _LargeInt),
                    ("LimitFlags", ctypes.c_ulong),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_ulong),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_ulong),
                    ("SchedulingClass", ctypes.c_ulong),
                ]

            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
            JobObjectBasicLimitInformation = 2
            bli = _BasicLimit()
            bli.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(
                h,
                JobObjectBasicLimitInformation,
                ctypes.byref(bli),
                ctypes.sizeof(bli),
            )
            _DAEMON_JOB_HANDLE = h
            log.info("[L1-C] Daemon KillOnJobClose Job Object created (handle=%d)", h)
            return h
        except Exception as e:
            log.debug("[L1-C] Could not create daemon Job Object: %s", e)
            return None


def _probe_job_object_support() -> bool:
    """Create and immediately close a throwaway Job Object to test availability.

    On some managed enterprise machines, CreateJobObjectW is restricted by
    group policy.  This probe is called once at session start so the result
    can be cached for the lifetime of the process.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.CreateJobObjectW(None, None)
        if not h:
            return False
        k32.CloseHandle(h)
        return True
    except Exception:
        return False


def ensure_sandbox_available() -> None:
    """Check Job Object support once per process.  Raises SandboxUnavailableError
    if the sandbox cannot be established and DETERMINEX_ALLOW_UNSANDBOXED is not set.

    Call this at the start of a Hive build session so the user gets a clear
    message before the first compilation attempt, not buried mid-run.
    """
    global _JOB_OBJECT_AVAILABLE
    if _JOB_OBJECT_AVAILABLE is None:
        _JOB_OBJECT_AVAILABLE = _probe_job_object_support()
    if not _JOB_OBJECT_AVAILABLE:
        if os.environ.get("DETERMINEX_ALLOW_UNSANDBOXED", "").strip() == "1":
            log.warning(
                "[SEC-2] Windows Job Object sandbox unavailable on this machine "
                "(CreateJobObjectW restricted by policy). Proceeding because "
                "DETERMINEX_ALLOW_UNSANDBOXED=1 is set. Compiler processes will run "
                "without UI/clipboard/system-params restrictions. "
                "AST blacklist (Lock 1) remains active."
            )
        else:
            raise SandboxUnavailableError(
                "SEC-2: Windows Job Object sandbox is unavailable on this machine "
                "(CreateJobObjectW may be restricted by group policy).\n"
                "Compiler subprocesses cannot be sandboxed — they will run with "
                "your full user privileges.\n\n"
                "To acknowledge this risk and proceed anyway, set:\n"
                "    DETERMINEX_ALLOW_UNSANDBOXED=1\n"
                "in your environment or .env file before starting Determinex.\n\n"
                "Note: The AST Import Blacklist (Lock 1) remains active regardless."
            )


def _apply_job_object_restrictions(proc_handle: int) -> bool:
    """
    SEC-2: Assign a running process to a Windows Job Object with UI and
    inter-process restrictions.  Called immediately after Popen so the
    process (and children it spawns) cannot create windows, touch the
    clipboard, change system parameters, or call ExitWindows.

    Low-Integrity tokens were considered but rejected for the compiler use
    case: the workspace lives in AppData\\Local\\Temp (Medium integrity) and
    cargo/rustc need write access to it.  Low-integrity processes cannot
    write to medium-integrity directories, which breaks compilation.  Job
    Objects provide meaningful restrictions without that constraint.

    Note: Job Object assignment is best-effort and post-spawn.  Processes
    cargo spawns before assignment completes are not covered; this is
    acceptable for the compiler check path (cargo build is trusted code).
    The correctness test runner (run_correctness_tests) is the higher-risk
    path and uses the AST blacklist (Lock 1) as primary defense.

    Returns True if the job was applied successfully.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        k32 = ctypes.windll.kernel32

        h_job = k32.CreateJobObjectW(None, None)
        if not h_job:
            return False

        # JOBOBJECT_BASIC_UI_RESTRICTIONS — block all UI interaction
        class _UIR(ctypes.Structure):
            _fields_ = [("UIRestrictionsClass", ctypes.c_ulong)]

        r = _UIR()
        r.UIRestrictionsClass = (
            0x0001  # UILIMIT_HANDLES        — no cross-process window sends
            | 0x0002  # UILIMIT_READCLIPBOARD
            | 0x0004  # UILIMIT_WRITECLIPBOARD
            | 0x0008  # UILIMIT_SYSTEMPARAMETERS
            | 0x0010  # UILIMIT_DISPLAYSETTINGS
            | 0x0020  # UILIMIT_GLOBALATOMS
            | 0x0040  # UILIMIT_DESKTOP        — no CreateDesktop
            | 0x0080  # UILIMIT_EXITWINDOWS    — no ExitWindowsEx
        )
        JobObjectBasicUIRestrictions = 4
        k32.SetInformationJobObject(
            h_job, JobObjectBasicUIRestrictions, ctypes.byref(r), ctypes.sizeof(r)
        )

        ok = bool(k32.AssignProcessToJobObject(h_job, proc_handle))
        k32.CloseHandle(h_job)

        # L1-C: Also assign to the daemon-lifetime job so KillOnJobClose fires
        # if Determinex crashes.  Windows 8+ supports nested job objects.
        daemon_h = _get_daemon_job_handle()
        if daemon_h:
            k32.AssignProcessToJobObject(daemon_h, proc_handle)

        return ok
    except Exception:
        return False


def _kill_process_tree(pid: int) -> None:
    """Mole-118: Kill a process and all its descendants via psutil.

    pytest and similar test runners spawn server subprocesses that outlive the
    parent when the parent is killed.  A plain proc.kill() leaves those children
    running, holding sockets open, until the next run races on the same port.
    """
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    except Exception as _e:
        log.debug("_kill_process_tree(%d) non-fatal: %s", pid, _e)


# ── Stratagem 2: Containerized Ephemeral Oracles ─────────────────────────────
#
# Execution priority: Docker (full isolation) → WSL2 (process isolation) →
# direct (SEC-2 Job Object + _make_safe_env as final fallback).
#
# Docker: zero host leakage — compiler runs in an ephemeral container that
#   sees only the mounted workspace. A malicious build.rs cannot read ~/.env
#   or any credential file. --network=none blocks outbound exfiltration.
# WSL2:   process-level isolation via `env -i`. Weaker than Docker (host
#   filesystem is still visible via /mnt/*) but available on all Windows 11
#   systems without Docker Desktop. env -i strips all host env vars before
#   the compiler runs.
# Direct: SEC-2 path — _make_safe_env() + Windows Job Object. Retained as
#   fallback when neither container runtime is present.

_ORACLE_IMAGES: dict[str, str] = {
    "rust": "rust:1.82-slim",
    "go": "golang:1.23-alpine",
    "python": "python:3.12-slim",
    # Built locally, not pulled: the oracle runs --network=none, so `npx tsc` would try
    # to fetch the compiler at RUN time and fail in a way indistinguishable from a type
    # error. typescript is baked in at build time instead.
    #   docker build -t determinex-oracle-ts:20 -f docker/oracle/typescript.Dockerfile .
    "typescript": "determinex-oracle-ts:20",
}

# How to obtain an image that is missing, so a failure names its own fix rather than
# leaving the operator to guess.
_ORACLE_IMAGE_HINT: dict[str, str] = {
    "typescript": "docker build -t determinex-oracle-ts:20 "
    "-f docker/oracle/typescript.Dockerfile .",
}

# Spellings that mean the same toolchain. Without this, lang="ts" missed the image lookup
# and fell through to the generic default image, where `tsc` does not exist -- so a missing
# oracle reported itself as a compile failure, which is the one thing an oracle must never
# do. Resolved for image selection only; the branch conditions stay explicit.
_LANG_ALIASES: dict[str, str] = {
    "ts": "typescript",
    "tsx": "typescript",
    "rs": "rust",
    "py": "python",
    "golang": "go",
}

# Type-check with an explicit file list rather than a baked tsconfig.
#
# The obvious version -- `tsc --project /determinex-tsconfig.json` -- is wrong in a way
# that still passes: tsconfig `include` globs resolve relative to the CONFIG's directory,
# so a config at / made tsc walk the entire container root and reach the sources sideways
# through /proc/1/cwd. It found the errors, but reported them as `../proc/1/cwd/bad.ts`,
# which no feedback consumer can map back to a real file, and it type-checked whatever
# else on the image happened to end in .ts.
#
# An explicit list rooted at the workspace keeps paths relative and the scope correct.
# The empty-source guard is load-bearing: `tsc` over zero files exits 0, so without it an
# empty or wrongly-pathed workspace would report PASS -- verifying nothing, confidently.
_TS_DEFAULT_CHECK = (
    "files=$(find . -name node_modules -prune -o "
    r"\( -name '*.ts' -o -name '*.tsx' \) -print); "
    'if [ -z "$files" ]; then '
    'echo "Compiler Oracle: no .ts/.tsx sources in workspace - nothing to verify"; '
    "exit 1; fi; "
    "exec tsc --noEmit --strict --skipLibCheck --target ES2022 "
    "--module ESNext --moduleResolution bundler $files"
)

_docker_checked: bool | None = None
_wsl2_checked: bool | None = None
_backend_logged = False
_oracle_backend_lock = threading.Lock()


def _oracle_backend() -> str:
    """Return 'docker', 'wsl2', or 'direct'. Probed once, cached for process lifetime."""
    global _docker_checked, _wsl2_checked, _backend_logged
    with _oracle_backend_lock:
        if _docker_checked is None:
            try:
                r = subprocess.run(["docker", "info"], capture_output=True, timeout=4)
                _docker_checked = r.returncode == 0
            except Exception:
                _docker_checked = False

        if not _docker_checked and _wsl2_checked is None:
            # Probe WSL2 availability unconditionally — wsl.exe returns non-zero
            # on non-Windows platforms so we don't need a sys.platform branch that
            # Pylance would constant-fold into dead code on this Windows machine.
            try:
                r = subprocess.run(["wsl", "--status"], capture_output=True, timeout=4)
                _wsl2_checked = r.returncode == 0
            except Exception:
                _wsl2_checked = False

        backend = "docker" if _docker_checked else ("wsl2" if _wsl2_checked else "direct")
        if not _backend_logged:
            log.info("[Oracle] Compiler execution backend: %s", backend)
            _backend_logged = True
        return backend


def _windows_to_wsl_path(path: Path) -> str:
    """Convert C:\\path\\to\\dir → /mnt/c/path/to/dir for WSL2 volume access."""
    posix = path.resolve().as_posix()  # "C:/path/to/dir"
    if len(posix) >= 2 and posix[1] == ":":
        return f"/mnt/{posix[0].lower()}{posix[2:]}"
    return posix


# Images confirmed present in this process. `docker image inspect` is only a local
# metadata read, but the oracle runs once per step per attempt and it is not free.
_IMAGES_PRESENT: set[str] = set()

# Provisioning an image is not compiling, and must not be charged to the compile budget.
# A first-ever build has to fetch its oracle image -- `rust:1.82-slim` alone is 808 MB --
# and that download used to happen implicitly inside `docker run`, i.e. inside
# `timeout + 60` where the 60 s was sized for container start. So a new user's very first
# spec timed out mid-download and was reported as "Fix Docker", which is neither the cause
# nor a thing they can act on. Found 2026-07-30 (S9).
_IMAGE_PULL_TIMEOUT = 1800


def _ensure_oracle_image(image: str, lang_key: str) -> None:
    """Make `image` local before a timed compile, so its download is not charged to it.

    Raises rather than continuing on failure, deliberately. Two reasons: letting
    `docker run` fall back to its own implicit pull is the bug this exists to fix, and a
    pull failure that reached the caller as a non-zero rc would be recorded as a COMPILE
    error -- putting a network or registry problem into the WAL as if the generated code
    were wrong. That is training-data corruption, not just a bad message.
    """
    if image in _IMAGES_PRESENT:
        return
    try:
        present = (
            subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                timeout=30,
            ).returncode
            == 0
        )
    except Exception:
        # Can't tell. Fall through: a real pull reports its own failure with a real reason.
        present = False

    if not present:
        # A locally-built image has no registry to pull from -- `docker pull
        # determinex-oracle-ts:20` fails with "pull access denied", which reads like an
        # auth problem and sends the operator looking for credentials that don't exist.
        # Name the build command instead.
        build_cmd = _ORACLE_IMAGE_HINT.get(lang_key)
        if build_cmd:
            raise RuntimeError(
                f"[Oracle] Sandbox image {image} is not built. It is built locally, not "
                f"pulled (the oracle runs --network=none, so the toolchain must be baked "
                f"in). Build it with: {build_cmd}"
            )
        log.info(
            "[Oracle] Pulling sandbox image %s — first use on this machine. Not charged "
            "to the %ss compile timeout.",
            image,
            COMPILE_TIMEOUT,
        )
        try:
            pull = subprocess.run(
                ["docker", "pull", image],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="backslashreplace",
                timeout=_IMAGE_PULL_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"[Oracle] Timed out after {_IMAGE_PULL_TIMEOUT}s pulling sandbox image "
                f"{image}. Pre-pull it with: docker pull {image}"
            ) from exc
        if pull.returncode != 0:
            detail = (pull.stderr or pull.stdout or "").strip().replace("\n", " ")
            raise RuntimeError(
                f"[Oracle] Could not pull sandbox image {image}: {detail[:300]}. "
                f"Pre-pull it with: docker pull {image}"
            )
        log.info("[Oracle] Sandbox image %s ready.", image)

    _IMAGES_PRESENT.add(image)


def _docker_oracle_run(
    cmd: list[str],
    workspace: Path,
    lang: str,
    timeout: int,
    allow_network: bool,
) -> subprocess.CompletedProcess:
    """Execute compiler command inside an ephemeral Docker container."""
    lang_lower = lang.lower()
    lang_key = _LANG_ALIASES.get(lang_lower, lang_lower)
    image = _ORACLE_IMAGES.get(lang_key, "ubuntu:22.04")
    _ensure_oracle_image(image, lang_key)
    net_flag = [] if allow_network else ["--network=none"]
    # Rust builds need a writable target directory — redirect into /tmp inside
    # the container so the workspace mount doesn't accumulate build artifacts.
    cargo_env = ["-e", "CARGO_TARGET_DIR=/tmp/cargo-target"] if "rust" in lang_lower else []
    workspace_abs = workspace.resolve()

    # G25: defense-in-depth — run build.rs grep check inside the container before
    # cargo build so the in-container scan fires even if the host-side scan was
    # skipped or the build.rs was written after the host scan completed.
    if "rust" in lang_lower and any("cargo" in c for c in cmd):
        _danger_pat = (
            r"Command:new\(|std::process::Command"
            r"|std::net::|std::fs::remove"
            r"|std::env::var\(|include!\("
            r"|std::env::set_var\(|std::fs::write\("
            r"|cc::Build"
        )
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        shell_payload = (
            f"if [ -f build.rs ] && grep -qE '{_danger_pat}' build.rs 2>/dev/null; then "
            f"echo '[Mole-121/G25] Dangerous build.rs pattern detected inside container' >&2; "
            f"exit 99; fi; {cmd_str}"
        )
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            *net_flag,
            "--memory=512m",
            "--cpus=2",
            "--security-opt=no-new-privileges",
            # Added 2026-08-02 against two published 2026 incidents, both of the same shape
            # as this code path: model-generated code inside an evaluation sandbox.
            #
            #   OpenAI ExploitGym (Jul 2026) -- an agent escaped its sandbox and abused a
            #   public code-evaluation sandbox to run commands as ROOT, using it as an
            #   external launchpad into a third party. The motive was reward hacking:
            #   reach the grader and take the answers rather than solve the task. This
            #   oracle IS a grader running untrusted code, so that is our threat model
            #   rather than an analogy to one.
            #
            #   Anthropic C0062 / GTG-1002 (Sep 2025, MITRE ATT&CK) -- T1567 exfiltration
            #   over web service, T1552.001 credentials in files.
            #
            # --network=none already blocks the exfiltration and launchpad legs. These two
            # close the privilege legs: a compiler needs no Linux capabilities at all, and
            # a bounded process table stops a candidate fork-bombing the host scheduler.
            "--cap-drop=ALL",
            "--pids-limit=512",
            "-v",
            f"{workspace_abs}:/workspace:rw",
            "-w",
            "/workspace",
            *cargo_env,
            image,
            "sh",
            "-c",
            shell_payload,
        ]
    else:
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            *net_flag,
            "--memory=512m",
            "--cpus=2",
            "--security-opt=no-new-privileges",
            # Added 2026-08-02 against two published 2026 incidents, both of the same shape
            # as this code path: model-generated code inside an evaluation sandbox.
            #
            #   OpenAI ExploitGym (Jul 2026) -- an agent escaped its sandbox and abused a
            #   public code-evaluation sandbox to run commands as ROOT, using it as an
            #   external launchpad into a third party. The motive was reward hacking:
            #   reach the grader and take the answers rather than solve the task. This
            #   oracle IS a grader running untrusted code, so that is our threat model
            #   rather than an analogy to one.
            #
            #   Anthropic C0062 / GTG-1002 (Sep 2025, MITRE ATT&CK) -- T1567 exfiltration
            #   over web service, T1552.001 credentials in files.
            #
            # --network=none already blocks the exfiltration and launchpad legs. These two
            # close the privilege legs: a compiler needs no Linux capabilities at all, and
            # a bounded process table stops a candidate fork-bombing the host scheduler.
            "--cap-drop=ALL",
            "--pids-limit=512",
            "-v",
            f"{workspace_abs}:/workspace:rw",
            "-w",
            "/workspace",
            *cargo_env,
            image,
            *cmd,
        ]
    return subprocess.run(
        docker_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        # 60s overhead: container start and teardown only. The image pull is handled by
        # _ensure_oracle_image above, so this budget no longer has to cover a download.
        # Measured warm on a Windows/WSL2 Docker Desktop host: a hello-world `cargo build`
        # is ~10s wall clock end to end, of which ~9s is container overhead.
        timeout=timeout + 60,
    )


def _wsl2_oracle_run(
    cmd: list[str],
    workspace: Path,
    lang: str,
    timeout: int,
    _allow_network: bool = False,  # WSL2 network isolation requires nftables; not enforced here
) -> subprocess.CompletedProcess:
    """Execute compiler command inside WSL2 with a clean environment (env -i)."""
    lang_lower = lang.lower()
    wsl_path = _windows_to_wsl_path(workspace)
    # Minimal PATH covering Rust, Go, and Python toolchain locations.
    path_dirs = (
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        ":/usr/local/cargo/bin"  # rustup / cargo
        ":/usr/local/go/bin"  # Go toolchain
    )
    extra_env = ""
    if "rust" in lang_lower:
        extra_env = f" CARGO_TARGET_DIR=/tmp/cargo-{os.getpid()}"
    cmd_str = " ".join(shlex.quote(c) for c in cmd)
    shell_cmd = (
        f"cd {shlex.quote(wsl_path)} && env -i HOME=/root PATH={path_dirs}{extra_env} {cmd_str}"
    )
    result = subprocess.run(
        ["wsl", "--exec", "bash", "-c", shell_cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=timeout + 5,
    )
    if result.returncode != 0:
        combined = ((result.stdout or "") + "\n" + (result.stderr or "")).replace("\x00", "")
        if "Wsl/Service/" in combined or "connection attempt failed" in combined:
            raise RuntimeError(f"[Oracle] WSL2 service execution failed: {combined[:500]}")
    return result


def _direct_oracle_run(
    cmd: list[str],
    workspace: Path,
    lang: str,
    timeout: int,
    _allow_network: bool = False,  # network isolation not available in direct exec path
) -> subprocess.CompletedProcess:
    """
    Direct subprocess execution — SEC-2 fallback.
    Uses _make_safe_env() + Windows Job Object restrictions.
    This path runs when neither Docker nor WSL2 is available.
    """
    lang_lower = lang.lower()
    env = _make_safe_env()
    if "rust" in lang_lower:
        # L3-C: RAMDisk fallback — require 512 MB free on T: before using it
        hive_target = Path("T:/determinex-target/hive")
        _use_ramdisk = False
        try:
            hive_target.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(hive_target).free >= 512 * 1024 * 1024:
                env["CARGO_TARGET_DIR"] = str(hive_target)
                _use_ramdisk = True
        except OSError:
            pass
        if not _use_ramdisk:
            _fallback = Path(tempfile.gettempdir()) / "determinex-target" / "hive"
            try:
                _fallback.mkdir(parents=True, exist_ok=True)
                env["CARGO_TARGET_DIR"] = str(_fallback)
                log.warning("L3-C: T: drive unavailable/full — CARGO_TARGET_DIR → %s", _fallback)
            except OSError:
                pass
        env["CARGO_TARGET_DIR"] = str(_select_cargo_target_dir())

    # SEC-2: spawn via Popen, immediately assign to a restricted Job Object
    try:
        _flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            env=env,
            creationflags=_flags,
        )
        try:
            applied = _apply_job_object_restrictions(proc._handle)  # type: ignore[attr-defined]
            if not applied:
                log.debug("SEC-2: Job Object assignment failed (non-fatal)")
        except AttributeError:
            pass
        try:
            _out, _err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            proc.communicate()
            raise
        return subprocess.CompletedProcess(
            cmd,
            proc.returncode,
            stdout=_out.decode("utf-8", errors="backslashreplace"),
            stderr=_err.decode("utf-8", errors="backslashreplace"),
        )
    except subprocess.TimeoutExpired:
        raise
    except Exception as _popen_err:
        log.debug("SEC-2 Popen path failed (%s) — falling back to subprocess.run", _popen_err)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=workspace,
        env=env,
    )


def _docker_run(
    cmd: list[str],
    workspace: Path,
    lang: str,
    timeout: int,
    allow_network: bool = False,
) -> subprocess.CompletedProcess:
    """
    Oracle execution dispatcher: Docker → WSL2 → direct.

    Security tiers (best to worst isolation):
      Docker  — ephemeral container, --network=none, 512MB RAM, no new privileges
      WSL2    — env -i clean environment, limited PATH, no credential inheritance
      Direct  — credential-stripped env, Windows Job Object (weakest)

    DETERMINEX_REQUIRE_DOCKER=1 (default): Docker failures abort instead of falling
    back to lower-isolation tiers. Set to 0 only in local-only offline environments
    where Docker is genuinely unavailable and cloud APIs are not in use.
    """
    _require_docker = os.environ.get("DETERMINEX_REQUIRE_DOCKER", "1") == "1"
    backend = _oracle_backend()

    if backend == "docker":
        try:
            return _docker_oracle_run(cmd, workspace, lang, timeout, allow_network)
        except Exception as _de:
            if _require_docker:
                raise RuntimeError(
                    f"[Oracle] Docker execution failed and DETERMINEX_REQUIRE_DOCKER=1 "
                    f"prevents fallback to lower-isolation tiers. "
                    f"Error: {_de}. "
                    f"Fix Docker or set DETERMINEX_REQUIRE_DOCKER=0 (reduces isolation)."
                ) from _de
            log.warning(
                "[Oracle] Docker run failed (%s) — falling back (DETERMINEX_REQUIRE_DOCKER=0)", _de
            )
    elif backend == "wsl2":
        if _require_docker:
            raise RuntimeError(
                "[Oracle] DETERMINEX_REQUIRE_DOCKER=1 but backend resolved to WSL2. "
                "Install Docker Desktop or set DETERMINEX_REQUIRE_DOCKER=0."
            )
        try:
            result = _wsl2_oracle_run(cmd, workspace, lang, timeout, allow_network)
            combined = ((result.stdout or "") + "\n" + (result.stderr or "")).replace("\x00", "")
            if result.returncode != 0 and _is_wsl_toolchain_unavailable(combined):
                raise RuntimeError(f"[Oracle] WSL2 toolchain unavailable: {combined[:500]}")
            return result
        except Exception as _we:
            log.warning("[Oracle] WSL2 run failed (%s) — falling back to direct", _we)
    elif _require_docker:
        raise RuntimeError(
            "[Oracle] DETERMINEX_REQUIRE_DOCKER=1 but no Docker or WSL2 backend available. "
            "Install Docker Desktop or set DETERMINEX_REQUIRE_DOCKER=0."
        )

    log.warning(
        "[Oracle] Running in DIRECT mode — weakest isolation. "
        "Set DETERMINEX_REQUIRE_DOCKER=1 and install Docker for full sandboxing."
    )
    return _direct_oracle_run(cmd, workspace, lang, timeout, allow_network)


# ── Mole-121: Build script pre-scan ─────────────────────────────────────────
# cargo build executes build.rs with host privileges before any security gate.
# pip install -e . executes setup.py/setup.cfg with host privileges.
# Scan these files for dangerous patterns before the compiler is ever invoked.

_BUILDRS_DANGER_RE = re.compile(
    r"Command\s*::\s*new\s*\("  # arbitrary subprocess execution
    r"|std\s*::\s*process\s*::\s*Command"
    r"|std\s*::\s*net\s*::"  # network access from build script
    r"|std\s*::\s*fs\s*::\s*remove"  # file deletion
    r"|std\s*::\s*env\s*::\s*var\s*\("  # env var reads (credential leak)
    r"|include!\s*\("  # arbitrary file inclusion
    # G24: additional dangerous patterns missed by original regex
    r"|std\s*::\s*env\s*::\s*set_var\s*\("  # env var writes — can inject PATH
    r"|std\s*::\s*fs\s*::\s*write\s*\("  # arbitrary file writes outside workspace
    r"|cc\s*::\s*Build",  # cc crate compiles native C code at build time
    re.MULTILINE,
)

_SETUP_PY_DANGER_RE = re.compile(
    r"os\s*\.\s*system\s*\("
    r"|subprocess\s*\."
    r"|eval\s*\("
    r"|exec\s*\("
    r"|__import__",
    re.MULTILINE,
)


def _scan_build_script(workspace: Path, lang: str) -> tuple[bool, str]:
    """Mole-121: Scan build entry-points for dangerous patterns before compiler invocation.

    Returns (is_safe, violation_message).
    """
    lang_lower = lang.lower()

    if "rust" in lang_lower:
        build_rs = workspace / "build.rs"
        if build_rs.exists():
            try:
                source = build_rs.read_text(encoding="utf-8", errors="backslashreplace")
            except OSError:
                return True, ""
            m = _BUILDRS_DANGER_RE.search(source)
            if m:
                msg = (
                    f"[Mole-121] build.rs blocked: dangerous pattern {m.group().strip()!r} "
                    f"would execute with host privileges during cargo build."
                )
                log.error(msg)
                return False, msg

    elif "python" in lang_lower:
        for name in ("setup.py", "setup.cfg"):
            script = workspace / name
            if script.exists():
                try:
                    source = script.read_text(encoding="utf-8", errors="backslashreplace")
                except OSError:
                    continue
                m = _SETUP_PY_DANGER_RE.search(source)
                if m:
                    msg = (
                        f"[Mole-121] {name} blocked: dangerous pattern {m.group().strip()!r} "
                        f"would execute with host privileges during pip install."
                    )
                    log.error(msg)
                    return False, msg

    return True, ""


# ── Scaffolding validation pre-flight ────────────────────────────────────────


def validate_scaffolding(workspace: Path, lang: str) -> tuple[bool, str]:
    """
    Run the appropriate empty-project validation before Step 1.
    Returns (passed, error_message).
    """
    lang = lang.lower()
    try:
        # Mole-121: scan build scripts before any compiler invocation
        safe, violation = _scan_build_script(workspace, lang)
        if not safe:
            return False, violation

        if "rust" in lang:
            r = _docker_run(
                ["cargo", "check"], workspace=workspace, lang=lang, timeout=60, allow_network=True
            )
            if r.returncode == 0:
                log.info("Scaffolding validation: cargo check PASSED")
                return True, ""
            err = (r.stderr or r.stdout)[:800]
            log.warning("Scaffolding validation: cargo check FAILED\n%s", err)
            return False, err

        elif "go" in lang:
            r = _docker_run(
                ["go", "mod", "tidy"],
                workspace=workspace,
                lang=lang,
                timeout=60,
                allow_network=True,
            )
            if r.returncode == 0:
                log.info("Scaffolding validation: go mod tidy PASSED")
                return True, ""
            err = (r.stderr or r.stdout)[:800]
            log.warning("Scaffolding validation: go mod tidy FAILED\n%s", err)
            return False, err

        elif "python" in lang:
            req = workspace / "requirements.txt"
            if req.exists() and req.read_text(encoding="utf-8").strip():
                # Mount the workspace and do pip install --dry-run inside the Docker container
                r = _docker_run(
                    ["python", "-m", "pip", "install", "-r", "requirements.txt", "--dry-run"],
                    workspace=workspace,
                    lang=lang,
                    timeout=60,
                    allow_network=True,
                )
                if r.returncode != 0:
                    err = (r.stderr or r.stdout)[:800]
                    log.warning("Scaffolding validation: pip --dry-run FAILED\n%s", err)
                    return False, err
            log.info("Scaffolding validation: Python PASSED")
            return True, ""

        else:
            log.info("Scaffolding validation: unknown lang '%s' — skipping", lang)
            return True, ""

    except subprocess.TimeoutExpired:
        return False, "Scaffolding validation timed out"
    except FileNotFoundError as e:
        msg = (
            f"Required toolchain not found: {e}\n"
            f"Run check_toolchain_available('{lang}') before starting a session."
        )
        log.error("Scaffolding validation: toolchain not found — FAIL: %s", e)
        return False, msg


# ── #SEC-1 Determinex Security Sentinel ─────────────────────────────────────────
#
# Applied exclusively to Architect-generated TEST HARNESSES before they are
# executed by run_correctness_tests. NOT applied to Builder code (which
# legitimately uses fs/network APIs).
#
# Design: three independent layers because no single layer is foolproof:
#   Layer 1 — Python AST visitor (catches direct imports and calls)
#   Layer 2 — Rust/Go pattern scanner (regex on raw text — tree-sitter optional)
#   Layer 3 — Generic high-confidence patterns across all languages
#
# Obfuscation note: dynamic-import tricks like `__import__('o'+'s')` are caught
# by the generic dangerous-builtin scan (Layer 1 visit_Call + Layer 3 regex).
# Perfect security is impossible without a real OS sandbox, but this gate
# raises the cost of a successful injection by orders of magnitude.

# Python: modules whose presence in a test file is never legitimate
_PY_FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "sys",
        "shutil",
        "socket",
        "requests",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "paramiko",
        "ctypes",
        "cffi",
        "multiprocessing",
        "pty",
        "signal",
        "importlib",
        "runpy",
        "code",
        "codeop",
        "builtins",  # `import builtins as b; b.eval(...)` bypass vector
    }
)
# Python: dangerous built-ins that allow arbitrary code execution
_PY_FORBIDDEN_BUILTINS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
    }
)

# Rust: import paths that must not appear in a correctness test
_RUST_FORBIDDEN_RE = re.compile(
    r"use\s+std::(fs|process|net|os|thread|env)"
    r"|std::(process::Command|fs::File|fs::remove|fs::write|net::Tcp)"
    r"|std::env::var\s*\("
    r"|unsafe\s*\{",
    re.MULTILINE,
)

# Go: import paths that must not appear in a correctness test
_GO_FORBIDDEN_RE = re.compile(
    r'import\s+["(](?:os|os/exec|net|net/http|syscall|unsafe|os/signal)',
    re.MULTILINE,
)

# Cross-language: high-confidence patterns for dynamic code execution tricks
_GENERIC_DANGER_RE = re.compile(
    r"__import__"
    r"|getattr\s*\(.*import"
    r"|eval\s*\("
    r"|exec\s*\("
    r"|compile\s*\(",
    re.MULTILINE,
)


class _PythonSentinelVisitor(ast.NodeVisitor):
    """Walk a Python AST and collect security violations.

    Tracks import aliases so that `import os as avocado; avocado.system(...)`
    is caught at BOTH the import level (alias.name is always the real module
    name) AND the call level (defense-in-depth via _forbidden_names).
    """

    def __init__(self) -> None:
        self.violations: list[str] = []
        # Maps local names → original forbidden module (e.g. "avocado" → "os")
        # Built during import visits; used in call detection for defense-in-depth.
        self._forbidden_names: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in _PY_FORBIDDEN_MODULES:
                self.violations.append(f"Forbidden import: {alias.name}")
            # Track the local binding regardless of whether it's forbidden,
            # so that call-level detection works even for aliased imports.
            bound = alias.asname if alias.asname else top
            if top in _PY_FORBIDDEN_MODULES:
                self._forbidden_names[bound] = top
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            top = node.module.split(".")[0]
            if top in _PY_FORBIDDEN_MODULES:
                self.violations.append(f"Forbidden import from: {node.module}")
                # Track every name imported from this forbidden module
                for alias in node.names:
                    bound = alias.asname if alias.asname else alias.name
                    self._forbidden_names[bound] = top
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Direct built-in call: eval(...), exec(...)
        if isinstance(node.func, ast.Name) and node.func.id in _PY_FORBIDDEN_BUILTINS:
            self.violations.append(f"Forbidden call: {node.func.id}()")
        # Attribute call on __builtins__: __builtins__['eval'](...)
        if isinstance(node.func, ast.Subscript):
            if isinstance(node.func.value, ast.Name) and node.func.value.id in (
                "__builtins__",
                "builtins",
            ):
                self.violations.append("Forbidden __builtins__ subscript call")
        # Alias-based call: `import os as av; av.system(...)` — defense-in-depth.
        # The import itself is already caught above; this adds a second layer in
        # case future code paths somehow reach call detection without import detection.
        if isinstance(node.func, ast.Attribute):
            root = node.func.value
            if isinstance(root, ast.Name) and root.id in self._forbidden_names:
                orig = self._forbidden_names[root.id]
                self.violations.append(
                    f"Call via forbidden module alias '{root.id}' "
                    f"(resolves to '{orig}'): {root.id}.{node.func.attr}()"
                )
        self.generic_visit(node)


def _scan_python_harness(source: str) -> list[str]:
    """Return a list of security violation strings for Python test source."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        # Unparseable Python is suspicious — flag it.
        return [f"SyntaxError during security scan (possible obfuscation): {e}"]
    visitor = _PythonSentinelVisitor()
    visitor.visit(tree)
    return visitor.violations


def _scan_rust_harness(source: str) -> list[str]:
    """Return a list of security violation strings for Rust test source."""
    violations: list[str] = []
    for m in _RUST_FORBIDDEN_RE.finditer(source):
        violations.append(f"Forbidden Rust import/call: {m.group().strip()!r}")
    return violations


def _scan_go_harness(source: str) -> list[str]:
    """Return a list of security violation strings for Go test source."""
    violations: list[str] = []
    for m in _GO_FORBIDDEN_RE.finditer(source):
        violations.append(f"Forbidden Go import: {m.group().strip()!r}")
    return violations


def scan_test_harness_security(source: str, lang: str) -> tuple[bool, list[str]]:
    """
    #SEC-1 Security Sentinel — scan an Architect-generated test harness for
    forbidden imports and dangerous function calls.

    Applied ONLY to test harnesses, not to Builder-generated production code.
    Builder code legitimately uses fs/network APIs; test harnesses must not.

    Returns (is_safe, violations).  is_safe is True iff violations is empty.

    Layers:
        1. Language-specific AST / regex scan (Python AST visitor; Rust/Go regex)
        2. Generic cross-language dangerous-builtin scan (catches obfuscation tricks)
    """
    lang_lower = lang.lower()
    violations: list[str] = []

    if "python" in lang_lower:
        violations.extend(_scan_python_harness(source))
    elif "rust" in lang_lower:
        violations.extend(_scan_rust_harness(source))
    elif "go" in lang_lower:
        violations.extend(_scan_go_harness(source))

    # Generic layer: applies across all languages
    for m in _GENERIC_DANGER_RE.finditer(source):
        msg = f"Generic danger pattern: {m.group().strip()!r}"
        if msg not in violations:
            violations.append(msg)

    is_safe = len(violations) == 0
    if not is_safe:
        log.warning(
            "[SEC-1] Test harness security scan FAILED (%d violation(s)): %s",
            len(violations),
            violations,
        )
    return is_safe, violations


# ── #SEC-2 Builder Output Security Scanner ───────────────────────────────────
#
# Unlike #SEC-1 (test harness sentinel), this runs on production Builder code.
# Production code legitimately uses fs/network, so the bar is different:
# we look for INTENT indicators — exfiltration, persistence, keylogging,
# anti-analysis, shellcode, cryptomining, process masquerading, etc.
#
# Delegates to the determinex_safety L3 Output Scanner for all pattern logic.
# Returns (is_safe, violations) matching the SEC-1 interface.


def scan_builder_output_security(source: str, lang: str) -> tuple[bool, list[str]]:
    """
    #SEC-2: Scan Builder-generated production code for malicious intent patterns.

    Complements scan_test_harness_security (#SEC-1): where SEC-1 blocks all
    fs/net imports in test code (conservative), SEC-2 targets exfiltration,
    persistence, anti-debug, shellcode, and other malicious-INTENT patterns
    in production code (surgical).

    Returns (is_safe, violations). is_safe is True iff violations is empty.
    """
    try:
        from determinex_safety import SafetyVerdict, check_output

        verdict: SafetyVerdict = check_output(source, lang)
        if not verdict.safe:
            log.warning(
                "[SEC-2] Builder output security scan FAILED (%d violation(s)): %s",
                len(verdict.violations),
                verdict.violations,
            )
            return False, verdict.violations
        return True, []
    except ImportError:
        log.warning("[SEC-2] determinex_safety not available — Builder output scan skipped")
        return True, []
    except Exception as e:
        log.error("[SEC-2] Builder output scan raised unexpectedly: %s — DENYING output", e)
        return False, [f"Scanner error (fail-closed): {e}"]


# ── Compiler Oracle — project-level validation ────────────────────────────────


def sanitize_compiler_output(raw: str, workspace_root: Path | None = None) -> str:
    """
    Strip workspace-specific absolute paths and timestamps from compiler output
    before hashing for the quality gate.

    #SEC-2 Pathlib-based path replacement — no fragile regexes.
    We derive the exact absolute path from the provided workspace_root and
    replace it directly. Falls back to the legacy regex approach if workspace_root
    is not provided.
    """
    s = raw.replace("\\", "/")

    if workspace_root:
        # Resolve to handle symlinks and normalize to absolute path
        root_str = str(workspace_root.resolve())
        root_posix = root_str.replace("\\", "/")

        # Replace the exact posix variant with /workspace/
        # Case insensitive replacement for Windows
        pattern = re.compile(re.escape(root_posix) + r"/?", re.IGNORECASE)
        s = pattern.sub("/workspace/", s)

        # Fallback if raw output somehow retained Windows backslashes
        pattern_win = re.compile(re.escape(root_str) + r"/?", re.IGNORECASE)
        s = pattern_win.sub("/workspace/", s)
    else:
        # Legacy fallback if no workspace is provided. We don't know the exact
        # tmp root (varies by OS, user, and worktree config), so scrub anywhere
        # the determinex workspace naming convention appears in the path.
        # NOTE (2026-07-19): this must match scripts/hive/workspace.py's actual
        # WORKSPACE_BASE, which still creates "determinex_workspaces" -- an
        # earlier premature rename to "determinex_workspace(s)" here silently
        # stopped stripping anything (workspace UUIDs, and the local username
        # in the temp path on Windows, leaked straight into hashed/displayed
        # compiler output; two runs of the identical error from different
        # session UUIDs also stopped hashing identically, defeating the
        # quality-gate dedup this function exists for).
        #   /tmp/determinex_workspaces/<id>/        → /workspace/
        #   /tmp/determinex_workspace_<id>/         → /workspace/   (legacy single-name form)
        #   C:/Temp/determinex_workspaces/<id>/     → /workspace/
        # The pattern matches any ancestor (drive letter or /) up through the id.
        s = re.sub(
            r"(?:[A-Za-z]:)?/[^\s\n:]*?determinex_workspaces/[\w\-]+/?",
            "/workspace/",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"(?:[A-Za-z]:)?/[^\s\n:]*?determinex_workspace_[\w\-]+/?",
            "/workspace/",
            s,
            flags=re.IGNORECASE,
        )

    # Scrub ISO-8601 timestamps that appear in cargo / go output
    s = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "TIMESTAMP", s)
    # Normalise rustc arrow lines to prevent hash drift from line numbers
    s = re.sub(
        r"^(\s+-->\s+)/workspace/.*$",
        r"\1/workspace/<sanitized>",
        s,
        flags=re.MULTILINE,
    )
    return s


_INTERNAL_FRAME_RE = re.compile(
    r'File "(?:[^"]*(?:site-packages|lib[/\\]python\d+\.\d+|compileall|'
    r'_bootstrap|importlib|pkg_resources|distutils)[^"]*)"',
    re.IGNORECASE,
)
_TRACEBACK_START_RE = re.compile(r"^Traceback \(most recent call last\):\s*$")


def _strip_internal_tracebacks(text: str) -> str:
    """L14-A: Remove traceback blocks whose frames are all Python internals.

    pytest/compileall crashes produce tracebacks from site-packages and stdlib
    internals. Feeding those frames to the Builder causes hallucinated CPython
    fixes. Only drop a block when EVERY file frame is from Python's own paths;
    mixed blocks (project code + internals) are kept intact.
    """
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    i = 0
    while i < len(lines):
        if _TRACEBACK_START_RE.match(lines[i]):
            block: list[str] = [lines[i]]
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                block.append(lines[i])
                i += 1
            # Grab the trailing exception line (unindented, non-traceback)
            if (
                i < len(lines)
                and not lines[i].startswith(" ")
                and not _TRACEBACK_START_RE.match(lines[i])
            ):
                block.append(lines[i])
                i += 1
            file_lines = [l for l in block if l.strip().startswith('File "')]
            if file_lines and all(_INTERNAL_FRAME_RE.search(l) for l in file_lines):
                continue  # all frames are Python internals — discard entire block
            result.extend(block)
        else:
            result.append(lines[i])
            i += 1
    return "".join(result)


# ── L12-A: Hardcode-cheat detection ──────────────────────────────────────────
# Detects: 3+ consecutive "if var == literal: return value" branches — the
# hallmark of a lookup-table masquerading as real logic.
_HARDCODE_CHEAT_LINE_RE = re.compile(
    r"""^[ \t]*if\s+\w+\s*==\s*(?:["'\d])""",
)


def _detect_hardcode_cheat(code: str) -> list[str]:
    """L12-A: Flag suspicious hardcoded input→output mapping in generated code."""
    lines = code.splitlines()
    hit_lines = [i + 1 for i, ln in enumerate(lines) if _HARDCODE_CHEAT_LINE_RE.match(ln)]
    if len(hit_lines) < 3:
        return []
    clusters: list[list[int]] = []
    run = [hit_lines[0]]
    for ln in hit_lines[1:]:
        if ln - run[-1] <= 5:
            run.append(ln)
        else:
            if len(run) >= 3:
                clusters.append(run[:])
            run = [ln]
    if len(run) >= 3:
        clusters.append(run)
    return [f"L12-A hardcode cluster lines {r[0]}-{r[-1]} ({len(r)} branches)" for r in clusters]


# ── Mole-113: Brevity-cheat detection ────────────────────────────────────────
# Detects stub functions (body = only `pass` / `...` / `return None`) — the
# minimum-token answer that satisfies the compiler but contributes nothing.
_STUB_BODY_RE = re.compile(
    r"def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?:\s*\n\s+(?:pass|\.\.\.|\.\.\.|return\s+None\s*)$",
    re.MULTILINE,
)


def _detect_brevity_cheat(code: str) -> list[str]:
    """Mole-113: Detect stub/placeholder functions masquerading as implementations."""
    stubs = _STUB_BODY_RE.findall(code)
    return [f"Mole-113: {len(stubs)} stub function(s) detected"] if stubs else []


# ── Mole-114: Ghost-import detection ─────────────────────────────────────────
# Detects Python imports that are never referenced in the code body, which
# accumulate silently because tests pass regardless of dead imports.


def _detect_ghost_imports(code: str, lang: str) -> list[str]:
    """Mole-114: Detect unused imports in Python generated code (AST-based)."""
    if "python" not in lang.lower():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    return []  # star-import makes analysis unreliable
                imported.append(alias.asname or alias.name)

    if not imported:
        return []

    code_body = re.sub(r"^(?:import|from)\s+\S.*$", "", code, flags=re.MULTILINE)
    return [
        f"Mole-114: ghost import '{name}'"
        for name in imported
        if not re.search(r"\b" + re.escape(name) + r"\b", code_body)
    ]


def hash_compiler_error(raw: str, workspace_root: Path | None = None) -> str:
    """SHA256 of sanitized compiler output. Used by quality gate."""
    sanitized = sanitize_compiler_output(raw, workspace_root)
    return hashlib.sha256(sanitized.encode("utf-8")).hexdigest()[:16]


def classify_training_quality(step: StepRecord) -> str:
    """
    Quality gate classification:
      training_ready  — compiler error hash CHANGES between attempts
      inconclusive    — compiler error hash is IDENTICAL across ALL attempts
                        AND Architect escalation also failed.

    G12: If step.quality was already set by an upstream gate (integrity checks,
    hack detection, oscillation abort), honour that verdict rather than
    overwriting a stricter classification with a weaker one.
    """
    if step.quality in ("compile_hacked", "inconclusive"):
        return step.quality  # upstream gate already decided — don't downgrade

    hashes = step.compiler_error_hashes
    if not hashes:
        return "inconclusive"
    if len(set(hashes)) > 1:
        return "training_ready"
    if step.escalations >= MAX_ESCALATIONS_PER_STEP and len(set(hashes)) == 1:
        return "inconclusive"
    return "training_ready"


def _oracle_install_hint(lang: str) -> str:
    """The universal oracle registry's install hint for a language, if it has one.

    Read-only: get_oracle() only looks up a dataclass, it does not verify anything, so
    nothing model-generated executes here. That distinction is the whole reason
    validate_project cannot simply delegate -- the registry's verify_fns run a direct
    host subprocess, and this gate's contract is that model output runs sandboxed.
    """
    try:
        import sys as _sys

        _s = str(Path(__file__).resolve().parent.parent)
        if _s not in _sys.path:
            _sys.path.insert(0, _s)
        from determinex_oracle import get_oracle

        o = get_oracle(lang)
        return f" A '{o.name}' oracle exists for it outside the sandbox ({o.install_hint})."
    except Exception:
        return ""


# Python files that are scaffolding rather than project code -- importing them proves
# nothing about the step and can drag in build-time side effects.
_PY_IMPORT_SKIP = ("setup.py", "conftest.py")

# Directories whose .py files are not the step's own output, so finding only these is the
# same as finding nothing. Without the exclusion a vendored .venv or a stale __pycache__
# would satisfy the has-sources check and hand back the empty-workspace pass it exists to
# prevent.
_PY_SOURCE_EXCLUDE = frozenset(
    {
        ".venv",
        "venv",
        "site-packages",
        "__pycache__",
        ".git",
        "node_modules",
    }
)


def _validate_python(workspace: Path, lang: str) -> tuple[bool, str]:
    """Compiler Oracle for Python: parse, then IMPORT, then run any tests present.

    `python -m compileall` alone -- which is all this used to do -- proves only that
    the file PARSES. It never executes a line, so a module-level NameError, a bad
    import, a call to a function that does not exist, or a class referencing an
    undefined base all pass a "Compiler Oracle: PASS". For a system whose entire
    reward signal is the oracle, that is the weakest possible reading of "verified",
    and it is why CLAUDE.md's "every training sample passed a real compiler" was a
    much softer claim for Python than for Rust.

    Three stages, cheapest first, each strictly stronger than the last:
      1. compileall      -- syntax
      2. import          -- module-level execution: undefined names, bad imports
      3. unittest        -- behaviour, when the project actually ships tests

    Stdlib only, deliberately. The sandbox image is python:3.12-slim with
    --network=none, so `pytest` is neither installed nor installable; invoking it would
    fail with "No module named pytest" and that would be indistinguishable from a real
    test failure. `unittest discover` is always present.
    """
    # 0. is there anything here at all?
    #
    # Every stage below exits 0 on an empty tree: compileall compiles nothing, the
    # importer imports nothing, unittest discovers nothing. So a workspace containing no
    # Python -- a builder step whose patch was malformed, or landed under a different path
    # than the step declared -- returned PASS, and the WAL recorded that step as verified.
    # The rust/go/typescript oracles all refuse an empty workspace; this one did not, in
    # the language the project uses most.
    #
    # Checked on the host rather than in the container: it needs no sandbox, and skipping a
    # container start is the difference between a cheap guard and one worth omitting.
    sources = [p for p in workspace.rglob("*.py") if not (set(p.parts) & _PY_SOURCE_EXCLUDE)]
    if not sources:
        msg = (
            "Compiler Oracle: no .py sources in workspace - nothing to verify. "
            "A step cannot be marked verified against an empty tree; check that the "
            "patch applied and wrote where the step declared."
        )
        log.warning("Compiler Oracle: FAIL (no sources)")
        return False, msg

    # 1. syntax
    r = _docker_run(
        ["python", "-m", "compileall", "-q", "."],
        workspace=workspace,
        lang=lang,
        timeout=COMPILE_TIMEOUT,
        allow_network=False,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout)[:400]
        log.warning("Compiler Oracle: FAIL (syntax)\n%s", err)
        return False, err

    # 2. import every project module. Executes module-level code -- which is the
    # point, and is safe only because this runs in the sandbox.
    skip = ",".join(repr(s) for s in _PY_IMPORT_SKIP)
    importer = (
        "import pathlib,importlib.util,sys,traceback\n"
        f"skip = ({skip},)\n"
        "bad = []\n"
        "for p in sorted(pathlib.Path('.').rglob('*.py')):\n"
        "    if p.name in skip or any(x.startswith('.') or x in ('__pycache__','build','dist')"
        " for x in p.parts):\n"
        "        continue\n"
        "    spec = importlib.util.spec_from_file_location(p.stem, p)\n"
        "    if spec is None or spec.loader is None:\n"
        "        continue\n"
        "    try:\n"
        "        spec.loader.exec_module(importlib.util.module_from_spec(spec))\n"
        "    except Exception:\n"
        "        bad.append(f'{p}: ' + traceback.format_exc(limit=3))\n"
        "if bad:\n"
        "    print('IMPORT FAILURES:'); [print(b) for b in bad]; sys.exit(1)\n"
    )
    r = _docker_run(
        ["python", "-c", importer],
        workspace=workspace,
        lang=lang,
        timeout=COMPILE_TIMEOUT,
        allow_network=False,
    )
    if r.returncode != 0:
        err = (r.stdout or r.stderr)[:800]
        log.warning("Compiler Oracle: FAIL (import)\n%s", err)
        return False, err

    # 3. behaviour, only if the project ships tests. "No tests" is NOT a failure --
    # a greenfield step legitimately has none, and reporting that as a FAIL would be
    # the un-actionable "fails for no reason" this project forbids.
    has_tests = any(workspace.rglob("test_*.py")) or any(workspace.rglob("*_test.py"))
    if has_tests:
        r = _docker_run(
            ["python", "-m", "unittest", "discover", "-v"],
            workspace=workspace,
            lang=lang,
            timeout=COMPILE_TIMEOUT,
            allow_network=False,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout)[:800]
            log.warning("Compiler Oracle: FAIL (tests)\n%s", err)
            return False, err
        log.info("Compiler Oracle: PASS (syntax + import + tests)")
        return True, ""

    log.info("Compiler Oracle: PASS (syntax + import; no tests shipped)")
    return True, ""


def validate_project(workspace: Path, lang: str) -> tuple[bool, str]:
    """
    Compiler Oracle: validate the FULL accumulated project state.
    """
    lang = lang.lower()
    try:
        # Mole-121: scan build scripts before any compiler invocation
        safe, violation = _scan_build_script(workspace, lang)
        if not safe:
            return False, violation

        if "rust" in lang:
            r = _docker_run(
                ["cargo", "build", "--message-format", "short"],
                workspace=workspace,
                lang=lang,
                timeout=COMPILE_TIMEOUT,
                allow_network=False,
            )
            output = r.stderr or r.stdout
            passed = r.returncode == 0
            if passed:
                log.info("Compiler Oracle: PASS")
            else:
                log.warning("Compiler Oracle: FAIL\n%s", output[:400])
            return passed, output

        elif "go" in lang:
            r = _docker_run(
                ["go", "build", "./..."],
                workspace=workspace,
                lang=lang,
                timeout=COMPILE_TIMEOUT,
                allow_network=False,
            )
            output = r.stderr or r.stdout
            passed = r.returncode == 0
            if passed:
                log.info("Compiler Oracle: PASS")
            else:
                log.warning("Compiler Oracle: FAIL\n%s", output[:400])
            return passed, output

        elif "python" in lang:
            return _validate_python(workspace, lang)

        elif "typescript" in lang or lang in ("ts", "tsx"):
            # A real type check, which is what CLAUDE.md has claimed all along while this
            # branch did not exist and TypeScript fell through to the lenient pass.
            #
            # The project's own tsconfig.json wins when it ships one -- its paths/strictness
            # are part of what the code means. Only when none exists does the image's baked
            # default apply, which is strict on purpose: a lenient tsc is most of the way
            # back to the lenient pass this replaces.
            #
            # NOT "javascript": tsc over plain JS checks almost nothing, and reporting that
            # as verified would be the same overclaim in a new place. JS still fails closed.
            has_cfg = (workspace / "tsconfig.json").is_file()
            cmd = ["tsc", "--noEmit"] if has_cfg else ["sh", "-c", _TS_DEFAULT_CHECK]
            r = _docker_run(
                cmd, workspace=workspace, lang=lang, timeout=COMPILE_TIMEOUT, allow_network=False
            )
            output = r.stdout or r.stderr
            passed = r.returncode == 0
            if passed:
                log.info(
                    "Compiler Oracle: PASS (tsc --noEmit%s)",
                    "" if has_cfg else ", image default tsconfig",
                )
            else:
                log.warning("Compiler Oracle: FAIL\n%s", output[:400])
            return passed, output

        else:
            # FAIL CLOSED. This branch used to return (True, "") -- a "lenient pass"
            # -- for every language outside rust/go/python. TypeScript, Java, C, C++
            # all landed here, so every step of such a session was recorded as
            # Compiler PASS having been verified by nothing at all. CLAUDE.md listed
            # `tsc` as part of the oracle; it was never reached.
            #
            # That directly contradicts the doctrine determinex_oracle.py was built to
            # enforce -- "a stub raises OracleUnavailable with an install hint: an
            # oracle NEVER silently passes" -- and a PASS that means nothing is worse
            # than an honest failure, because it is indistinguishable from a real one
            # in the WAL and in the training corpus.
            #
            # Not delegated to determinex_oracle.get_oracle(): its verify_fns run a
            # direct host subprocess, and running model-generated code outside the
            # sandbox to gain verification would trade a correctness gap for a
            # security one. The fix is an oracle IMAGE for the language (see
            # _ORACLE_IMAGES), not a looser execution boundary.
            hint = _oracle_install_hint(lang)
            for key, build_cmd in _ORACLE_IMAGE_HINT.items():
                if key in lang:
                    hint += f" Build its sandbox image with: {build_cmd}"
                    break
            msg = (
                f"No sandboxed Compiler Oracle for lang '{lang}'. Configured: "
                f"{sorted(_ORACLE_IMAGES)}. A step cannot be marked verified without "
                f"one.{hint} Set DETERMINEX_ORACLE_LENIENT=1 to accept UNVERIFIED "
                f"passes for this language (recorded as such, not recommended)."
            )
            if os.environ.get("DETERMINEX_ORACLE_LENIENT", "") == "1":
                log.warning(
                    "Compiler Oracle: UNVERIFIED lenient pass for '%s' "
                    "(DETERMINEX_ORACLE_LENIENT=1) — this step was checked by "
                    "nothing",
                    lang,
                )
                return True, f"UNVERIFIED: {msg}"
            log.error("Compiler Oracle: FAIL — %s", msg)
            return False, msg

    except subprocess.TimeoutExpired:
        return False, f"Compilation timed out after {COMPILE_TIMEOUT}s"
    except FileNotFoundError as e:
        log.warning("Compiler Oracle: toolchain not found (%s)", e)
        return False, f"Toolchain not found: {e}"


# ── Plan A: Correctness Oracle ────────────────────────────────────────────────

# Timeout for correctness tests (shorter than build — tests must be fast by design)
CORRECTNESS_TEST_TIMEOUT = 30

# Patterns that indicate the Builder reward-hacked compilation:
# compiles cleanly but doesn't actually implement anything.
_COMPILE_HACK_PATTERNS = re.compile(
    r"unimplemented!\s*\(\)"  # Rust unimplemented!()
    r"|todo!\s*\(\)"  # Rust todo!()
    r"|panic!\s*\(['\"]not implemented"  # Rust panic
    r"|raise\s+NotImplementedError"  # Python NotImplementedError
    r"|pass\s*#\s*TODO"  # Python empty stub
    r"|return\s+(?:0|None|\"\"|-1|false|true)\s*(?:#.*)?$"  # trivial hardcoded return
    r"|//\s*TODO",  # Go/Rust unimplemented comment stub
    re.MULTILINE,
)
_EMPTY_RUST_MAIN_ONLY = re.compile(r"^\s*fn\s+main\s*\(\s*\)\s*\{\s*\}\s*$", re.DOTALL)


def detect_compile_hack(code: str) -> bool:
    """
    Static heuristic scan for reward-hacking patterns.
    Catches the most common cases: unimplemented!(), todo!(), empty stubs.
    Returns True if the code looks like a compilation hack rather than a real impl.
    This is a pre-filter — the correctness test runner is the authoritative check.
    """
    return bool(_COMPILE_HACK_PATTERNS.search(code) or _EMPTY_RUST_MAIN_ONLY.search(code))


def _write_empty_stub(workspace: Path, lang: str) -> Path | None:
    """
    #SEC-3 Reference Failure: write a minimal empty stub for the project's
    main source file so we can run the test harness against it.
    Returns the path of the stub file, or None if the stub cannot be determined.
    """
    lang_lower = lang.lower()
    stubs: dict[str, tuple[str, str]] = {
        "rust": ("src/lib.rs", "// empty stub\n"),
        "go": ("main.go", "package main\nfunc main() {}\n"),
        "python": ("main.py", "# empty stub\n"),
    }
    for key, (rel, content) in stubs.items():
        if key in lang_lower:
            stub_path = workspace / rel
            return stub_path if stub_path.exists() else None
    return None


def run_correctness_tests(
    workspace: Path,
    lang: str,
    test_harness_rel: str,
) -> tuple[bool, str]:
    """
    Plan A Correctness Oracle: run the Architect-generated happy-path test harness
    against the current workspace after a Compiler PASS.

    Returns (passed, output).

    Design constraints for the test harness (enforced by Architect prompt):
    - Pure assertions only — no filesystem writes, no network calls, no threads
    - Must compile cleanly alongside the project (already in workspace)
    - Timeout: 30s — tests should be millisecond-range assertions

    #SEC-1 Security Gate: the harness is scanned for forbidden imports and
    dangerous calls before any subprocess is spawned. A harness that tries to
    import `os`, `subprocess`, `std::fs`, or `os/exec` is rejected immediately
    with status REJECTED_SECURITY.

    #SEC-3 Reference Failure (Watchmen Fix): before the harness is accepted,
    we run it against an EMPTY or UNIMPLEMENTED stub of the production code.
    If the test PASSES on empty code, it is a hallucinated assertion — it proves
    nothing. The harness is rejected with status REJECTED_HALLUCINATED_TEST.
    """
    lang = lang.lower()
    harness = workspace / test_harness_rel

    if not harness.exists():
        log.warning("Correctness test harness not found: %s — skipping", harness)
        return True, "harness_not_found"

    # ── #SEC-1 Security scan before any subprocess ────────────────────────────
    try:
        harness_source = harness.read_text(encoding="utf-8", errors="backslashreplace")
    except OSError as e:
        log.warning("Cannot read test harness '%s': %s — skipping", harness, e)
        return True, f"harness_read_error: {e}"

    is_safe, violations = scan_test_harness_security(harness_source, lang)
    if not is_safe:
        msg = "REJECTED_SECURITY: " + "; ".join(violations)
        log.warning("[SEC-1] Harness rejected — security violations: %s", violations)
        return False, msg

    def _run_tests() -> tuple[bool, str]:
        """Inner helper — runs the actual test command. Called twice (stub + real)."""
        try:
            if "rust" in lang:
                r = _docker_run(
                    ["cargo", "test"],
                    workspace=workspace,
                    lang=lang,
                    timeout=CORRECTNESS_TEST_TIMEOUT,
                    allow_network=False,
                )
                return r.returncode == 0, (r.stdout + r.stderr)[:1000]

            elif "go" in lang:
                r = _docker_run(
                    ["go", "test", "./...", "-timeout", "25s", "-v"],
                    workspace=workspace,
                    lang=lang,
                    timeout=CORRECTNESS_TEST_TIMEOUT,
                    allow_network=False,
                )
                return r.returncode == 0, (r.stdout + r.stderr)[:1000]

            elif "python" in lang:
                r = _docker_run(
                    ["python", "-m", "unittest", test_harness_rel],
                    workspace=workspace,
                    lang=lang,
                    timeout=CORRECTNESS_TEST_TIMEOUT,
                    allow_network=False,
                )
                return r.returncode == 0, (r.stdout + r.stderr)[:1000]

            else:
                return True, "lang_unsupported"

        except subprocess.TimeoutExpired:
            log.warning(
                "Correctness tests timed out after %ds — treating as skip",
                CORRECTNESS_TEST_TIMEOUT,
            )
            return True, "test_timeout"
        except FileNotFoundError as e:
            log.warning("Correctness test runner not found: %s — skipping", e)
            return True, f"runner_not_found: {e}"

    # ── #SEC-3 Reference Failure: run harness against empty/stub state ────────
    # We snapshot the current production source, replace it with an empty stub,
    # run the tests, then restore the original before running real tests.
    # If the tests PASS on empty code, the harness is a hallucination — reject.
    stub_path = _write_empty_stub(workspace, lang)
    if stub_path is not None and stub_path.exists():
        original_source = stub_path.read_text(encoding="utf-8")
        is_actually_empty = original_source.strip() in (
            "",
            "// placeholder",
            "// empty stub",
            "# empty stub",
            "// empty stub\n",
            "# empty stub\n",
        )
        if not is_actually_empty:
            # Temporarily replace with a do-nothing stub
            _LANG_EMPTY_STUBS = {
                "rust": "// empty stub\n",
                "go": "package main\nfunc main() {}\n",
                "python": "# empty stub\n",
            }
            empty_content = next((v for k, v in _LANG_EMPTY_STUBS.items() if k in lang), None)
            if empty_content:
                try:
                    stub_path.write_text(empty_content, encoding="utf-8")
                    stub_passed, _stub_out = _run_tests()
                finally:
                    # Always restore, even if the test runner crashes
                    stub_path.write_text(original_source, encoding="utf-8")

                if stub_passed:
                    msg = (
                        "REJECTED_HALLUCINATED_TEST: harness passed against empty stub — "
                        "it is not verifying the Builder's implementation. "
                        "Architect must rewrite the test with stronger assertions."
                    )
                    log.warning("[SEC-3] %s", msg)
                    return False, msg
                else:
                    log.info(
                        "[SEC-3] Reference failure confirmed — harness correctly "
                        "fails on empty stub. Proceeding to real test run."
                    )

    # ── Real test run against Builder's actual code ───────────────────────────
    passed, output = _run_tests()
    log.info("Correctness tests (%s): %s", lang, "PASS" if passed else "FAIL")
    return passed, output


def generate_test_harness_prompt(md_spec: str, lang: str) -> str:
    """
    Return the Architect prompt to generate a constrained happy-path test harness.

    The harness must satisfy these constraints (enforced in the prompt):
    - Pure functional assertions — no I/O, no network, no filesystem writes, no sleep
    - Uses only the public API described in the MD spec
    - Covers the happy path of each described function/struct
    - Does NOT test error paths or edge cases (those require richer context)
    - Compiles cleanly as part of the existing project (imports from project modules)

    These constraints make the harness useful for catching reward-hacking
    (unimplemented!(), return 0) while being straightforward to generate correctly.
    """
    lang_hints = {
        "rust": (
            "Write a Rust integration test file in tests/correctness.rs. "
            "Use #[test] functions. Import from the library crate with `use your_crate::*;`. "
            "Assert return values. No std::fs, no std::net, no std::thread::sleep."
        ),
        "go": (
            "Write a Go test file in <package>_test.go. "
            "Use func TestXxx(t *testing.T) functions. "
            "Call public functions and assert with t.Errorf. No os.File writes, no http, no time.Sleep."
        ),
        "python": (
            "Write a pytest file tests/test_correctness.py. "
            "Use def test_xxx() functions with assert statements. "
            "No open(), no requests, no time.sleep, no random."
        ),
    }
    lang_hint = lang_hints.get(lang.lower(), "Write tests using the standard test framework.")

    return (
        f"You are the Architect for a {lang} project. "
        f"Generate a CONSTRAINED correctness test harness for the following MD spec.\n\n"
        f"CONSTRAINTS — violation means the test will be rejected:\n"
        f"1. Pure assertions only — test return values and state, nothing else\n"
        f"2. No filesystem writes, no network calls, no threads, no sleep, no randomness\n"
        f"3. Uses ONLY the public API described in the spec — no internal functions\n"
        f"4. Must compile cleanly alongside the project (use proper imports)\n"
        f"5. Happy path only — do not test error cases or edge cases\n\n"
        f"Language: {lang}\n"
        f"Format: {lang_hint}\n\n"
        f"MD Spec:\n{md_spec}\n\n"
        f"Output ONLY the test file content — no explanation, no markdown fences."
    )


# ── File merge — write_mode strategies ───────────────────────────────────────


def _is_full_file_rewrite(existing: str, new_code: str, target_file: str) -> bool:
    """
    Return True if new_code looks like a full-file rewrite rather than incremental
    code to append.  Used to catch 1.5B models that output the entire file for every
    'append_to_file' step instead of just the new delta.

    Heuristics (any one is sufficient):
    1. Python: new_code redefines ≥50% of the top-level class/function names already
       present in existing — i.e. the model regenerated the whole class.
    2. Any language: new_code starts with the same import block as existing AND
       new_code is longer than existing (so it's not just a duplicate of a smaller file).
    3. Any language: new_code contains existing's first non-empty, non-comment line,
       strongly suggesting the model copied the file header before adding the delta.
    """
    if not existing.strip() or not new_code.strip():
        return False

    # ── Heuristic 1: Python AST symbol overlap ────────────────────────────────
    if target_file.endswith(".py"):
        try:

            def _top_names(src: str) -> set[str]:
                tree = ast.parse(src)
                return {
                    n.name
                    for n in tree.body
                    if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                }

            existing_names = _top_names(existing)
            new_names = _top_names(new_code)
            if existing_names and len(existing_names & new_names) >= len(existing_names) * 0.5:
                return True
        except SyntaxError:
            pass  # fall through to other heuristics

    # ── Heuristic 2: shared import header + new_code is longer ────────────────
    existing_lines = [l for l in existing.splitlines() if l.strip()]
    new_lines = [l for l in new_code.splitlines() if l.strip()]
    import_lines = [l for l in existing_lines[:10] if l.startswith(("import ", "from ", "#!"))]
    if import_lines and len(new_lines) > len(existing_lines):
        new_head = new_code[:300]
        if all(imp in new_head for imp in import_lines[:2]):
            return True

    # ── Heuristic 3: first meaningful line of existing appears in new_code ────
    for line in existing_lines[:5]:
        if len(line.strip()) > 10 and not line.strip().startswith("#"):
            if line in new_code:
                return True
            break

    return False


def _fsync_file(path: Path) -> None:
    """#20: Force OS kernel to flush write buffers to physical disk."""
    try:
        with open(path, "r+b") as fh:
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as e:
        log.warning("fsync failed for %s: %s", path, e)


# ── L3-A: Atomic file write ───────────────────────────────────────────────────
# open(target, "w") is non-atomic: a crash between open() and close() leaves a
# 0-byte or partially written source file that silently corrupts the workspace.
# The fix: write to a sibling temp file, fsync, then os.replace() which is
# atomic on POSIX and atomic on Windows (same-volume rename via MoveFileExW).

_ENV_FILE_RE = re.compile(
    r"(\.env$|\.env\.|\.pem$|\.key$|\.pfx$|\.p12$|id_rsa|id_ed25519|id_ecdsa)",
    re.IGNORECASE,
)


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically: temp-file → fsync → os.replace().

    Also enforces Mole-109: blocks AI-generated writes to .env / key files.
    Raises ValueError if path matches the secret-file denylist.
    """
    if _ENV_FILE_RE.search(path.name):
        raise ValueError(
            f"[Mole-109] Blocked write to sensitive file: {path.name}. "
            "AI-generated output must not create credential files."
        )
    # Mole-126: strip BOM so re-writing a BOM-prefixed file doesn't double it
    content = content.lstrip("﻿")
    tmp = path.parent / f".determinex_tmp_{path.name}"
    try:
        tmp.write_text(content, encoding="utf-8")
        _fsync_file(tmp)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── L3-B: Windows MAX_PATH (260-char ceiling) ────────────────────────────────
def _win32_long_path(path: Path) -> Path:
    """Prepend \\?\\ prefix on Windows for paths that exceed 256 characters."""
    if sys.platform.startswith("win"):
        raw = str(path.resolve())
        if len(raw) >= 256 and not raw.startswith("\\\\?\\"):
            return Path("\\\\?\\" + raw)
    return path


# ── Mole-119: Git conflict marker detection ───────────────────────────────────
_GIT_CONFLICT_RE = re.compile(r"^(<{7}|={7}|>{7})\s", re.MULTILINE)

# ── Mole-123: Shebang hijack ──────────────────────────────────────────────────
# Allow only standard interpreter shebangs.  A shebang pointing to a path that
# doesn't match one of these patterns is a red flag for interpreter substitution.
_SAFE_SHEBANG_RE = re.compile(
    r"^#!\s*(?:"
    r"/usr/bin/env\s+|/usr/local/bin/env\s+"  # env-style: /usr/bin/env python3
    r"|/usr/(?:local/)?bin/"  # direct: /usr/bin/python3
    r"|/bin/"  # system: /bin/bash
    r")"
    r"(?:python3?|bash|sh|zsh|node|perl|ruby)\b"
)
_SHEBANG_LINE_RE = re.compile(r"^#!")

# ── Mole-115: Mock addiction (unittest.mock in source files) ──────────────────
_MOCK_IN_SOURCE_RE = re.compile(
    r"(?:^|\n)\s*(?:import\s+unittest\.mock|from\s+unittest(?:\.mock)?\s+import\s+(?:mock|Mock|MagicMock|patch))",
    re.IGNORECASE,
)


# ── Mole-110: Indentation normalisation ──────────────────────────────────────
def _normalize_indentation(code: str) -> str:
    """Convert leading tabs to 4-space indentation to prevent mixed-indent crashes."""
    lines = []
    for line in code.splitlines(keepends=True):
        stripped = line.lstrip("\t")
        if stripped is not line:  # had leading tabs
            n_tabs = len(line) - len(stripped)
            lines.append("    " * n_tabs + stripped)
        else:
            lines.append(line)
    return "".join(lines)


def apply_step_output(workspace: Path, step: StepRecord, code: str) -> bool:
    """
    Apply Builder's output to the workspace using the step's write_mode strategy.
    Returns True on success.
    """
    # ── #21 Normalize Unicode before writing to disk ───────────────────────────
    # LLMs may output NFC/NFD mixed forms or invisible Unicode characters
    # (zero-width spaces, non-breaking spaces) that compile as syntax errors.
    code = normalize_code_text(code)

    # ── Mole-110: Normalize indentation — tabs → 4-space ─────────────────────
    code = _normalize_indentation(code)

    # ── Path traversal guard ──────────────────────────────────────────────────
    # target_file comes from the AI Architect. An injected/hallucinated path like
    # "../../Windows/System32/foo" must never escape the workspace sandbox.
    try:
        target = (workspace / step.target_file).resolve()
        workspace_resolved = workspace.resolve()
        target.relative_to(workspace_resolved)  # raises ValueError if outside
    except ValueError:
        log.error(
            "PATH TRAVERSAL BLOCKED: target_file '%s' resolves outside workspace %s — "
            "step %d skipped.",
            step.target_file,
            workspace,
            step.id,
        )
        return False

    # ── #9 Symlink exfiltration guard ────────────────────────────────────────
    if target.exists() and os.path.islink(target):
        log.error(
            "SYMLINK EXFILTRATION BLOCKED: '%s' is a symlink — step %d skipped. "
            "The Builder may have injected a filesystem escape.",
            step.target_file,
            step.id,
        )
        return False

    # ── Mole-109: Block AI writes to credential / key files ──────────────────
    if _ENV_FILE_RE.search(target.name):
        log.error(
            "[Mole-109] CREDENTIAL WRITE BLOCKED: AI attempted to write '%s' — step %d skipped.",
            step.target_file,
            step.id,
        )
        return False

    # ── Mole-119: Block code containing git conflict markers ─────────────────
    if _GIT_CONFLICT_RE.search(code):
        log.error(
            "[Mole-119] GIT CONFLICT MARKERS in generated code for '%s' — step %d skipped.",
            step.target_file,
            step.id,
        )
        return False

    # ── Mole-123: Reject suspicious shebangs ─────────────────────────────────
    first_line = code.lstrip().split("\n")[0] if code.strip() else ""
    if _SHEBANG_LINE_RE.match(first_line) and not _SAFE_SHEBANG_RE.match(first_line):
        log.error(
            "[Mole-123] SHEBANG HIJACK BLOCKED: '%s' has non-standard shebang '%s' — step %d skipped.",
            step.target_file,
            first_line[:80],
            step.id,
        )
        return False

    # ── Mole-115: Block mock imports in source files ──────────────────────────
    _is_test_file = (
        any(
            kw in step.target_file.lower()
            for kw in ("test_", "_test.", "/tests/", "\\tests\\", "spec_", "_spec.")
        )
        if step.target_file
        else False
    )
    if not _is_test_file and _MOCK_IN_SOURCE_RE.search(code):
        log.warning(
            "[Mole-115] unittest.mock in source file '%s' — step %d routed to human review.",
            step.target_file,
            step.id,
        )
        step.quality = "inconclusive"  # demote; don't block the write

    target.parent.mkdir(parents=True, exist_ok=True)
    # L3-B: use long-path prefix on Windows for deep workspace trees
    target = _win32_long_path(target)
    mode = step.write_mode

    # L9-B: Phantom target guard — replace modes on a file that doesn't exist yet
    # create orphan files outside DAG ordering, breaking subsequent compile steps.
    if mode in ("replace_file", "replace_function") and not target.exists():
        log.error(
            "[L9-B] PHANTOM TARGET: '%s' does not exist for write_mode='%s' — step %d skipped. "
            "Ensure a prior new_file step creates this target before replacing it.",
            step.target_file,
            mode,
            step.id,
        )
        return False

    if mode == "new_file":
        _atomic_write(target, code)  # L3-A
        log.info("write_mode=new_file → %s", step.target_file)
        return True

    if mode == "replace_file":
        _atomic_write(target, code)  # L3-A
        log.info("write_mode=replace_file → %s", step.target_file)
        return True

    if mode == "append_to_file":
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if existing and _is_full_file_rewrite(existing, code, step.target_file):
            _atomic_write(target, code)  # L3-A
            log.info(
                "write_mode=append_to_file (full-rewrite detected → replace) → %s", step.target_file
            )
        else:
            sep = "\n" if existing and not existing.endswith("\n") else ""
            _atomic_write(target, existing + sep + code)  # L3-A
            log.info("write_mode=append_to_file → %s", step.target_file)
        return True

    if mode == "replace_function":
        if not step.target_region:
            log.warning("replace_function: no target_region — falling back to replace_file")
            _atomic_write(target, code)  # L3-A
            return True
        success = _ast_replace_function(workspace, target, step.target_region, code)
        if not success:
            log.warning("replace_function: tree-sitter failed — falling back to replace_file")
            _atomic_write(target, code)  # L3-A
        return True

    log.error("Unknown write_mode: '%s' — no action taken", mode)
    return False


def _ast_replace_function(workspace: Path, target: Path, fn_name: str, replacement: str) -> bool:
    """
    Invoke the Determinex ast_editor via the Tauri CLI bridge.
    Returns True on success, False on any error.
    """
    try:
        tauri_bin = _ROOT / "frontend" / "src-tauri" / "target" / "debug" / "determinex"
        if not tauri_bin.exists():
            tauri_bin = _ROOT / "frontend" / "src-tauri" / "target" / "release" / "determinex"
        if not tauri_bin.exists():
            log.debug("ast_editor: Tauri binary not found — falling back")
            return False

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".rs", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(replacement)
            tmp_path = tf.name

        r = subprocess.run(
            [
                str(tauri_bin),
                "ast-replace-fn",
                "--file",
                str(target),
                "--fn",
                fn_name,
                "--replacement",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=workspace,
        )
        Path(tmp_path).unlink(missing_ok=True)
        return r.returncode == 0

    except Exception as e:
        log.debug("ast_editor IPC error: %s", e)
        return False


# ── Public API snapshot extraction ────────────────────────────────────────────


def extract_public_api(file_path: Path, lang: str) -> dict:
    """
    Extract public API surface from a source file for DAG invalidation detection.
    """
    if not file_path.exists():
        return {"structs": [], "functions": [], "fields": {}, "return_types": {}}

    content = file_path.read_text(encoding="utf-8")
    lang = lang.lower()

    if "rust" in lang:
        return _extract_rust_api(content)
    elif "go" in lang:
        return _extract_go_api(content)
    elif "python" in lang:
        return _extract_python_api(content)
    return {"structs": [], "functions": [], "fields": {}, "return_types": {}}


def _extract_rust_api(content: str) -> dict:
    structs = re.findall(r"^pub\s+struct\s+(\w+)", content, re.MULTILINE)
    functions = re.findall(
        r"^pub\s+(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)\s*(->\\s*[^{]+)?", content, re.MULTILINE
    )
    fn_names = [f[0] for f in functions]
    return_types = {f[0]: f[2].strip().lstrip("->").strip() if f[2] else "()" for f in functions}
    return {"structs": structs, "functions": fn_names, "fields": {}, "return_types": return_types}


def _extract_go_api(content: str) -> dict:
    funcs = re.findall(r"^func\s+(\w+)\s*\(([^)]*)\)\s*([^\s{]*)", content, re.MULTILINE)
    fn_names = [f[0] for f in funcs if f[0][0].isupper()]
    ret_types = {f[0]: f[2].strip() for f in funcs if f[0][0].isupper()}
    types = re.findall(r"^type\s+(\w+)\s+struct", content, re.MULTILINE)
    return {"structs": types, "functions": fn_names, "fields": {}, "return_types": ret_types}


def _extract_python_api(content: str) -> dict:
    try:
        tree = ast.parse(content)
        funcs = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
        ]
        klasses = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        return {"structs": klasses, "functions": funcs, "fields": {}, "return_types": {}}
    except SyntaxError:
        return {"structs": [], "functions": [], "fields": {}, "return_types": {}}


def api_snapshots_differ(snap_a: dict, snap_b: dict) -> bool:
    """Returns True if the two public API snapshots are materially different."""
    if set(snap_a.get("structs", [])) != set(snap_b.get("structs", [])):
        return True
    if set(snap_a.get("functions", [])) != set(snap_b.get("functions", [])):
        return True
    if snap_a.get("return_types", {}) != snap_b.get("return_types", {}):
        return True
    return False
