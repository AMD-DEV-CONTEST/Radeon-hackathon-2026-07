"""scripts/determinex_doctor.py — first-run setup detector.

Walks the local environment and reports what Determinex can actually run on this
machine. Output is both a human-readable table and a JSON payload at
`--json <path>` so the future Tauri first-run wizard can consume it.

Checks (each reports ACTIVE / UNAVAILABLE WITH REASON / NOT IMPLEMENTED BY DESIGN):

  ── core toolchain ─────────────────────────────────────────────────────
    python_version          must be ≥3.11
    git                     git on PATH; HEAD reachable from repo
    docker_daemon           docker version + daemon up
    bash                    POSIX shell available (Windows: Git Bash / WSL)

  ── ai backends ────────────────────────────────────────────────────────
    ollama                  ollama serve responding; list of installed models
    api_keys                ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENROUTER_API_KEY
                            (presence only — never logs the key value)

  ── compilers (per language family executors need these) ──────────────
    rust_toolchain          rustc + cargo
    go_toolchain            go (≥1.21)
    c_compiler              cc / gcc / clang on PATH
    cpp_compiler            c++ / g++ / clang++ on PATH
    node                    node + npm
    java                    javac + java

  ── determinex models ─────────────────────────────────────────────────────
    determinex_models_dir      T:/determinex-models (or DETERMINEX_MODELS_DIR env) exists
    rosetta_v1_pt           ~/.determinex/rosetta/rosetta_v1.pt or in models dir
    ollama_determinex_models   determinex-engineer-* / determinex-observer-* / determinex-sentinel-*
                            present in `ollama list`

  ── hardware ───────────────────────────────────────────────────────────
    gpu                     nvidia-smi or torch.cuda.is_available()
    vram                    free + total VRAM
    disk_space              C: and T: free space
    cpu_count               logical CPU count

  ── data ───────────────────────────────────────────────────────────────
    huggingface_cache       T:/huggingface_cache or HF_HOME
    programbench_dir        T:/Dev/ProgramBench or PROGRAMBENCH_DIR
    pre_cloned_tasks        T:/determinex-programbench (pre-cloned task repos)

  ── determinex cockpit (existing) ────────────────────────────────────────
    ledger                  logs/determinex_ledger.db readable
    eval_jsons_present      any *.eval.json under T:/determinex-programbench/

Plus a deterministic "demo mode" verdict at the end: can Determinex produce a
useful first impression on this machine WITHOUT cloud API keys, WITHOUT
Ollama models installed, and WITHOUT Docker? (Yes if the read-only cockpit +
ledger work; that's the safe demo floor.)

Usage:
    python scripts/determinex_doctor.py
    python scripts/determinex_doctor.py --json logs/determinex_doctor_latest.json
    python scripts/determinex_doctor.py --strict   # exit 1 if any UNAVAILABLE
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Settings spine — loaded lazily so doctor can still run if scripts/ isn't on path
_SETTINGS = None


def _get_settings():
    global _SETTINGS
    if _SETTINGS is None:
        try:
            import sys as _sys

            _scripts = str(REPO_ROOT / "scripts")
            if _scripts not in _sys.path:
                _sys.path.insert(0, _scripts)
            from determinex_settings import get_settings

            _SETTINGS = get_settings()
        except Exception:
            _SETTINGS = None
    return _SETTINGS


ACTIVE = "ACTIVE"
UNAVAIL = "UNAVAILABLE WITH REASON"
DESIGN_ONLY = "NOT IMPLEMENTED BY DESIGN"
PARTIAL = "PARTIAL"  # works but with caveats


@dataclass
class Check:
    name: str
    category: str  # "core" | "ai" | "compilers" | "models" | "hardware" | "data" | "cockpit"
    status: str  # ACTIVE | UNAVAILABLE WITH REASON | PARTIAL | NOT IMPLEMENTED BY DESIGN
    detail: str = ""
    extra: dict = field(default_factory=dict)
    fix: str = ""  # one-line recovery hint when status != ACTIVE

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _try(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    """Run `cmd`, return (rc, stdout, stderr). Never raises on missing exe."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    except OSError as e:
        return -1, "", f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_python_version() -> Check:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        return Check(
            "python_version",
            "core",
            ACTIVE,
            detail=f"{platform.python_version()}",
            extra={"version": platform.python_version()},
        )
    return Check(
        "python_version",
        "core",
        UNAVAIL,
        detail=f"Python {major}.{minor} — Determinex requires ≥3.11",
        fix="install Python 3.11 or 3.12",
    )


