"""Private SSH placement controller for bundled AMD target recipes."""

from __future__ import annotations

import json
import struct
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from uuid import uuid4

from ..compatibility import TargetCompatibilityFacts
from ..manifests import ExecutionProfileManifest, ManifestCapability
from ..placement import (
    AmdExecutionSession,
    AmdMaterializationCancelledError,
    AmdPlacementError,
    AmdRuntimeKey,
    LoopbackHttpBinding,
    RuntimeIncarnation,
)
from ..progress import AmdProgressMilestone, AmdProgressSink, report_progress
from ..reconcile import AmdCancellationSignal, AmdExecutionLocation, AmdGenerationMaterialization
from ..remote_supervisor import RemoteEnvironmentSetting, RemoteGenerationIdentity, RemoteLaunchSpec
from ..recipes import ComponentRecipe, TargetAsset, recipe_for, target_asset_upload_script
from .ssh import PrivateSshAmdPlacement, SshAmdExecutionSession, SshPlacementError


class PrivateRecipePlacementError(AmdPlacementError):
    """A bundled Private recipe could not be completed safely."""

    error_code = "amd_private_recipe_failed"


_PROVISION_TIMEOUT_SECONDS = 7_200.0
_STARTUP_TIMEOUT_SECONDS = 180.0
@dataclass(slots=True)
class _PrivateRecipeSession(AmdExecutionSession):
    """One SSH session plus volatile recipe metadata."""

    raw: SshAmdExecutionSession
    recipes: dict[AmdRuntimeKey, ComponentRecipe]

    @property
    def incarnation(self) -> RuntimeIncarnation:
        return self.raw.incarnation

    def resolve_binding(self, key: AmdRuntimeKey) -> LoopbackHttpBinding:
        return self.raw.resolve_binding(key)

    def close(self) -> None:
        self.raw.close()

    def recipe_for(self, key: AmdRuntimeKey) -> ComponentRecipe:
        recipe = self.recipes.get(key)
        if recipe is None:
            raise PrivateRecipePlacementError("Private AMD generation is unavailable in this session.")
        return recipe


