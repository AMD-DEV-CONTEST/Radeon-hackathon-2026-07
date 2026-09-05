from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ...exceptions import ValidationError
from .execution import OpenSshClient
from .worker_settings import (
    MLWorkerConfig,
    MLWorkerSetupState,
    MLWorkerValidationStatus,
    generate_worker_id,
    validation_record,
)

SSH_CONFIG_BEGIN = "# BEGIN XENIX MANAGED HOST {alias}"
SSH_CONFIG_END = "# END XENIX MANAGED HOST {alias}"

REQUIRED_REMOTE_IMPORTS = [
    "pandas",
    "openpyxl",
    "joblib",
    "sklearn",
    "xgboost",
    "lightgbm",
    "mlxtend",
    "apyori",
]

REMOTE_PIP_PACKAGES = [
    "pandas",
    "openpyxl",
    "joblib",
    "scikit-learn",
    "xgboost",
    "lightgbm",
    "mlxtend",
    "apyori",
]


@dataclass(frozen=True)
class SshWorkerSetupInput:
    display_name: str
    host: str
    user: str = ""
    port: int = 22
    identity_file_path: str = ""
    ssh_alias: str = ""
    remote_root: str = "~/.xenix/workers/default"
    python_command: str = "python3"
    write_ssh_config: bool = True
    install_dependencies: bool = True
    ssh_config_path: Path | None = None


@dataclass(frozen=True)
class SshWorkerSetupResult:
    worker: MLWorkerConfig
    details: list[str]


