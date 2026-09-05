"""Restricted WSL2 placement for AMD Linux target supervision.

WSL is an explicit local Linux target, not an SSH target and not a Windows
ROCm fallback.  This module owns the only Windows process boundary: fixed
``wsl.exe`` invocation with a validated distribution name.  It intentionally
does not expose an arbitrary shell API.  The only target programs accepted by
the transport are the supervisor's fixed fencing programs and recipes admitted
into a composition-owned catalogue before the session is opened.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Protocol

from ..compatibility import TargetCompatibilityFacts
from ..manifests import CompatibilityTargetKind
from ..placement import AmdExecutionSession, AmdPlacementError, AmdRuntimeKey, LoopbackHttpBinding, RuntimeIncarnation
from ..remote_supervisor import (
    ProtectedRuntimeSecret,
    RemoteGenerationIdentity,
    RemoteLaunchSpec,
    RemoteProcessObservation,
    RemoteScriptResult,
    RemoteSupervisor,
)

_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()@+-]{0,79}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,159}$")
_MAX_WSL_OUTPUT = 64 * 1_024
_TARGET_ROOT_SUFFIX = ".local/share/Xenix/amd-runtime"
_TARGET_ROOT_SCRIPT = "set -eu\nprintf '%s\\n' \"$HOME\""
_RESOLVE_EXECUTABLE_SCRIPT = 'set -eu\nreadlink -f -- "$1"'
_ALLOCATE_LOOPBACK_PORT_SCRIPT = (
    "set -eu\npython3 -c 'import socket; s=socket.socket(); "
    's.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()\''
)
_SELF_TEST_SCRIPT = r"""
set -eu
[ "$(uname -s)" = Linux ] || exit 31
for tool in sh flock setsid readlink awk grep; do
    command -v "$tool" >/dev/null 2>&1 || exit 32
done
[ -r /proc/self/stat ] || exit 33
[ -r /proc/version ] || exit 34
grep -qi 'wsl2\|microsoft-standard' /proc/version || exit 35
printf 'xenix-wsl-target-v1\n'
""".strip()
_TARGET_FACTS_SCRIPT = r"""
set -eu
target_root=$1
for tool in uname awk python3 rocminfo hipcc df; do
    command -v "$tool" >/dev/null 2>&1 || exit 31
