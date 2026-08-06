from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

try:
    from .radeon_cloud_execution import (
        JOB_SCHEMA,
        RadeonCloudJob,
        inspect_cloud_package,
        sha256_file,
        verify_cloud_result,
        read_json,
        write_json,
    )
except ImportError:
    from radeon_cloud_execution import (
        JOB_SCHEMA,
        RadeonCloudJob,
        inspect_cloud_package,
        sha256_file,
        verify_cloud_result,
        read_json,
        write_json,
    )

SESSION_SCHEMA = 'aahj.radeon-cloud-session/v1'
TRANSFER_SCHEMA = 'aahj.radeon-cloud-transfer/v1'
STATES = {'declared', 'ready', 'running', 'completed', 'failed', 'closed'}
CHUNK = 1024 * 1024


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _required(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} is required')
    return value.strip()


def _safe_relative(name: str, value: Any) -> str:
    text = _required(name, value)
    path = Path(text)
    if path.is_absolute() or '..' in path.parts or text == '.':
        raise ValueError(f'{name} must be a safe relative path')
    return path.as_posix()


@dataclass(frozen=True)
class RadeonCloudSession:
    provider: str
    workspace_root: str
    state: str = 'declared'
    remote_reference: str | None = None
    metadata: Mapping[str, str] | None = None
    ssh_connection: Mapping[str, Any] | None = None
    schema_version: str = SESSION_SCHEMA

    def __post_init__(self) -> None:
        _required('provider', self.provider)
        _required('workspace_root', self.workspace_root)
        if self.state not in STATES:
            raise ValueError(f'unsupported session state: {self.state}')
        metadata = dict(sorted((self.metadata or {}).items()))
        for key, value in metadata.items():
            _required('metadata key', key)
            if not isinstance(value, str):
                raise ValueError('metadata values must be strings')
        object.__setattr__(self, 'metadata', metadata)
        if self.ssh_connection is not None:
            if not isinstance(self.ssh_connection, Mapping):
                raise ValueError('ssh_connection must be an object')
            # The SSH module performs the complete schema validation.  Keeping
            # the canonical mapping here avoids a dependency cycle while still
            # making session documents immutable.
            object.__setattr__(
                self,
                'ssh_connection',
                json.loads(_canonical(dict(self.ssh_connection))),
            )

    def as_dict(self) -> dict[str, Any]:
        value = {
            'schema_version': self.schema_version,
            'provider': self.provider,
            'workspace_root': self.workspace_root,
            'state': self.state,
            'remote_reference': self.remote_reference,
            'metadata': dict(sorted((self.metadata or {}).items())),
        }
        if self.ssh_connection is not None:
            value['ssh_connection'] = dict(self.ssh_connection)
        return value

    @property
    def session_id(self) -> str:
        return _digest_text(_canonical(self.as_dict()))

    def transition(self, state: str) -> 'RadeonCloudSession':
        allowed = {
            'declared': {'ready', 'closed'},
            'ready': {'running', 'closed'},
            'running': {'completed', 'failed', 'closed'},
            'completed': {'closed'},
            'failed': {'ready', 'closed'},
            'closed': set(),
        }
        if state == self.state:
            return self
        if state not in allowed[self.state]:
            raise ValueError(f'invalid session transition: {self.state} -> {state}')
        return RadeonCloudSession(
            provider=self.provider,
            workspace_root=self.workspace_root,
            state=state,
            remote_reference=self.remote_reference,
            metadata=self.metadata,
            ssh_connection=self.ssh_connection,
        )


@dataclass(frozen=True)
class TransferReceipt:
    source: str
    destination: str
    sha256: str
    size_bytes: int
    resumed_from_bytes: int
    schema_version: str = TRANSFER_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'source': self.source,
            'destination': self.destination,
            'sha256': self.sha256,
            'size_bytes': self.size_bytes,
            'resumed_from_bytes': self.resumed_from_bytes,
        }

    @property
    def receipt_id(self) -> str:
        return _digest_text(_canonical(self.as_dict()))


def copy_resumable(source: Path, destination: Path) -> TransferReceipt:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f'source file is missing: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_size = source.stat().st_size
    resumed = 0

    if destination.exists():
        if not destination.is_file():
            raise ValueError(f'destination is not a file: {destination}')
        current_size = destination.stat().st_size
        if current_size == source_size and sha256_file(destination) == sha256_file(source):
            resumed = source_size
        elif current_size < source_size:
            with source.open('rb') as expected, destination.open('rb') as observed:
                remaining = current_size
                matches = True
                while remaining:
                    size = min(CHUNK, remaining)
                    if expected.read(size) != observed.read(size):
                        matches = False
                        break
                    remaining -= size
            if matches:
                resumed = current_size
            else:
                destination.unlink()
        else:
            destination.unlink()

    if resumed < source_size or not destination.exists():
        with source.open('rb') as incoming, destination.open('ab' if resumed else 'wb') as outgoing:
            incoming.seek(resumed)
            while True:
                block = incoming.read(CHUNK)
                if not block:
                    break
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())

    digest = sha256_file(source)
    if destination.stat().st_size != source_size:
        raise RuntimeError('transfer size verification failed')
    if sha256_file(destination) != digest:
        raise RuntimeError('transfer digest verification failed')
    return TransferReceipt(str(source), str(destination), digest, source_size, resumed)