def check_git() -> Check:
    rc, out, err = _try(["git", "--version"])
    if rc != 0:
        return Check(
            "git",
            "core",
            UNAVAIL,
            detail=err or "git not on PATH",
            fix="install git from https://git-scm.com/",
        )
    rc2, head, _ = _try(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"])
    return Check(
        "git",
        "core",
        ACTIVE,
        detail=f"{out}  head={head if rc2 == 0 else 'unknown'}",
        extra={"head": head if rc2 == 0 else None},
    )


def check_docker() -> Check:
    # 30s timeout: under benchmark load Docker Desktop can take >10s to respond
    rc, out, err = _try(["docker", "version", "--format", "{{.Server.Version}}"], timeout=30.0)
    if rc != 0:
        return Check(
            "docker_daemon",
            "core",
            UNAVAIL,
            detail=err[:160] or "docker daemon not reachable",
            fix="install Docker Desktop and start it",
        )
    return Check("docker_daemon", "core", ACTIVE, detail=f"server v{out}")


def check_bash() -> Check:
    sh = _which("bash")
    if not sh:
        return Check(
            "bash",
            "core",
            UNAVAIL,
            detail="bash not on PATH",
            fix="install Git Bash (Windows) or WSL",
        )
    return Check("bash", "core", ACTIVE, detail=sh)


def check_ollama() -> Check:
    rc, out, _ = _try(["ollama", "list"], timeout=5.0)
    if rc != 0:
        return Check(
            "ollama",
            "ai",
            UNAVAIL,
            detail="ollama not on PATH or daemon not running",
            fix="install Ollama from https://ollama.com/ and run `ollama serve`",
        )
    # Count models from list output
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("NAME")]
    return Check(
        "ollama",
        "ai",
        ACTIVE,
        detail=f"{len(lines)} model(s) installed",
        extra={"models": [ln.split()[0] for ln in lines if ln.split()][:20]},
    )


def check_api_keys() -> Check:
    keys = {
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "DEEPSEEK_API_KEY": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY")),
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
    }
    set_keys = [k for k, v in keys.items() if v]
    if not set_keys:
        return Check(
            "api_keys",
            "ai",
            UNAVAIL,
            detail="no cloud LLM API key set",
            fix="set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY in .env (local-only mode works without)",
            extra={"checked": list(keys.keys())},
        )
    return Check(
        "api_keys",
        "ai",
        ACTIVE,
        detail=f"{len(set_keys)} key(s) present: {set_keys}",
        # NEVER include the key value — only presence
        extra={"present": set_keys, "absent": [k for k, v in keys.items() if not v]},
    )


def _compiler_check(
    name: str, exe_candidates: list[str], version_args: list[str], category: str, fix_hint: str
) -> Check:
    for cand in exe_candidates:
        if _which(cand):
            rc, out, _ = _try([cand, *version_args])
            if rc == 0:
                return Check(name, category, ACTIVE, detail=out.splitlines()[0][:120])
    return Check(name, category, UNAVAIL, detail=f"none of {exe_candidates} on PATH", fix=fix_hint)


