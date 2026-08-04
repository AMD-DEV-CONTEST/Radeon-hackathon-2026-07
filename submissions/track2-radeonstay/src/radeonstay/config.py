from __future__ import annotations

import hmac
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_AUDIT_SECRET = "development-only-change-before-demo"
DEFAULT_IDENTITY_SECRET = "development-identity-change-before-demo"
EXAMPLE_AUDIT_SECRET = "replace-with-a-random-local-secret"
EXAMPLE_IDENTITY_SECRET = "replace-with-a-different-random-local-secret"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_env_file(path: Path, *, override: bool = False) -> None:
    """Load a small KEY=VALUE .env file without adding a runtime dependency."""
    if not path.is_file():
        return
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

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        database = Path(os.getenv("RADEONSTAY_DATABASE_PATH", "runtime/radeonstay.db"))
        policies = Path(os.getenv("RADEONSTAY_POLICY_DIR", "data/policies"))
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
            database_path=(database if database.is_absolute() else root / database).resolve(),
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
        self.validate_private_model_endpoint()
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
        public_bind = self.host not in {"127.0.0.1", "localhost", "::1"}
        if public_bind:
            if not self.public_demo_enabled:
                raise ValueError(
                    "Non-loopback binding requires RADEONSTAY_PUBLIC_DEMO_ENABLED=1"
                )
            if len(self.ui_username) < 4 or len(self.ui_password) < 12:
                raise ValueError(
                    "Public demo binding requires a UI username and 12+ character password"
                )

    def ensure_runtime_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