class ArtifactTransport(Protocol):
    def stage_package(self, session: RadeonCloudSession, package: Path) -> TransferReceipt: ...
    def collect_result(self, session: RadeonCloudSession, cloud_result: Path, destination: Path) -> tuple[TransferReceipt, ...]: ...


@dataclass(frozen=True)
class SharedDirectoryTransport:
    inbox: str = 'aahj-inbox'

    def _workspace(self, session: RadeonCloudSession) -> Path:
        root = Path(session.workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f'workspace root is missing: {root}')
        return root

    def stage_package(self, session: RadeonCloudSession, package: Path) -> TransferReceipt:
        summary = inspect_cloud_package(package)
        target = self._workspace(session) / self.inbox / f"{summary['package_id']}.tar.gz"
        return copy_resumable(package, target)

    def collect_result(self, session: RadeonCloudSession, cloud_result: Path, destination: Path) -> tuple[TransferReceipt, ...]:
        workspace = self._workspace(session)
        source_root = cloud_result.resolve() if cloud_result.is_absolute() else (workspace / cloud_result).resolve()
        if not source_root.is_dir():
            raise ValueError(f'result directory is missing: {source_root}')
        result = verify_cloud_result(source_root / 'result.json', result_root=source_root)
        required = {Path('result.json'), Path('stdout.log'), Path('stderr.log')}
        required.update(Path(item['path']) for item in result.outputs)
        destination = destination.expanduser().resolve()
        receipts = []
        for relative in sorted(required, key=lambda value: value.as_posix()):
            safe = Path(_safe_relative('result path', relative.as_posix()))
            receipts.append(copy_resumable(source_root / safe, destination / safe))
        verify_cloud_result(destination / 'result.json', result_root=destination)
        return tuple(receipts)


class Provider(Protocol):
    name: str
    def build_job(self, configuration: Mapping[str, Any]) -> RadeonCloudJob: ...


@dataclass(frozen=True)
class DirectPythonProvider:
    name: str = 'direct-python'

    def build_job(self, configuration: Mapping[str, Any]) -> RadeonCloudJob:
        script = _safe_relative('script', configuration.get('script'))
        arguments = configuration.get('arguments', [])
        if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
            raise ValueError('arguments must be an array of strings')
        return RadeonCloudJob.from_mapping({
            'schema_version': JOB_SCHEMA,
            'argv': ['python3', script, *arguments],
            'environment': configuration.get('environment', {}),
            'working_directory': configuration.get('working_directory', 'payload'),
            'output_paths': configuration.get('output_paths', ['outputs']),
            'timeout_seconds': configuration.get('timeout_seconds', 3600),
        })


@dataclass(frozen=True)
class NotebookScriptProvider(DirectPythonProvider):
    name: str = 'notebook-script'


@dataclass(frozen=True)
class CommandProvider:
    name: str = 'command'

    def build_job(self, configuration: Mapping[str, Any]) -> RadeonCloudJob:
        argv = configuration.get('argv')
        if not isinstance(argv, list) or not argv:
            raise ValueError('argv must be a non-empty array')
        return RadeonCloudJob.from_mapping({
            'schema_version': JOB_SCHEMA,
            'argv': argv,
            'environment': configuration.get('environment', {}),
            'working_directory': configuration.get('working_directory', 'payload'),
            'output_paths': configuration.get('output_paths', ['outputs']),
            'timeout_seconds': configuration.get('timeout_seconds', 3600),
        })


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.name in self._providers:
            raise ValueError(f'duplicate provider: {provider.name}')
        self._providers[provider.name] = provider

    def resolve(self, name: str) -> Provider:
        if name not in self._providers:
            raise ValueError(f'unknown Radeon Cloud provider: {name}')
        return self._providers[name]

    @classmethod
    def defaults(cls) -> 'ProviderRegistry':
        result = cls()
        result.register(DirectPythonProvider())
        result.register(NotebookScriptProvider())
        result.register(CommandProvider())
        return result


def save_session(path: Path, session: RadeonCloudSession) -> Path:
    return write_json(path, {**session.as_dict(), 'session_id': session.session_id})


def load_session(path: Path) -> RadeonCloudSession:
    value = read_json(path)
    if value.get('schema_version') != SESSION_SCHEMA:
        raise ValueError(f'schema_version must be {SESSION_SCHEMA}')
    session = RadeonCloudSession(
        provider=value.get('provider'),
        workspace_root=value.get('workspace_root'),
        state=value.get('state', 'declared'),
        remote_reference=value.get('remote_reference'),
        metadata=value.get('metadata', {}),
        ssh_connection=value.get('ssh_connection'),
    )
    if value.get('session_id') != session.session_id:
        raise ValueError('session_id does not match session')
    return session
