"""Same-host Linux/ROCm placement for bundled AMD component recipes."""

from __future__ import annotations

import json
import os
import re
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from uuid import uuid4

from ..compatibility import TargetCompatibilityFacts
from ..components.auth import BearerTokenHandoff
from ..components.process import ManagedProcess
from ..manifests import ExecutionProfileManifest, ManifestCapability
from ..placement import (
    AmdExecutionSession,
    AmdMaterializationCancelledError,
    AmdPlacementError,
    AmdRuntimeKey,
    LoopbackHttpBinding,
    RuntimeIncarnation,
)
from ..recipes import ComponentRecipe, recipe_for
from ..reconcile import AmdCancellationSignal, AmdExecutionLocation, AmdGenerationMaterialization
from ..remote_supervisor import RemoteGenerationIdentity
from ..progress import AmdProgressSink
from ..local_supervisor import (
    LocalCleanupRefusedError,
    LocalLaunchSpec,
    LocalProcessObservation,
    LocalSupervisor,
    LocalSupervisorError,
)


class LocalRecipePlacementError(AmdPlacementError):
    """A same-host AMD recipe could not be realized without weakening a fence."""


_PROVISION_TIMEOUT_SECONDS = 7_200.0
_LOCAL_TARGET_ID = "local-linux"


@dataclass(slots=True)
class _LocalRealization:
    process: ManagedProcess = field(repr=False)
    observation: LocalProcessObservation = field(repr=False)
    binding: LoopbackHttpBinding = field(repr=False)
    token_handoff: BearerTokenHandoff = field(repr=False)
    recipe: ComponentRecipe


@dataclass(slots=True)
class LocalAmdExecutionSession(AmdExecutionSession):
    """One volatile local controller incarnation."""

    supervisor: LocalSupervisor = field(repr=False)
    _incarnation: RuntimeIncarnation = field(repr=False)
    _realizations: dict[AmdRuntimeKey, _LocalRealization] = field(default_factory=dict, repr=False)
    _stopped: dict[AmdRuntimeKey, LocalProcessObservation] = field(default_factory=dict, repr=False)
    _closed: bool = False

    @property
    def incarnation(self) -> RuntimeIncarnation:
        return self._incarnation

    @property
    def target_root(self) -> Path:
        return self.supervisor.product_root

    def resolve_binding(self, key: AmdRuntimeKey) -> LoopbackHttpBinding:
        self._require_open()
        realization = self._realizations.get(key)
        if realization is None:
            raise LocalRecipePlacementError("Local AMD runtime binding is unavailable.")
        if not self.supervisor.observe(realization.observation):
            self._realizations.pop(key, None)
            raise LocalRecipePlacementError("Local AMD runtime identity could not be revalidated.")
        return realization.binding

    def realize(
        self,
        *,
        generation: RemoteGenerationIdentity,
        layout_command: tuple[str, ...],
        layout_environment: tuple[tuple[str, str], ...],
        public_port: int,
        cancellation: AmdCancellationSignal | None = None,
    ) -> LoopbackHttpBinding:
        self._require_open()
        if generation.incarnation != self._incarnation:
            raise LocalRecipePlacementError("Local launch incarnation does not belong to this session.")
        key = generation.runtime_key
        existing = self._realizations.get(key)
        if existing is not None:
            if self.supervisor.observe(existing.observation):
                return existing.binding
            raise LocalRecipePlacementError("A different local process already owns this generation.")
        generation_root = self.supervisor.prepare_generation(generation)
        handoff = self.supervisor.create_token_handoff(generation)
        try:
            process, observation = self.supervisor.start(
                LocalLaunchSpec(
                    generation=generation,
                    command=layout_command,
                    environment=dict(layout_environment),
                    loopback_port=public_port,
                    cwd=generation_root,
                    token_file=handoff.token_file,
                ),
                token_handoff=handoff,
                cancellation=cancellation,
            )
        except Exception:
            try:
                handoff.remove()
            except Exception:
                pass
            raise
        token = handoff.token.value
        binding = LoopbackHttpBinding(base_url=f"http://127.0.0.1:{public_port}", bearer_token=token)
        self._realizations[key] = _LocalRealization(
            process=process,
            observation=observation,
            binding=binding,
            token_handoff=handoff,
            recipe=recipe_for(generation),
        )
        return binding

    def stop(self, key: AmdRuntimeKey) -> None:
        self._require_open()
        realization = self._realizations.get(key)
        if realization is None:
            return
        self.supervisor.stop(realization.process, realization.observation, token_handoff=realization.token_handoff)
        self._realizations.pop(key, None)
        self._stopped[key] = realization.observation

    def retire_and_cleanup_generation(
        self,
        *,
        key: AmdRuntimeKey,
        manifest_digest: str,
        owned_relative_paths: tuple[str, ...],
    ) -> None:
        self._require_open()
        # Persist exact retirement intent before stopping or deleting anything.
        # The supervisor's installation-anchored control lock serializes this
        # claim with forward provisioning, asset publication, and launch.
        self.supervisor.cancel_provisioning_for_retirement(
            runtime_key=key,
            manifest_digest=manifest_digest,
        )
        if key in self._realizations:
            self.stop(key)
        observation = self._stopped.get(key)
        if observation is None:
            observation = self.supervisor.recover_stopped(runtime_key=key, manifest_digest=manifest_digest)
        if observation.generation.manifest_digest != manifest_digest:
            raise LocalRecipePlacementError("Recovered local generation identity changed.")
        self.supervisor.cleanup(observation, owned_relative_paths)
        self._stopped.pop(key, None)

    def close(self) -> None:
        if self._closed:
            return
        failures = False
        for key in tuple(self._realizations):
            realization = self._realizations[key]
            try:
                self.supervisor.stop(realization.process, realization.observation, token_handoff=realization.token_handoff)
                self._realizations.pop(key, None)
                self._stopped[key] = realization.observation
            except (AmdPlacementError, OSError):
                failures = True
        self._closed = True
        if failures:
            raise LocalRecipePlacementError("One or more local AMD processes could not be stopped safely.")

    def _require_open(self) -> None:
        if self._closed:
            raise LocalRecipePlacementError("Local AMD execution session is closed.")


