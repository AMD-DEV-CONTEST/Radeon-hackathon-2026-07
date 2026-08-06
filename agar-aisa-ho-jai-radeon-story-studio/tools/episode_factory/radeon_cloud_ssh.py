from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

try:
    from .radeon_cloud_execution import (
        canonical_json,
        inspect_cloud_package,
        read_json,
        sha256_file,
        verify_cloud_result,
        write_json,
    )
    from .radeon_cloud_session import RadeonCloudSession, load_session, save_session
except ImportError:
    from radeon_cloud_execution import (
        canonical_json,
        inspect_cloud_package,
        read_json,
        sha256_file,
        verify_cloud_result,
        write_json,
    )
    from radeon_cloud_session import RadeonCloudSession, load_session, save_session


SSH_CONNECTION_SCHEMA = "aahj.radeon-cloud-ssh-connection/v1"
SSH_EXECUTION_SCHEMA = "aahj.radeon-cloud-ssh-execution/v1"
SSH_TRANSFER_SCHEMA = "aahj.radeon-cloud-ssh-transfer/v1"
SSH_PROBE_SCHEMA = "aahj.radeon-cloud-ssh-probe/v1"
ATTACHED_RUN_SCHEMA = "aahj.radeon-cloud-attached-run/v1"

Runner = Callable[..., subprocess.CompletedProcess[Any]]


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _identity(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _required_token(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    text = value.strip()
    if any(ord(character) < 33 or ord(character) == 127 for character in text):
        raise ValueError(f"{name} contains unsafe characters")
    if text.startswith("-"):
        raise ValueError(f"{name} must not begin with '-'")
    pattern = r"[A-Za-z0-9._-]+" if name == "username" else r"[A-Za-z0-9.:[\]-]+"
    if re.fullmatch(pattern, text) is None:
        raise ValueError(f"{name} contains unsafe characters")
    return text


def _remote_path(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{name} contains unsafe characters")
    # Whitespace and backslashes make scp's remote-path grammar ambiguous.
    if any(character.isspace() for character in value) or "\\" in value:
        raise ValueError(f"{name} contains unsafe characters")
    if re.fullmatch(r"/[A-Za-z0-9._/-]+", value) is None:
        raise ValueError(f"{name} contains unsafe characters")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must be an absolute safe POSIX path")
    normalized = posixpath.normpath(value)
    if normalized == "/":
        raise ValueError(f"{name} must not be the filesystem root")
    return normalized


def quote_remote_argv(argv: Sequence[str]) -> str:
    """Render one caller-supplied argv for OpenSSH's remote POSIX shell."""
    if not argv or not all(isinstance(item, str) and "\x00" not in item for item in argv):
        raise ValueError("remote argv must be a non-empty sequence of strings")
    return shlex.join(list(argv))


def _validated_timeout(value: float | None) -> float | None:
    if value is not None and (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError("timeout must be greater than zero")
    return None if value is None else float(value)


@dataclass(frozen=True)
class SshWorkspaceConnection:
    host: str
    port: int
    username: str
    identity_file: str | Path
    workspace_root: str
    remote_repository: str
    strict_host_key_checking: bool = True
    schema_version: str = SSH_CONNECTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != SSH_CONNECTION_SCHEMA:
            raise ValueError(f"schema_version must be {SSH_CONNECTION_SCHEMA}")
        host = _required_token("host", self.host)
        if "[" in host or "]" in host:
            if not (host.startswith("[") and host.endswith("]") and "[" not in host[1:] and "]" not in host[:-1]):
                raise ValueError("host contains malformed IPv6 brackets")
            host = host[1:-1]
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "username", _required_token("username", self.username))
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("port must be in the range 1-65535")
        if not isinstance(self.strict_host_key_checking, bool):
            raise ValueError("strict_host_key_checking must be a boolean")
        if not isinstance(self.identity_file, (str, Path)) or not str(self.identity_file).strip():
            raise ValueError("identity_file is required")
        identity = Path(self.identity_file).expanduser().resolve()
        if not identity.is_file():
            raise ValueError(f"identity_file must be an existing regular file: {identity}")
        object.__setattr__(self, "identity_file", str(identity))
        object.__setattr__(self, "workspace_root", _remote_path("workspace_root", self.workspace_root))
        object.__setattr__(self, "remote_repository", _remote_path("remote_repository", self.remote_repository))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SshWorkspaceConnection":
        if not isinstance(value, Mapping):
            raise ValueError("SSH connection must be an object")
        connection = cls(
            schema_version=value.get("schema_version", ""),
            host=value.get("host"),
            port=value.get("port"),
            username=value.get("username"),
            identity_file=value.get("identity_file"),
            workspace_root=value.get("workspace_root"),
            remote_repository=value.get("remote_repository"),
            strict_host_key_checking=value.get("strict_host_key_checking", True),
        )
        declared_id = value.get("connection_id")
        if declared_id is not None and declared_id != connection.connection_id:
            raise ValueError("connection_id does not match SSH connection")
        return connection

    @classmethod
    def load(cls, path: Path) -> "SshWorkspaceConnection":
        return cls.from_mapping(read_json(path))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "identity_file": str(self.identity_file),
            "workspace_root": self.workspace_root,
            "remote_repository": self.remote_repository,
            "strict_host_key_checking": self.strict_host_key_checking,
        }

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())

    @classmethod
    def from_json(cls, value: str) -> "SshWorkspaceConnection":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid SSH connection JSON: {exc}") from exc
        return cls.from_mapping(payload)

    @property
    def connection_id(self) -> str:
        return _identity(self.as_dict())

    def save(self, path: Path) -> Path:
        return write_json(path, {**self.as_dict(), "connection_id": self.connection_id})

    @property
    def destination(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{self.username}@{host}"

    def ssh_options(self, executable: str = "ssh") -> tuple[str, ...]:
        port_flag = "-P" if Path(executable).name == "scp" else "-p"
        return (
            executable,
            port_flag,
            str(self.port),
            "-i",
            str(self.identity_file),
            "-o",
            "BatchMode=yes",
            "-o",
            f"StrictHostKeyChecking={'yes' if self.strict_host_key_checking else 'no'}",
        )

    def ssh_argv(self, remote_argv: Sequence[str]) -> tuple[str, ...]:
        return (*self.ssh_options("ssh"), "--", self.destination, quote_remote_argv(remote_argv))


@dataclass(frozen=True)
class SshExecutionEvidence:
    remote_argv: tuple[str, ...]
    local_argv: tuple[str, ...]
    outcome: str
    started_at: str
    finished_at: str
    return_code: int | None
    stdout: str
    stderr: str
    timeout_seconds: float | None
    schema_version: str = SSH_EXECUTION_SCHEMA

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded"

    def as_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "remote_argv": list(self.remote_argv),
            "local_ssh_argv": list(self.local_argv),
            "outcome": self.outcome,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timeout_seconds": self.timeout_seconds,
        }
        return {**value, "evidence_id": _identity(value)}


class SshCommandError(RuntimeError):
    def __init__(self, message: str, evidence: SshExecutionEvidence):
        super().__init__(message)
        self.evidence = evidence


@dataclass
class SshCommandExecutor:
    connection: SshWorkspaceConnection
    runner: Runner = subprocess.run

    def execute(
        self,
        remote_argv: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> SshExecutionEvidence:
        timeout = _validated_timeout(timeout)
        remote = tuple(remote_argv)
        local = self.connection.ssh_argv(remote)
        started = _utc_now()
        try:
            completed = self.runner(
                list(local),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return_code = completed.returncode
            if return_code == 0:
                outcome = "succeeded"
            elif return_code == 255:
                outcome = "connection-interrupted"
            elif return_code < 0:
                outcome = "local-ssh-failure"
            else:
                outcome = "remote-nonzero"
            stdout = _text(completed.stdout)
            stderr = _text(completed.stderr)
        except subprocess.TimeoutExpired as exc:
            return_code = None
            outcome = "timeout"
            stdout = _text(exc.stdout)
            stderr = _text(exc.stderr)
        except OSError as exc:
            return_code = None
            outcome = "local-ssh-failure"
            stdout = ""
            stderr = str(exc)
        return SshExecutionEvidence(
            remote_argv=remote,
            local_argv=local,
            outcome=outcome,
            started_at=started,
            finished_at=_utc_now(),
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            timeout_seconds=timeout,
        )

    def require(self, remote_argv: Sequence[str], *, timeout: float | None = None) -> SshExecutionEvidence:
        evidence = self.execute(remote_argv, timeout=timeout)
        if not evidence.succeeded:
            raise SshCommandError(f"SSH command failed ({evidence.outcome})", evidence)
        return evidence

    def remote_file_metadata(self, path: str) -> tuple[dict[str, Any], SshExecutionEvidence]:
        remote = _remote_path("remote file", path)
        script = "\n".join(
            (
                "import hashlib,json,pathlib,sys",
                "p=pathlib.Path(sys.argv[1])",
                "is_file=p.is_file()",
                "digest=None",
                "if is_file:",
                " h=hashlib.sha256()",
                " with p.open('rb') as stream:",
                "  for block in iter(lambda:stream.read(1048576),b''): h.update(block)",
                " digest=h.hexdigest()",
                "print(json.dumps({'exists':p.exists(),'is_file':is_file,'size_bytes':p.stat().st_size if is_file else None,'sha256':digest},sort_keys=True))",
            )
        )
        evidence = self.require(("python3", "-c", script, remote), timeout=120)
        try:
            value = json.loads(evidence.stdout)
        except json.JSONDecodeError as exc:
            raise SshCommandError("remote file metadata was not valid JSON", evidence) from exc
        return value, evidence

    def remote_sha256(self, path: str) -> tuple[str, SshExecutionEvidence]:
        value, evidence = self.remote_file_metadata(path)
        if not value.get("is_file"):
            raise SshCommandError(f"remote file is missing: {path}", evidence)
        return str(value["sha256"]), evidence

    def probe(self, *, include_runtime: bool = True) -> dict[str, Any]:
        root = self.connection.workspace_root
        repository = self.connection.remote_repository
        runner = posixpath.join(repository, "tools/episode_factory/radeon_cloud_runner.py")
        script = (
            "import getpass,json,os,pathlib,platform,shutil,sys,tempfile;"
            "w=pathlib.Path(sys.argv[1]);r=pathlib.Path(sys.argv[2]);q=pathlib.Path(sys.argv[3]);"
            "write=False;err=None;"
            "\ntry:\n f=tempfile.NamedTemporaryFile(prefix='.aahj-write-',dir=w,delete=False);f.close();os.unlink(f.name);write=True\nexcept Exception as e: err=str(e)\n"
            "u=shutil.disk_usage(w) if w.is_dir() else None;"
            "print(json.dumps({'remote_user':getpass.getuser(),'working_directory':os.getcwd(),"
            "'python_version':platform.python_version(),'workspace_exists':w.is_dir(),"
            "'workspace_writable':write,'workspace_write_error':err,'repository_exists':r.is_dir(),"
            "'runner_exists':q.is_file(),'free_disk_bytes':u.free if u else None,"
            "'dev_kfd':pathlib.Path('/dev/kfd').exists(),'dev_dri':pathlib.Path('/dev/dri').exists()},sort_keys=True))"
        )
        base = self.execute(("python3", "-c", script, root, repository, runner), timeout=30)
        details: dict[str, Any] = {}
        if base.succeeded:
            try:
                details = json.loads(base.stdout)
            except json.JSONDecodeError:
                details = {"probe_error": "base probe returned invalid JSON"}
        base_ready = bool(
            base.succeeded
            and details.get("workspace_exists")
            and details.get("workspace_writable")
            and details.get("repository_exists")
            and details.get("runner_exists")
        )
        runtime: dict[str, Any] = {"checked": include_runtime}
        if include_runtime and base.succeeded:
            rocminfo = self.execute(("rocminfo",), timeout=60)
            rocm_smi = self.execute(("rocm-smi",), timeout=60)
            normalized_rocminfo = rocminfo.stdout.lower()
            visible = rocminfo.succeeded and (
                "gfx" in normalized_rocminfo
                or ("amd" in normalized_rocminfo and "gpu" in normalized_rocminfo)
            )
            runtime.update(
                {
                    "rocminfo": rocminfo.as_dict(),
                    "rocm_smi": rocm_smi.as_dict(),
                    "rocm_smi_optional": True,
                    "radeon_visible": visible,
                    "ready": bool(rocminfo.succeeded and visible),
                }
            )
        else:
            runtime["ready"] = None
        value = {
            "schema_version": SSH_PROBE_SCHEMA,
            "connection_id": self.connection.connection_id,
            "base": details,
            "base_command": base.as_dict(),
            "base_ready": base_ready,
            "runtime": runtime,
            "production_ready": bool(base_ready and runtime.get("ready")) if include_runtime else base_ready,
        }
        return {**value, "probe_id": _identity(value)}


@dataclass(frozen=True)
class SshTransferReceipt:
    direction: str
    source: str
    destination: str
    sha256: str | None
    size_bytes: int | None
    transport: str
    verified: bool
    idempotent: bool = False
    resumed_from_bytes: int = 0
    transfer_argv: tuple[str, ...] = ()
    schema_version: str = SSH_TRANSFER_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "direction": self.direction,
            "source": self.source,
            "destination": self.destination,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "transport": self.transport,
            "verified": self.verified,
            "idempotent": self.idempotent,
            "resumed_from_bytes": self.resumed_from_bytes,
            "transfer_argv": list(self.transfer_argv),
        }
        return {**value, "receipt_id": _identity(value)}


class SshTransferError(RuntimeError):
    def __init__(self, message: str, *, evidence: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.evidence = dict(evidence or {})


@dataclass
class SshArtifactTransport:
    connection: SshWorkspaceConnection
    executor: SshCommandExecutor | None = None
    runner: Runner = subprocess.run
    which: Callable[[str], str | None] = shutil.which

    def __post_init__(self) -> None:
        if self.executor is None:
            self.executor = SshCommandExecutor(self.connection, runner=self.runner)

    @property
    def inbox(self) -> str:
        return posixpath.join(self.connection.workspace_root, "aahj-inbox")

    @property
    def results_root(self) -> str:
        return posixpath.join(self.connection.workspace_root, "aahj-results")

    def _run_transfer(self, argv: Sequence[str], *, timeout: float | None) -> subprocess.CompletedProcess[Any]:
        timeout = _validated_timeout(timeout)
        try:
            completed = self.runner(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise SshTransferError("artifact transfer timed out", evidence={"argv": list(argv), "stdout": _text(exc.stdout), "stderr": _text(exc.stderr)}) from exc
        except OSError as exc:
            raise SshTransferError("local artifact transfer process failed", evidence={"argv": list(argv), "error": str(exc)}) from exc
        if completed.returncode != 0:
            raise SshTransferError(
                f"artifact transfer exited with code {completed.returncode}",
                evidence={"argv": list(argv), "return_code": completed.returncode, "stdout": _text(completed.stdout), "stderr": _text(completed.stderr)},
            )
        return completed

    def _rsync_rsh(self) -> str:
        return shlex.join(list(self.connection.ssh_options("ssh")))

    def _use_rsync(self) -> bool:
        if not self.which("rsync"):
            return False
        assert self.executor is not None
        evidence = self.executor.execute(("rsync", "--version"), timeout=30)
        if evidence.succeeded:
            return True
        if evidence.outcome == "remote-nonzero":
            return False
        raise SshCommandError(
            f"could not determine remote rsync availability ({evidence.outcome})",
            evidence,
        )

    def _remote_spec(self, path: str) -> str:
        suffix = "/." if path.endswith("/.") else "/" if path.endswith("/") else ""
        base = path[:-2] if suffix == "/." else path[:-1] if suffix == "/" else path
        return f"{self.connection.destination}:{_remote_path('remote transfer path', base)}{suffix}"

    def stage_package(self, package_or_session: Path | RadeonCloudSession, package: Path | None = None, *, timeout: float | None = 3600) -> SshTransferReceipt:
        source = Path(package if package is not None else package_or_session).expanduser().resolve()
        summary = inspect_cloud_package(source)
        digest = sha256_file(source)
        size = source.stat().st_size
        final = posixpath.join(self.inbox, f"{summary['package_id']}.tar.gz")
        partial = final + ".partial"
        assert self.executor is not None
        self.executor.require(("mkdir", "-p", "--", self.inbox), timeout=30)
        existing, existing_evidence = self.executor.remote_file_metadata(final)
        if existing.get("exists"):
            if existing.get("is_file") and existing.get("size_bytes") == size and existing.get("sha256") == digest:
                return SshTransferReceipt("upload", str(source), final, digest, size, "existing", True, True, size)
            raise SshTransferError("conflicting remote package already exists", evidence=existing_evidence.as_dict())
        partial_before, _ = self.executor.remote_file_metadata(partial)
        resumed = int(partial_before.get("size_bytes") or 0) if partial_before.get("is_file") else 0
        partial_verified = bool(
            partial_before.get("is_file")
            and partial_before.get("size_bytes") == size
            and partial_before.get("sha256") == digest
        )
        if partial_before.get("is_file") and not partial_verified and resumed >= size:
            self.executor.require(("rm", "-f", "--", partial), timeout=30)
            resumed = 0
        if partial_verified:
            argv: tuple[str, ...] = ()
            transport = "existing-partial"
            resumed = size
        elif self._use_rsync():
            argv = (
                "rsync", "--partial", "--append-verify", "--protect-args", "-e", self._rsync_rsh(),
                "--", str(source), self._remote_spec(partial),
            )
            transport = "rsync"
        else:
            argv = (*self.connection.ssh_options("scp"), "--", str(source), self._remote_spec(partial))
            transport = "scp"
            resumed = 0
        if argv:
            self._run_transfer(argv, timeout=timeout)
        uploaded, upload_evidence = self.executor.remote_file_metadata(partial)
        if uploaded.get("size_bytes") != size or uploaded.get("sha256") != digest:
            raise SshTransferError("remote package digest or size mismatch", evidence=upload_evidence.as_dict())
        finalize = "\n".join(
            (
                "import hashlib,os,pathlib,sys",
                "p=pathlib.Path(sys.argv[1]);f=pathlib.Path(sys.argv[2]);e=sys.argv[3];s=int(sys.argv[4])",
                "def digest(path):",
                " h=hashlib.sha256()",
                " with path.open('rb') as stream:",
                "  for block in iter(lambda:stream.read(1048576),b''): h.update(block)",
                " return h.hexdigest()",
                "if f.exists():",
                " ok=f.is_file() and f.stat().st_size==s and digest(f)==e",
                " if ok: p.unlink(missing_ok=True)",
                " raise SystemExit(0 if ok else 9)",
                "if not p.is_file() or p.stat().st_size!=s or digest(p)!=e: raise SystemExit(8)",
                "os.replace(p,f)",
            )
        )
        finalize_evidence = self.executor.require(("python3", "-c", finalize, partial, final, digest, str(size)), timeout=120)
        verified, verified_evidence = self.executor.remote_file_metadata(final)
        if verified.get("size_bytes") != size or verified.get("sha256") != digest:
            raise SshTransferError("final remote package verification failed", evidence=verified_evidence.as_dict())
        receipt = SshTransferReceipt("upload", str(source), final, digest, size, transport, True, False, min(resumed, size), tuple(argv))
        # Keep evidence reachable for callers without putting key contents in it.
        del finalize_evidence
        return receipt

    def download_result(
        self,
        remote_result: str,
        destination: Path,
        *,
        expected_plan_id: str | None = None,
        expected_package_id: str | None = None,
        expected_job_id: str | None = None,
        timeout: float | None = 3600,
    ) -> SshTransferReceipt:
        remote = _remote_path("remote result", remote_result)
        target = destination.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.partial-", dir=target.parent))
        if self._use_rsync():
            argv = (
                "rsync", "--recursive", "--links", "--safe-links", "--protect-args", "-e", self._rsync_rsh(),
                "--", self._remote_spec(remote + "/"), str(staging) + "/",
            )
            transport = "rsync"
        else:
            argv = (*self.connection.ssh_options("scp"), "-r", "--", self._remote_spec(remote + "/."), str(staging))
            transport = "scp"
        try:
            self._run_transfer(argv, timeout=timeout)
            result_file = staging / "result.json"
            for item in staging.rglob("*"):
                if item.is_symlink() or not (item.is_file() or item.is_dir()):
                    raise ValueError(f"unsafe downloaded result entry: {item.relative_to(staging)}")
            result = verify_cloud_result(result_file, expected_plan_id=expected_plan_id, result_root=staging)
            payload = read_json(result_file)
            if expected_package_id is not None and payload.get("package_id") != expected_package_id:
                raise ValueError("result belongs to a different execution package")
            if expected_job_id is not None and payload.get("job_id") != expected_job_id:
                raise ValueError("result belongs to a different job")
            for log_name in ("stdout.log", "stderr.log"):
                if not (staging / log_name).is_file():
                    raise ValueError(f"result diagnostic is missing: {log_name}")
            if target.exists():
                for item in target.rglob("*"):
                    if item.is_symlink() or not (item.is_file() or item.is_dir()):
                        raise ValueError(f"unsafe existing result entry: {item.relative_to(target)}")
                existing = verify_cloud_result(target / "result.json", expected_plan_id=expected_plan_id, result_root=target)
                if existing.result_id != result.result_id:
                    raise ValueError(f"destination contains a different result: {target}")
                shutil.rmtree(staging)
                idempotent = True
            else:
                os.replace(staging, target)
                idempotent = False
            digest = sha256_file(target / "result.json")
            size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
            return SshTransferReceipt("download", remote, str(target), digest, size, transport, True, idempotent, 0, tuple(argv))
        except Exception as exc:
            if isinstance(exc, SshTransferError):
                exc.evidence.setdefault("preserved_partial", str(staging))
                raise
            raise SshTransferError(f"downloaded result verification failed: {exc}", evidence={"preserved_partial": str(staging), "argv": list(argv)}) from exc

    def collect_result(self, session: RadeonCloudSession, cloud_result: Path, destination: Path) -> tuple[SshTransferReceipt, ...]:
        del session
        return (self.download_result(cloud_result.as_posix(), destination),)


@dataclass
class AttachedRadeonCloudProvider:
    connection: SshWorkspaceConnection
    executor: SshCommandExecutor | None = None
    transport: SshArtifactTransport | None = None

    name: str = field(default="attached-ssh", init=False)

    def __post_init__(self) -> None:
        if self.executor is None:
            self.executor = SshCommandExecutor(self.connection)
        if self.transport is None:
            self.transport = SshArtifactTransport(self.connection, executor=self.executor)

    @classmethod
    def from_session(cls, session: RadeonCloudSession) -> "AttachedRadeonCloudProvider":
        if session.provider != "attached-ssh" or session.ssh_connection is None:
            raise ValueError("session is not an attached SSH Radeon Cloud session")
        connection = SshWorkspaceConnection.from_mapping(session.ssh_connection)
        if session.remote_reference != connection.connection_id:
            raise ValueError("session remote_reference does not match SSH connection")
        return cls(connection)

    def run_remote(
        self,
        session_path: Path,
        package: Path,
        destination: Path,
        *,
        timeout: float | None = None,
        evidence_directory: Path | None = None,
    ) -> dict[str, Any]:
        timeout = _validated_timeout(timeout)
        session = load_session(session_path)
        if session.state != "ready":
            raise ValueError("attached session must be ready before remote execution")
        if session.ssh_connection is None or SshWorkspaceConnection.from_mapping(session.ssh_connection) != self.connection:
            raise ValueError("provider connection does not match session")
        evidence_root = (evidence_directory or destination.parent / f"{destination.name}-ssh-evidence").expanduser().resolve()
        evidence_root.mkdir(parents=True, exist_ok=True)
        evidence_paths: list[str] = []
        session = session.transition("running")
        save_session(session_path, session)
        try:
            assert self.executor is not None and self.transport is not None
            probe = self.executor.probe(include_runtime=True)
            probe_path = write_json(evidence_root / "probe.json", probe)
            evidence_paths.append(str(probe_path))
            if not probe["production_ready"]:
                raise RuntimeError("remote Radeon runtime preflight failed; see probe evidence")
            summary = inspect_cloud_package(package)
            upload = self.transport.stage_package(package, timeout=timeout or 3600)
            upload_path = write_json(evidence_root / "upload-receipt.json", upload.as_dict())
            evidence_paths.append(str(upload_path))
            execution_id = summary["package_id"]
            remote_result = posixpath.join(self.transport.results_root, execution_id)
            self.executor.require(("mkdir", "-p", "--", self.transport.results_root), timeout=30)
            runner_path = posixpath.join(self.connection.remote_repository, "tools/episode_factory/radeon_cloud_runner.py")
            execution = self.executor.execute(
                ("python3", runner_path, upload.destination, "--result-directory", remote_result),
                timeout=timeout,
            )
            execution_path = write_json(evidence_root / "ssh-execution.json", execution.as_dict())
            evidence_paths.append(str(execution_path))
            (evidence_root / "ssh-stdout.log").write_text(execution.stdout, encoding="utf-8")
            (evidence_root / "ssh-stderr.log").write_text(execution.stderr, encoding="utf-8")
            evidence_paths.extend([str(evidence_root / "ssh-stdout.log"), str(evidence_root / "ssh-stderr.log")])
            if execution.outcome in {"timeout", "local-ssh-failure", "connection-interrupted"}:
                raise SshCommandError(f"remote runner failed ({execution.outcome})", execution)
            download = self.transport.download_result(
                remote_result,
                destination,
                expected_plan_id=summary["plan_id"],
                expected_package_id=summary["package_id"],
                expected_job_id=summary["job_id"],
                timeout=timeout or 3600,
            )
            download_path = write_json(evidence_root / "download-receipt.json", download.as_dict())
            evidence_paths.append(str(download_path))
            result = verify_cloud_result(destination / "result.json", expected_plan_id=summary["plan_id"], result_root=destination)
            if execution.return_code != 0 or result.status != "succeeded":
                raise RuntimeError(f"remote execution did not succeed (ssh exit {execution.return_code}, result {result.status})")
            session = session.transition("completed")
            save_session(session_path, session)
            value = {
                "schema_version": ATTACHED_RUN_SCHEMA,
                "session_id": session.session_id,
                "state": session.state,
                "package": summary,
                "result_id": result.result_id,
                "result_directory": str(destination.resolve()),
                "remote_result_directory": remote_result,
                "evidence_paths": evidence_paths,
            }
            run_path = write_json(evidence_root / "run.json", {**value, "run_id": _identity(value)})
            value["evidence_paths"].append(str(run_path))
            return value
        except Exception as exc:
            if session.state == "running":
                session = session.transition("failed")
                save_session(session_path, session)
            failure_path = evidence_root / "failure.json"
            preserved_paths = [*evidence_paths, str(failure_path)]
            if isinstance(exc, SshTransferError) and exc.evidence.get("preserved_partial"):
                preserved_paths.append(str(exc.evidence["preserved_partial"]))
            failure = {
                "schema_version": ATTACHED_RUN_SCHEMA,
                "state": session.state,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "evidence_paths": preserved_paths,
            }
            if isinstance(exc, SshCommandError):
                failure["cause_evidence"] = exc.evidence.as_dict()
            elif isinstance(exc, SshTransferError):
                failure["cause_evidence"] = exc.evidence
            write_json(failure_path, failure)
            rendered_paths = ", ".join(preserved_paths)
            raise RuntimeError(
                f"attached Radeon Cloud execution failed: {exc}; preserved evidence: {rendered_paths}"
            ) from exc


def attached_session(connection: SshWorkspaceConnection, *, state: str = "declared") -> RadeonCloudSession:
    return RadeonCloudSession(
        provider="attached-ssh",
        workspace_root=connection.workspace_root,
        state=state,
        remote_reference=connection.connection_id,
        metadata={"transport": "ssh"},
        ssh_connection=connection.as_dict(),
    )