class PrivateSshRecipePlacement:
    """Product controller for the Private SSH placement kind."""

    placement_kind = "private_ssh"

    def __init__(self, placement: PrivateSshAmdPlacement) -> None:
        if not isinstance(placement, PrivateSshAmdPlacement):
            raise TypeError("Private AMD recipe placement requires an SSH placement.")
        self._placement = placement
        self._controller_owner_id = f"amd-controller-{uuid4().hex}"

    def observe(
        self,
        *,
        profile: ExecutionProfileManifest,
        location: AmdExecutionLocation,
    ) -> TargetCompatibilityFacts:
        del profile
        target_id = _require_private_location(location)
        session = self._open(target_id)
        try:
            return session.raw.observe_target_facts()
        finally:
            session.close()

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
        del profile
        target_id = _require_private_location(location)
        session = self._open(target_id)
        try:
            for generation in generations:
                self._materialize_generation(
                    session,
                    installation_id,
                    generation,
                    cancellation,
                    progress,
                )
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
        target_id = _require_private_location(location)
        return self._open(target_id)

    def self_test(
        self,
        *,
        session: AmdExecutionSession,
        generation: AmdGenerationMaterialization,
    ) -> str:
        private_session = _require_private_session(session)
        key = _key_for_materialization(private_session, generation)
        recipe = private_session.recipe_for(key)
        deadline = max(test.deadline_seconds for test in generation.manifest.self_tests)
        binding = _wait_for_binding(private_session, key, generation, deadline)
        _assert_unauthenticated_rejected(binding, generation)
        if recipe.kind == "vllm":
            _assert_vllm_contract(binding, generation)
        elif recipe.kind == "rapidocr":
            _assert_rapidocr_contract(binding, generation)
        else:
            raise PrivateRecipePlacementError("AMD target recipe self-test is unsupported.")
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
        private_session = _require_private_session(session)
        private_session.raw.cancel_generation_provisioning(
            key=_generation_key(installation_id, generation),
            manifest_digest=generation.manifest.manifest_digest,
        )

    def retire_generation(
        self,
        *,
        session: AmdExecutionSession,
        installation_id: str,
        profile: ExecutionProfileManifest,
        generation: AmdGenerationMaterialization,
    ) -> None:
        del profile
        private_session = _require_private_session(session)
        recipe = recipe_for(generation)
        layout = recipe.launch_layout(
            generation_root=(
                f"{private_session.raw.target_root}/installations/{installation_id}/generations/{generation.generation_id}"
            ),
            public_port=1_024,
            backend_port=1_025 if recipe.kind == "vllm" else None,
        )
        private_session.raw.retire_and_cleanup_generation(
            key=_generation_key(installation_id, generation),
            manifest_digest=generation.manifest.manifest_digest,
            owned_relative_paths=layout.owned_relative_paths,
        )

    def _materialize_generation(
        self,
        session: _PrivateRecipeSession,
        installation_id: str,
        generation: AmdGenerationMaterialization,
        cancellation: AmdCancellationSignal | None,
        progress: AmdProgressSink | None,
    ) -> None:
        _raise_if_cancelled(cancellation)
        recipe = recipe_for(generation)
        identity = _identity(installation_id, generation, session.incarnation)
        root = session.raw.prepare_recipe_root(identity)
        report_progress(
            progress,
            AmdProgressMilestone.COMPONENT_PREPARATION_STARTED,
            generation.capability,
        )
        result = session.raw.run_generation_recipe(
            identity,
            recipe.provisioning_script(),
            recipe.provisioning_arguments(),
            timeout_seconds=_PROVISION_TIMEOUT_SECONDS,
        )
        _raise_if_cancelled(cancellation)
        if result.return_code != 0:
            raise PrivateRecipePlacementError("AMD target provisioning did not complete.")
        for asset in recipe.target_assets():
            _raise_if_cancelled(cancellation)
            self._upload_asset(session.raw, identity, asset)
            _raise_if_cancelled(cancellation)
        report_progress(
            progress,
            AmdProgressMilestone.COMPONENT_PREPARED,
            generation.capability,
        )
        public_port = session.raw.allocate_remote_loopback_port()
        backend_port = session.raw.allocate_remote_loopback_port() if recipe.kind == "vllm" else None
        layout = recipe.launch_layout(generation_root=root, public_port=public_port, backend_port=backend_port)
        _raise_if_cancelled(cancellation)
        process_executable = session.raw.resolve_process_executable(layout.command[0])
        report_progress(
            progress,
            AmdProgressMilestone.RUNTIME_STARTING,
            generation.capability,
        )
        binding = session.raw.realize(
            RemoteLaunchSpec(
                generation=identity,
                command=layout.command,
                process_executable=process_executable,
                environment=tuple(RemoteEnvironmentSetting(name=name, value=value) for name, value in layout.environment),
                remote_loopback_port=layout.public_port,
                startup_deadline_seconds=_STARTUP_TIMEOUT_SECONDS,
            )
        )
        key = _generation_key(installation_id, generation)
        if session.raw.resolve_binding(key) != binding:
            raise PrivateRecipePlacementError("Private AMD runtime binding changed during launch.")
        session.recipes[key] = recipe
        report_progress(
            progress,
            AmdProgressMilestone.RUNTIME_STARTED,
            generation.capability,
        )

    @staticmethod
    def _upload_asset(session: SshAmdExecutionSession, identity: RemoteGenerationIdentity, asset: TargetAsset) -> None:
        result = session.run_generation_recipe(
            identity,
            target_asset_upload_script(),
            (asset.filename, "1" if asset.executable else "0"),
            stdin=asset.source,
            timeout_seconds=60.0,
        )
        if result.return_code != 0:
            raise PrivateRecipePlacementError("AMD target asset transfer did not complete.")

    def _open(self, target_id: str) -> _PrivateRecipeSession:
        incarnation = RuntimeIncarnation(
            controller_owner_id=self._controller_owner_id,
            incarnation_id=f"amd-incarnation-{uuid4().hex}",
        )
        try:
            raw = self._placement.open_session(target_id, incarnation)
        except SshPlacementError as exc:
            raise PrivateRecipePlacementError(
                "Private AMD target is unavailable.",
                error_code=exc.error_code,
            ) from exc
        return _PrivateRecipeSession(raw=raw, recipes={})