def check_rust() -> Check:
    rc, out, _ = _try(["rustc", "--version"])
    if rc != 0:
        return Check(
            "rust_toolchain",
            "compilers",
            UNAVAIL,
            detail="rustc not on PATH",
            fix="install Rust via https://rustup.rs/",
        )
    rc2, cargo, _ = _try(["cargo", "--version"])
    if rc2 != 0:
        return Check(
            "rust_toolchain",
            "compilers",
            PARTIAL,
            detail=f"rustc={out} but cargo missing",
            fix="cargo should come with rustup; rerun rustup-init",
        )
    return Check("rust_toolchain", "compilers", ACTIVE, detail=f"{out} / {cargo}")


def check_go() -> Check:
    rc, out, _ = _try(["go", "version"])
    if rc != 0:
        return Check(
            "go_toolchain",
            "compilers",
            UNAVAIL,
            detail="go not on PATH",
            fix="install Go from https://go.dev/",
        )
    return Check("go_toolchain", "compilers", ACTIVE, detail=out)


def check_c() -> Check:
    return _compiler_check(
        "c_compiler",
        ["cc", "gcc", "clang"],
        ["--version"],
        "compilers",
        "install gcc, clang, or MSVC",
    )


def check_cpp() -> Check:
    return _compiler_check(
        "cpp_compiler",
        ["c++", "g++", "clang++"],
        ["--version"],
        "compilers",
        "install g++, clang++, or MSVC",
    )


def check_node() -> Check:
    rc, out, _ = _try(["node", "--version"])
    if rc != 0:
        return Check(
            "node",
            "compilers",
            UNAVAIL,
            detail="node not on PATH",
            fix="install Node.js LTS from https://nodejs.org/",
        )
    return Check("node", "compilers", ACTIVE, detail=f"node {out}")


def check_java() -> Check:
    rc1, _, jerr = _try(["java", "-version"])
    rc2, _, _ = _try(["javac", "-version"])
    if rc1 != 0:
        return Check(
            "java",
            "compilers",
            UNAVAIL,
            detail="java not on PATH",
            fix="install a JDK (Adoptium Temurin recommended)",
        )
    line = (jerr.splitlines() or [""])[0][:120]
    if rc2 != 0:
        return Check(
            "java",
            "compilers",
            PARTIAL,
            detail=f"{line} (JRE only — javac missing)",
            fix="install a full JDK",
        )
    return Check("java", "compilers", ACTIVE, detail=line)


def check_determinex_models_dir() -> Check:
    s = _get_settings()
    p = (
        s.models_dir
        if s is not None
        else Path(os.environ.get("DETERMINEX_MODELS_DIR", "T:/determinex-models"))
    )
    if not p.is_dir():
        return Check(
            "determinex_models_dir",
            "models",
            UNAVAIL,
            detail=f"{p} not found",
            fix="set DETERMINEX_MODELS_DIR env var to your models dir",
        )
    ggufs = list(p.glob("*.gguf"))
    return Check(
        "determinex_models_dir",
        "models",
        ACTIVE,
        detail=f"{p}  ({len(ggufs)} *.gguf files)",
        extra={"path": str(p), "n_ggufs": len(ggufs)},
    )


def check_rosetta_v1_pt() -> Check:
    s = _get_settings()
    models_dir = (
        s.models_dir
        if s is not None
        else Path(os.environ.get("DETERMINEX_MODELS_DIR", "T:/determinex-models"))
    )
    candidates = [
        Path.home() / ".determinex" / "rosetta" / "rosetta_v1.pt",
        models_dir / "rosetta_v1.pt",
        REPO_ROOT / "rosetta" / "rosetta_v1.pt",
    ]
    found = next((p for p in candidates if p.is_file()), None)
    if found is None:
        return Check(
            "rosetta_v1_pt",
            "models",
            UNAVAIL,
            detail="rosetta_v1.pt not found",
            fix="train via rosetta/train_rosetta.py or fetch from registry",
            extra={"checked": [str(p) for p in candidates]},
        )
    return Check(
        "rosetta_v1_pt",
        "models",
        ACTIVE,
        detail=f"found at {found}",
        extra={"path": str(found), "size": found.stat().st_size},
    )


