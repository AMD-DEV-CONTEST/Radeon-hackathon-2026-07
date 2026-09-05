"""Identity-fenced supervision for the same-host Linux AMD placement.

The local placement deliberately uses the same ownership model as the SSH
supervisor, but keeps the transport in this process.  Receipts are private
observations used only for an explicit retirement/recovery operation; live
bindings, tokens, and process handles remain in the execution session.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import stat
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Mapping, Protocol

from .components.auth import (
    BearerTokenHandoff,
    RuntimeBearerToken,
    create_bearer_token_handoff,
    remove_bearer_token_handoff,
)
from .components.errors import ManagedProcessError
from .components.process import (
    ManagedProcess,
    ManagedProcessIdentity,
    ManagedProcessSpec,
    ProcessStartIdentity,
    command_fingerprint,
    verify_managed_process_fence,
)
from .placement import AmdPlacementError, AmdRuntimeKey, RuntimeIncarnation
from .remote_supervisor import RemoteGenerationIdentity


class LocalSupervisorError(AmdPlacementError):
    """A local ownership or process fence could not be established."""


class LocalCleanupRefusedError(LocalSupervisorError):
    """Local cleanup could not be proven to target only owned files."""


class LocalProcessConflictError(LocalSupervisorError):
    """A different process currently occupies an exact generation."""


class _CancellationSignal(Protocol):
    """The narrow volatile signal accepted while a local recipe is running."""

    def is_set(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class _RecipeProcessIdentity:
    """In-memory fence for the process group created for one recipe only."""

    pid: int
    process_group_id: int
    session_id: int
    owner_uid: int
    start_identity: ProcessStartIdentity
    executable: str
    command_fingerprint: str


@dataclass(frozen=True, slots=True)
class _ProvisioningObservation:
    """Durable identity fence for one bounded provisioning process group."""

    generation: RemoteGenerationIdentity
    identity: _RecipeProcessIdentity = field(repr=False)


@dataclass(frozen=True, slots=True)
class _StartClaimIdentity:
    generation: RemoteGenerationIdentity
    pid: int
    owner_uid: int
    boot_id: str
    start_ticks: int


@dataclass(frozen=True, slots=True)
class LocalProcessObservation:
    """Exact process identity captured after a fenced local launch."""

    generation: RemoteGenerationIdentity
    identity: ManagedProcessIdentity = field(repr=False)
    executable: str = field(repr=False)
    command_fingerprint: str = field(repr=False)
    loopback_port: int = field(repr=False)

    def __post_init__(self) -> None:
        if self.identity.command_fingerprint != self.command_fingerprint:
            raise LocalSupervisorError("Local process identity changed during launch.")
        if not isinstance(self.executable, str) or not self.executable.startswith("/"):
            raise LocalSupervisorError("Local process executable is invalid.")
        if not isinstance(self.loopback_port, int) or not 1_024 <= self.loopback_port <= 65_535:
            raise LocalSupervisorError("Local loopback port is invalid.")

    @property
    def pid(self) -> int:
        return self.identity.pid


@dataclass(frozen=True, slots=True)
class LocalScriptResult:
    return_code: int
    stdout: bytes = field(repr=False, default=b"")


@dataclass(frozen=True, slots=True)
class LocalLaunchSpec:
    generation: RemoteGenerationIdentity
    command: tuple[str, ...] = field(repr=False)
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    loopback_port: int = field(default=0, repr=False)
    cwd: Path = field(repr=False, default=Path("."))
    token_file: Path | None = field(repr=False, default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.generation, RemoteGenerationIdentity):
            raise LocalSupervisorError("Local launch generation is invalid.")
        if not isinstance(self.environment, Mapping):
            raise LocalSupervisorError("Local launch environment is invalid.")
        if not self.command or not self.command[0].startswith("/"):
            raise LocalSupervisorError("Local launch command is invalid.")
        if not any(argument in {"127.0.0.1", "::1"} for argument in self.command):
            raise LocalSupervisorError("Local launch must explicitly declare a loopback listener.")
        if any(argument in {"0.0.0.0", "::", "*"} for argument in self.command):
            raise LocalSupervisorError("Local launch cannot declare a public listener.")
        if not isinstance(self.loopback_port, int) or not 1_024 <= self.loopback_port <= 65_535:
            raise LocalSupervisorError("Local loopback port is invalid.")
        if str(self.loopback_port) not in self.command and str(self.loopback_port) not in self.environment.values():
            raise LocalSupervisorError("Local launch must explicitly declare its loopback port.")
        path = Path(self.cwd)
        if not path.is_absolute():
            raise LocalSupervisorError("Local launch working directory is invalid.")
        if self.token_file is None or not Path(self.token_file).is_absolute():
            raise LocalSupervisorError("Local runtime token file is invalid.")
        object.__setattr__(self, "command", tuple(self.command))
        object.__setattr__(self, "environment", dict(self.environment))
        object.__setattr__(self, "cwd", path)
        object.__setattr__(self, "token_file", Path(self.token_file))


class LocalSupervisor:
    """Own one injected product root and fence process/file operations below it."""

    _TARGET_MARKER = ".xenix-target"
    _GENERATION_MARKER = ".xenix-generation"
    _RUNTIME_RECEIPT = ".xenix-runtime"
    _STOPPED_RECEIPT = ".xenix-stopped"
    _START_CLAIM = ".xenix-start-claim"
    _PROVISIONING_DIRECTORY = ".xenix-provisioning"
    _PROVISIONING_RECEIPT = "receipt"
    _STOPPED_PROVISIONING_RECEIPT = ".xenix-provisioning-stopped"
    _RETIRING_TOMBSTONE = ".xenix-retiring"
    _CONTROL_DIRECTORY = ".xenix-control"
    _CONTROL_LOCK = "generation.lock"
    _RUNTIME_TOKEN = ".xenix-runtime-token"
    _RECEIPT_VERSION = "xenix-local-runtime-v1"
    _START_CLAIM_VERSION = "xenix-local-start-claim-v1"
    _PROVISIONING_RECEIPT_VERSION = "xenix-local-provisioning-v1"
    _RECIPE_POLL_SECONDS = 0.05
    _RECIPE_TERM_SECONDS = 10.0
    _RECIPE_KILL_SECONDS = 5.0

    def __init__(
        self,
        *,
        product_root: Path,
        target_id: str = "local-linux",
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(product_root, Path):
            product_root = Path(product_root)
        if not product_root.is_absolute() or product_root == product_root.root:
            raise LocalSupervisorError("Local product root must be an absolute private path.")
        if any(part in {"", ".", ".."} for part in product_root.parts):
            raise LocalSupervisorError("Local product root is unsafe.")
        if str(product_root) in {"/", "/tmp", "/var", "/opt", "/home", "/workspace"}:
            raise LocalSupervisorError("Local product root is too broad.")
        self._root = product_root
        self._target_id = target_id
        self._token_factory = token_factory

    @property
    def product_root(self) -> Path:
        return self._root

    def probe_prerequisites(self) -> None:
        if os.name != "posix" or not sys_platform_linux() or not Path("/proc").is_dir():
            raise LocalSupervisorError("Local Linux process supervision is unavailable.")
        if not hasattr(os, "killpg"):
            raise LocalSupervisorError("Local Linux process supervision is unavailable.")

    def prepare_generation(self, generation: RemoteGenerationIdentity) -> Path:
        self._claim_root()
        install_root = self._root / "installations" / generation.runtime_key.installation_id
        generation_root = install_root / "generations" / generation.runtime_key.component_generation_id
        self._mkdir_private(install_root)
        self._mkdir_private(install_root / "generations")
        self._mkdir_private(install_root / self._CONTROL_DIRECTORY)
        install_marker = install_root / ".xenix-installation"
        install_value = f"{self._target_id}\t{generation.runtime_key.installation_id}\n"
        self._write_or_verify(install_marker, install_value)
        self._mkdir_private(generation_root)
        marker = generation_root / self._GENERATION_MARKER
        value = (
            f"{self._target_id}\t{generation.runtime_key.installation_id}\t"
            f"{generation.runtime_key.component_generation_id}\t{generation.manifest_digest}\n"
        )
        self._write_or_verify(marker, value)
        return generation_root

    @contextmanager
    def _generation_control_lock(self, key: AmdRuntimeKey) -> Iterator[None]:
        """Serialize one generation without placing the lock in deletable state.

        The lock lives below the installation's private control directory, not
        below the generation root.  Cleanup can therefore remove a generation
        tree without unlinking the inode that concurrent operations use for
        exclusion.
        """

        control = self._root / "installations" / key.installation_id / self._CONTROL_DIRECTORY
        self._mkdir_private(control)
        lock_path = control / f"{key.component_generation_id}.{self._CONTROL_LOCK}"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = -1
        try:
            fd = os.open(lock_path, flags, 0o600)
            os.fchmod(fd, 0o600)
            lock_stat = os.fstat(fd)
            if lock_stat.st_uid != os.geteuid() or stat.S_IMODE(lock_stat.st_mode) != 0o600:
                raise OSError
            os.fsync(fd)
            self._fsync_directory(control, "Local generation control lock could not be established safely.")
        except OSError:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise LocalCleanupRefusedError("Local generation control lock could not be established safely.") from None
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            os.close(fd)
            raise LocalSupervisorError("Local Linux generation control lock is unavailable.") from None
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def run_recipe(
        self,
        generation: RemoteGenerationIdentity,
        script: str,
        arguments: tuple[str, ...],
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
        cancellation: _CancellationSignal | None = None,
    ) -> LocalScriptResult:
        if not isinstance(script, str) or not script.strip() or "\x00" in script:
            raise LocalSupervisorError("Local generation recipe is invalid.")
        if not 0 < timeout_seconds <= 7_200:
            raise LocalSupervisorError("Local generation recipe deadline is invalid.")
        generation_root = self.prepare_generation(generation)
        argv = (
            self._root,
            self._target_id,
            generation.runtime_key.installation_id,
            generation.runtime_key.component_generation_id,
            generation.manifest_digest,
            generation.incarnation.controller_owner_id,
            generation.incarnation.incarnation_id,
            *arguments,
        )
        wrapper = (
            'gate_fd="$1"; shift; '
            'eval "IFS= read -r gate <&$gate_fd" || exit 125; '
            '[ "$gate" = xenix-go ] || exit 125; '
            'recipe="$1"; shift; '
            '/bin/sh -c "$recipe" xenix "$@"'
        )
        gate_read, gate_write = os.pipe()
        provisioning: Path | None = None
        process: subprocess.Popen[bytes] | None = None
        identity: _RecipeProcessIdentity | None = None
        try:
            command = ("/bin/sh", "-c", wrapper, "xenix", str(gate_read), script, *map(str, argv))
            with self._generation_control_lock(generation.runtime_key):
                self._assert_no_start_claim(generation_root)
                self._assert_not_retiring(generation, generation_root)
                provisioning = self._acquire_provisioning_slot(generation_root)
                if self._is_recipe_cancelled(cancellation):
                    self._discard_empty_provisioning_slot(provisioning)
                    return LocalScriptResult(return_code=-int(signal.SIGTERM))
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=str(self._root),
                        env={
                            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                            "HOME": os.environ.get("HOME", str(Path.home())),
                        },
                        stdin=subprocess.PIPE if stdin is not None else None,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                        pass_fds=(gate_read,),
                        start_new_session=True,
                    )
                except (OSError, TypeError, ValueError, subprocess.SubprocessError):
                    self._discard_empty_provisioning_slot(provisioning)
                    provisioning = None
                    raise LocalSupervisorError("Local generation recipe could not run safely.") from None

                identity = self._capture_recipe_process_identity(process.pid, expected_command=command)
                if identity is None:
                    self._reap_recipe_without_receipt(process)
                    self._discard_empty_provisioning_slot(provisioning)
                    provisioning = None
                    return self._recipe_result(process.returncode, b"")
                observation = _ProvisioningObservation(generation=generation, identity=identity)
                try:
                    self._write_provisioning_receipt(provisioning, observation)
                except Exception:
                    try:
                        self._stop_recipe_process_group(process, identity, None)
                    finally:
                        if not self._process_group_has_live_members(identity.process_group_id):
                            self._discard_empty_provisioning_slot(provisioning)
                            provisioning = None
                    raise
                # The receipt is durable before the payload can execute.  A
                # retirement claim made by another controller is checked again
                # while the same generation lock is still held.
                if self._is_recipe_cancelled(cancellation) or self._is_retiring(generation, generation_root):
                    self._stop_recipe_process_group(process, identity, None)
                    self._move_provisioning_to_stopped(observation)
                    raise LocalProcessConflictError("Local generation retirement revoked recipe execution.")
                os.write(gate_write, b"xenix-go\n")
                os.close(gate_write)
                gate_write = -1
            try:
                stdout, _ = self._wait_for_recipe(
                    process,
                    identity,
                    stdin=stdin,
                    timeout_seconds=float(timeout_seconds),
                    cancellation=cancellation,
                )
            except LocalSupervisorError:
                with self._generation_control_lock(generation.runtime_key):
                    self._move_provisioning_to_stopped(observation)
                raise
            except (OSError, subprocess.SubprocessError):
                with self._generation_control_lock(generation.runtime_key):
                    self._move_provisioning_to_stopped(observation)
                raise LocalSupervisorError("Local generation recipe could not run safely.") from None
            with self._generation_control_lock(generation.runtime_key):
                if self._process_group_has_live_members(identity.process_group_id):
                    raise LocalSupervisorError("Local generation recipe process group could not be reaped safely.")
                self._move_provisioning_to_stopped(observation)
            return self._recipe_result(process.returncode, stdout)
        finally:
            try:
                os.close(gate_read)
            except OSError:
                pass
            if gate_write >= 0:
                try:
                    os.close(gate_write)
                except OSError:
                    pass
            if provisioning is not None and process is None:
                self._discard_empty_provisioning_slot(provisioning)

    @staticmethod
    def _recipe_result(return_code: int | None, stdout: bytes) -> LocalScriptResult:
        if return_code is None:
            raise LocalSupervisorError("Local generation recipe did not exit safely.")
        if len(stdout) > 64 * 1_024:
            raise LocalSupervisorError("Local generation recipe output exceeded its bound.")
        return LocalScriptResult(return_code=return_code, stdout=stdout)

    def _wait_for_recipe(
        self,
        process: subprocess.Popen[bytes],
        identity: _RecipeProcessIdentity,
        *,
        stdin: bytes | None,
        timeout_seconds: float,
        cancellation: _CancellationSignal | None,
    ) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + timeout_seconds
        input_value = stdin
        while True:
            if self._is_recipe_cancelled(cancellation):
                return self._stop_recipe_process_group(process, identity, input_value)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop_recipe_process_group(process, identity, input_value)
                raise LocalSupervisorError("Local generation recipe exceeded its deadline.")
            try:
                return process.communicate(input=input_value, timeout=min(self._RECIPE_POLL_SECONDS, remaining))
            except subprocess.TimeoutExpired:
                input_value = None

    def _reap_recipe_without_receipt(self, process: subprocess.Popen[bytes]) -> None:
        """Reap a wrapper that never yielded a verifiable process identity."""

        try:
            stdout, _ = process.communicate(timeout=self._RECIPE_POLL_SECONDS)
        except subprocess.TimeoutExpired:
            raise LocalSupervisorError("Local generation recipe process group could not be fenced safely.") from None
        except (OSError, subprocess.SubprocessError):
            raise LocalSupervisorError("Local generation recipe could not run safely.") from None
        self._assert_process_group_empty(process.pid, "Local generation recipe process group could not be fenced safely.")
        if len(stdout) > 64 * 1_024:
            raise LocalSupervisorError("Local generation recipe output exceeded its bound.")

    def _stop_recipe_process_group(
        self,
        process: subprocess.Popen[bytes],
        identity: _RecipeProcessIdentity,
        stdin: bytes | None,
    ) -> tuple[bytes, bytes]:
        if not self._process_group_has_live_members(identity.process_group_id):
            try:
                return process.communicate(input=stdin, timeout=self._RECIPE_POLL_SECONDS)
            except subprocess.TimeoutExpired:
                raise LocalSupervisorError("Local generation recipe did not exit safely.") from None
        self._signal_recipe_process_group(identity, signal.SIGTERM)
        try:
            return self._wait_for_recipe_group_exit(process, identity, stdin, self._RECIPE_TERM_SECONDS)
        except subprocess.TimeoutExpired:
            self._signal_recipe_process_group(identity, signal.SIGKILL)
            try:
                return self._wait_for_recipe_group_exit(process, identity, None, self._RECIPE_KILL_SECONDS)
            except subprocess.TimeoutExpired:
                raise LocalSupervisorError("Local generation recipe process group could not be reaped safely.") from None

    def _wait_for_recipe_group_exit(
        self,
        process: subprocess.Popen[bytes],
        identity: _RecipeProcessIdentity,
        stdin: bytes | None,
        timeout_seconds: float,
    ) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + timeout_seconds
        input_value = stdin
        result: tuple[bytes, bytes] | None = None
        while True:
            group_is_live = self._process_group_has_live_members(identity.process_group_id)
            if result is None:
                try:
                    result = process.communicate(
                        input=input_value,
                        timeout=min(self._RECIPE_POLL_SECONDS, max(0.0, deadline - time.monotonic())),
                    )
                except subprocess.TimeoutExpired:
                    input_value = None
            if result is not None and not group_is_live:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout_seconds)
            if result is not None:
                time.sleep(min(self._RECIPE_POLL_SECONDS, remaining))

    def _capture_recipe_process_identity(
        self,
        pid: int,
        *,
        expected_command: tuple[str, ...] | None = None,
        allow_terminal: bool = False,
    ) -> _RecipeProcessIdentity | None:
        try:
            state, process_group_id, session_id, start_ticks = self._read_proc_identity(pid)
            if (state in {"Z", "X"} and not allow_terminal) or process_group_id != pid or session_id != pid:
                return None
            process_path = Path(f"/proc/{pid}")
            if process_path.stat().st_uid != os.geteuid():
                return None
            executable = os.readlink(process_path / "exe")
            command_line = (process_path / "cmdline").read_bytes()
            if not command_line.endswith(b"\x00"):
                return None
            command = tuple(os.fsdecode(argument) for argument in command_line[:-1].split(b"\x00"))
            fingerprint = command_fingerprint(command)
            if expected_command is not None and fingerprint != command_fingerprint(expected_command):
                return None
            return _RecipeProcessIdentity(
                pid=pid,
                process_group_id=process_group_id,
                session_id=session_id,
                owner_uid=os.geteuid(),
                start_identity=ProcessStartIdentity(
                    boot_id=Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip(),
                    start_ticks=start_ticks,
                ),
                executable=executable,
                command_fingerprint=fingerprint,
            )
        except (OSError, UnicodeError, ValueError, ManagedProcessError):
            return None

    def _signal_recipe_process_group(self, identity: _RecipeProcessIdentity, sig: signal.Signals) -> None:
        current = self._capture_recipe_process_identity(identity.pid)
        if current != identity:
            raise LocalSupervisorError("Local generation recipe process group ownership changed.")
        try:
            os.killpg(identity.process_group_id, sig)
        except OSError:
            raise LocalSupervisorError("Local generation recipe process group could not be signalled safely.") from None

    @staticmethod
    def _is_recipe_cancelled(cancellation: _CancellationSignal | None) -> bool:
        if cancellation is None:
            return False
        try:
            return bool(cancellation.is_set())
        except Exception:
            raise LocalSupervisorError("Local generation recipe cancellation signal is invalid.") from None

    @staticmethod
    def _read_proc_identity(pid: int) -> tuple[str, int, int, int]:
        payload = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        closing = payload.rfind(") ")
        fields = payload[closing + 2 :].split() if closing >= 0 else []
        if len(fields) <= 19:
            raise ValueError
        state = fields[0]
        process_group_id = int(fields[2])
        session_id = int(fields[3])
        start_ticks = int(fields[19])
        if not state or process_group_id <= 0 or session_id <= 0 or start_ticks < 0:
            raise ValueError
        return state, process_group_id, session_id, start_ticks

    def _process_group_has_live_members(self, process_group_id: int) -> bool:
        try:
            entries = os.scandir("/proc")
        except OSError:
            raise LocalSupervisorError("Local generation recipe process group cannot be observed safely.") from None
        try:
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                try:
                    state, group_id, _, _ = self._read_proc_identity(int(entry.name))
                except FileNotFoundError:
                    continue
                except (OSError, UnicodeError, ValueError):
                    raise LocalSupervisorError("Local generation recipe process group cannot be observed safely.") from None
                if group_id == process_group_id and state not in {"Z", "X"}:
                    return True
        finally:
            entries.close()
        return False

    def _acquire_provisioning_slot(self, generation_root: Path) -> Path:
        """Atomically reserve a recipe slot before starting its process group."""

        provisioning = generation_root / self._PROVISIONING_DIRECTORY
        stopped = generation_root / self._STOPPED_PROVISIONING_RECEIPT
        if stopped.exists() or stopped.is_symlink():
            raise LocalProcessConflictError("A prior local provisioning receipt still owns this generation.")
        try:
            provisioning.mkdir(mode=0o700)
            provisioning.chmod(0o700)
            if provisioning.is_symlink() or not provisioning.is_dir():
                raise OSError
            self._fsync_directory(generation_root, "Local provisioning receipt directory could not be established safely.")
        except FileExistsError:
            raise LocalProcessConflictError("A bounded local generation recipe is already active.") from None
        except OSError:
            raise LocalCleanupRefusedError("Local provisioning receipt directory is unsafe.") from None
        return provisioning

    @staticmethod
    def _discard_empty_provisioning_slot(provisioning: Path) -> None:
        try:
            if provisioning.is_dir() and not provisioning.is_symlink() and not any(provisioning.iterdir()):
                provisioning.rmdir()
        except OSError:
            pass

    def _write_provisioning_receipt(self, provisioning: Path, observation: _ProvisioningObservation) -> None:
        receipt = provisioning / self._PROVISIONING_RECEIPT
        identity = observation.identity
        self._write_json_exclusive(
            receipt,
            {
                "version": self._PROVISIONING_RECEIPT_VERSION,
                "installation": observation.generation.runtime_key.installation_id,
                "generation": observation.generation.runtime_key.component_generation_id,
                "manifest": observation.generation.manifest_digest,
                "owner": observation.generation.incarnation.controller_owner_id,
                "incarnation": observation.generation.incarnation.incarnation_id,
                "pid": identity.pid,
                "pgid": identity.process_group_id,
                "session": identity.session_id,
                "uid": identity.owner_uid,
                "boot": identity.start_identity.boot_id,
                "start": identity.start_identity.start_ticks,
                "executable": identity.executable,
                "command": identity.command_fingerprint,
            },
            "Local provisioning receipt could not be recorded.",
        )

    def _read_provisioning_receipt(self, receipt: Path) -> _ProvisioningObservation:
        data = self._read_private_json(receipt, "Local provisioning receipt is unsafe.")
        try:
            if data["version"] != self._PROVISIONING_RECEIPT_VERSION:
                raise ValueError
            identity = _RecipeProcessIdentity(
                pid=int(data["pid"]),
                process_group_id=int(data["pgid"]),
                session_id=int(data["session"]),
                owner_uid=int(data["uid"]),
                start_identity=ProcessStartIdentity(boot_id=str(data["boot"]), start_ticks=int(data["start"])),
                executable=str(data["executable"]),
                command_fingerprint=str(data["command"]),
            )
            generation = RemoteGenerationIdentity(
                runtime_key=AmdRuntimeKey(str(data["installation"]), str(data["generation"])),
                manifest_digest=str(data["manifest"]),
                incarnation=RuntimeIncarnation(str(data["owner"]), str(data["incarnation"])),
            )
            if (
                identity.pid <= 0
                or identity.process_group_id != identity.pid
                or identity.session_id != identity.pid
                or identity.owner_uid != os.geteuid()
                or not identity.executable.startswith("/")
                or not identity.command_fingerprint
            ):
                raise ValueError
            return _ProvisioningObservation(generation=generation, identity=identity)
        except (ValueError, TypeError, KeyError, AmdPlacementError, ManagedProcessError):
            raise LocalCleanupRefusedError("Local provisioning receipt is malformed.") from None

    def _move_provisioning_to_stopped(self, observation: _ProvisioningObservation) -> None:
        generation_root = self._generation_root(observation.generation.runtime_key)
        provisioning = generation_root / self._PROVISIONING_DIRECTORY
        receipt = provisioning / self._PROVISIONING_RECEIPT
        stopped = generation_root / self._STOPPED_PROVISIONING_RECEIPT
        if self._process_group_has_live_members(observation.identity.process_group_id):
            raise LocalCleanupRefusedError("Local provisioning process group is still live.")
        if not receipt.exists():
            if stopped.exists() and self._read_provisioning_receipt(stopped) == observation:
                return
            raise LocalCleanupRefusedError("Local provisioning receipt is unavailable.")
        if stopped.exists() or stopped.is_symlink():
            raise LocalCleanupRefusedError("Local stopped provisioning receipt already exists.")
        if self._read_provisioning_receipt(receipt) != observation:
            raise LocalCleanupRefusedError("Local provisioning receipt changed before stop.")
        try:
            receipt.replace(stopped)
            provisioning.rmdir()
            self._fsync_directory(generation_root, "Local provisioning receipt could not be stopped safely.")
        except OSError:
            raise LocalCleanupRefusedError("Local provisioning receipt could not be stopped safely.") from None

    def _assert_no_start_claim(self, generation_root: Path) -> None:
        claim = generation_root / self._START_CLAIM
        if claim.exists() or claim.is_symlink():
            self._read_start_claim(claim)
            raise LocalProcessConflictError("A local generation start claim is active.")

    def _retirement_marker_value(self, generation: RemoteGenerationIdentity) -> str:
        return (
            f"{self._target_id}\t{generation.runtime_key.installation_id}\t"
            f"{generation.runtime_key.component_generation_id}\t{generation.manifest_digest}\n"
        )

    def _claim_retirement(self, generation: RemoteGenerationIdentity, generation_root: Path) -> None:
        """Persist exact desired absence before touching a recipe process group."""

        tombstone = generation_root / self._RETIRING_TOMBSTONE
        self._write_or_verify(tombstone, self._retirement_marker_value(generation))
        self._verify_private_marker(
            tombstone,
            self._retirement_marker_value(generation),
            "Local retirement tombstone is unsafe.",
        )

    def _is_retiring(self, generation: RemoteGenerationIdentity, generation_root: Path) -> bool:
        tombstone = generation_root / self._RETIRING_TOMBSTONE
        if not tombstone.exists() and not tombstone.is_symlink():
            return False
        self._verify_private_marker(
            tombstone,
            self._retirement_marker_value(generation),
            "Local retirement tombstone is unsafe.",
        )
        return True

    def _assert_not_retiring(self, generation: RemoteGenerationIdentity, generation_root: Path) -> None:
        if self._is_retiring(generation, generation_root):
            raise LocalProcessConflictError("Local generation retirement has revoked new work.")

    def _require_retirement_tombstone(
        self,
        generation: RemoteGenerationIdentity,
        generation_root: Path,
    ) -> None:
        if not self._is_retiring(generation, generation_root):
            raise LocalCleanupRefusedError("Local cleanup lacks an exact retirement tombstone.")

    def _acquire_start_claim(
        self, generation: RemoteGenerationIdentity, generation_root: Path
    ) -> tuple[Path, _StartClaimIdentity]:
        claim = generation_root / self._START_CLAIM
        pid = os.getpid()
        try:
            _, _, _, start_ticks = self._read_proc_identity(pid)
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
            if not boot_id or start_ticks < 0:
                raise ValueError
        except (OSError, UnicodeError, ValueError):
            raise LocalSupervisorError("Local generation start claim could not be established safely.") from None
        identity = _StartClaimIdentity(
            generation=generation,
            pid=pid,
            owner_uid=os.geteuid(),
            boot_id=boot_id,
            start_ticks=start_ticks,
        )
        self._write_json_exclusive(
            claim,
            {
                "version": self._START_CLAIM_VERSION,
                "installation": generation.runtime_key.installation_id,
                "generation": generation.runtime_key.component_generation_id,
                "manifest": generation.manifest_digest,
                "owner": generation.incarnation.controller_owner_id,
                "incarnation": generation.incarnation.incarnation_id,
                "pid": pid,
                "uid": identity.owner_uid,
                "boot": boot_id,
                "start": start_ticks,
            },
            "Local generation start claim could not be established safely.",
            conflict_message="A local generation start claim is already active.",
        )
        return claim, identity

    def _read_start_claim(self, claim: Path) -> _StartClaimIdentity:
        data = self._read_private_json(claim, "Local generation start claim is unsafe.")
        try:
            generation = RemoteGenerationIdentity(
                runtime_key=AmdRuntimeKey(str(data["installation"]), str(data["generation"])),
                manifest_digest=str(data["manifest"]),
                incarnation=RuntimeIncarnation(str(data["owner"]), str(data["incarnation"])),
            )
            identity = _StartClaimIdentity(
                generation=generation,
                pid=int(data["pid"]),
                owner_uid=int(data["uid"]),
                boot_id=str(data["boot"]),
                start_ticks=int(data["start"]),
            )
            ProcessStartIdentity(boot_id=identity.boot_id, start_ticks=identity.start_ticks)
            if (
                data["version"] != self._START_CLAIM_VERSION
                or identity.owner_uid != os.geteuid()
                or identity.pid <= 0
                or identity.start_ticks < 0
                or not identity.boot_id
                or not generation.runtime_key.installation_id
                or not generation.runtime_key.component_generation_id
                or not generation.manifest_digest
                or not generation.incarnation.controller_owner_id
                or not generation.incarnation.incarnation_id
            ):
                raise ValueError
            return identity
        except (ValueError, TypeError, KeyError, AmdPlacementError, ManagedProcessError):
            raise LocalCleanupRefusedError("Local generation start claim is malformed.") from None

    def _release_start_claim(
        self,
        claim: Path,
        expected: _StartClaimIdentity,
        *,
        process_group_id: int | None = None,
        receipt: LocalProcessObservation | None = None,
    ) -> None:
        current = self._read_start_claim(claim)
        if current != expected:
            raise LocalCleanupRefusedError("Local generation start claim changed before release.")
        if receipt is None and process_group_id is not None:
            self._assert_process_group_empty(
                process_group_id,
                "Local generation start claim cannot be released while a process remains.",
            )
        if receipt is not None:
            runtime = self._generation_root(receipt.generation.runtime_key) / self._RUNTIME_RECEIPT
            if not runtime.exists() or self._read_receipt(runtime) != receipt:
                raise LocalCleanupRefusedError("Local runtime receipt is not durable before claim release.")
        try:
            claim.unlink()
            self._fsync_directory(claim.parent, "Local generation start claim could not be released safely.")
        except OSError:
            raise LocalCleanupRefusedError("Local generation start claim could not be released safely.") from None

    def create_token_handoff(self, generation: RemoteGenerationIdentity) -> BearerTokenHandoff:
        generation_root = self.prepare_generation(generation)
        with self._generation_control_lock(generation.runtime_key):
            self._assert_not_retiring(generation, generation_root)
            handoff = create_bearer_token_handoff(generation_root)
            if self._token_factory is None:
                return handoff
            try:
                token = RuntimeBearerToken(self._token_factory())
                fd = os.open(handoff.token_file, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.write(fd, token.value.encode("ascii") + b"\n")
                    os.fchmod(fd, 0o600)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                object.__setattr__(handoff, "token", token)
                handoff.verify()
                return handoff
            except Exception:
                try:
                    handoff.remove()
                except Exception:
                    pass
                raise LocalSupervisorError("Local runtime token factory produced an invalid handoff.") from None

    def write_target_asset(
        self,
        generation: RemoteGenerationIdentity,
        *,
        filename: str,
        source: bytes,
        executable: bool,
    ) -> None:
        """Install one bundled target asset only before retirement is claimed."""

        generation_root = self.prepare_generation(generation)
        with self._generation_control_lock(generation.runtime_key):
            self._assert_not_retiring(generation, generation_root)
            target_dir = generation_root / "target"
            target = target_dir / filename
            if (
                not isinstance(filename, str)
                or not filename
                or Path(filename).name != filename
                or "/" in filename
                or "\\" in filename
                or not isinstance(source, bytes)
                or target.parent != target_dir
                or target_dir.is_symlink()
                or not target_dir.is_dir()
            ):
                raise LocalCleanupRefusedError("Local target asset path is unsafe.")
            try:
                fd = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    offset = 0
                    while offset < len(source):
                        offset += os.write(fd, source[offset:])
                    os.fchmod(fd, 0o700 if executable else 0o600)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self._fsync_directory(target_dir, "Local target asset could not be installed safely.")
            except OSError:
                raise LocalCleanupRefusedError("Local target asset could not be installed safely.") from None
            self._assert_not_retiring(generation, generation_root)

    def start(
        self,
        spec: LocalLaunchSpec,
        *,
        token_handoff: BearerTokenHandoff,
        cancellation: _CancellationSignal | None = None,
    ) -> tuple[ManagedProcess, LocalProcessObservation]:
        if token_handoff.token_file != spec.token_file:
            raise LocalSupervisorError("Local token handoff changed.")
        generation_root = self._generation_root(spec.generation.runtime_key)
        claim: Path | None = None
        claim_identity: _StartClaimIdentity | None = None
        claim_releasable = True
        managed: ManagedProcess | None = None
        observation: LocalProcessObservation | None = None
        with self._generation_control_lock(spec.generation.runtime_key):
            try:
                generation_root = self.prepare_generation(spec.generation)
                claim, claim_identity = self._acquire_start_claim(spec.generation, generation_root)
                self._assert_not_retiring(spec.generation, generation_root)
                self._fence_existing_receipt(spec.generation, generation_root)
                claim_releasable = False
                if self._is_recipe_cancelled(cancellation):
                    claim_releasable = True
                    raise LocalProcessConflictError("Local generation retirement revoked runtime launch.")
                self._assert_not_retiring(spec.generation, generation_root)
                try:
                    managed = ManagedProcessSpec(
                        command=spec.command,
                        cwd=spec.cwd,
                        token_file=token_handoff.token_file,
                        environment=spec.environment,
                    ).launch()
                except ManagedProcessError as exc:
                    claim_releasable = True
                    raise LocalSupervisorError("Local runtime could not be started safely.") from exc
                try:
                    executable = os.readlink(f"/proc/{managed.identity.pid}/exe")
                    observation = LocalProcessObservation(
                        generation=spec.generation,
                        identity=managed.identity,
                        executable=executable,
                        command_fingerprint=command_fingerprint(spec.command),
                        loopback_port=spec.loopback_port,
                    )
                    self._write_receipt(observation)
                except Exception:
                    try:
                        self._terminate_unrecorded_runtime(managed)
                    finally:
                        if not self._process_group_has_live_members(managed.identity.process_group_id):
                            claim_releasable = True
                    raise LocalSupervisorError("Local runtime could not be recorded safely.") from None
                if self._is_recipe_cancelled(cancellation) or self._is_retiring(spec.generation, generation_root):
                    try:
                        self._terminate_unrecorded_runtime(managed)
                        self._move_to_stopped(observation)
                    except Exception:
                        claim_releasable = False
                        raise
                    claim_releasable = True
                    raise LocalProcessConflictError("Local generation retirement revoked runtime launch.")
                claim_releasable = True
                return managed, observation
            finally:
                if claim_releasable and claim is not None and claim_identity is not None:
                    process_group_id = None if observation is not None else managed.identity.process_group_id if managed is not None else None
                    self._release_start_claim(
                        claim,
                        claim_identity,
                        process_group_id=process_group_id,
                        receipt=observation,
                    )

    def _terminate_unrecorded_runtime(self, managed: ManagedProcess) -> None:
        """Fence a just-launched process group before its session publishes it."""

        try:
            managed.terminate(timeout_seconds=5.0, kill_after_timeout=True)
        except Exception as exc:
            raise LocalSupervisorError("New local runtime could not be reaped safely.") from exc
        self._assert_process_group_empty(
            managed.identity.process_group_id,
            "New local runtime process group could not be observed safely.",
        )

    def _fence_existing_receipt(self, generation: RemoteGenerationIdentity, generation_root: Path) -> None:
        runtime = generation_root / self._RUNTIME_RECEIPT
        stopped = generation_root / self._STOPPED_RECEIPT
        self._assert_no_active_provisioning(generation_root)
        self._assert_stopped_provisioning_is_quiescent(generation_root, generation)
        if runtime.exists():
            previous = self._read_receipt(runtime)
            if previous.generation.runtime_key != generation.runtime_key or previous.generation.manifest_digest != generation.manifest_digest:
                raise LocalProcessConflictError("A different local process already owns this generation.")
            if self.observe(previous):
                raise LocalProcessConflictError("A different local process already owns this generation.")
            self._assert_process_group_empty(previous.identity.process_group_id, "Local runtime process group cannot be observed safely.")
            runtime.unlink()
            self._remove_runtime_token(generation_root)
            self._fsync_directory(generation_root, "Local runtime receipt could not be reaped safely.")
        if stopped.exists():
            previous = self._read_receipt(stopped)
            if previous.generation.runtime_key != generation.runtime_key or previous.generation.manifest_digest != generation.manifest_digest:
                raise LocalProcessConflictError("A different stopped local generation owns this root.")
            self._assert_process_group_empty(previous.identity.process_group_id, "Local stopped runtime process group cannot be observed safely.")
            stopped.unlink()
            self._fsync_directory(generation_root, "Local stopped receipt could not be reaped safely.")

    def observe(self, observation: LocalProcessObservation) -> bool:
        try:
            verify_managed_process_fence(observation.identity)
            if os.readlink(f"/proc/{observation.identity.pid}/exe") != observation.executable:
                raise ManagedProcessError
        except (ManagedProcessError, OSError) as exc:
            if self._process_group_has_live_members(observation.identity.process_group_id):
                raise LocalProcessConflictError("Local runtime receipt has live process-group peers.") from exc
            return False
        return True

    def stop(
        self,
        managed: ManagedProcess,
        observation: LocalProcessObservation,
        *,
        token_handoff: BearerTokenHandoff | None,
    ) -> None:
        generation_root = self._generation_root(observation.generation.runtime_key)
        with self._generation_control_lock(observation.generation.runtime_key):
            self._assert_no_start_claim(generation_root)
            try:
                managed.terminate(timeout_seconds=10.0, kill_after_timeout=True)
            except ManagedProcessError as exc:
                raise LocalSupervisorError("Local process changed before safe stop.") from exc
            self._assert_process_group_empty(observation.identity.process_group_id, "Local runtime process group could not be reaped safely.")
            self._move_to_stopped(observation)
            if token_handoff is not None:
                try:
                    remove_bearer_token_handoff(token_handoff)
                except Exception as exc:
                    raise LocalSupervisorError("Local runtime token could not be removed safely.") from exc

    def recover_stopped(self, *, runtime_key: AmdRuntimeKey, manifest_digest: str) -> LocalProcessObservation:
        generation_root = self._generation_root(runtime_key)
        provisional = RemoteGenerationIdentity(
            runtime_key=runtime_key,
            manifest_digest=manifest_digest,
            incarnation=RuntimeIncarnation("local-recovery", "local-recovery"),
        )
        self._verify_generation_marker(provisional)
        with self._generation_control_lock(runtime_key):
            self._assert_no_start_claim(generation_root)
            self._assert_no_active_provisioning(generation_root)
            self._assert_stopped_provisioning_is_quiescent(generation_root, provisional)
            runtime = generation_root / self._RUNTIME_RECEIPT
            stopped = generation_root / self._STOPPED_RECEIPT
            if runtime.exists() and stopped.exists():
                raise LocalCleanupRefusedError("Local generation has conflicting process receipts.")
            receipt = runtime if runtime.exists() else stopped if stopped.exists() else None
            if receipt is None:
                raise LocalCleanupRefusedError("No recoverable local runtime fence exists.")
            observation = self._read_receipt(receipt)
            if (
                observation.generation.runtime_key != runtime_key
                or observation.generation.manifest_digest != manifest_digest
            ):
                raise LocalCleanupRefusedError("Local runtime receipt identity changed.")
            if receipt == runtime:
                if self.observe(observation):
                    self._signal_and_wait(observation.identity)
                self._assert_process_group_empty(observation.identity.process_group_id, "Local runtime process group cannot be observed safely.")
                self._move_to_stopped(observation)
            else:
                self._assert_process_group_empty(observation.identity.process_group_id, "Local stopped runtime process group cannot be observed safely.")
            self._remove_runtime_token(generation_root)
            return observation

    def cleanup(self, observation: LocalProcessObservation, owned_relative_paths: tuple[str, ...]) -> None:
        with self._generation_control_lock(observation.generation.runtime_key):
            self._cleanup_locked(observation, owned_relative_paths)

    def _cleanup_locked(self, observation: LocalProcessObservation, owned_relative_paths: tuple[str, ...]) -> None:
        generation_root = self._generation_root(observation.generation.runtime_key)
        self._verify_generation_marker(observation.generation)
        self._require_retirement_tombstone(observation.generation, generation_root)
        self._assert_no_start_claim(generation_root)
        self._assert_no_active_provisioning(generation_root)
        stopped = generation_root / self._STOPPED_RECEIPT
        if not stopped.exists() or (generation_root / self._RUNTIME_RECEIPT).exists():
            raise LocalCleanupRefusedError("Local cleanup lacks an exact stopped-process fence.")
        current = self._read_receipt(stopped)
        if current != observation:
            raise LocalCleanupRefusedError("Local stopped-process fence changed.")
        self._assert_process_group_empty(current.identity.process_group_id, "Local stopped runtime process group cannot be observed safely.")
        stopped_provisioning = generation_root / self._STOPPED_PROVISIONING_RECEIPT
        provisioning_observation: _ProvisioningObservation | None = None
        if stopped_provisioning.exists() or stopped_provisioning.is_symlink():
            provisioning_observation = self._read_provisioning_receipt(stopped_provisioning)
            self._require_provisioning_generation(
                provisioning_observation,
                observation.generation.runtime_key,
                observation.generation.manifest_digest,
            )
            self._assert_process_group_empty(
                provisioning_observation.identity.process_group_id,
                "Local stopped provisioning process group cannot be observed safely.",
            )
        for relative in owned_relative_paths:
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0].startswith(".xenix-"):
                raise LocalCleanupRefusedError("Local cleanup path is unsafe.")
            candidate = generation_root.joinpath(*path.parts)
            try:
                candidate.resolve(strict=False).relative_to(generation_root.resolve())
            except ValueError:
                raise LocalCleanupRefusedError("Local cleanup path escaped its generation root.") from None
            if candidate.exists() or candidate.is_symlink():
                if candidate.is_dir() and not candidate.is_symlink():
                    import shutil

                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
        for remaining in generation_root.iterdir():
            if remaining.name not in {
                self._GENERATION_MARKER,
                self._STOPPED_RECEIPT,
                self._STOPPED_PROVISIONING_RECEIPT,
                self._RETIRING_TOMBSTONE,
            }:
                raise LocalCleanupRefusedError("Unlisted local generation content blocks cleanup.")
        stopped.unlink()
        if provisioning_observation is not None:
            stopped_provisioning.unlink()
        (generation_root / self._RETIRING_TOMBSTONE).unlink()
        (generation_root / self._GENERATION_MARKER).unlink()
        self._fsync_directory(generation_root, "Local generation cleanup could not be committed safely.")
        generation_root.rmdir()
        self._fsync_directory(generation_root.parent, "Local generation cleanup could not be committed safely.")

    def cancel_provisioning_for_retirement(self, *, runtime_key: AmdRuntimeKey, manifest_digest: str) -> None:
        """Stop only the exact active recipe fenced by its durable receipt."""

        generation_root = self._generation_root(runtime_key)
        if not generation_root.exists() and not generation_root.is_symlink():
            return
        provisional = RemoteGenerationIdentity(
            runtime_key=runtime_key,
            manifest_digest=manifest_digest,
            incarnation=RuntimeIncarnation("local-recovery", "local-recovery"),
        )
        self._verify_generation_marker(provisional)
        with self._generation_control_lock(runtime_key):
            # Retirement intent is durable before any process or receipt is
            # inspected, so a concurrent forward operation fails closed.
            self._claim_retirement(provisional, generation_root)
            self._assert_no_start_claim(generation_root)
            provisioning = generation_root / self._PROVISIONING_DIRECTORY
            stopped = generation_root / self._STOPPED_PROVISIONING_RECEIPT
            if not provisioning.exists() and not provisioning.is_symlink():
                if stopped.exists() or stopped.is_symlink():
                    observation = self._read_provisioning_receipt(stopped)
                    self._require_provisioning_generation(observation, runtime_key, manifest_digest)
                    self._assert_process_group_empty(observation.identity.process_group_id, "Local stopped provisioning process group cannot be observed safely.")
                return
            if provisioning.is_symlink() or not provisioning.is_dir():
                raise LocalCleanupRefusedError("Local provisioning receipt directory is unsafe.")
            if stopped.exists() or stopped.is_symlink():
                raise LocalCleanupRefusedError("Local generation has conflicting provisioning receipts.")
            observation = self._read_provisioning_receipt(provisioning / self._PROVISIONING_RECEIPT)
            self._require_provisioning_generation(observation, runtime_key, manifest_digest)
            identity = observation.identity
            if self._recipe_identity_is_exact(identity):
                self._signal_recipe_process_group(identity, signal.SIGTERM)
                try:
                    self._wait_for_recipe_group_exit_without_process(identity, self._RECIPE_TERM_SECONDS)
                except subprocess.TimeoutExpired:
                    self._signal_recipe_process_group(identity, signal.SIGKILL)
                    self._wait_for_recipe_group_exit_without_process(identity, self._RECIPE_KILL_SECONDS)
            self._assert_process_group_empty(identity.process_group_id, "Local provisioning process group cannot be observed safely.")
            self._move_provisioning_to_stopped(observation)

    def cleanup_provisioned_generation(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
        owned_relative_paths: tuple[str, ...],
    ) -> bool:
        """Clean a retired generation that has only a stopped recipe fence."""

        generation_root = self._generation_root(runtime_key)
        if not generation_root.exists() and not generation_root.is_symlink():
            return False
        with self._generation_control_lock(runtime_key):
            return self._cleanup_provisioned_generation_locked(
                runtime_key=runtime_key,
                manifest_digest=manifest_digest,
                owned_relative_paths=owned_relative_paths,
            )

    def _cleanup_provisioned_generation_locked(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
        owned_relative_paths: tuple[str, ...],
    ) -> bool:

        generation_root = self._generation_root(runtime_key)
        if not generation_root.exists() and not generation_root.is_symlink():
            return False
        provisional = RemoteGenerationIdentity(
            runtime_key=runtime_key,
            manifest_digest=manifest_digest,
            incarnation=RuntimeIncarnation("local-recovery", "local-recovery"),
        )
        self._verify_generation_marker(provisional)
        self._require_retirement_tombstone(provisional, generation_root)
        self._assert_no_start_claim(generation_root)
        if (generation_root / self._RUNTIME_RECEIPT).exists() or (generation_root / self._STOPPED_RECEIPT).exists():
            return False
        self._assert_no_active_provisioning(generation_root)
        stopped = generation_root / self._STOPPED_PROVISIONING_RECEIPT
        if not stopped.exists() and not stopped.is_symlink():
            return False
        observation = self._read_provisioning_receipt(stopped)
        self._require_provisioning_generation(observation, runtime_key, manifest_digest)
        self._assert_process_group_empty(observation.identity.process_group_id, "Local stopped provisioning process group cannot be observed safely.")
        self._cleanup_generation_paths(
            generation_root,
            owned_relative_paths,
            allowed_remaining={
                self._GENERATION_MARKER,
                self._STOPPED_PROVISIONING_RECEIPT,
                self._RETIRING_TOMBSTONE,
            },
        )
        stopped.unlink()
        (generation_root / self._RETIRING_TOMBSTONE).unlink()
        (generation_root / self._GENERATION_MARKER).unlink()
        self._fsync_directory(generation_root, "Local generation cleanup could not be committed safely.")
        generation_root.rmdir()
        self._fsync_directory(generation_root.parent, "Local generation cleanup could not be committed safely.")
        return True

    def cleanup_empty_generation(self, *, runtime_key: AmdRuntimeKey, manifest_digest: str) -> bool:
        """Remove only a marked generation root with no runtime or recipe state."""

        generation_root = self._generation_root(runtime_key)
        if not generation_root.exists() and not generation_root.is_symlink():
            return True
        with self._generation_control_lock(runtime_key):
            return self._cleanup_empty_generation_locked(runtime_key=runtime_key, manifest_digest=manifest_digest)

    def _cleanup_empty_generation_locked(self, *, runtime_key: AmdRuntimeKey, manifest_digest: str) -> bool:

        generation_root = self._generation_root(runtime_key)
        if not generation_root.exists() and not generation_root.is_symlink():
            return True
        provisional = RemoteGenerationIdentity(
            runtime_key=runtime_key,
            manifest_digest=manifest_digest,
            incarnation=RuntimeIncarnation("local-recovery", "local-recovery"),
        )
        self._verify_generation_marker(provisional)
        self._require_retirement_tombstone(provisional, generation_root)
        self._assert_no_start_claim(generation_root)
        if any(
            (generation_root / name).exists() or (generation_root / name).is_symlink()
            for name in (
                self._RUNTIME_RECEIPT,
                self._STOPPED_RECEIPT,
                self._PROVISIONING_DIRECTORY,
                self._STOPPED_PROVISIONING_RECEIPT,
            )
        ):
            return False
        self._cleanup_generation_paths(
            generation_root,
            (),
            allowed_remaining={self._GENERATION_MARKER, self._RETIRING_TOMBSTONE},
        )
        (generation_root / self._RETIRING_TOMBSTONE).unlink()
        (generation_root / self._GENERATION_MARKER).unlink()
        self._fsync_directory(generation_root, "Local generation cleanup could not be committed safely.")
        generation_root.rmdir()
        self._fsync_directory(generation_root.parent, "Local generation cleanup could not be committed safely.")
        return True

    def _assert_no_active_provisioning(self, generation_root: Path) -> None:
        provisioning = generation_root / self._PROVISIONING_DIRECTORY
        if provisioning.exists() or provisioning.is_symlink():
            if provisioning.is_symlink() or not provisioning.is_dir():
                raise LocalCleanupRefusedError("Local provisioning receipt directory is unsafe.")
            self._read_provisioning_receipt(provisioning / self._PROVISIONING_RECEIPT)
            raise LocalProcessConflictError("A bounded local generation recipe is already active.")

    def _assert_stopped_provisioning_is_quiescent(
        self,
        generation_root: Path,
        expected_generation: RemoteGenerationIdentity,
    ) -> None:
        stopped = generation_root / self._STOPPED_PROVISIONING_RECEIPT
        if stopped.exists() or stopped.is_symlink():
            observation = self._read_provisioning_receipt(stopped)
            self._require_provisioning_generation(
                observation,
                expected_generation.runtime_key,
                expected_generation.manifest_digest,
            )
            self._assert_process_group_empty(
                observation.identity.process_group_id,
                "Local stopped provisioning process group cannot be observed safely.",
            )

    def _require_provisioning_generation(
        self,
        observation: _ProvisioningObservation,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> None:
        if observation.generation.runtime_key != runtime_key or observation.generation.manifest_digest != manifest_digest:
            raise LocalCleanupRefusedError("Local provisioning receipt identity changed.")

    def _recipe_identity_is_exact(self, identity: _RecipeProcessIdentity) -> bool:
        current = self._capture_recipe_process_identity(identity.pid)
        if current == identity:
            return True
        if self._process_group_has_live_members(identity.process_group_id):
            raise LocalCleanupRefusedError("Local provisioning process identity cannot be verified.")
        return False

    def _wait_for_recipe_group_exit_without_process(
        self,
        identity: _RecipeProcessIdentity,
        timeout_seconds: float,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while self._process_group_has_live_members(identity.process_group_id):
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(identity.executable, timeout_seconds)
            time.sleep(self._RECIPE_POLL_SECONDS)

    def _assert_process_group_empty(self, process_group_id: int, message: str) -> None:
        try:
            if self._process_group_has_live_members(process_group_id):
                raise LocalCleanupRefusedError(message)
        except LocalSupervisorError as exc:
            if isinstance(exc, LocalCleanupRefusedError):
                raise
            raise LocalCleanupRefusedError(message) from exc

    def _cleanup_generation_paths(
        self,
        generation_root: Path,
        owned_relative_paths: tuple[str, ...],
        *,
        allowed_remaining: set[str],
    ) -> None:
        for relative in owned_relative_paths:
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0].startswith(".xenix-"):
                raise LocalCleanupRefusedError("Local cleanup path is unsafe.")
            candidate = generation_root.joinpath(*path.parts)
            try:
                candidate.resolve(strict=False).relative_to(generation_root.resolve())
            except ValueError:
                raise LocalCleanupRefusedError("Local cleanup path escaped its generation root.") from None
            if candidate.exists() or candidate.is_symlink():
                if candidate.is_dir() and not candidate.is_symlink():
                    import shutil

                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
        for remaining in generation_root.iterdir():
            if remaining.name not in allowed_remaining:
                raise LocalCleanupRefusedError("Unlisted local generation content blocks cleanup.")

    def _claim_root(self) -> None:
        self._mkdir_private(self._root)
        marker = self._root / self._TARGET_MARKER
        self._write_or_verify(marker, f"{self._target_id}\n")

    def _generation_root(self, key: AmdRuntimeKey) -> Path:
        return self._root / "installations" / key.installation_id / "generations" / key.component_generation_id

    def _write_receipt(self, observation: LocalProcessObservation) -> None:
        generation_root = self._generation_root(observation.generation.runtime_key)
        receipt = generation_root / self._RUNTIME_RECEIPT
        data = {
            "version": self._RECEIPT_VERSION,
            "installation": observation.generation.runtime_key.installation_id,
            "generation": observation.generation.runtime_key.component_generation_id,
            "manifest": observation.generation.manifest_digest,
            "owner": observation.generation.incarnation.controller_owner_id,
            "incarnation": observation.generation.incarnation.incarnation_id,
            "pid": observation.identity.pid,
            "pgid": observation.identity.process_group_id,
            "session": observation.identity.session_id,
            "uid": observation.identity.owner_uid,
            "boot": observation.identity.start_identity.boot_id,
            "start": observation.identity.start_identity.start_ticks,
            "executable": observation.executable,
            "command": observation.command_fingerprint,
            "port": observation.loopback_port,
        }
        self._atomic_json(receipt, data)

    def _read_receipt(self, receipt: Path) -> LocalProcessObservation:
        data = self._read_private_json(receipt, "Local process receipt is unsafe.")
        try:
            identity = ManagedProcessIdentity(
                pid=int(data["pid"]),
                process_group_id=int(data["pgid"]),
                session_id=int(data["session"]),
                owner_uid=int(data["uid"]),
                start_identity=ProcessStartIdentity(boot_id=str(data["boot"]), start_ticks=int(data["start"])),
                command_fingerprint=str(data["command"]),
            )
            generation = RemoteGenerationIdentity(
                runtime_key=AmdRuntimeKey(str(data["installation"]), str(data["generation"])),
                manifest_digest=str(data["manifest"]),
                incarnation=RuntimeIncarnation(str(data["owner"]), str(data["incarnation"])),
            )
            if data["version"] != self._RECEIPT_VERSION:
                raise ValueError
            return LocalProcessObservation(
                generation=generation,
                identity=identity,
                executable=str(data["executable"]),
                command_fingerprint=str(data["command"]),
                loopback_port=int(data["port"]),
            )
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, AmdPlacementError, ManagedProcessError):
            raise LocalCleanupRefusedError("Local process receipt is malformed.") from None

    def _move_to_stopped(self, observation: LocalProcessObservation) -> None:
        generation_root = self._generation_root(observation.generation.runtime_key)
        runtime = generation_root / self._RUNTIME_RECEIPT
        stopped = generation_root / self._STOPPED_RECEIPT
        self._assert_process_group_empty(observation.identity.process_group_id, "Local runtime process group is still live.")
        if not runtime.exists():
            if stopped.exists() and self._read_receipt(stopped) == observation:
                return
            raise LocalCleanupRefusedError("Local runtime receipt is unavailable.")
        if stopped.exists():
            raise LocalCleanupRefusedError("Local stopped receipt already exists.")
        if self._read_receipt(runtime) != observation:
            raise LocalCleanupRefusedError("Local runtime receipt changed before stop.")
        try:
            runtime.replace(stopped)
            self._fsync_directory(generation_root, "Local stopped receipt could not be recorded safely.")
        except OSError:
            raise LocalCleanupRefusedError("Local stopped receipt could not be recorded safely.") from None

    def _remove_runtime_token(self, generation_root: Path) -> None:
        token = generation_root / self._RUNTIME_TOKEN
        if not token.exists() and not token.is_symlink():
            return
        try:
            token_stat = token.stat(follow_symlinks=False)
            if (
                token.is_symlink()
                or not stat.S_ISREG(token_stat.st_mode)
                or token_stat.st_uid != os.geteuid()
                or stat.S_IMODE(token_stat.st_mode) != 0o600
            ):
                raise OSError
            token.unlink()
        except OSError:
            raise LocalCleanupRefusedError("Local runtime token could not be removed safely.") from None

    def _verify_generation_marker(self, generation: RemoteGenerationIdentity) -> None:
        self._verify_product_marker()
        root = self._generation_root(generation.runtime_key)
        if root.is_symlink() or not root.is_dir() or any(parent.is_symlink() for parent in root.parents if parent == self._root or self._root in parent.parents):
            raise LocalCleanupRefusedError("Local generation root is unsafe.")
        marker = root / self._GENERATION_MARKER
        expected = (
            f"{self._target_id}\t{generation.runtime_key.installation_id}\t"
            f"{generation.runtime_key.component_generation_id}\t{generation.manifest_digest}\n"
        )
        self._verify_private_marker(marker, expected, "Local generation marker is unsafe.")

    def _verify_product_marker(self) -> None:
        if self._root.is_symlink() or not self._root.is_dir():
            raise LocalCleanupRefusedError("Local product root is unsafe.")
        marker = self._root / self._TARGET_MARKER
        self._verify_private_marker(
            marker,
            f"{self._target_id}\n",
            "Local product ownership marker is unsafe.",
        )

    def _signal_and_wait(self, identity: ManagedProcessIdentity) -> None:
        try:
            verify_managed_process_fence(identity)
            os.killpg(identity.process_group_id, signal.SIGTERM)
        except (ManagedProcessError, OSError) as exc:
            raise LocalCleanupRefusedError("Local runtime could not be stopped safely.") from exc
        deadline = time.monotonic() + 10.0
        while self._process_group_has_live_members(identity.process_group_id):
            if time.monotonic() >= deadline:
                try:
                    verify_managed_process_fence(identity)
                    os.killpg(identity.process_group_id, signal.SIGKILL)
                except (ManagedProcessError, OSError) as exc:
                    raise LocalCleanupRefusedError("Local runtime could not be reaped safely.") from exc
                deadline = time.monotonic() + 5.0
            time.sleep(0.05)

    @staticmethod
    def _proc_exists(pid: int) -> bool:
        return Path(f"/proc/{pid}").exists()

    @staticmethod
    def _proc_state(pid: int) -> str | None:
        try:
            payload = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            closing = payload.rfind(") ")
            return payload[closing + 2 :].split()[0] if closing >= 0 else None
        except (OSError, IndexError):
            return None

    @staticmethod
    def _group_exists(process_group_id: int) -> bool:
        killpg = getattr(os, "killpg", None)
        if killpg is None:
            return False
        try:
            killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    @staticmethod
    def _mkdir_private(path: Path) -> None:
        try:
            for parent in (path, *path.parents):
                if parent.exists() and parent.is_symlink():
                    raise OSError
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
            if not path.is_dir() or path.is_symlink():
                raise OSError
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(path, flags)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            raise LocalCleanupRefusedError("Local ownership directory is unsafe.") from None

    @staticmethod
    def _write_or_verify(path: Path, expected: str) -> None:
        payload = expected.encode("utf-8")
        try:
            if path.exists() or path.is_symlink():
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    path_stat = os.fstat(fd)
                    if (
                        not stat.S_ISREG(path_stat.st_mode)
                        or path_stat.st_uid != os.geteuid()
                        or stat.S_IMODE(path_stat.st_mode) != 0o600
                        or os.read(fd, len(payload) + 1) != payload
                    ):
                        raise OSError
                finally:
                    os.close(fd)
                return
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                offset = 0
                while offset < len(payload):
                    offset += os.write(fd, payload[offset:])
                os.fsync(fd)
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            LocalSupervisor._fsync_directory(path.parent, "Local ownership marker could not be established.")
        except (OSError, UnicodeError):
            raise LocalCleanupRefusedError("Local ownership marker could not be established.") from None

    @staticmethod
    def _verify_private_marker(path: Path, expected: str, message: str) -> None:
        payload = expected.encode("utf-8")
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                path_stat = os.fstat(fd)
                if (
                    not stat.S_ISREG(path_stat.st_mode)
                    or path_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(path_stat.st_mode) != 0o600
                    or os.read(fd, len(payload) + 1) != payload
                ):
                    raise OSError
            finally:
                os.close(fd)
        except (OSError, UnicodeError):
            raise LocalCleanupRefusedError(message) from None

    @staticmethod
    def _atomic_json(path: Path, data: dict[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(16)}.tmp")
        fd = -1
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temporary, flags, 0o600)
            payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
            offset = 0
            while offset < len(payload):
                offset += os.write(fd, payload[offset:])
            os.fchmod(fd, 0o600)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, path)
            LocalSupervisor._fsync_directory(path.parent, "Local process receipt could not be recorded.")
        except (OSError, TypeError, ValueError):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                if temporary.is_file() and not temporary.is_symlink():
                    temporary.unlink()
            except OSError:
                pass
            raise LocalSupervisorError("Local process receipt could not be recorded.") from None

    @staticmethod
    def _read_private_json(path: Path, message: str) -> dict[str, object]:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                path_stat = os.fstat(fd)
                if (
                    not stat.S_ISREG(path_stat.st_mode)
                    or path_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(path_stat.st_mode) != 0o600
                ):
                    raise OSError
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 64 * 1_024 + 1)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if sum(map(len, chunks)) > 64 * 1_024:
                        raise ValueError
                data = json.loads(b"".join(chunks).decode("utf-8"))
            finally:
                os.close(fd)
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            raise LocalCleanupRefusedError(message) from None

    @staticmethod
    def _write_json_exclusive(
        path: Path,
        data: dict[str, object],
        message: str,
        *,
        conflict_message: str | None = None,
    ) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
            try:
                payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                offset = 0
                while offset < len(payload):
                    offset += os.write(fd, payload[offset:])
                os.fsync(fd)
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
        except FileExistsError:
            if conflict_message is not None:
                raise LocalProcessConflictError(conflict_message) from None
            raise LocalCleanupRefusedError(message) from None
        except (OSError, TypeError, ValueError):
            raise LocalCleanupRefusedError(message) from None
        LocalSupervisor._fsync_directory(path.parent, message)

    @staticmethod
    def _fsync_directory(path: Path, message: str) -> None:
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(path, flags)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            raise LocalCleanupRefusedError(message) from None


def sys_platform_linux() -> bool:
    import sys

    return sys.platform == "linux"


__all__ = [
    "LocalCleanupRefusedError",
    "LocalLaunchSpec",
    "LocalProcessConflictError",
    "LocalProcessObservation",
    "LocalScriptResult",
    "LocalSupervisor",
    "LocalSupervisorError",
]