class LocalAmdPlacement:
    """Product controller for ``placement_kind='local_linux'``."""

    placement_kind = "local_linux"

    def __init__(
        self,
        *,
        product_root: Path,
        target_facts_provider: Callable[[], TargetCompatibilityFacts] | None = None,
        supervisor: LocalSupervisor | None = None,
        token_factory: Callable[[], str] | None = None,
        port_factory: Callable[[], int] | None = None,
    ) -> None:
        if not isinstance(product_root, Path):
            product_root = Path(product_root)
        if not product_root.is_absolute():
            raise LocalRecipePlacementError("Local AMD product root must be absolute.")
        self._supervisor = supervisor or LocalSupervisor(
            product_root=product_root,
            target_id=_LOCAL_TARGET_ID,
            token_factory=token_factory,
        )
        if self._supervisor.product_root != product_root:
            raise LocalRecipePlacementError("Local AMD supervisor root does not match the placement root.")
        self._target_facts_provider = target_facts_provider
        self._port_factory = port_factory or _allocate_loopback_port
        self._controller_owner_id = f"amd-controller-{uuid4().hex}"

    def observe(
        self,
        *,
        profile: ExecutionProfileManifest,
        location: AmdExecutionLocation,
    ) -> TargetCompatibilityFacts:
        del profile
        self._require_local_location(location)
        self._supervisor.probe_prerequisites()
        if self._target_facts_provider is not None:
            try:
                facts = self._target_facts_provider()
            except Exception:
                raise LocalRecipePlacementError("Local AMD target facts could not be observed.") from None
            if not isinstance(facts, TargetCompatibilityFacts):
                raise LocalRecipePlacementError("Local AMD target facts are malformed.")
            return facts
        return _observe_local_target(self._supervisor.product_root)

    def materialize(
        self,
        *,
        installation_id: str,
        location: AmdExecutionLocation,
        profile: ExecutionProfileManifest,
        generations: tuple[AmdGenerationMaterialization, ...],
        cancellation: AmdCancellationSignal | None = None,
        progress: AmdProgressSink | None = None,
    ) -> AmdExecutionSession:
        del profile, progress
        self._require_local_location(location)
        self._supervisor.probe_prerequisites()
        session = self._open()
        try:
            for generation in generations:
                self._materialize_generation(session, installation_id, generation, cancellation)
            return session
        except Exception:
            try:
                session.close()
            except Exception:
                pass
            raise

    def open_retirement_session(
        self,
        *,
        installation_id: str,
        location: AmdExecutionLocation,
        profile: ExecutionProfileManifest,
        generations: tuple[AmdGenerationMaterialization, ...],
    ) -> AmdExecutionSession:
        del installation_id, profile, generations
        self._require_local_location(location)
        self._supervisor.probe_prerequisites()
        return self._open()

    def self_test(
        self,
        *,
        session: AmdExecutionSession,
        generation: AmdGenerationMaterialization,
    ) -> str:
        local = _require_local_session(session)
        key = AmdRuntimeKey("_", "_")
        for candidate in local._realizations:
            if local._realizations[candidate].recipe.materialization == generation:
                key = candidate
                break
        if key.installation_id == "_":
            raise LocalRecipePlacementError("Local AMD generation is unavailable in this session.")
        deadline = max(test.deadline_seconds for test in generation.manifest.self_tests)
        binding = _wait_for_binding(local, key, generation, deadline)
        _assert_unauthenticated_rejected(binding, generation)
        recipe = local._realizations[key].recipe
        if recipe.kind == "vllm":
            _assert_vllm_contract(binding, generation)
        elif recipe.kind == "rapidocr":
            _assert_rapidocr_contract(binding, generation)
        else:
            raise LocalRecipePlacementError("Local AMD recipe self-test is unsupported.")
        return f"self-test-{generation.manifest.manifest_digest[:24]}"

    def cancel_generation_provisioning(
        self,
        *,
        session: AmdExecutionSession,
        installation_id: str,
        profile: ExecutionProfileManifest,
        generation: AmdGenerationMaterialization,
    ) -> None:
        del profile
        _require_local_session(session)
        key = AmdRuntimeKey(installation_id=installation_id, component_generation_id=generation.generation_id)
        try:
            self._supervisor.cancel_provisioning_for_retirement(
                runtime_key=key,
                manifest_digest=generation.manifest.manifest_digest,
            )
        except LocalCleanupRefusedError as exc:
            raise LocalRecipePlacementError("Local AMD provisioning cancellation was refused safely.") from exc
        except LocalSupervisorError as exc:
            raise LocalRecipePlacementError("Local AMD provisioning cancellation failed safely.") from exc

    def retire_generation(
        self,
        *,
        session: AmdExecutionSession,
        installation_id: str,
        profile: ExecutionProfileManifest,
        generation: AmdGenerationMaterialization,
    ) -> None:
        del profile
        local = _require_local_session(session)
        recipe = recipe_for(generation)
        key = AmdRuntimeKey(installation_id=installation_id, component_generation_id=generation.generation_id)
        generation_root = self._supervisor.product_root / "installations" / installation_id / "generations" / generation.generation_id
        layout = recipe.launch_layout(
            generation_root=str(generation_root),
            public_port=1_024,
            backend_port=1_025 if recipe.kind == "vllm" else None,
        )
        try:
            self._supervisor.cancel_provisioning_for_retirement(
                runtime_key=key,
                manifest_digest=generation.manifest.manifest_digest,
            )
            if self._supervisor.cleanup_provisioned_generation(
                runtime_key=key,
                manifest_digest=generation.manifest.manifest_digest,
                owned_relative_paths=layout.owned_relative_paths,
            ):
                return
            if self._supervisor.cleanup_empty_generation(
                runtime_key=key,
                manifest_digest=generation.manifest.manifest_digest,
            ):
                return
            local.retire_and_cleanup_generation(
                key=key,
                manifest_digest=generation.manifest.manifest_digest,
                owned_relative_paths=layout.owned_relative_paths,
            )
        except LocalCleanupRefusedError as exc:
            raise LocalRecipePlacementError("Local AMD generation cleanup was refused safely.") from exc
        except LocalSupervisorError as exc:
            raise LocalRecipePlacementError("Local AMD generation cleanup failed safely.") from exc

    def _materialize_generation(
        self,
        session: LocalAmdExecutionSession,
        installation_id: str,
        generation: AmdGenerationMaterialization,
        cancellation: AmdCancellationSignal | None,
    ) -> None:
        _raise_if_cancelled(cancellation)
        recipe = recipe_for(generation)
        identity = RemoteGenerationIdentity(
            runtime_key=AmdRuntimeKey(installation_id=installation_id, component_generation_id=generation.generation_id),
            manifest_digest=generation.manifest.manifest_digest,
            incarnation=session.incarnation,
        )
        generation_root = self._supervisor.prepare_generation(identity)
        result = self._supervisor.run_recipe(
            identity,
            recipe.provisioning_script(),
            recipe.provisioning_arguments(),
            timeout_seconds=_PROVISION_TIMEOUT_SECONDS,
            cancellation=cancellation,
        )
        _raise_if_cancelled(cancellation)
        if result.return_code != 0:
            raise LocalRecipePlacementError("Local AMD target provisioning did not complete.")
        for asset in recipe.target_assets():
            _raise_if_cancelled(cancellation)
            self._supervisor.write_target_asset(
                identity,
                filename=asset.filename,
                source=asset.source,
                executable=asset.executable,
            )
            _raise_if_cancelled(cancellation)
        public_port = _require_allocated_port(self._port_factory)
        backend_port = None
        if recipe.kind == "vllm":
            for _ in range(3):
                candidate = _require_allocated_port(self._port_factory)
                if candidate != public_port:
                    backend_port = candidate
                    break
            if backend_port is None:
                raise LocalRecipePlacementError("Local loopback ports could not be separated safely.")
        layout = recipe.launch_layout(generation_root=str(generation_root), public_port=public_port, backend_port=backend_port)
        _raise_if_cancelled(cancellation)
        session.realize(
            generation=identity,
            layout_command=layout.command,
            layout_environment=layout.environment,
            public_port=public_port,
            cancellation=cancellation,
        )

    def _open(self) -> LocalAmdExecutionSession:
        incarnation = RuntimeIncarnation(
            controller_owner_id=self._controller_owner_id,
            incarnation_id=f"amd-incarnation-{uuid4().hex}",
        )
        return LocalAmdExecutionSession(supervisor=self._supervisor, _incarnation=incarnation)

    @staticmethod
    def _require_local_location(location: AmdExecutionLocation) -> None:
        if not isinstance(location, AmdExecutionLocation) or location.placement_kind != "local_linux":
            raise LocalRecipePlacementError("Historical Local Linux AMD placement received the wrong execution location.")