done
[ -r /etc/os-release ] && [ -r /proc/meminfo ] && [ -r /proc/version ] && [ -r /opt/rocm/.info/version ] || exit 32
grep -qi 'wsl2\|microsoft-standard' /proc/version || exit 33
. /etc/os-release
parent=${target_root%/*}
while [ ! -d "$parent" ]; do
    next=${parent%/*}
    [ "$next" != "$parent" ] || exit 34
    parent=$next
done
gpu_agents=$(rocminfo | awk '$1 == "Name:" && $2 ~ /^gfx[0-9a-z]+$/ { print $2 }')
gpu_architectures=$(printf '%s\n' "$gpu_agents" | sort -u | paste -sd, -)
[ -n "$gpu_architectures" ] || exit 35
gpu_count=$(printf '%s\n' "$gpu_agents" | awk 'END { print NR }')
hip_memory=$(python3 - <<'PY'
import ctypes
import ctypes.util
import sys

library_name = ctypes.util.find_library("amdhip64") or "libamdhip64.so"
try:
    hip = ctypes.CDLL(library_name)
except OSError:
    sys.exit(1)
hip.hipInit.argtypes = [ctypes.c_uint]
hip.hipInit.restype = ctypes.c_int
hip.hipGetDeviceCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
hip.hipGetDeviceCount.restype = ctypes.c_int
hip.hipSetDevice.argtypes = [ctypes.c_int]
hip.hipSetDevice.restype = ctypes.c_int
hip.hipMemGetInfo.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
hip.hipMemGetInfo.restype = ctypes.c_int
if hip.hipInit(0) != 0:
    sys.exit(2)
count = ctypes.c_int()
if hip.hipGetDeviceCount(ctypes.byref(count)) != 0 or count.value < 1:
    sys.exit(3)
free_total = 0
for index in range(count.value):
    if hip.hipSetDevice(index) != 0:
        sys.exit(4)
    free = ctypes.c_size_t()
    total = ctypes.c_size_t()
    if hip.hipMemGetInfo(ctypes.byref(free), ctypes.byref(total)) != 0:
        sys.exit(5)
    free_total += free.value
print(count.value, free_total)
PY
)
set -- $hip_memory
[ "$#" = 2 ] || exit 36
[ "$1" = "$gpu_count" ] || exit 37
case "$2" in *[!0-9]*|'') exit 38 ;; esac
free_memory=$(awk '/^MemAvailable:/ { print $2 * 1024; found=1 } END { exit found ? 0 : 1 }' /proc/meminfo)
hip_version=$(hipcc --version | awk '/^HIP version:/ { print $3; found=1 } END { exit found ? 0 : 1 }')
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
printf 'wsl_kernel\t%s\n' "$(uname -r)"
printf 'os_name\t%s\n' "$NAME"
printf 'os_version\t%s\n' "$VERSION_ID"
printf 'kernel_version\t%s\n' "$(uname -r)"
printf 'architecture\t%s\n' "$(uname -m)"
printf 'gpu_architectures\t%s\n' "$gpu_architectures"
printf 'rocm_version\t%s\n' "$(cat /opt/rocm/.info/version)"
printf 'hip_version\t%s\n' "$hip_version"
printf 'python_version\t%s\n' "$python_version"
printf 'gpu_count\t%s\n' "$gpu_count"
printf 'free_vram_bytes\t%s\n' "$2"
printf 'free_system_memory_bytes\t%s\n' "$free_memory"
printf 'free_persistent_bytes\t%s\n' "$(df -B1 --output=avail "$parent" | awk 'NR == 2 { print $1 }')"
""".strip()


class WslPlacementError(AmdPlacementError):
    """WSL target operation failed without exposing target output or secrets."""

    error_code = "amd_wsl_operation_failed"


class WslDistributionError(WslPlacementError):
    """The explicitly selected WSL distribution is invalid or unavailable."""

    error_code = "amd_wsl_distribution_unavailable"


class WslClientUnavailableError(WslPlacementError):
    """Windows could not start its fixed WSL client."""

    error_code = "amd_wsl_client_unavailable"


class WslCommandTimeoutError(WslPlacementError):
    """A bounded WSL target operation exceeded its deadline."""

    error_code = "amd_wsl_operation_timeout"


class WslRecipeError(WslPlacementError):
    """A caller requested a recipe outside the composition-owned catalogue."""

    error_code = "amd_wsl_recipe_unavailable"


@dataclass(frozen=True, slots=True)
class WslTarget:
    """Explicit, durable-safe reference to one local WSL Linux target."""

    target_id: str
    distribution: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.target_id, "WSL target ID")
        _require_distribution(self.distribution)


@dataclass(frozen=True, slots=True)
class WslTargetRecipe:
    """Bundled target program admitted by composition, never user shell input."""

    recipe_id: str
    script: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.recipe_id, "WSL recipe ID")
        _require_recipe_script(self.script)


@dataclass(frozen=True, slots=True)
class WslTargetFacts:
    """Read-only WSL observations, preserving the target-kind fact explicitly.

    ``compatibility`` retains both the actual WSL kernel version and the WSL2
    target-kind proof.  A caller must not silently project this as an ordinary
    native-Linux target.
    """

    compatibility: TargetCompatibilityFacts
    is_wsl2: bool = True

    def __post_init__(self) -> None:
        if self.is_wsl2 is not True:
            raise WslPlacementError("WSL target facts must identify WSL2.")


@dataclass(frozen=True, slots=True)
class _WslCommandResult:
    """Bounded Windows-side process result; stderr never leaves this boundary."""

    return_code: int
    stdout: bytes = field(repr=False, default=b"")
    stderr: bytes = field(repr=False, default=b"")


class _WslProcessRunner(Protocol):
    """Injectable fixed-process boundary; callers cannot select an executable."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: bytes | None,
        timeout_seconds: float,
    ) -> _WslCommandResult: ...


class WslLoopbackVerifier(Protocol):
    """Prove that a Windows loopback binding reaches its exact WSL generation.

    Implementations are capability-owned: they must make an authenticated
    request using ``binding`` and reject a response that cannot prove
    ``generation``.  A plain TCP connect is deliberately insufficient because
    Windows could have another process on the same local port.
    """

    def verify(
        self,
        binding: LoopbackHttpBinding,
        generation: RemoteGenerationIdentity,
        *,
        timeout_seconds: float,
    ) -> None: ...


class _SubprocessWslRunner:
    """Production implementation for a fixed ``wsl.exe`` client invocation."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: bytes | None,
        timeout_seconds: float,
    ) -> _WslCommandResult:
        try:
            completed = subprocess.run(
                tuple(arguments),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout_seconds,
                creationflags=_no_window_creation_flags(),
            )
        except subprocess.TimeoutExpired:
            raise WslCommandTimeoutError("WSL target operation exceeded its deadline.") from None
        except OSError:
            raise WslClientUnavailableError("WSL client could not be started.") from None
        return _WslCommandResult(
            return_code=completed.returncode,
            stdout=completed.stdout[: _MAX_WSL_OUTPUT + 1],
            stderr=completed.stderr[: _MAX_WSL_OUTPUT + 1],
        )


class _WslSupervisorTransport:
    """Private RemoteSupervisor transport over one immutable WSL distribution."""

    def __init__(self, target: WslTarget, process_runner: _WslProcessRunner) -> None:
        self._target = target
        self._process_runner = process_runner

    def run_script(
        self,
        script: str,
        arguments: tuple[str, ...] = (),
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
    ) -> RemoteScriptResult:
        _require_target_script(script)
        _require_deadline(timeout_seconds)
        for argument in arguments:
            _require_argument(argument)
        result = self._process_runner.run(
            (
                "wsl.exe",
                "--distribution",
                self._target.distribution,
                "--exec",
                "/bin/sh",
                "-c",
                script,
                "xenix-wsl-supervisor",
                *arguments,
            ),
            stdin=stdin,
            timeout_seconds=float(timeout_seconds),
        )
        if len(result.stdout) > _MAX_WSL_OUTPUT or len(result.stderr) > _MAX_WSL_OUTPUT:
            raise WslPlacementError("WSL target output exceeded its safety bound.")
        if result.return_code < 0:
            raise WslPlacementError("WSL target process terminated unexpectedly.")
        return RemoteScriptResult(return_code=result.return_code, stdout=result.stdout)


@dataclass(slots=True)
class _WslRealization:
    observation: RemoteProcessObservation = field(repr=False)
    binding: LoopbackHttpBinding = field(repr=False)


class WslAmdExecutionSession(AmdExecutionSession):
    """One WSL target session governed by exact remote generation fences."""

    def __init__(
        self,
        *,
        target: WslTarget,
        incarnation: RuntimeIncarnation,
        supervisor: RemoteSupervisor,
        transport: _WslSupervisorTransport,
        recipes: Mapping[str, WslTargetRecipe],
        token_factory: Callable[[], str],
        target_root: str,
        loopback_verifier: WslLoopbackVerifier,
    ) -> None:
        self._target = target
        self._incarnation = incarnation
        self._supervisor = supervisor
        self._transport = transport
        self._recipes = dict(recipes)
        self._token_factory = token_factory
        self._target_root = target_root
        self._loopback_verifier = loopback_verifier
        self._realizations: dict[AmdRuntimeKey, _WslRealization] = {}
        self._stopped: dict[AmdRuntimeKey, RemoteProcessObservation] = {}
        self._closed = False

    @property
    def incarnation(self) -> RuntimeIncarnation:
        return self._incarnation

    @property
    def target(self) -> WslTarget:
        return self._target

    @property
    def target_root(self) -> str:
        """Ephemeral WSL path derived from the selected distribution's home."""

        return self._target_root

    def observe(self, generation: RemoteGenerationIdentity) -> RemoteProcessObservation | None:
        self._require_generation(generation, "WSL observation")
        return self._supervisor.observe(generation)

    def observe_target_facts(self) -> WslTargetFacts:
        """Collect WSL facts using ``rocminfo`` and HIP, never ``rocm-smi``."""

        self._require_open()
        result = self._transport.run_script(
            _TARGET_FACTS_SCRIPT,
            (self._target_root,),
            timeout_seconds=30.0,
        )
        if result.return_code != 0 or len(result.stdout) > 8_192:
            raise WslPlacementError("WSL target compatibility facts could not be observed.")
        return _parse_target_facts(result.stdout)

    def realize(self, spec: RemoteLaunchSpec) -> LoopbackHttpBinding:
        """Start one fenced Linux process and expose only its Windows loopback URL."""

        self._require_generation(spec.generation, "WSL launch")
        key = spec.generation.runtime_key
        existing = self._realizations.get(key)
        if existing is not None:
            if existing.observation.matches(spec):
                return self.resolve_binding(key)
            raise WslPlacementError("A different WSL realization already owns this runtime key.")

        token = self._token_factory()
        secret = ProtectedRuntimeSecret(token)
        observation = self._supervisor.start(spec, secret)
        binding = LoopbackHttpBinding(
            base_url=f"http://127.0.0.1:{spec.remote_loopback_port}",
            bearer_token=token,
        )
        try:
            self._loopback_verifier.verify(
                binding,
                spec.generation,
                timeout_seconds=spec.startup_deadline_seconds,
            )
        except Exception:
            try:
                self._supervisor.stop(observation)
            except AmdPlacementError:
                pass
            raise WslPlacementError("Windows loopback could not be proven to reach the exact WSL runtime.") from None
        self._realizations[key] = _WslRealization(observation=observation, binding=binding)
        return binding

    def prepare_recipe_root(self, generation: RemoteGenerationIdentity) -> str:
        self._require_generation(generation, "WSL recipe")
        return self._supervisor.prepare_recipe_root(generation)

    def run_generation_recipe(
        self,
        generation: RemoteGenerationIdentity,
        recipe_id: str,
        arguments: tuple[str, ...] = (),
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
    ) -> RemoteScriptResult:
        """Run one composition-admitted recipe; raw shell source is never accepted."""

        self._require_generation(generation, "WSL recipe")
        _require_identifier(recipe_id, "WSL recipe ID")
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            raise WslRecipeError("WSL target recipe is not admitted for this session.")
        return self._supervisor.run_generation_recipe(
            generation,
            recipe.script,
            tuple(arguments),
            stdin=stdin,
            timeout_seconds=timeout_seconds,
        )

    def resolve_process_executable(self, command_executable: str) -> str:
        """Resolve a target executable through a fixed, non-recipe program."""

        self._require_open()
        if not isinstance(command_executable, str) or not command_executable.startswith("/"):
            raise WslPlacementError("WSL command executable is invalid.")
        result = self._transport.run_script(
            _RESOLVE_EXECUTABLE_SCRIPT,
            (command_executable,),
            timeout_seconds=15.0,
        )
        if result.return_code != 0 or len(result.stdout) > 4_096:
            raise WslPlacementError("WSL command executable could not be resolved.")
        try:
            executable = result.stdout.decode("utf-8", errors="strict").removesuffix("\n")
        except UnicodeDecodeError:
            raise WslPlacementError("WSL command executable could not be resolved.") from None
        path = PurePosixPath(executable)
        if not executable or not path.is_absolute() or ".." in path.parts or "\r" in executable or "\n" in executable:
            raise WslPlacementError("WSL command executable could not be resolved.")
        return executable

    def allocate_remote_loopback_port(self) -> int:
        """Return a WSL loopback port candidate without reserving persistent state."""

        self._require_open()
        result = self._transport.run_script(_ALLOCATE_LOOPBACK_PORT_SCRIPT, timeout_seconds=15.0)
        if result.return_code != 0 or len(result.stdout) > 16:
            raise WslPlacementError("WSL loopback port could not be allocated.")
        try:
            port = int(result.stdout.decode("ascii", errors="strict").strip())
        except (UnicodeDecodeError, ValueError):
            raise WslPlacementError("WSL loopback port could not be allocated.") from None
        if not 1_024 <= port <= 65_535:
            raise WslPlacementError("WSL loopback port could not be allocated.")
        return port

    def resolve_binding(self, key: AmdRuntimeKey) -> LoopbackHttpBinding:
        self._require_open()
        realization = self._realizations.get(key)
        if realization is None:
            raise WslPlacementError("Managed WSL runtime binding is unavailable.")
        try:
            observed = self._supervisor.observe(realization.observation.generation)
        except AmdPlacementError:
            self._realizations.pop(key, None)
            raise WslPlacementError("Managed WSL runtime identity could not be revalidated.") from None
        if observed != realization.observation:
            self._realizations.pop(key, None)
            raise WslPlacementError("Managed WSL runtime identity changed.")
        return realization.binding

    def stop(self, key: AmdRuntimeKey) -> None:
        self._require_open()
        realization = self._realizations.get(key)
        if realization is None:
            return
        self._supervisor.stop(realization.observation)
        self._realizations.pop(key, None)
        self._stopped[key] = realization.observation

    def retire_and_cleanup_generation(
        self,
        *,
        key: AmdRuntimeKey,
        manifest_digest: str,
        owned_relative_paths: tuple[str, ...],
    ) -> None:
        """Retire only a generation that the Linux supervisor can fence exactly."""

        self._require_open()
        self._supervisor.cancel_provisioning_for_retirement(
            runtime_key=key,
            manifest_digest=manifest_digest,
        )
        if self._supervisor.cleanup_provisioned_generation(
            runtime_key=key,
            manifest_digest=manifest_digest,
            owned_relative_paths=owned_relative_paths,
        ) or self._supervisor.cleanup_empty_generation(
            runtime_key=key,
            manifest_digest=manifest_digest,
        ):
            return
        if key in self._realizations:
            self.stop(key)
        observation = self._stopped.get(key)
        if observation is None:
            observation = self._supervisor.recover_stopped_observation(
                runtime_key=key,
                manifest_digest=manifest_digest,
            )
        if observation.generation.runtime_key != key or observation.generation.manifest_digest != manifest_digest:
            raise WslPlacementError("Recovered WSL generation identity changed.")
        self._supervisor.cleanup_generation(observation, owned_relative_paths)
        self._stopped.pop(key, None)

    def close(self) -> None:
        if self._closed:
            return
        failures = False
        for key, realization in tuple(self._realizations.items()):
            try:
                self._supervisor.stop(realization.observation)
            except AmdPlacementError:
                try:
                    self._supervisor.reap_stale_receipt(realization.observation.generation)
                except AmdPlacementError:
                    failures = True
                    continue
            self._realizations.pop(key, None)
            self._stopped[key] = realization.observation
        self._closed = True
        if failures:
            raise WslPlacementError("One or more exact WSL realizations could not be stopped safely.")

    def _require_generation(self, generation: RemoteGenerationIdentity, operation: str) -> None:
        self._require_open()
        if generation.incarnation != self._incarnation:
            raise WslPlacementError(f"{operation} incarnation does not belong to this session.")

    def _require_open(self) -> None:
        if self._closed:
            raise WslPlacementError("WSL execution session is closed.")


class WslAmdPlacement:
    """Open an explicit WSL2 distribution as a restricted Linux target session."""

    def __init__(
        self,
        *,
        recipes: Mapping[str, WslTargetRecipe] | None = None,
        target_root_suffix: str = _TARGET_ROOT_SUFFIX,
        process_runner: _WslProcessRunner | None = None,
        token_factory: Callable[[], str] | None = None,
        loopback_verifier: WslLoopbackVerifier,
    ) -> None:
        if loopback_verifier is None:
            raise WslPlacementError("WSL loopback verifier is required.")
        self._recipes = _validated_recipe_catalogue(recipes or {})
        self._target_root_suffix = _require_target_root_suffix(target_root_suffix)
        self._process_runner = process_runner or _SubprocessWslRunner()
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._loopback_verifier = loopback_verifier

    def list_distributions(self) -> tuple[str, ...]:
        """List explicit WSL distributions without selecting a default target."""

        result = self._process_runner.run(
            ("wsl.exe", "--list", "--quiet"),
            stdin=None,
            timeout_seconds=15.0,
        )
        if result.return_code != 0 or len(result.stdout) > _MAX_WSL_OUTPUT:
            raise WslDistributionError("WSL distributions could not be listed.")
        return _parse_distribution_listing(result.stdout)

    def self_test(self, target: WslTarget) -> None:
        """Run read-only WSL dispatch and target-supervision prerequisite checks."""

        transport = _WslSupervisorTransport(target, self._process_runner)
        result = transport.run_script(_SELF_TEST_SCRIPT, timeout_seconds=20.0)
        if result.return_code != 0 or result.stdout != b"xenix-wsl-target-v1\n":
            raise WslDistributionError("Selected WSL distribution failed the managed target self-test.")
        root = _resolve_target_root(transport, self._target_root_suffix)
        supervisor = RemoteSupervisor(transport, target_id=target.target_id, product_root=root)
        supervisor.probe_prerequisites()

    def open_session(self, target: WslTarget, incarnation: RuntimeIncarnation) -> WslAmdExecutionSession:
        """Open one session only after read-only distribution and supervisor checks."""

        transport = _WslSupervisorTransport(target, self._process_runner)
        result = transport.run_script(_SELF_TEST_SCRIPT, timeout_seconds=20.0)
        if result.return_code != 0 or result.stdout != b"xenix-wsl-target-v1\n":
            raise WslDistributionError("Selected WSL distribution failed the managed target self-test.")
        root = _resolve_target_root(transport, self._target_root_suffix)
        supervisor = RemoteSupervisor(transport, target_id=target.target_id, product_root=root)
        supervisor.probe_prerequisites()
        return WslAmdExecutionSession(
            target=target,
            incarnation=incarnation,
            supervisor=supervisor,
            transport=transport,
            recipes=self._recipes,
            token_factory=self._token_factory,
            target_root=root,
            loopback_verifier=self._loopback_verifier,
        )


def _resolve_target_root(transport: _WslSupervisorTransport, suffix: str) -> str:
    result = transport.run_script(_TARGET_ROOT_SCRIPT, timeout_seconds=15.0)
    if result.return_code != 0 or len(result.stdout) > 1_024:
        raise WslDistributionError("WSL target home directory could not be resolved.")
    try:
        home = result.stdout.decode("utf-8", errors="strict").removesuffix("\n")
    except UnicodeDecodeError:
        raise WslDistributionError("WSL target home directory could not be resolved.") from None
    path = PurePosixPath(home)
    if (
        not home
        or "\r" in home
        or "\n" in home
        or not path.is_absolute()
        or ".." in path.parts
        or str(path) in {"/", "/home"}
    ):
        raise WslDistributionError("WSL target home directory is unsafe.")
    return str(path / suffix)


def _validated_recipe_catalogue(recipes: Mapping[str, WslTargetRecipe]) -> dict[str, WslTargetRecipe]:
    try:
        items = tuple(recipes.items())
    except AttributeError:
        raise WslRecipeError("WSL recipe catalogue is invalid.") from None
    catalogue: dict[str, WslTargetRecipe] = {}
    for recipe_id, recipe in items:
        _require_identifier(recipe_id, "WSL recipe ID")
        if not isinstance(recipe, WslTargetRecipe) or recipe.recipe_id != recipe_id:
            raise WslRecipeError("WSL recipe catalogue is invalid.")
        catalogue[recipe_id] = recipe
    return catalogue


def _parse_target_facts(payload: bytes) -> WslTargetFacts:
    try:
        text = payload.decode("utf-8", errors="strict")
        values: dict[str, str] = {}
        for line in text.splitlines():
            key, value = line.split("\t", 1)
            if key in values or not value or "\t" in value:
                raise ValueError
            values[key] = value
        expected = {
            "architecture",
            "free_persistent_bytes",
            "free_system_memory_bytes",
            "free_vram_bytes",
            "gpu_architectures",
            "gpu_count",
            "hip_version",
            "kernel_version",
            "os_name",
            "os_version",
            "python_version",
            "rocm_version",
            "wsl_kernel",
        }
        if set(values) != expected or values["wsl_kernel"] != values["kernel_version"]:
            raise ValueError
        architectures = tuple(item for item in values["gpu_architectures"].split(",") if item)
        return WslTargetFacts(
            compatibility=TargetCompatibilityFacts(
                os_name=values["os_name"],
                os_version=values["os_version"],
                kernel_version=values["kernel_version"],
                architecture=values["architecture"],
                gpu_architectures=architectures,
                driver_version=None,
                rocm_version=values["rocm_version"],
                hip_version=values["hip_version"],
                python_version=values["python_version"],
                gpu_count=int(values["gpu_count"]),
                free_vram_bytes=int(values["free_vram_bytes"]),
                free_system_memory_bytes=int(values["free_system_memory_bytes"]),
                free_persistent_bytes=int(values["free_persistent_bytes"]),
                target_kind=CompatibilityTargetKind.WSL2,
                wsl_runtime_proven=True,
            )
        )
    except (UnicodeDecodeError, ValueError):
        raise WslPlacementError("WSL target compatibility facts were malformed.") from None


def _parse_distribution_listing(payload: bytes) -> tuple[str, ...]:
    if not isinstance(payload, bytes) or len(payload) > _MAX_WSL_OUTPUT:
        raise WslDistributionError("WSL distributions could not be listed.")
    try:
        if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = payload.decode("utf-16")
        elif b"\x00" in payload:
            text = payload.decode("utf-16-le")
        else:
            text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise WslDistributionError("WSL distributions could not be listed.") from None
    distributions: list[str] = []
    for value in text.splitlines():
        if not value:
            continue
        _require_distribution(value)
        if value not in distributions:
            distributions.append(value)
    return tuple(distributions)


def _require_distribution(value: str) -> None:
    if (
        not isinstance(value, str)
        or not _DISTRIBUTION.fullmatch(value)
        or value != value.strip()
        or value.startswith("-")
    ):
        raise WslDistributionError("WSL distribution name is invalid.", error_code="amd_wsl_distribution_invalid")


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise WslPlacementError(f"{label} is invalid.")


def _require_target_root_suffix(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or "\x00" in value:
        raise WslPlacementError("Managed WSL target root suffix is invalid.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise WslPlacementError("Managed WSL target root suffix is invalid.")
    return str(path)


def _require_recipe_script(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 64 * 1_024 or "\x00" in value:
        raise WslRecipeError("WSL bundled recipe is invalid.")


def _require_target_script(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 64 * 1_024 or "\x00" in value:
        raise WslPlacementError("WSL target supervision program is invalid.")


def _require_argument(value: str) -> None:
    if not isinstance(value, str) or len(value) > 16_384 or "\x00" in value:
        raise WslPlacementError("WSL target argument is invalid.")


def _require_deadline(value: float) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0 < float(value) <= 7_200:
        raise WslPlacementError("WSL target operation deadline is invalid.")


def _no_window_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


__all__ = [
    "WslAmdExecutionSession",
    "WslAmdPlacement",
    "WslClientUnavailableError",
    "WslCommandTimeoutError",
    "WslDistributionError",
    "WslPlacementError",
    "WslLoopbackVerifier",
    "WslRecipeError",
    "WslTarget",
    "WslTargetFacts",
    "WslTargetRecipe",
]