def check_gpu() -> Check:
    rc, out, _ = _try(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
        timeout=5.0,
    )
    if rc == 0 and out:
        first = out.splitlines()[0]
        return Check("gpu", "hardware", ACTIVE, detail=first)
    # torch fallback
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            free, total = torch.cuda.mem_get_info()
            return Check(
                "gpu",
                "hardware",
                ACTIVE,
                detail=f"{name}  vram={free / 1e9:.1f}/{total / 1e9:.1f} GB free",
                extra={
                    "name": name,
                    "free_gb": round(free / 1e9, 2),
                    "total_gb": round(total / 1e9, 2),
                },
            )
    except ImportError:
        pass
    return Check(
        "gpu",
        "hardware",
        UNAVAIL,
        detail="no NVIDIA GPU detected (or driver missing)",
        fix="install NVIDIA driver + CUDA runtime; CPU-only mode works but slower",
    )


def check_disk_space() -> Check:
    # Probe both POSIX (Git Bash) and Windows-style paths so the same code
    # works under MSYS, Git Bash, and native Windows Python.
    drives_info = []
    for posix_path, win_path in (("/c/", "C:/"), ("/t/", "T:/")):
        for variant in (posix_path, win_path):
            try:
                if not Path(variant).exists():
                    continue
                usage = shutil.disk_usage(variant)
                drives_info.append(
                    {
                        "drive": variant.rstrip("/"),
                        "free_gb": round(usage.free / 1e9, 1),
                        "total_gb": round(usage.total / 1e9, 1),
                    }
                )
                break  # one variant per drive is enough
            except OSError:
                continue
    if not drives_info:
        return Check(
            "disk_space",
            "hardware",
            UNAVAIL,
            detail="no recognized data drives found",
            fix="ensure C: and/or T: are mounted",
        )
    detail = "  ".join(
        f"{d['drive']}: {d['free_gb']:.0f}/{d['total_gb']:.0f}GB free" for d in drives_info
    )
    # Warn if any drive has <50GB free (ProgramBench + SWE-bench images need it)
    tight = any(d["free_gb"] < 50 for d in drives_info)
    return Check(
        "disk_space",
        "hardware",
        PARTIAL if tight else ACTIVE,
        detail=detail + ("  ⚠️ <50GB free" if tight else ""),
        extra={"drives": drives_info},
        fix="free at least 50GB on the data drive for docker images" if tight else "",
    )


def check_cpu_count() -> Check:
    n = os.cpu_count() or 0
    if n == 0:
        return Check("cpu_count", "hardware", UNAVAIL, detail="cpu_count unknown", fix="")
    return Check("cpu_count", "hardware", ACTIVE, detail=f"{n} logical CPUs", extra={"count": n})


def check_huggingface_cache() -> Check:
    s = _get_settings()
    candidates = [
        s.hf_home if s is not None else None,
        Path(os.environ.get("HF_HOME", "")) if os.environ.get("HF_HOME") else None,
        Path("T:/huggingface_cache"),
        Path.home() / ".cache" / "huggingface",
    ]
    candidates = [c for c in candidates if c is not None]
    found = next((c for c in candidates if c.is_dir()), None)
    if found is None:
        return Check(
            "huggingface_cache",
            "data",
            UNAVAIL,
            detail="no HF cache dir found",
            fix="set HF_HOME or run any `huggingface-cli download`",
            extra={"checked": [str(c) for c in candidates]},
        )
    return Check("huggingface_cache", "data", ACTIVE, detail=str(found))