class SshWorkerSetupService:
    def __init__(
        self,
        *,
        ssh_command: str = "ssh",
        scp_command: str = "scp",
    ) -> None:
        self._ssh_command = ssh_command
        self._scp_command = scp_command

    def build_worker(self, input_data: SshWorkerSetupInput) -> MLWorkerConfig:
        requested_alias = input_data.ssh_alias.strip()
        if input_data.write_ssh_config:
            ssh_alias = requested_alias or generate_worker_id()
            if not ssh_alias.startswith("xenix."):
                ssh_alias = f"xenix.{ssh_alias}"
            worker_id = ssh_alias
        else:
            ssh_alias = requested_alias
            worker_id = ssh_alias if ssh_alias.startswith("xenix.") else generate_worker_id()
        return MLWorkerConfig(
            id=worker_id,
            display_name=input_data.display_name.strip() or worker_id,
            kind="ssh",
            host=input_data.host.strip(),
            user=input_data.user.strip(),
            port=input_data.port,
            ssh_alias=ssh_alias,
            identity_file_path=str(Path(input_data.identity_file_path).expanduser()) if input_data.identity_file_path else "",
            remote_root=input_data.remote_root.strip() or f"~/.xenix/workers/{worker_id}",
            python_command=input_data.python_command.strip() or "python3",
        )

    def setup(self, input_data: SshWorkerSetupInput) -> SshWorkerSetupResult:
        worker = self.build_worker(input_data)
        details: list[str] = []
        if input_data.write_ssh_config:
            self.write_ssh_config(worker, input_data.ssh_config_path)
            details.append(f"Wrote OpenSSH config for {worker.ssh_alias}.")
        self._require_local_command(self._ssh_command)
        self._require_local_command(self._scp_command)
        details.append("OpenSSH commands are available.")
        client = OpenSshClient(worker, ssh_command=self._ssh_command, scp_command=self._scp_command)
        self._run_checked(client, "true", "SSH connection", details)
        self._run_checked(client, f"{_sh_quote(worker.python_command)} - <<'PY'\nimport sys\nraise SystemExit(0 if sys.version_info >= (3, 12) else 1)\nPY", "Python 3.12+", details)
        worker = worker.model_copy(update={"remote_root": self._resolve_remote_root(client, worker)})
        self._run_checked(client, f"mkdir -p {_sh_quote(worker.remote_root)}", "Remote root", details)
        python_command = worker.python_command
        if input_data.install_dependencies:
            venv_python = f"{worker.remote_root.rstrip('/')}/venv/bin/python"
            self._run_checked(
                client,
                f"{worker.python_command} -m venv {_sh_quote(worker.remote_root.rstrip('/') + '/venv')}",
                "Remote virtual environment",
                details,
            )
            self._run_checked(
                client,
                f"{_sh_quote(venv_python)} -m pip install --upgrade pip {' '.join(REMOTE_PIP_PACKAGES)}",
                "Remote ML dependencies",
                details,
            )
            python_command = venv_python
            worker = worker.model_copy(update={"python_command": python_command})
        imports = "; ".join(f"import {module}" for module in REQUIRED_REMOTE_IMPORTS)
        self._run_checked(client, f"{_sh_quote(python_command)} - <<'PY'\n{imports}\nPY", "Remote imports", details)
        smoke_name = ".xenix-upload-download-smoke.txt"
        with tempfile.TemporaryDirectory(prefix="xenix-ssh-smoke-") as temp_dir:
            local_smoke = Path(temp_dir) / smoke_name
            local_smoke.write_text("xenix smoke\n", encoding="utf-8")
            remote_smoke = f"{worker.remote_root.rstrip('/')}/{smoke_name}"
            client.upload(local_smoke, remote_smoke)
            downloaded = Path(temp_dir) / ".xenix-upload-download-smoke.downloaded.txt"
            client.download(remote_smoke, downloaded)
            if downloaded.read_text(encoding="utf-8") != "xenix smoke\n":
                raise ValidationError("Upload/download smoke content did not match.")
        details.append("Upload/download smoke succeeded.")
        worker = worker.model_copy(
            update={
                "setup_state": MLWorkerSetupState.READY,
                "last_validation": validation_record(
                    MLWorkerValidationStatus.SUCCEEDED,
                    "SSH worker setup completed.",
                    details,
                ),
            }
        )
        return SshWorkerSetupResult(worker=worker, details=details)

    def validate(self, worker: MLWorkerConfig) -> MLWorkerConfig:
        details: list[str] = []
        try:
            self._require_local_command(self._ssh_command)
            self._require_local_command(self._scp_command)
            client = OpenSshClient(worker, ssh_command=self._ssh_command, scp_command=self._scp_command)
            self._run_checked(client, "true", "SSH connection", details)
            worker = worker.model_copy(update={"remote_root": self._resolve_remote_root(client, worker)})
            self._run_checked(client, f"test -w {_sh_quote(worker.remote_root)}", "Remote root writable", details)
            imports = "; ".join(f"import {module}" for module in REQUIRED_REMOTE_IMPORTS)
            self._run_checked(client, f"{_sh_quote(worker.python_command)} - <<'PY'\n{imports}\nPY", "Remote imports", details)
        except Exception as exc:
            return worker.model_copy(
                update={
                    "setup_state": MLWorkerSetupState.FAILED,
                    "last_validation": validation_record(
                        MLWorkerValidationStatus.FAILED,
                        str(exc),
                        details,
                    ),
                }
            )
        return worker.model_copy(
            update={
                "setup_state": MLWorkerSetupState.READY,
                "last_validation": validation_record(
                    MLWorkerValidationStatus.SUCCEEDED,
                    "SSH worker validation completed.",
                    details,
                ),
            }
        )

    def write_ssh_config(self, worker: MLWorkerConfig, config_path: Path | None = None) -> Path:
        path = config_path or Path.home() / ".ssh" / "config"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing:
            backup_path = path.with_suffix(path.suffix + ".xenix.bak")
            backup_path.write_text(existing, encoding="utf-8")
        block = self._ssh_config_block(worker)
        path.write_text(_replace_managed_block(existing, worker.ssh_alias, block), encoding="utf-8")
        return path

    def _ssh_config_block(self, worker: MLWorkerConfig) -> str:
        if not worker.ssh_alias.startswith("xenix."):
            raise ValidationError("Xenix-managed SSH aliases must start with 'xenix.'.")
        if not worker.host:
            raise ValidationError("Writing an Xenix-managed SSH config block requires a host.")
        lines = [
            SSH_CONFIG_BEGIN.format(alias=worker.ssh_alias),
            f"Host {worker.ssh_alias}",
            f"    HostName {worker.host}",
        ]
        if worker.user:
            lines.append(f"    User {worker.user}")
        lines.append(f"    Port {worker.port}")
        lines.append("    BatchMode yes")
        if worker.identity_file_path:
            lines.append(f"    IdentityFile {worker.identity_file_path}")
        lines.append(SSH_CONFIG_END.format(alias=worker.ssh_alias))
        return "\n".join(lines)

    def _require_local_command(self, command: str) -> None:
        if shutil.which(command) is None:
            raise ValidationError(f"Required command '{command}' was not found.")

    def _run_checked(
        self,
        client: OpenSshClient,
        command: str,
        label: str,
        details: list[str],
    ) -> None:
        result = client.run(command, check=False)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise ValidationError(f"{label} failed: {detail}")
        details.append(f"{label} succeeded.")

    def _resolve_remote_root(self, client: OpenSshClient, worker: MLWorkerConfig) -> str:
        remote_root = worker.remote_root.strip()
        if not remote_root.startswith("~"):
            return remote_root
        result = client.run(
            f"{_sh_quote(worker.python_command)} - <<'PY'\n"
            "from pathlib import Path\n"
            f"print(Path({remote_root!r}).expanduser().as_posix())\n"
            "PY",
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[-1]
        raise ValidationError("Unable to resolve the remote root path.")


def _replace_managed_block(existing: str, alias: str, block: str) -> str:
    begin = SSH_CONFIG_BEGIN.format(alias=alias)
    end = SSH_CONFIG_END.format(alias=alias)
    lines = existing.splitlines()
    output: list[str] = []
    index = 0
    replaced = False
    while index < len(lines):
        if lines[index].strip() == begin:
            output.extend(block.splitlines())
            replaced = True
            index += 1
            while index < len(lines) and lines[index].strip() != end:
                index += 1
            if index < len(lines):
                index += 1
            continue
        output.append(lines[index])
        index += 1
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.extend(block.splitlines())
    return "\n".join(output).rstrip() + "\n"


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