def _generation_key(installation_id: str, generation: AmdGenerationMaterialization) -> AmdRuntimeKey:
    return AmdRuntimeKey(installation_id=installation_id, component_generation_id=generation.generation_id)


def _identity(
    installation_id: str,
    generation: AmdGenerationMaterialization,
    incarnation: RuntimeIncarnation,
) -> RemoteGenerationIdentity:
    return RemoteGenerationIdentity(
        runtime_key=_generation_key(installation_id, generation),
        manifest_digest=generation.manifest.manifest_digest,
        incarnation=incarnation,
    )


def _require_private_session(session: AmdExecutionSession) -> _PrivateRecipeSession:
    if not isinstance(session, _PrivateRecipeSession):
        raise PrivateRecipePlacementError("Private AMD placement received the wrong execution session.")
    return session


def _require_private_location(location: AmdExecutionLocation) -> str:
    if not isinstance(location, AmdExecutionLocation) or location.placement_kind != "private_ssh":
        raise PrivateRecipePlacementError("Private AMD placement received the wrong execution location.")
    target_id = location.private_target_id
    if target_id is None:
        raise PrivateRecipePlacementError("Private AMD placement requires an enrolled target.")
    return target_id


def _raise_if_cancelled(cancellation: AmdCancellationSignal | None) -> None:
    if cancellation is not None and cancellation.is_set():
        raise AmdMaterializationCancelledError("AMD materialization was cancelled by retirement.")


def _key_for_materialization(session: _PrivateRecipeSession, generation: AmdGenerationMaterialization) -> AmdRuntimeKey:
    for key, recipe in session.recipes.items():
        if recipe.materialization == generation:
            return key
    raise PrivateRecipePlacementError("Private AMD generation is unavailable in this session.")