def check_programbench_dir() -> Check:
    s = _get_settings()
    p = (
        s.programbench_dir
        if s is not None
        else Path(os.environ.get("PROGRAMBENCH_DIR", "T:/Dev/ProgramBench"))
    )
    if not (p / "src" / "programbench").is_dir():
        return Check(
            "programbench_dir",
            "data",
            UNAVAIL,
            detail=f"{p} doesn't look like a programbench checkout",
            fix="clone https://github.com/programbench/programbench and set PROGRAMBENCH_DIR",
        )
    return Check("programbench_dir", "data", ACTIVE, detail=str(p))


def check_pre_cloned_tasks() -> Check:
    s = _get_settings()
    p = (
        s.pb_tasks_root
        if s is not None
        else Path(os.environ.get("DETERMINEX_PB_TASKS_ROOT", "T:/determinex-programbench"))
    )
    if not p.is_dir():
        return Check(
            "pre_cloned_tasks",
            "data",
            UNAVAIL,
            detail=f"{p} not found",
            fix="optional — speeds up first runs by ~4-6 min per tool",
        )
    subs = [s for s in p.iterdir() if s.is_dir()]
    return Check(
        "pre_cloned_tasks",
        "data",
        ACTIVE,
        detail=f"{p}  ({len(subs)} task dirs)",
        extra={"count": len(subs)},
    )


def check_ledger() -> Check:
    db = REPO_ROOT / "logs" / "determinex_ledger.db"
    if not db.is_file():
        return Check(
            "ledger",
            "cockpit",
            UNAVAIL,
            detail="no ledger yet (fresh install or empty cache)",
            fix="run any eval — the cockpit will populate it automatically",
        )
    return Check(
        "ledger",
        "cockpit",
        ACTIVE,
        detail=str(db),
        extra={"size_kb": round(db.stat().st_size / 1024, 1)},
    )


# ---------------------------------------------------------------------------
# Security & Observability checks
# ---------------------------------------------------------------------------


def check_settings_spine() -> Check:
    """Verify determinex_settings.py is importable and safety defaults are closed."""
    _old_path = sys.path[:]
    try:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from determinex_settings import DeterminexSettings

        s = DeterminexSettings()
        violations = s.assert_safety_defaults()
        summary = s.resolved_summary()
        if violations:
            return Check(
                "settings_spine",
                "security",
                PARTIAL,
                detail=f"importable but {len(violations)} safety flag(s) open: {violations[0]}",
                fix="review open safety flags before production use",
                extra={"violations": violations},
            )
        return Check(
            "settings_spine",
            "security",
            ACTIVE,
            detail=f"importable; all safety defaults closed; {len(summary)} settings resolved",
            extra={"n_settings": len(summary)},
        )
    except ImportError as e:
        return Check(
            "settings_spine",
            "security",
            UNAVAIL,
            detail=f"determinex_settings not importable: {e}",
            fix="ensure scripts/determinex_settings.py exists and scripts/ is on PYTHONPATH",
        )
    except Exception as e:
        return Check(
            "settings_spine",
            "security",
            UNAVAIL,
            detail=f"settings_spine error: {type(e).__name__}: {e}",
            fix="check scripts/determinex_settings.py",
        )
    finally:
        sys.path[:] = _old_path


#: The corpus HMAC key env var names, in the SAME precedence the settings spine declares
#: (`DeterminexSettings.hmac_key`, AliasChoices). Primary first.
#:
#: This check used to read `DETERMINEX_HMAC_KEY` and nothing else, while every actual consumer --
#: `determinex_safety._corpus_hmac_key`, `hive/workspace`, `corpus/corpus_manager` -- reads only
#: `DETERMINEX_CORPUS_HMAC_KEY`. So the diagnostic disagreed with the thing it diagnoses, in both
#: directions:
#:
#:   * Follow doctor's own fix and set DETERMINEX_HMAC_KEY -> doctor turns green, and corpus rows
#:     are STILL unsigned. `determinex_hive new-session` keeps warning "No
#:     DETERMINEX_CORPUS_HMAC_KEY set -- using session-ephemeral HMAC key" on the very next
#:     command. A resolved warning that isn't resolved is worse than the warning.
#:   * Set the name that actually works -> doctor reports it "not set".
#:
#: Measured 2026-07-31 by running `determinex doctor` and then `determinex_hive.py new-session`
#: back to back and reading the two messages. determinex_settings.py already carries a comment
#: about having had this precedence backwards once; this is the same fact stated in a third place,
#: which is why the names are listed once here and the messages are generated from them.
_HMAC_KEY_ENV_NAMES = ("DETERMINEX_CORPUS_HMAC_KEY", "DETERMINEX_HMAC_KEY")