def _require_local_session(session: AmdExecutionSession) -> LocalAmdExecutionSession:
    if not isinstance(session, LocalAmdExecutionSession):
        raise LocalRecipePlacementError("Local AMD placement received the wrong execution session.")
    return session


def _raise_if_cancelled(cancellation: AmdCancellationSignal | None) -> None:
    if cancellation is not None and cancellation.is_set():
        raise AmdMaterializationCancelledError("AMD materialization was cancelled by retirement.")


def _allocate_loopback_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
    except OSError:
        raise LocalRecipePlacementError("A local loopback port could not be allocated.") from None
    if not 1_024 <= port <= 65_535:
        raise LocalRecipePlacementError("A local loopback port could not be allocated.")
    return port


def _require_allocated_port(factory: Callable[[], int]) -> int:
    try:
        value = factory()
    except Exception:
        raise LocalRecipePlacementError("A local loopback port could not be allocated.") from None
    if not isinstance(value, int) or isinstance(value, bool) or not 1_024 <= value <= 65_535:
        raise LocalRecipePlacementError("A local loopback port could not be allocated.")
    return value


def _wait_for_binding(
    session: LocalAmdExecutionSession,
    key: AmdRuntimeKey,
    generation: AmdGenerationMaterialization,
    deadline_seconds: float,
) -> LoopbackHttpBinding:
    deadline = time.monotonic() + deadline_seconds
    while True:
        try:
            binding = session.resolve_binding(key)
            _request_bytes(
                binding,
                _readiness_path(generation),
                method="GET",
                body=None,
                authenticated=True,
                timeout_seconds=5.0,
            )
            return binding
        except (AmdPlacementError, OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
            if time.monotonic() >= deadline:
                raise LocalRecipePlacementError("Local AMD target did not become ready before its deadline.") from None
            time.sleep(0.5)


def _readiness_path(generation: AmdGenerationMaterialization) -> str:
    if generation.capability is ManifestCapability.OCR:
        return f"/v2/models/{generation.manifest.launch.served_model_name}/ready"
    return "/health"


def _assert_unauthenticated_rejected(binding: LoopbackHttpBinding, generation: AmdGenerationMaterialization) -> None:
    path = "/v1/models" if generation.capability is not ManifestCapability.OCR else "/v2/models/rapidocr-ppocrv6"
    try:
        _request_bytes(binding, path, method="GET", body=None, authenticated=False, timeout_seconds=10.0)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return
        raise LocalRecipePlacementError("Local AMD authentication self-test returned an unexpected status.") from None
    except (OSError, urllib.error.URLError):
        raise LocalRecipePlacementError("Local AMD authentication self-test could not complete.") from None
    raise LocalRecipePlacementError("Local AMD target accepted an unauthenticated request.")


def _assert_vllm_contract(binding: LoopbackHttpBinding, generation: AmdGenerationMaterialization) -> None:
    model = generation.manifest.launch.served_model_name
    if generation.capability is ManifestCapability.CHAT:
        response = _json_response(binding, "/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": "Reply with the word ready."}], "max_tokens": 8, "stream": False})
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise LocalRecipePlacementError("Local Chat self-test returned an invalid response.")
        _assert_chat_stream(binding, model)
        _assert_chat_tool_call(binding, model)
        return
    if generation.capability is ManifestCapability.EMBEDDING:
        response = _json_response(binding, "/v1/embeddings", {"model": model, "input": ["Xenix AMD embedding self-test."]})
        try:
            vector = response["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LocalRecipePlacementError("Local Embedding self-test returned an invalid response.") from exc
        if not isinstance(vector, list) or len(vector) != 1024:
            raise LocalRecipePlacementError("Local Embedding self-test returned the wrong vector space.")
        return
    raise LocalRecipePlacementError("vLLM recipe received the wrong capability.")


def _assert_chat_stream(binding: LoopbackHttpBinding, model: str) -> None:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the word ready."}],
        "max_tokens": 8,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    raw = _request_bytes(
        binding,
        "/v1/chat/completions",
        method="POST",
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        authenticated=True,
        timeout_seconds=180.0,
        extra_headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    if b"data: " not in raw or b"[DONE]" not in raw:
        raise LocalRecipePlacementError("Local Chat streaming self-test returned an invalid SSE response.")


def _assert_chat_tool_call(binding: LoopbackHttpBinding, model: str) -> None:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Use the supplied get_status tool now. Do not answer with ordinary text.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_status",
                    "description": "Return the Xenix AMD deployment status.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "get_status"}},
        "max_tokens": 96,
        "stream": False,
    }
    response = _json_response(binding, "/v1/chat/completions", payload)
    try:
        tool_calls = response["choices"][0]["message"]["tool_calls"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LocalRecipePlacementError("Local Chat self-test did not return a Tool Call.") from exc
    if not isinstance(tool_calls, list) or not tool_calls:
        raise LocalRecipePlacementError("Local Chat self-test did not return a Tool Call.")
    first = tool_calls[0]
    if not isinstance(first, dict) or first.get("type") != "function":
        raise LocalRecipePlacementError("Local Chat self-test returned an invalid Tool Call.")
    function = first.get("function")
    if not isinstance(function, dict) or function.get("name") != "get_status":
        raise LocalRecipePlacementError("Local Chat self-test returned the wrong Tool Call.")


def _assert_rapidocr_contract(binding: LoopbackHttpBinding, generation: AmdGenerationMaterialization) -> None:
    model = generation.manifest.launch.served_model_name
    image = _png_fixture()
    packed = struct.pack("<I", len(image)) + image
    header = json.dumps({"id": "amd-self-test", "inputs": [{"name": "image", "datatype": "BYTES", "shape": [1], "parameters": {"binary_data_size": len(packed), "content_type": "image/png"}}], "outputs": [{"name": "page_xml", "parameters": {"binary_data": True}}]}, separators=(",", ":")).encode()
    raw = _request_bytes(binding, f"/v2/models/{model}/infer", method="POST", body=header + packed, authenticated=True, timeout_seconds=180.0, extra_headers={"Content-Type": "application/octet-stream", "Inference-Header-Content-Length": str(len(header))})
    if b"http://schema.primaresearch.org/PAGE/gts/pagecontent/2024-07-15" not in raw:
        raise LocalRecipePlacementError("Local OCR self-test did not return PAGE XML.")


def _json_response(binding: LoopbackHttpBinding, path: str, payload: object) -> object:
    raw = _request_bytes(binding, path, method="POST", body=json.dumps(payload, separators=(",", ":")).encode(), authenticated=True, timeout_seconds=180.0, extra_headers={"Content-Type": "application/json"})
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalRecipePlacementError("Local AMD self-test returned invalid JSON.") from exc


def _request_bytes(binding: LoopbackHttpBinding, path: str, *, method: str, body: bytes | None, authenticated: bool, timeout_seconds: float, extra_headers: dict[str, str] | None = None) -> bytes:
    headers = dict(extra_headers or {})
    if authenticated:
        headers["Authorization"] = binding.authorization_header()
    request = urllib.request.Request(binding.base_url + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024:
        raise LocalRecipePlacementError("Local AMD self-test response exceeds its bound.")
    return payload


def _png_fixture() -> bytes:
    width, height = 64, 32
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _observe_local_target(product_root: Path) -> TargetCompatibilityFacts:
    if os.name != "posix" or not __import__("sys").platform == "linux":
        raise LocalRecipePlacementError("Local AMD placement requires Linux.")
    try:
        os_release = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os_release[key] = value.strip().strip('"')
        gpu_lines = subprocess.run(["rocm_agent_enumerator"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False).stdout.decode()
        gpu_agents = [line.strip() for line in gpu_lines.splitlines() if re.fullmatch(r"gfx[0-9a-z]+", line.strip())]
        gpu_architectures = tuple(sorted(set(gpu_agents)))
        if not gpu_architectures:
            raise ValueError
        hip = subprocess.run(["hipcc", "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False).stdout.decode()
        hip_version = next((line.split(":", 1)[1].strip() for line in hip.splitlines() if line.startswith("HIP version:")), None)
        if not hip_version:
            raise ValueError
        smi = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
        data = json.loads(smi.stdout.decode())
        free_vram = sum(int(card["VRAM Total Memory (B)"]) - int(card["VRAM Total Used Memory (B)"]) for card in data.values())
        free_memory = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
        stat = os.statvfs(product_root.parent)
        free_persistent = stat.f_bavail * stat.f_frsize
        driver = Path("/sys/module/amdgpu/version").read_text(encoding="utf-8").strip()
        rocm = Path("/opt/rocm/.info/version").read_text(encoding="utf-8").strip()
        python_version = ".".join(map(str, __import__("sys").version_info[:3]))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, UnicodeDecodeError, StopIteration, json.JSONDecodeError):
        raise LocalRecipePlacementError("Local AMD target compatibility facts could not be observed.") from None
    try:
        return TargetCompatibilityFacts(
            os_name=os_release.get("NAME"), os_version=os_release.get("VERSION_ID"), kernel_version=__import__("platform").release(), architecture=__import__("platform").machine(), gpu_architectures=gpu_architectures, driver_version=driver, rocm_version=rocm, hip_version=hip_version, python_version=python_version, gpu_count=len(gpu_agents), free_vram_bytes=free_vram, free_system_memory_bytes=free_memory, free_persistent_bytes=free_persistent,
        )
    except ValueError:
        raise LocalRecipePlacementError("Local AMD target compatibility facts were invalid.") from None


__all__ = ["LocalAmdExecutionSession", "LocalAmdPlacement", "LocalRecipePlacementError"]