def _wait_for_binding(
    session: _PrivateRecipeSession,
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
                raise PrivateRecipePlacementError("AMD target did not become ready before its deadline.") from None
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
        raise PrivateRecipePlacementError("AMD target authentication self-test returned an unexpected status.") from exc
    raise PrivateRecipePlacementError("AMD target accepted an unauthenticated request.")


def _assert_vllm_contract(binding: LoopbackHttpBinding, generation: AmdGenerationMaterialization) -> None:
    model = generation.manifest.launch.served_model_name
    if generation.capability is ManifestCapability.CHAT:
        response = _json_response(
            binding,
            "/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with the word ready."}],
                "max_tokens": 8,
                "stream": False,
            },
        )
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise PrivateRecipePlacementError("AMD Chat self-test returned an invalid response.")
        _assert_chat_stream(binding, model)
        _assert_chat_tool_call(binding, model)
        return
    if generation.capability is ManifestCapability.EMBEDDING:
        response = _json_response(
            binding,
            "/v1/embeddings",
            {"model": model, "input": ["Xenix AMD embedding self-test."]},
        )
        try:
            vector = response["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PrivateRecipePlacementError("AMD Embedding self-test returned an invalid response.") from exc
        if not isinstance(vector, list) or len(vector) != 1024:
            raise PrivateRecipePlacementError("AMD Embedding self-test returned the wrong vector space.")
        return
    raise PrivateRecipePlacementError("vLLM recipe received the wrong capability.")


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
        raise PrivateRecipePlacementError("AMD Chat streaming self-test returned an invalid SSE response.")


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
        raise PrivateRecipePlacementError("AMD Chat self-test did not return a Tool Call.") from exc
    if not isinstance(tool_calls, list) or not tool_calls:
        raise PrivateRecipePlacementError("AMD Chat self-test did not return a Tool Call.")
    first = tool_calls[0]
    if not isinstance(first, dict) or first.get("type") != "function":
        raise PrivateRecipePlacementError("AMD Chat self-test returned an invalid Tool Call.")
    function = first.get("function")
    if not isinstance(function, dict) or function.get("name") != "get_status":
        raise PrivateRecipePlacementError("AMD Chat self-test returned the wrong Tool Call.")


def _assert_rapidocr_contract(binding: LoopbackHttpBinding, generation: AmdGenerationMaterialization) -> None:
    model = generation.manifest.launch.served_model_name
    image = _png_fixture()
    packed = struct.pack("<I", len(image)) + image
    request_id = "amd-self-test"
    header = json.dumps(
        {
            "id": request_id,
            "inputs": [
                {
                    "name": "image",
                    "datatype": "BYTES",
                    "shape": [1],
                    "parameters": {"binary_data_size": len(packed), "content_type": "image/png"},
                }
            ],
            "outputs": [{"name": "page_xml", "parameters": {"binary_data": True}}],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    raw = _request_bytes(
        binding,
        f"/v2/models/{model}/infer",
        method="POST",
        body=header + packed,
        authenticated=True,
        timeout_seconds=180.0,
        extra_headers={
            "Content-Type": "application/octet-stream",
            "Inference-Header-Content-Length": str(len(header)),
        },
    )
    if b"http://schema.primaresearch.org/PAGE/gts/pagecontent/2024-07-15" not in raw:
        raise PrivateRecipePlacementError("AMD OCR self-test did not return PAGE XML.")


def _json_response(binding: LoopbackHttpBinding, path: str, payload: object) -> object:
    raw = _request_bytes(
        binding,
        path,
        method="POST",
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        authenticated=True,
        timeout_seconds=180.0,
        extra_headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateRecipePlacementError("AMD target self-test returned invalid JSON.") from exc


def _request_bytes(
    binding: LoopbackHttpBinding,
    path: str,
    *,
    method: str,
    body: bytes | None,
    authenticated: bool,
    timeout_seconds: float,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    headers = dict(extra_headers or {})
    if authenticated:
        headers["Authorization"] = binding.authorization_header()
    request = urllib.request.Request(
        binding.base_url + path,
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024:
        raise PrivateRecipePlacementError("AMD target self-test response exceeds its bound.")
    return payload


def _png_fixture() -> bytes:
    """Return a fixed readable text image so all OCR stages are exercised."""

    glyphs = {
        "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
        "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
        "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    }
    scale = 14
    margin = 22
    spacing = scale * 2
    width = margin * 2 + len(glyphs) * 5 * scale + (len(glyphs) - 1) * spacing
    height = margin * 2 + 7 * scale
    pixels = bytearray(b"\xff\xff\xff" * width * height)
    x_offset = margin
    for letter in "AMD":
        for row, pattern in enumerate(glyphs[letter]):
            for column, enabled in enumerate(pattern):
                if enabled != "1":
                    continue
                for y in range(row * scale + margin, (row + 1) * scale + margin):
                    for x in range(column * scale + x_offset, (column + 1) * scale + x_offset):
                        index = (y * width + x) * 3
                        pixels[index : index + 3] = b"\x00\x00\x00"
        x_offset += 5 * scale + spacing

    raw = b"".join(
        b"\x00" + pixels[row * width * 3 : (row + 1) * width * 3]
        for row in range(height)
    )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


__all__ = ["PrivateRecipePlacementError", "PrivateSshRecipePlacement"]