#: What `determinex_safety._load_hmac_key` actually requires: `bytes.fromhex(raw)` must parse AND
#: yield at least this many bytes, or it silently falls back to an ephemeral key. 32 BYTES is 64
#: hex characters -- and this check used to compare `len(key) < 32` against the hex STRING, so a
#: 32-hex-char (16-byte) key was reported ACTIVE and then rejected by the signing code. Doctor's
#: verdict has to predict the consumer's behaviour or it is not a diagnostic.
_HMAC_KEY_MIN_BYTES = 32


def check_hmac_key() -> Check:
    """The corpus HMAC key must be set and usable; presence-only (never logs the value)."""
    primary, alias = _HMAC_KEY_ENV_NAMES
    found_name, key = "", ""
    for name in _HMAC_KEY_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            found_name, key = name, value
            break

    if not key:
        return Check(
            "hmac_key",
            "security",
            UNAVAIL,
            detail=f"{primary} not set — corpus rows will not be signed",
            fix=f"set {primary}=<64 hex chars> in .env "
            '(generate: python -c "import secrets; print(secrets.token_hex(32))")',
        )

    # The alias is honoured by the SETTINGS SPINE only. determinex_safety, hive/workspace and
    # corpus/corpus_manager each read the canonical name directly and consult no settings object,
    # so an alias-only configuration leaves rows signed with an ephemeral key. Reporting that as
    # ACTIVE is the exact overclaim this check existed to prevent.
    if found_name != primary:
        return Check(
            "hmac_key",
            "security",
            PARTIAL,
            detail=f"only {alias} is set — the signing code reads {primary}, so corpus rows "
            "are still signed with an ephemeral key",
            fix=f"rename it to {primary} in .env",
        )

    try:
        raw = bytes.fromhex(key)
    except ValueError:
        return Check(
            "hmac_key",
            "security",
            PARTIAL,
            detail=f"{primary} is not valid hex — the signing code will fall back to an "
            "ephemeral key",
            fix='regenerate with: python -c "import secrets; print(secrets.token_hex(32))"',
        )
    if len(raw) < _HMAC_KEY_MIN_BYTES:
        return Check(
            "hmac_key",
            "security",
            PARTIAL,
            detail=f"{primary} decodes to {len(raw)} bytes; the signing code requires "
            f"≥{_HMAC_KEY_MIN_BYTES} and falls back to an ephemeral key below that",
            fix='regenerate with: python -c "import secrets; print(secrets.token_hex(32))"',
        )
    return Check(
        "hmac_key",
        "security",
        ACTIVE,
        detail=f"{primary} set ({len(raw)} bytes)",
    )


def check_corpus_writable() -> Check:
    """Corpus output directories must be writable."""
    candidates = [
        REPO_ROOT / "corpus" / "programbench" / "training_corpus",
        REPO_ROOT / "corpus",
    ]
    for p in candidates:
        if p.is_dir():
            test_file = p / ".doctor_write_probe"
            try:
                test_file.write_text("probe", encoding="utf-8")
                test_file.unlink()
                return Check(
                    "corpus_writable",
                    "security",
                    ACTIVE,
                    detail=f"corpus dir writable: {p}",
                    extra={"path": str(p)},
                )
            except OSError as e:
                return Check(
                    "corpus_writable",
                    "security",
                    UNAVAIL,
                    detail=f"corpus dir not writable: {p} — {e}",
                    fix="check directory permissions",
                )
    return Check(
        "corpus_writable",
        "security",
        UNAVAIL,
        detail="no corpus directory found under repo root",
        fix="create corpus/ directory or run any factory task",
    )


