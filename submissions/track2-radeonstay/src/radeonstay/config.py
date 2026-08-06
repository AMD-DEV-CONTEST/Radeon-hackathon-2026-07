from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_AUDIT_SECRET = "development-only-change-before-demo"
DEFAULT_IDENTITY_SECRET = "development-identity-change-before-demo"
EXAMPLE_AUDIT_SECRET = "replace-with-a-random-local-secret"
EXAMPLE_IDENTITY_SECRET = "replace-with-a-different-random-local-secret"
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_DEMO_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$")
_REQUEST_CONFIGURATION_FIELDS = frozenset(
    {"thinking_enabled", "schema_constrained", "fused_plan_evidence"}
)
LOCAL_INFERENCE_PROVIDER = "local_llamacpp"
RADEON_CLOUD_FREE_PROVIDER = "radeon_cloud_free"
SUPPORTED_INFERENCE_PROVIDERS = frozenset(
    {LOCAL_INFERENCE_PROVIDER, RADEON_CLOUD_FREE_PROVIDER}
)
DEFAULT_RADEON_CLOUD_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
DEFAULT_RADEON_CLOUD_MODEL = "Qwen3.6-35B-A3B"


def normalize_request_configuration(value: object) -> dict[str, bool]:
    """Validate the complete app-side model-request optimization profile."""

    if not isinstance(value, dict) or set(value) != _REQUEST_CONFIGURATION_FIELDS:
        raise ValueError("Request configuration fields are incomplete")
    if any(type(value[field]) is not bool for field in _REQUEST_CONFIGURATION_FIELDS):
        raise ValueError("Request configuration values must be booleans")
    if value["schema_constrained"] is not True:
        raise ValueError("Competition requests must use schema-constrained generation")
    return {
        "thinking_enabled": value["thinking_enabled"],
        "schema_constrained": value["schema_constrained"],
        "fused_plan_evidence": value["fused_plan_evidence"],
    }


def request_configuration_sha256(value: object) -> str:
    """Hash the canonical request profile used by runtime/release binding."""

    normalized = normalize_request_configuration(value)
    canonical = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be an explicit boolean value")


