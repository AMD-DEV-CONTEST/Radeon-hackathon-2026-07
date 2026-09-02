"""scripts/determinex_settings.py — Determinex central configuration spine.

Single source of truth for every path, flag, and tunable that was previously
scattered across 80+ scripts as naked ``os.environ.get()`` calls.

Usage::

    from determinex_settings import get_settings
    s = get_settings()
    print(s.audit_dir)          # resolved Path, may be T:/ or local fallback
    print(s.safety_mode)        # "strict" by default
    print(s.resolved_summary()) # dict of all resolved values (for doctor output)

Environment variable rules
--------------------------
Every value is sourced **only** from environment variables (or a hard default).
No Windows drive letter is *required* for correctness — every T:/ default has a
portable local fallback used automatically when the drive is absent and the env
var is not set.

Safe defaults
-------------
All security and isolation flags fail **closed**:
  - online_discovery = False
  - allow_cloud_fallback = False
  - allow_unsandboxed = False
  - require_docker = True
  - require_cloak = True
  - offline_observer = True
  - safety_mode = "strict"

These can be opened only by explicit env-var assignment.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_core import PydanticUseDefault
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


_warned_dead_overrides: set[str] = set()


def _warn_dead_override(env_var: str, p: Path) -> None:
    """Say once, on stderr, that an env-var path override does not exist.

    Deduplicated per variable: these properties are read repeatedly (the settings
    object is a cached singleton but individual properties re-resolve), and a
    warning repeated fifty times per run trains people to ignore it.
    """
    if env_var in _warned_dead_overrides:
        return
    _warned_dead_overrides.add(env_var)
    print(
        f"[determinex_settings] WARNING: {env_var}={p} does not exist. "
        f"Every consumer of this setting will see an empty/missing directory. "
        f"Fix the value in .env or unset it to use the built-in default.",
        file=sys.stderr,
    )


def _resolve_path(
    env_var: str,
    t_default: str,
    local_fallback: str | Path | None = None,
) -> Path:
    """Resolve a path with portability-safe fallback.

    Priority:
      1. Env var (authoritative)
      2. t_default — used as-is when its drive exists OR no local_fallback
      3. local_fallback — when the t_default drive is absent and fallback provided

    This ensures that no T:/ (or any other drive letter) is *required* for
    correctness when a local fallback is available.
    """
    raw = os.environ.get(env_var, "").strip()
    if raw:
        p = Path(raw)
        # An env override that points at nothing is returned anyway -- an operator
        # may legitimately be naming a directory that does not exist yet, and
        # silently redirecting them somewhere else would be worse. But it must not
        # be SILENT: the override short-circuits before the local_fallback branch
        # below, so a stale value defeats this function's own documented promise
        # that "no T:/ is required for correctness when a local fallback is
        # available" and hands every consumer an empty directory instead.
        #
        # Found live 2026-07-28: .env carried DETERMINEX_CORPUS_ROOT=T:/citadel_corpus
        # from before the rename. T:/determinex_corpus exists and is populated,
        # T:/citadel_corpus does not exist at all, and every reader of
        # settings.corpus_root was quietly pointed at the dead path. This is the
        # same split-brain that corpus_wiring_census.py records as "healed
        # 2026-07-18" -- healed in the data, but not in the pointer.
        if not p.exists():
            _warn_dead_override(env_var, p)
        return p

    t_path = Path(t_default)

    if local_fallback is not None:
        # Check whether the drive root for the T-path is accessible.
        drive = t_path.drive  # e.g. "T:" on Windows, "" on POSIX
        if drive:
            drive_root = Path(drive + "/")
            if not drive_root.exists():
                return (
                    _REPO_ROOT / local_fallback
                    if not Path(str(local_fallback)).is_absolute()
                    else Path(str(local_fallback))
                )

    return t_path


# ---------------------------------------------------------------------------
# Settings class
# ---------------------------------------------------------------------------


class DeterminexSettings(BaseSettings):
    """Centralized Determinex configuration resolved from environment variables.

    Instantiate via :func:`get_settings` to get the cached singleton.
    Direct instantiation is fine for tests (pass env overrides before calling).

    Scalar settings (safety flags, model IDs, API keys, budget/context tuning)
    are real pydantic-settings fields, populated and type-validated once at
    construction time -- this is where the "naked os.environ.get() scattered
    across 80+ scripts" problem this module's docstring describes actually
    lived. Path settings keep the pre-existing @property + _resolve_path()
    pattern: their drive-portability fallback (does T:/ exist? no -> use a
    relative local path instead) is genuine business logic pydantic's env
    loading doesn't model, not a naked-env-read case, and changing that
    pattern would break test_audit_dir_local_fallback_when_drive_absent's
    monkeypatch of the module-level _resolve_path function.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    # Only bool/int/float fields need this -- pydantic's native coercion
    # rejects "" for those types (the old _env_bool/_env_int/_env_float
    # fell back to the default instead). str fields don't need it ("" is
    # already a valid str), which matters here: a wildcard "*" validator
    # combined with any AliasChoices-aliased field below causes genuine
    # infinite recursion inside pydantic-settings' alias resolution
    # (reproduced in isolation, not a fluke) -- scoping to only the
    # non-string field names sidesteps that entirely.
    _EMPTY_STRING_FALLBACK_FIELDS = (
        "online_discovery",
        "allow_cloud_fallback",
        "allow_unsandboxed",
        "require_docker",
        "require_cloak",
        "offline_observer",
        "flywheel_auto",
        "cloak_enabled",
        "cloak_audit",
        "budget_usd",
        "budget_calls",
        "budget_per_task",
        "max_retries",
        "observer_timeout",
        "test_timeout",
        "rosetta_layer2",
        "no_rosetta",
    )

    @field_validator(*_EMPTY_STRING_FALLBACK_FIELDS, mode="before")
    @classmethod
    def _empty_string_uses_default(cls, v):
        if v == "":
            raise PydanticUseDefault()
        return v

    # ------------------------------------------------------------------
    # Safety flags — all fail CLOSED
    # ------------------------------------------------------------------

    safety_mode: str = Field(default="strict", validation_alias="DETERMINEX_SAFETY_MODE")
    online_discovery: bool = Field(default=False, validation_alias="DETERMINEX_ONLINE_DISCOVERY")
    allow_cloud_fallback: bool = Field(
        default=False, validation_alias="DETERMINEX_ALLOW_CLOUD_FALLBACK"
    )
    # 2026-07-26: finalized to DETERMINEX_* as part of the Citadel->Determinex rename.
    # The REAL enforcement point (hive/compiler.py's SEC-2 gate) must read the same
    # name this Field validates, or assert_safety_defaults() below could report "no
    # violations" while the compiler was actually running unsandboxed -- keep these two
    # in sync.
    allow_unsandboxed: bool = Field(default=False, validation_alias="DETERMINEX_ALLOW_UNSANDBOXED")
    require_docker: bool = Field(default=True, validation_alias="DETERMINEX_REQUIRE_DOCKER")
    require_cloak: bool = Field(default=True, validation_alias="DETERMINEX_REQUIRE_CLOAK")
    offline_observer: bool = Field(default=True, validation_alias="DETERMINEX_OFFLINE_OBSERVER")
    flywheel_auto: bool = Field(default=False, validation_alias="DETERMINEX_FLYWHEEL_AUTO")
    cloak_enabled: bool = Field(default=False, validation_alias="DETERMINEX_CLOAK")
    cloak_audit: bool = Field(default=False, validation_alias="DETERMINEX_CLOAK_AUDIT")

    # ------------------------------------------------------------------
    # Model identifiers
    # ------------------------------------------------------------------

    builder_model: str = Field(
        default="determinex-engineer-v11-dsl", validation_alias="DETERMINEX_BUILDER_MODEL"
    )
    observer_model: str = Field(
        default="determinex-observer-v6-dsl", validation_alias="DETERMINEX_OBSERVER_MODEL"
    )
    architect_model: str = Field(
        default="determinex-sentinel-v5-dsl", validation_alias="DETERMINEX_ARCHITECT_MODEL"
    )
    deepseek_model: str = Field(
        default="deepseek-chat", validation_alias="DETERMINEX_DEEPSEEK_MODEL"
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-6", validation_alias="DETERMINEX_ANTHROPIC_MODEL"
    )
    ollama_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("DETERMINEX_OLLAMA_URL", "OLLAMA_HOST"),
    )
    vllm_url: str = Field(
        default="http://localhost:8000/v1", validation_alias="DETERMINEX_VLLM_URL"
    )
    vllm_model: str = Field(
        default="Qwen/Qwen2.5-Coder-7B-Instruct", validation_alias="DETERMINEX_VLLM_MODEL"
    )
    inference_backend: str = Field(
        default="ollama", validation_alias="DETERMINEX_INFERENCE_BACKEND"
    )

    # ------------------------------------------------------------------
    # API keys — no defaults; callers must handle empty string
    # ------------------------------------------------------------------

    anthropic_api_key: str = Field(
        default="", validation_alias=AliasChoices("ANTHROPIC_API_KEY", "DETERMINEX_ANTHROPIC_KEY")
    )
    deepseek_api_key: str = Field(
        default="", validation_alias=AliasChoices("DETERMINEX_DEEPSEEK_KEY", "DEEPSEEK_API_KEY")
    )
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openai_api_key: str = Field(
        default="", validation_alias=AliasChoices("DETERMINEX_OPENAI_KEY", "OPENAI_API_KEY")
    )
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("DETERMINEX_GEMINI_KEY", "GEMINI_API_KEY")
    )
    # HMAC signing key for corpus rows. The real signing code (determinex_safety.py,
    # corpus/corpus_manager.py) reads DETERMINEX_CORPUS_HMAC_KEY -- this used to check
    # DETERMINEX_HMAC_KEY/DETERMINEX_CORPUS_HMAC_KEY first, names nothing else honors,
    # so DETERMINEX_CORPUS_HMAC_KEY must be the primary alias, not the fallback.
    hmac_key: str = Field(
        default="",
        validation_alias=AliasChoices("DETERMINEX_CORPUS_HMAC_KEY", "DETERMINEX_HMAC_KEY"),
    )

    # ------------------------------------------------------------------
    # Budget / rate limits
    # ------------------------------------------------------------------

    budget_usd: float = Field(default=2.50, validation_alias="DETERMINEX_BUDGET_USD")
    budget_calls: int = Field(default=200, validation_alias="DETERMINEX_BUDGET_CALLS")
    budget_per_task: float = Field(default=6.0, validation_alias="DETERMINEX_BUDGET_PER_TASK")

    # ------------------------------------------------------------------
    # Context / inference tuning
    # ------------------------------------------------------------------

    max_retries: int = Field(default=5, validation_alias="DETERMINEX_MAX_RETRIES")
    observer_timeout: int = Field(default=7200, validation_alias="DETERMINEX_OBSERVER_TIMEOUT")
    test_timeout: int = Field(default=60, validation_alias="DETERMINEX_TEST_TIMEOUT")
    rosetta_layer2: bool = Field(default=False, validation_alias="DETERMINEX_ROSETTA_LAYER2")
    no_rosetta: bool = Field(default=False, validation_alias="DETERMINEX_NO_ROSETTA")

    # ------------------------------------------------------------------
    # Core paths
    # ------------------------------------------------------------------

    @property
    def repo_root(self) -> Path:
        return _resolve_path("DETERMINEX_ROOT", str(_REPO_ROOT))

    @property
    def models_dir(self) -> Path:
        return _resolve_path(
            "DETERMINEX_MODELS_DIR",
            "T:/determinex-models",
            local_fallback="data/models",
        )

    @property
    def audit_dir(self) -> Path:
        return _resolve_path(
            "DETERMINEX_AUDIT_DIR",
            "T:/determinex_audit/events",
            local_fallback="logs/events",
        )

    @property
    def corpus_root(self) -> Path:
        return _resolve_path(
            "DETERMINEX_CORPUS_ROOT",
            "T:/determinex_corpus",
            local_fallback="corpus",
        )

    @property
    def swebench_repos(self) -> Path:
        return _resolve_path(
            "DETERMINEX_SWEBENCH_REPOS",
            "T:/determinex-swebench",
        )

    @property
    def programbench_dir(self) -> Path:
        """The ProgramBench evaluation harness root (uv run programbench eval …)."""
        return _resolve_path(
            "PROGRAMBENCH_DIR",
            "T:/Dev/ProgramBench",
        )

    @property
    def pb_tasks_root(self) -> Path:
        """Determinex's per-tool ProgramBench build/eval output directory."""
        return _resolve_path(
            "DETERMINEX_PB_TASKS_ROOT",
            "T:/determinex-programbench",
        )

    @property
    def pb_staging_root(self) -> Path:
        return _resolve_path(
            "DETERMINEX_PB_STAGING_ROOT",
            "T:/determinex-staging",
            local_fallback="data/pb_staging",
        )

    @property
    def rosetta_pt_path(self) -> Path:
        return _resolve_path(
            "DETERMINEX_ROSETTA_PT_PATH",
            "T:/determinex-models/rosetta_v1.pt",
        )

    @property
    def hf_home(self) -> Path:
        return _resolve_path(
            "HF_HOME",
            "T:/huggingface_cache",
            local_fallback=str(Path.home() / ".cache" / "huggingface"),
        )

    @property
    def artifact_quarantine(self) -> Path:
        return _resolve_path(
            "DETERMINEX_QUARANTINE_DIR",
            "T:/determinex_artifacts/quarantine",
            local_fallback="data/quarantine",
        )

    @property
    def artifact_cache(self) -> Path:
        return _resolve_path(
            "DETERMINEX_ARTIFACT_CACHE",
            "T:/determinex_artifacts/cache",
            local_fallback="data/artifact_cache",
        )

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def resolved_summary(self) -> dict[str, object]:
        """Return a flat dict of all resolved values — used by determinex doctor."""
        return {
            # paths
            "repo_root": str(self.repo_root),
            "models_dir": str(self.models_dir),
            "audit_dir": str(self.audit_dir),
            "corpus_root": str(self.corpus_root),
            "swebench_repos": str(self.swebench_repos),
            "programbench_dir": str(self.programbench_dir),
            "pb_tasks_root": str(self.pb_tasks_root),
            "pb_staging_root": str(self.pb_staging_root),
            "rosetta_pt_path": str(self.rosetta_pt_path),
            "hf_home": str(self.hf_home),
            "artifact_quarantine": str(self.artifact_quarantine),
            "artifact_cache": str(self.artifact_cache),
            # safety
            "safety_mode": self.safety_mode,
            "online_discovery": self.online_discovery,
            "allow_cloud_fallback": self.allow_cloud_fallback,
            "allow_unsandboxed": self.allow_unsandboxed,
            "require_docker": self.require_docker,
            "require_cloak": self.require_cloak,
            "offline_observer": self.offline_observer,
            "flywheel_auto": self.flywheel_auto,
            "cloak_enabled": self.cloak_enabled,
            # models
            "builder_model": self.builder_model,
            "observer_model": self.observer_model,
            "architect_model": self.architect_model,
            "ollama_url": self.ollama_url,
            "inference_backend": self.inference_backend,
            # api keys (masked)
            "anthropic_api_key": "***" if self.anthropic_api_key else "(unset)",
            "deepseek_api_key": "***" if self.deepseek_api_key else "(unset)",
            "openrouter_api_key": "***" if self.openrouter_api_key else "(unset)",
            "openai_api_key": "***" if self.openai_api_key else "(unset)",
            "hmac_key": f"***({len(self.hmac_key)} chars)" if self.hmac_key else "(unset)",
        }

    def check_path_availability(self) -> dict[str, bool]:
        """Return which paths currently exist on disk (for doctor pass/warn/fail)."""
        return {
            "repo_root": self.repo_root.exists(),
            "models_dir": self.models_dir.exists(),
            "audit_dir": self.audit_dir.exists(),
            "corpus_root": self.corpus_root.exists(),
            "swebench_repos": self.swebench_repos.exists(),
            "programbench_dir": self.programbench_dir.exists(),
            "pb_tasks_root": self.pb_tasks_root.exists(),
            "pb_staging_root": self.pb_staging_root.exists(),
            "rosetta_pt_path": self.rosetta_pt_path.exists(),
            "hf_home": self.hf_home.exists(),
        }

    def assert_safety_defaults(self) -> list[str]:
        """Return a list of safety violation strings (empty = all closed).

        Call this in any script that should verify it is running in a safe
        configuration before touching corpus or evidence artifacts.
        """
        violations: list[str] = []
        if self.online_discovery:
            violations.append(
                "DETERMINEX_ONLINE_DISCOVERY=1 (unsafe: online artifact discovery enabled)"
            )
        if self.allow_cloud_fallback:
            violations.append("DETERMINEX_ALLOW_CLOUD_FALLBACK=1 (unsafe: cloud fallback enabled)")
        if self.allow_unsandboxed:
            violations.append(
                "DETERMINEX_ALLOW_UNSANDBOXED=1 (unsafe: unsandboxed execution enabled)"
            )
        return violations


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: DeterminexSettings | None = None
_lock = threading.Lock()


def get_settings() -> DeterminexSettings:
    """Return the process-wide settings singleton (created on first call)."""
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = DeterminexSettings()
    return _singleton


def reset_settings() -> None:
    """Reset the singleton — intended for tests only."""
    global _singleton
    with _lock:
        _singleton = None


# Module-level convenience alias (import and use directly)
settings = DeterminexSettings()


# ---------------------------------------------------------------------------
# CLI: python -m scripts.determinex_settings  (or python scripts/determinex_settings.py)
# ---------------------------------------------------------------------------


def _main() -> int:
    s = get_settings()
    summary = s.resolved_summary()
    availability = s.check_path_availability()
    violations = s.assert_safety_defaults()

    print("Determinex Settings — resolved configuration\n")
    width = max(len(k) for k in summary) + 2
    for key, val in summary.items():
        exists = availability.get(key)
        tag = ""
        if exists is True:
            tag = "  [exists]"
        elif exists is False:
            tag = "  [missing]"
        print(f"  {key:<{width}} {val}{tag}")

    if violations:
        print("\nSafety violations:")
        for v in violations:
            print(f"  !! {v}")
    else:
        print("\n  Safety defaults: all closed (OK)")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(_main())