def check_workspace_guard() -> Check:
    """Verify hive.workspace.assert_inside_workspace is importable (escape guard active)."""
    _old_path = sys.path[:]
    try:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from hive.workspace import assert_inside_workspace  # noqa: F401

        return Check(
            "workspace_guard",
            "security",
            ACTIVE,
            detail="hive.workspace.assert_inside_workspace importable — escape guard active",
        )
    except ImportError as e:
        return Check(
            "workspace_guard",
            "security",
            UNAVAIL,
            detail=f"hive.workspace not importable: {e}",
            fix="ensure scripts/ is on PYTHONPATH and hive/workspace.py exists",
        )
    finally:
        sys.path[:] = _old_path


def check_event_log_dir() -> Check:
    """Event log directory (DETERMINEX_AUDIT_DIR or T:/determinex_audit/events) must be writable."""
    s = _get_settings()
    primary = (
        s.audit_dir
        if s is not None
        else Path(os.environ.get("DETERMINEX_AUDIT_DIR", "T:/determinex_audit/events"))
    )
    fallback = REPO_ROOT / "logs" / "events"

    for candidate in (primary, fallback):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        test_file = candidate / ".doctor_write_probe"
        try:
            test_file.write_text("probe", encoding="utf-8")
            test_file.unlink()
            # Count existing event log files
            n_logs = len(list(candidate.glob("*.jsonl")))
            return Check(
                "event_log_dir",
                "security",
                ACTIVE,
                detail=f"writable: {candidate}  ({n_logs} daily log(s))",
                extra={"path": str(candidate), "n_logs": n_logs},
            )
        except OSError:
            continue

    return Check(
        "event_log_dir",
        "security",
        UNAVAIL,
        detail="no writable event log directory found",
        fix="set DETERMINEX_AUDIT_DIR to a writable path in .env",
    )


def check_schema_registry() -> Check:
    """Verify corpus schema registry is importable and functional."""
    _old_path = sys.path[:]
    try:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from corpus.schema_registry import CURRENT_VERSION, get_registry

        registry = get_registry()
        registry.validate_version(CURRENT_VERSION)
        history = registry.version_history()
        return Check(
            "schema_registry",
            "security",
            ACTIVE,
            detail=f"current={CURRENT_VERSION}  history={history}",
            extra={"current_version": CURRENT_VERSION, "history": history},
        )
    except ImportError as e:
        return Check(
            "schema_registry",
            "security",
            UNAVAIL,
            detail=f"corpus.schema_registry not importable: {e}",
            fix="ensure scripts/ is on PYTHONPATH",
        )
    except Exception as e:
        return Check(
            "schema_registry",
            "security",
            UNAVAIL,
            detail=f"schema registry error: {type(e).__name__}: {e}",
            fix="check scripts/corpus/schema_registry.py",
        )
    finally:
        sys.path[:] = _old_path


# ---------------------------------------------------------------------------
# Demo-mode verdict
# ---------------------------------------------------------------------------