def load_env_file(path: Path, *, override: bool = False) -> None:
    """Load a small KEY=VALUE .env file without adding a runtime dependency."""
    if path.is_symlink():
        raise ValueError(f"Refusing to load a symbolic-link .env file: {path}")
    if not path.exists():
        return
    if not path.is_file():
        raise ValueError(f"Environment path must be a regular file: {path}")
    path.chmod(PRIVATE_FILE_MODE)
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid .env entry at {path}:{line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
            raise ValueError(f"Invalid .env key at {path}:{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or name not in os.environ:
            os.environ[name] = value


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    model_base_url: str
    model_name: str
    model_api_key: str = field(repr=False)
    model_timeout_seconds: float
    database_path: Path
    policy_dir: Path
    audit_secret: str = field(repr=False)
    identity_secret: str = field(repr=False)
    deterministic_mode: bool
    host: str
    port: int
    public_demo_enabled: bool
    ui_username: str
    ui_password: str = field(repr=False)
    model_enable_thinking: bool = False
    fused_plan_evidence: bool = False
    runtime_proof_path: Path | None = None
    runtime_instance_path: Path | None = None
    isolated_demo: bool = False
    demo_run_id: str | None = None
    evidence_run_id: str | None = None
    inference_provider: str = LOCAL_INFERENCE_PROVIDER
    radeon_cloud_base_url: str = DEFAULT_RADEON_CLOUD_BASE_URL
    radeon_cloud_model: str = DEFAULT_RADEON_CLOUD_MODEL
    radeon_cloud_api_key: str = field(default="", repr=False)
    radeon_cloud_structured_mode: str = "auto"
    bonus_demo: bool = False

    @property
    def uses_radeon_cloud_free(self) -> bool:
        return self.inference_provider == RADEON_CLOUD_FREE_PROVIDER

    @property
    def local_only(self) -> bool:
        return not self.uses_radeon_cloud_free

    @property
    def runtime_proof_required(self) -> bool:
        """Competition-isolated demos must bind readiness to local ROCm evidence."""

        return self.isolated_demo

    @property
    def runtime_instance_required(self) -> bool:
        """Competition-isolated demos must bind calls to one llama-server process."""

        return self.isolated_demo

    @property
    def request_configuration(self) -> dict[str, bool]:
        """Return the complete request-side optimization profile."""

        return {
            "thinking_enabled": self.model_enable_thinking,
            "schema_constrained": True,
            "fused_plan_evidence": self.fused_plan_evidence,
        }

    @property
    def request_configuration_sha256(self) -> str:
        return request_configuration_sha256(self.request_configuration)

    @property
    def uses_in_memory_database(self) -> bool:
        """Recognize only SQLite's exact non-filesystem sentinel."""

        return str(self.database_path) == ":memory:"

    @property
    def isolated_database_run_bound(self) -> bool:
        """Require the isolated database filename to end in its exact run ID."""

        if not self.isolated_demo:
            return True
        if self.demo_run_id is None or self.uses_in_memory_database:
            return False
        suffix = self.database_path.suffix or ".db"
        return self.database_path.name.endswith(f"-{self.demo_run_id}{suffix}")

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        database = Path(os.getenv("RADEONSTAY_DATABASE_PATH", "runtime/radeonstay.db"))
        policies = Path(os.getenv("RADEONSTAY_POLICY_DIR", "data/policies"))
        runtime_proof = os.getenv("RADEONSTAY_RUNTIME_PROOF_PATH", "").strip()
        runtime_proof_path = Path(runtime_proof) if runtime_proof else None
        runtime_instance = os.getenv(
            "RADEONSTAY_RUNTIME_INSTANCE_PATH",
            "",
        ).strip()
        runtime_instance_path = Path(runtime_instance) if runtime_instance else None
        isolated_demo = _env_bool("RADEONSTAY_ISOLATED_DEMO")
        demo_run_id = os.getenv("RADEONSTAY_DEMO_RUN_ID", "").strip() or None
        evidence_run_id = (
            os.getenv("RADEONSTAY_EVIDENCE_RUN_ID", "").strip() or None
        )
        if demo_run_id is not None and _DEMO_RUN_ID_RE.fullmatch(demo_run_id) is None:
            raise ValueError("RADEONSTAY_DEMO_RUN_ID has an invalid format")
        if (
            evidence_run_id is not None
            and _DEMO_RUN_ID_RE.fullmatch(evidence_run_id) is None
        ):
            raise ValueError("RADEONSTAY_EVIDENCE_RUN_ID has an invalid format")
        if isolated_demo and demo_run_id is not None:
            suffix = database.suffix or ".db"
            database = database.with_name(
                f"{database.stem}-{demo_run_id}{suffix}"
            )
        return cls(
            project_root=root,
            model_base_url=os.getenv(
                "RADEONSTAY_MODEL_BASE_URL", "http://127.0.0.1:8000/v1"
            ).rstrip("/"),
            model_name=os.getenv(
                "RADEONSTAY_MODEL_NAME", "qwen3.6-35b-a3b-q6k"
            ),
            model_api_key=os.getenv("RADEONSTAY_MODEL_API_KEY", "local-only"),
            model_timeout_seconds=float(
                os.getenv("RADEONSTAY_MODEL_TIMEOUT_SECONDS", "120")
            ),
            database_path=(
                Path(":memory:")
                if str(database) == ":memory:"
                else Path(
                    os.path.abspath(
                        database if database.is_absolute() else root / database
                    )
                )
            ),
            # Preserve the lexical path until the retrieval boundary verifies
            # that no path component is a symbolic link.
            policy_dir=Path(
                os.path.abspath(policies if policies.is_absolute() else root / policies)
            ),
            audit_secret=os.getenv(
                "RADEONSTAY_AUDIT_SECRET", DEFAULT_AUDIT_SECRET
            ),
            identity_secret=os.getenv(
                "RADEONSTAY_IDENTITY_SECRET", DEFAULT_IDENTITY_SECRET
            ),
            deterministic_mode=_env_bool("RADEONSTAY_DETERMINISTIC_MODE"),
            host=os.getenv("RADEONSTAY_HOST", "127.0.0.1"),
            port=int(os.getenv("RADEONSTAY_PORT", "7860")),
            public_demo_enabled=_env_bool("RADEONSTAY_PUBLIC_DEMO_ENABLED"),
            ui_username=os.getenv("RADEONSTAY_UI_USERNAME", ""),
            ui_password=os.getenv("RADEONSTAY_UI_PASSWORD", ""),
            model_enable_thinking=_env_bool("RADEONSTAY_MODEL_ENABLE_THINKING"),
            fused_plan_evidence=_env_bool(
                "RADEONSTAY_FUSED_PLAN_EVIDENCE",
                default=True,
            ),
            runtime_proof_path=(
                Path(
                    os.path.abspath(
                        runtime_proof_path
                        if runtime_proof_path.is_absolute()
                        else root / runtime_proof_path
                    )
                )
                if runtime_proof_path is not None
                else None
            ),
            runtime_instance_path=(
                Path(
                    os.path.abspath(
                        runtime_instance_path
                        if runtime_instance_path.is_absolute()
                        else root / runtime_instance_path
                    )
                )
                if runtime_instance_path is not None
                else None
            ),
            isolated_demo=isolated_demo,
            demo_run_id=demo_run_id,
            evidence_run_id=evidence_run_id,
            inference_provider=os.getenv(
                "RADEONSTAY_INFERENCE_PROVIDER",
                LOCAL_INFERENCE_PROVIDER,
            ).strip(),
            radeon_cloud_base_url=os.getenv(
                "RADEONSTAY_RADEON_CLOUD_BASE_URL",
                DEFAULT_RADEON_CLOUD_BASE_URL,
            ).rstrip("/"),
            radeon_cloud_model=os.getenv(
                "RADEONSTAY_RADEON_CLOUD_MODEL",
                DEFAULT_RADEON_CLOUD_MODEL,
            ).strip(),
            radeon_cloud_api_key=os.getenv(
                "RADEONSTAY_RADEON_CLOUD_API_KEY",
                "",
            ).strip(),
            radeon_cloud_structured_mode=os.getenv(
                "RADEONSTAY_RADEON_CLOUD_STRUCTURED_MODE",
                "auto",
            ).strip(),
            bonus_demo=_env_bool("RADEONSTAY_BONUS_DEMO"),
        )

    def validate_radeon_cloud_endpoint(self) -> None:
        parsed = urlparse(self.radeon_cloud_base_url)
        if parsed.scheme != "https":
            raise ValueError("Radeon Cloud Model API must use https")
        if parsed.username or parsed.password:
            raise ValueError("Radeon Cloud Model API URL must not embed credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("Radeon Cloud Model API URL must not contain query or fragment")
        if (parsed.hostname or "").lower() != "developer.amd.com.cn":
            raise ValueError("Radeon Cloud Model API host is not allow-listed")
        if parsed.port not in {None, 443}:
            raise ValueError("Radeon Cloud Model API must use the default HTTPS port")
        if parsed.path != "/radeon/api/v1":
            raise ValueError("Radeon Cloud Model API path is not allow-listed")
        if self.radeon_cloud_model != DEFAULT_RADEON_CLOUD_MODEL:
            raise ValueError(
                "Public Free bonus mode requires the pinned Qwen3.6-35B-A3B model"
            )
        if self.radeon_cloud_structured_mode not in {
            "auto",
            "json_schema",
            "json_object",
            "prompt_json",
        }:
            raise ValueError(
                "RADEONSTAY_RADEON_CLOUD_STRUCTURED_MODE has an invalid value"
            )
        placeholders = {
            "",
            "<api_key>",
            "replace-me",
            "replace-with-api-key",
        }
        if (
            self.radeon_cloud_api_key.casefold() in placeholders
            or len(self.radeon_cloud_api_key) < 16
        ):
            raise ValueError(
                "RADEONSTAY_RADEON_CLOUD_API_KEY must contain a private API key"
            )

    def validate_private_model_endpoint(self) -> None:
        parsed = urlparse(self.model_base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("The model endpoint must use http or https")
        if parsed.username or parsed.password:
            raise ValueError("The model endpoint must not embed credentials in its URL")
        if parsed.query or parsed.fragment:
            raise ValueError("The model endpoint must not contain a query or fragment")
        hostname = (parsed.hostname or "").lower()
        allowed = {
            "127.0.0.1",
            "localhost",
            "::1",
            "host.docker.internal",
        }
        if hostname not in allowed:
            raise ValueError(
                "The model endpoint must be local/private for the competition path. "
                f"Received host: {hostname!r}"
            )

    def validate_runtime_security(self) -> None:
        if self.inference_provider not in SUPPORTED_INFERENCE_PROVIDERS:
            raise ValueError(
                "RADEONSTAY_INFERENCE_PROVIDER must be local_llamacpp or "
                "radeon_cloud_free"
            )
        if self.uses_radeon_cloud_free:
            self.validate_radeon_cloud_endpoint()
            if not self.bonus_demo:
                raise ValueError(
                    "radeon_cloud_free requires RADEONSTAY_BONUS_DEMO=1"
                )
            if self.deterministic_mode:
                raise ValueError(
                    "Radeon Cloud bonus mode forbids deterministic fallback"
                )
            if self.isolated_demo:
                raise ValueError(
                    "Radeon Cloud bonus mode cannot claim local isolated-demo proof"
                )
            if self.runtime_proof_path is not None or self.runtime_instance_path is not None:
                raise ValueError(
                    "Radeon Cloud bonus mode must not load local ROCm runtime proof"
                )
        else:
            self.validate_private_model_endpoint()
            if self.bonus_demo:
                raise ValueError(
                    "RADEONSTAY_BONUS_DEMO=1 requires radeon_cloud_free"
                )
        if not math.isfinite(self.model_timeout_seconds) or self.model_timeout_seconds <= 0:
            raise ValueError("Model timeout must be positive")
        if not self.host.strip():
            raise ValueError("Application host must not be empty")
        if not 1 <= self.port <= 65_535:
            raise ValueError("Application port must be between 1 and 65535")
        if any(
            len(secret.encode("utf-8")) < 32
            for secret in (self.audit_secret, self.identity_secret)
        ):
            raise ValueError("Audit and identity secrets must each contain at least 32 bytes")
        if hmac_compare(self.audit_secret, self.identity_secret):
            raise ValueError("Audit and identity secrets must be different")
        known_placeholders = {
            DEFAULT_AUDIT_SECRET,
            DEFAULT_IDENTITY_SECRET,
            EXAMPLE_AUDIT_SECRET,
            EXAMPLE_IDENTITY_SECRET,
        }
        if any(
            hmac_compare(secret, placeholder)
            for secret in (self.audit_secret, self.identity_secret)
            for placeholder in known_placeholders
        ):
            raise ValueError(
                "Replace the default/example audit and identity secrets before starting "
                "RadeonStay"
            )
        if self.demo_run_id is not None and _DEMO_RUN_ID_RE.fullmatch(
            self.demo_run_id
        ) is None:
            raise ValueError("RADEONSTAY_DEMO_RUN_ID has an invalid format")
        if self.isolated_demo:
            if self.deterministic_mode:
                raise ValueError(
                    "Isolated competition demo mode forbids deterministic fallback"
                )
            if self.demo_run_id is None:
                raise ValueError(
                    "RADEONSTAY_ISOLATED_DEMO=1 requires a unique "
                    "RADEONSTAY_DEMO_RUN_ID"
                )
            if self.runtime_instance_path is None:
                raise ValueError(
                    "RADEONSTAY_ISOLATED_DEMO=1 requires "
                    "RADEONSTAY_RUNTIME_INSTANCE_PATH"
                )
            if not self.isolated_database_run_bound:
                raise ValueError(
                    "Isolated demo database filename must bind the exact demo run ID"
                )
        public_bind = self.host not in {"127.0.0.1", "localhost", "::1"}
        if public_bind and not self.public_demo_enabled:
            raise ValueError(
                "Non-loopback binding requires RADEONSTAY_PUBLIC_DEMO_ENABLED=1"
            )
        public_access = public_bind or self.public_demo_enabled
        if public_access and (
            len(self.ui_username) < 4 or len(self.ui_password) < 12
        ):
            raise ValueError(
                "Public demo access requires a UI username and 12+ character password"
            )

    def ensure_runtime_dirs(self) -> None:
        if self.uses_in_memory_database:
            return
        if self.isolated_demo and not self.isolated_database_run_bound:
            raise ValueError(
                "Isolated demo database filename must bind the exact demo run ID"
            )
        runtime_dir = self.database_path.parent
        try:
            runtime_metadata = runtime_dir.lstat()
        except FileNotFoundError:
            runtime_metadata = None
        if runtime_metadata is not None:
            if stat.S_ISLNK(runtime_metadata.st_mode):
                raise ValueError("Runtime directory must not be a symbolic link")
            if not stat.S_ISDIR(runtime_metadata.st_mode):
                raise ValueError("Runtime directory must be a directory")
            if runtime_metadata.st_uid != os.geteuid():
                raise ValueError("Runtime directory must be owned by the current user")
            existing_mode = stat.S_IMODE(runtime_metadata.st_mode)
            if existing_mode != PRIVATE_DIRECTORY_MODE:
                raise ValueError(
                    "Existing runtime directory must already use mode 0700; "
                    "choose a dedicated directory or fix its permissions"
                )
        else:
            runtime_dir.mkdir(
                mode=PRIVATE_DIRECTORY_MODE,
                parents=True,
                exist_ok=False,
            )
            runtime_dir.chmod(PRIVATE_DIRECTORY_MODE)

        existing_artifacts: dict[Path, os.stat_result] = {}
        for path in self.database_related_paths():
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"Runtime database artifact must not be a symlink: {path}")
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(
                    f"Runtime database artifact must be a regular file: {path}"
                )
            if metadata.st_uid != os.geteuid():
                raise ValueError(
                    f"Runtime database artifact must be owned by the current user: {path}"
                )
            if (
                self.isolated_demo
                and stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE
            ):
                raise ValueError(
                    f"Existing isolated database artifact must use mode 0600: {path}"
                )
            existing_artifacts[path] = metadata

        primary_metadata = existing_artifacts.get(self.database_path)
        if self.isolated_demo and primary_metadata is None and existing_artifacts:
            raise ValueError(
                "Refusing orphaned isolated SQLite sidecars without the run-bound database"
            )
        if self.isolated_demo and primary_metadata is not None:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                descriptor = os.open(self.database_path, flags)
            except OSError as exc:
                raise ValueError(
                    "Existing isolated database could not be opened safely"
                ) from exc
            try:
                opened_metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened_metadata.st_mode)
                    or opened_metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(opened_metadata.st_mode) != PRIVATE_FILE_MODE
                    or opened_metadata.st_dev != primary_metadata.st_dev
                    or opened_metadata.st_ino != primary_metadata.st_ino
                ):
                    raise ValueError(
                        "Existing isolated database changed during secure reopen"
                    )
            finally:
                os.close(descriptor)
            return

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if self.isolated_demo:
            flags |= os.O_EXCL
        try:
            descriptor = os.open(self.database_path, flags, PRIVATE_FILE_MODE)
        except FileExistsError as exc:
            raise ValueError(
                "Isolated database appeared during exclusive creation; stop and inspect "
                "this deployment run"
            ) from exc
        try:
            opened_metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_metadata.st_mode)
                or opened_metadata.st_uid != os.geteuid()
            ):
                raise ValueError(
                    "Runtime database must be a regular file owned by the current user"
                )
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        finally:
            os.close(descriptor)

    def database_related_paths(self) -> tuple[Path, ...]:
        if self.uses_in_memory_database:
            return ()
        base = str(self.database_path)
        return tuple(
            Path(f"{base}{suffix}")
            for suffix in ("", "-wal", "-shm", "-journal")
        )

    def secure_runtime_files(self) -> None:
        """Keep SQLite data and sidecars private after SQLite creates them."""
        if self.uses_in_memory_database:
            return
        if not self.database_path.exists():
            raise ValueError("Runtime database file does not exist")
        for path in self.database_related_paths():
            if path.is_symlink():
                raise ValueError(
                    f"Runtime database artifact must not be a symlink: {path}"
                )
            if not path.exists():
                continue
            if not path.is_file():
                raise ValueError(f"Runtime database artifact must be a regular file: {path}")
            path.chmod(PRIVATE_FILE_MODE)

    def runtime_security_report(self) -> dict[str, object]:
        """Return a bounded, path-free startup permission preflight."""
        if self.uses_in_memory_database:
            return {
                "ok": True,
                "storage": "memory",
                "directory": {"ok": True, "required": False, "mode": None},
                "primary_database": {"ok": True, "kind": "memory"},
                "database_files": [],
            }
        runtime_dir = self.database_path.parent
        try:
            directory_metadata = runtime_dir.lstat()
        except FileNotFoundError:
            directory_metadata = None
        directory_mode = (
            stat.S_IMODE(directory_metadata.st_mode)
            if directory_metadata is not None
            else None
        )
        files: list[dict[str, object]] = []
        primary_database_ok = False
        for path in self.database_related_paths():
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                files.append({"name": path.name, "ok": False, "mode": None})
                continue
            mode = stat.S_IMODE(metadata.st_mode)
            file_ok = (
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_uid == os.geteuid()
                and mode == PRIVATE_FILE_MODE
            )
            if path == self.database_path:
                primary_database_ok = file_ok
            files.append(
                {
                    "name": path.name,
                    "ok": file_ok,
                    "mode": f"{mode:04o}",
                }
            )
        directory_ok = (
            directory_metadata is not None
            and stat.S_ISDIR(directory_metadata.st_mode)
            and not stat.S_ISLNK(directory_metadata.st_mode)
            and directory_metadata.st_uid == os.geteuid()
            and directory_mode == PRIVATE_DIRECTORY_MODE
        )
        return {
            "ok": bool(
                directory_ok
                and primary_database_ok
                and all(bool(item["ok"]) for item in files)
            ),
            "directory": {
                "ok": directory_ok,
                "mode": f"{directory_mode:04o}" if directory_mode is not None else None,
            },
            "primary_database": {"ok": primary_database_ok},
            "database_files": files,
        }


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