def deterministic_demo_verdict(checks: list[Check]) -> dict:
    """Can Determinex produce a useful first impression on this machine WITHOUT
    cloud API keys, WITHOUT Ollama models, and WITHOUT Docker?

    Yes iff: python_version ACTIVE + bash ACTIVE + ledger reachable (or
    creatable) + the read-only cockpit pieces (no network, no models needed).
    """
    by = {c.name: c for c in checks}
    can_demo = (
        by["python_version"].status == ACTIVE
        and by["bash"].status == ACTIVE
        and by["git"].status == ACTIVE
    )
    missing_for_full = [
        c.name
        for c in checks
        if c.status == UNAVAIL and c.category in ("ai", "compilers", "models")
    ]
    return {
        "can_run_demo_without_models": can_demo,
        "can_run_local_inference": by["ollama"].status == ACTIVE,
        "can_run_cloud_inference": by["api_keys"].status == ACTIVE,
        "can_run_full_benchmarks": (
            by["docker_daemon"].status == ACTIVE and by["programbench_dir"].status == ACTIVE
        ),
        "missing_for_full_capability": missing_for_full,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_python_version,
    check_git,
    check_docker,
    check_bash,
    check_ollama,
    check_api_keys,
    check_rust,
    check_go,
    check_c,
    check_cpp,
    check_node,
    check_java,
    check_determinex_models_dir,
    check_rosetta_v1_pt,
    check_gpu,
    check_disk_space,
    check_cpu_count,
    check_huggingface_cache,
    check_programbench_dir,
    check_pre_cloned_tasks,
    check_ledger,
    check_settings_spine,
    check_hmac_key,
    check_corpus_writable,
    check_workspace_guard,
    check_event_log_dir,
    check_schema_registry,
]


def run_all() -> list[Check]:
    out: list[Check] = []
    for fn in ALL_CHECKS:
        try:
            t0 = time.time()
            r = fn()
            r.extra.setdefault("elapsed_ms", int(1000 * (time.time() - t0)))
        except Exception as e:
            r = Check(
                fn.__name__, "core", UNAVAIL, detail=f"check crashed: {type(e).__name__}: {e}"
            )
        out.append(r)
    return out


def render_table(checks: list[Check]) -> str:
    by_cat: dict[str, list[Check]] = {}
    for c in checks:
        by_cat.setdefault(c.category, []).append(c)
    lines = []
    cat_order = ["core", "ai", "compilers", "models", "hardware", "data", "cockpit", "security"]
    for cat in cat_order:
        if cat not in by_cat:
            continue
        lines.append(f"\n== {cat.upper()} ==")
        for c in by_cat[cat]:
            marker = {ACTIVE: "✓", UNAVAIL: "✗", PARTIAL: "~", DESIGN_ONLY: "∅"}.get(c.status, "?")
            detail = c.detail[:90]
            lines.append(f"  {marker} {c.name:<26} {c.status:<24} {detail}")
            if c.status != ACTIVE and c.fix:
                lines.append(f"      → fix: {c.fix}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex first-run setup detector")
    ap.add_argument("--json", type=Path, default=None, help="write a JSON report to this path")
    ap.add_argument(
        "--strict", action="store_true", help="exit nonzero if any check is UNAVAILABLE"
    )
    args = ap.parse_args()

    checks = run_all()
    demo = deterministic_demo_verdict(checks)

    print(render_table(checks))
    print()
    print("== DEMO MODE ==")
    print(
        f"  can run demo without models / API keys: "
        f"{'YES' if demo['can_run_demo_without_models'] else 'no'}"
    )
    print(
        f"  can run local inference (Ollama):       "
        f"{'YES' if demo['can_run_local_inference'] else 'no'}"
    )
    print(
        f"  can run cloud inference (API key):      "
        f"{'YES' if demo['can_run_cloud_inference'] else 'no'}"
    )
    print(
        f"  can run full benchmarks (Docker + PB):  "
        f"{'YES' if demo['can_run_full_benchmarks'] else 'no'}"
    )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": time.time(),
            "checks": [c.to_dict() for c in checks],
            "demo_verdict": demo,
            "summary": {
                "active": sum(1 for c in checks if c.status == ACTIVE),
                "partial": sum(1 for c in checks if c.status == PARTIAL),
                "unavailable": sum(1 for c in checks if c.status == UNAVAIL),
                "total": len(checks),
            },
        }
        args.json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {args.json}")

    if args.strict:
        return 0 if all(c.status == ACTIVE for c in checks) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
