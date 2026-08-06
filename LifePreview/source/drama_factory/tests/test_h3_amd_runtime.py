from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import drama.h3.amd_runtime as amd_runtime
from drama.h3.amd_runtime import (
    AmdDeviceIdentity,
    H3AmdRuntimeConfig,
    H3AmdRuntimeError,
    H3DurableComfyTransport,
    H3FfprobeBackend,
    H3MediaProbe,
    H3OutputVerifier,
    H3RequestsComfyTransport,
    load_h3_amd_runtime_config,
    validate_amd_device_identity,
)
from drama.v3.durable_comfy import (
    ComfyObservation,
    ComfySubmissionOutcomeUnknown,
)
from drama.v3.durable_provider import (
    DurableProviderCoordinator,
    InMemoryDurableProviderStore,
    ProviderGrantAction,
    ProviderInvocationPhase,
    ProviderObservation,
    ProviderObservationState,
    ProviderStateConflict,
    new_grant,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "h3.amd.yaml"


def test_h3_runtime_config_pins_pvc_models_workspace_cache_and_one_rocm_gpu() -> None:
    config = load_h3_amd_runtime_config(CONFIG)

    assert config.schema_version == "h3-amd-runtime.v1"
    assert config.comfy_base_url == "http://127.0.0.1:18188"
    assert config.persistent_root == "/persistent/douyin-amd"
    assert config.runtime_root == "/workspace/amd-runtime-cache"
    assert config.h3_model_root == (
        "/persistent/douyin-amd/models/minimax-h3/h3-amd-local-v1"
    )
    assert config.flux2_model_root == (
        "/persistent/douyin-amd/models/flux2-dev/flux2-dev-fp8mixed-v1"
    )
    assert config.gpu_count == config.comfyui_count == config.video_worker_count == 1
    assert config.serial_model_execution is True
    assert config.device == AmdDeviceIdentity(
        vendor="amd",
        backend="rocm",
        arch="gfx1100",
        framework_device="cuda:0",
    )


def test_amd_device_identity_requires_rocm_gfx1100_but_framework_uses_cuda_zero() -> None:
    expected = AmdDeviceIdentity(
        vendor="amd",
        backend="rocm",
        arch="gfx1100",
        framework_device="cuda:0",
    )
    assert validate_amd_device_identity(expected) == expected

    for invalid in (
        AmdDeviceIdentity("nvidia", "cuda", "sm_89", "cuda:0"),
        AmdDeviceIdentity("amd", "rocm", "gfx1100", "cuda:1"),
        AmdDeviceIdentity("amd", "cuda", "gfx1100", "cuda:0"),
    ):
        with pytest.raises(H3AmdRuntimeError, match="AMD|ROCm|gfx1100|cuda:0"):
            validate_amd_device_identity(invalid)

    class _EqualAnything:
        def __eq__(self, _other: object) -> bool:
            return True

    with pytest.raises(H3AmdRuntimeError, match="type|string"):
        AmdDeviceIdentity(_EqualAnything(), _EqualAnything(), _EqualAnything(), _EqualAnything())

    with pytest.raises(H3AmdRuntimeError, match="integer|count"):
        H3AmdRuntimeConfig(
            schema_version="h3-amd-runtime.v1",
            comfy_base_url="http://127.0.0.1:18188",
            persistent_root="/persistent/douyin-amd",
            runtime_root="/workspace/amd-runtime-cache",
            h3_model_root="/persistent/douyin-amd/models/minimax-h3/h3-amd-local-v1",
            flux2_model_root="/persistent/douyin-amd/models/flux2-dev/flux2-dev-fp8mixed-v1",
            gpu_count=True,
            comfyui_count=1,
            video_worker_count=1,
            serial_model_execution=True,
            device=AmdDeviceIdentity("amd", "rocm", "gfx1100", "cuda:0"),
        )


class _UploadResponse:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _UploadSession:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _UploadResponse:
        self.calls.append({"url": url, **kwargs})
        return _UploadResponse(self.payload)


def test_reference_upload_verifies_local_digest_and_rejects_unsafe_provider_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "front.png"
    source.write_bytes(b"approved-reference")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    session = _UploadSession(
        {"name": "front.png", "subfolder": "h3/attempt-1", "type": "input"}
    )
    transport = H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=session,
    )

    remote = transport.upload_reference(
        source,
        expected_sha256=digest,
        subfolder="h3/attempt-1",
    )
    assert remote == "h3/attempt-1/front.png"
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == "http://127.0.0.1:18188/upload/image"

    with pytest.raises(H3AmdRuntimeError, match="digest"):
        transport.upload_reference(
            source,
            expected_sha256="0" * 64,
            subfolder="h3/attempt-2",
        )
    assert len(session.calls) == 1

    unsafe = H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=_UploadSession(
            {"name": "../front.png", "subfolder": "h3/attempt-1", "type": "input"}
        ),
    )
    with pytest.raises(H3AmdRuntimeError, match="unsafe"):
        unsafe.upload_reference(
            source,
            expected_sha256=digest,
            subfolder="h3/attempt-1",
        )


def test_reference_upload_hashes_the_uploaded_handle_and_requires_exact_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = b"approved-reference"
    source = tmp_path / "front.png"
    source.write_bytes(approved)
    digest = hashlib.sha256(approved).hexdigest()

    class _ReadingSession(_UploadSession):
        uploaded = b""

        def post(self, url: str, **kwargs: object) -> _UploadResponse:
            handle = kwargs["files"]["image"][1]  # type: ignore[index]
            self.uploaded = handle.read()
            return super().post(url, **kwargs)

    session = _ReadingSession(
        {"name": "front.png", "subfolder": "h3/attempt-1", "type": "input"}
    )
    original_hash = amd_runtime._sha256_file

    def swap_after_legacy_hash(path: Path) -> str:
        value = original_hash(path)
        path.write_bytes(b"tampered-after-hash")
        return value

    monkeypatch.setattr(amd_runtime, "_sha256_file", swap_after_legacy_hash)
    transport = H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=session,
    )
    transport.upload_reference(
        source,
        expected_sha256=digest,
        subfolder="h3/attempt-1",
    )
    assert session.uploaded == approved

    monkeypatch.setattr(amd_runtime, "_sha256_file", original_hash)
    source.write_bytes(approved)

    class _InPlaceMutatingSession(_UploadSession):
        uploaded = b""

        def post(self, url: str, **kwargs: object) -> _UploadResponse:
            source.write_bytes(b"tampered-same-inode")
            handle = kwargs["files"]["image"][1]  # type: ignore[index]
            self.uploaded = handle.read()
            return super().post(url, **kwargs)

    in_place = _InPlaceMutatingSession(
        {"name": "front.png", "subfolder": "h3/attempt-1", "type": "input"}
    )
    H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=in_place,
    ).upload_reference(
        source,
        expected_sha256=digest,
        subfolder="h3/attempt-1",
    )
    assert in_place.uploaded == approved

    wrong_echo = H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=_UploadSession(
            {"name": "other.png", "subfolder": "h3/attempt-1", "type": "input"}
        ),
    )
    source.write_bytes(approved)
    with pytest.raises(H3AmdRuntimeError, match="name|location|echo"):
        wrong_echo.upload_reference(
            source,
            expected_sha256=digest,
            subfolder="h3/attempt-1",
        )


class _DownloadResponse:
    status_code = 200

    def __init__(self, *, payload: object | None = None, content: bytes = b"") -> None:
        self.payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _DownloadSession:
    def __init__(
        self,
        descriptor: dict[str, object],
        *,
        status: dict[str, object] | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.status = status or {"completed": True}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _DownloadResponse:
        self.calls.append((url, kwargs))
        if "/history/" in url:
            prompt_id = url.rsplit("/", 1)[-1]
            return _DownloadResponse(
                payload={
                    prompt_id: {
                        "status": self.status,
                        "outputs": {"15": {"videos": [self.descriptor]}},
                    }
                }
            )
        return _DownloadResponse(content=b"verified-later-by-ffprobe")


def test_h3_download_accepts_only_pinned_savevideo_output_descriptor(
    tmp_path: Path,
) -> None:
    session = _DownloadSession(
        {
            "filename": "h3_sequence_00001_.mp4",
            "subfolder": "h3/sequence-001",
            "type": "output",
        }
    )
    destination = tmp_path / "result.mp4"

    result = H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=session,
        output_root=tmp_path,
    ).download("prompt-12345678", destination)

    assert result == destination
    assert destination.read_bytes() == b"verified-later-by-ffprobe"
    assert session.calls[-1][0] == "http://127.0.0.1:18188/view"
    assert session.calls[-1][1]["params"] == {
        "filename": "h3_sequence_00001_.mp4",
        "subfolder": "h3/sequence-001",
        "type": "output",
    }


@pytest.mark.parametrize(
    "descriptor",
    [
        {"filename": "../secret.mp4", "subfolder": "h3", "type": "output"},
        {"filename": "clip.webm", "subfolder": "h3", "type": "output"},
        {"filename": "clip.mp4", "subfolder": "../private", "type": "output"},
        {"filename": "clip.mp4", "subfolder": "h3", "type": "input"},
    ],
)
def test_h3_download_rejects_untrusted_comfy_output_location(
    tmp_path: Path,
    descriptor: dict[str, object],
) -> None:
    session = _DownloadSession(descriptor)

    with pytest.raises(H3AmdRuntimeError, match="output|unsafe|location"):
        H3RequestsComfyTransport(
            "http://127.0.0.1:18188",
            session=session,
            output_root=tmp_path,
        ).download("prompt-12345678", tmp_path / "result.mp4")

    assert len(session.calls) == 1
    assert not (tmp_path / "result.mp4").exists()


@pytest.mark.parametrize("status_text", ["error", "failed", "cancelled", "canceled"])
def test_h3_download_rejects_failed_terminal_history_before_view(
    tmp_path: Path,
    status_text: str,
) -> None:
    session = _DownloadSession(
        {
            "filename": "h3_sequence_00001_.mp4",
            "subfolder": "h3/sequence-001",
            "type": "output",
        },
        status={"completed": True, "status_str": status_text},
    )

    with pytest.raises(H3AmdRuntimeError, match="not ready|status"):
        H3RequestsComfyTransport(
            "http://127.0.0.1:18188",
            session=session,
            output_root=tmp_path,
        ).download("prompt-12345678", tmp_path / "result.mp4")

    assert len(session.calls) == 1
    assert "/history/" in session.calls[0][0]


def test_h3_download_recovers_owned_stale_partial_after_crash(tmp_path: Path) -> None:
    destination = tmp_path / "result.mp4"
    partial = tmp_path / "result.mp4.partial"
    partial.write_bytes(b"crash-fragment")
    session = _DownloadSession(
        {
            "filename": "h3_sequence_00001_.mp4",
            "subfolder": "h3/sequence-001",
            "type": "output",
        }
    )

    result = H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=session,
        output_root=tmp_path,
    ).download("prompt-12345678", destination)

    assert result.read_bytes() == b"verified-later-by-ffprobe"
    assert not partial.exists()


def test_h3_download_rejects_destination_with_lexical_parent_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "output"
    root.mkdir()
    session = _DownloadSession(
        {"filename": "clip.mp4", "subfolder": "h3", "type": "output"}
    )

    with pytest.raises(H3AmdRuntimeError, match="destination|unsafe"):
        H3RequestsComfyTransport(
            "http://127.0.0.1:18188",
            session=session,
            output_root=root,
        ).download("prompt-12345678", root / ".." / "escaped.mp4")

    assert session.calls == []


def test_h3_download_rejects_destination_through_ancestor_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "output"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    session = _DownloadSession(
        {"filename": "clip.mp4", "subfolder": "h3", "type": "output"}
    )

    with pytest.raises(H3AmdRuntimeError, match="destination|unsafe"):
        H3RequestsComfyTransport(
            "http://127.0.0.1:18188",
            session=session,
            output_root=root,
        ).download("prompt-12345678", link / "escaped.mp4")

    assert session.calls == []
    assert not (outside / "escaped.mp4").exists()


def test_h3_ffprobe_rejects_subtitle_or_data_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1344,
                        "height": 768,
                        "avg_frame_rate": "24/1",
                        "nb_read_frames": "209",
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "channels": 2,
                    },
                    {"codec_type": "subtitle", "codec_name": "mov_text"},
                ],
                "format": {"duration": "8.708333"},
            }
        )

    monkeypatch.setattr(amd_runtime.subprocess, "run", lambda *_args, **_kwargs: _Completed())

    with pytest.raises(H3AmdRuntimeError, match="exactly|stream"):
        H3FfprobeBackend().probe(tmp_path / "candidate.mp4")


class _ProbeBackend:
    def __init__(self, value: H3MediaProbe) -> None:
        self.value = value

    def probe(self, _path: Path) -> H3MediaProbe:
        return self.value


def _probe(**overrides: object) -> H3MediaProbe:
    values: dict[str, object] = {
        "width": 1344,
        "height": 768,
        "fps_numerator": 24,
        "fps_denominator": 1,
        "frame_count": 209,
        "duration_seconds": 209 / 24,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_channels": 2,
    }
    values.update(overrides)
    return H3MediaProbe(**values)


def test_h3_output_verifier_requires_native_audio_exact_frames_fps_and_resolution(
    tmp_path: Path,
) -> None:
    output = tmp_path / "sequence.mp4"
    output.write_bytes(b"h3-native-audiovisual-output")
    verified = H3OutputVerifier(_ProbeBackend(_probe())).verify(
        output,
        expected_frame_count=209,
        expected_fps=24,
        expected_width=1344,
        expected_height=768,
    )
    assert verified.artifact_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert verified.probe.audio_codec == "aac"

    for broken in (
        _probe(audio_codec=None, audio_channels=0),
        _probe(frame_count=208),
        _probe(fps_numerator=30),
        _probe(width=512),
    ):
        with pytest.raises(H3AmdRuntimeError):
            H3OutputVerifier(_ProbeBackend(broken)).verify(
                output,
                expected_frame_count=209,
                expected_fps=24,
                expected_width=1344,
                expected_height=768,
            )


def test_h3_output_verifier_accepts_73_frame_short_slice_and_rejects_less(
    tmp_path: Path,
) -> None:
    output = tmp_path / "short-sequence.mp4"
    output.write_bytes(b"h3-short-native-audiovisual-output")
    short_probe = _probe(
        frame_count=73,
        duration_seconds=73 / 24,
    )

    verified = H3OutputVerifier(_ProbeBackend(short_probe)).verify(
        output,
        expected_frame_count=73,
        expected_fps=24,
        expected_width=1344,
        expected_height=768,
    )
    assert verified.probe.frame_count == 73

    with pytest.raises(H3AmdRuntimeError, match="execution profile"):
        H3OutputVerifier(
            _ProbeBackend(
                _probe(frame_count=56, duration_seconds=56 / 24)
            )
        ).verify(
            output,
            expected_frame_count=56,
            expected_fps=24,
            expected_width=1344,
            expected_height=768,
        )


def test_h3_output_verifier_rejects_mutation_during_probe(tmp_path: Path) -> None:
    output = tmp_path / "sequence.mp4"
    output.write_bytes(b"h3-native-audiovisual-output")

    class _MutatingProbe:
        def probe(self, _snapshot_path: Path) -> H3MediaProbe:
            output.write_bytes(b"changed-during-probe-same-size")
            return _probe()

    with pytest.raises(H3AmdRuntimeError, match="changed|snapshot|mutation"):
        H3OutputVerifier(_MutatingProbe()).verify(
            output,
            expected_frame_count=209,
            expected_fps=24,
            expected_width=1344,
            expected_height=768,
        )

    output.write_bytes(b"h3-native-audiovisual-output")

    class _MutatingSnapshotProbe:
        def probe(self, snapshot_path: Path) -> H3MediaProbe:
            snapshot_path.write_bytes(b"probe-mutated-snapshot")
            return _probe()

    with pytest.raises(H3AmdRuntimeError, match="changed|snapshot|mutation"):
        H3OutputVerifier(_MutatingSnapshotProbe()).verify(
            output,
            expected_frame_count=209,
            expected_fps=24,
            expected_width=1344,
            expected_height=768,
        )


class _RecoverableComfy:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.find_calls = 0
        self.submitted_providers: list[str] = []
        self.task_by_identity: dict[tuple[str, str, str, str], str] = {}
        self.states: dict[str, ComfyObservation] = {}
        self.find_identities: list[tuple[str, str, str | None, str | None]] = []

    def submit(self, workflow, *, client_id: str, extra_data):
        assert workflow["15"]["class_type"] == "SaveVideo"
        self.submit_calls += 1
        self.submitted_providers.append(extra_data["provider"])
        prompt_id = f"h3-prompt-{self.submit_calls}"
        self.task_by_identity[
            (
                client_id,
                extra_data["submission_nonce"],
                extra_data["provider"],
                extra_data["workflow_digest"],
            )
        ] = prompt_id
        self.states[prompt_id] = ComfyObservation.RUNNING
        raise ComfySubmissionOutcomeUnknown("response dropped after H3 acceptance")

    def find_submission(
        self,
        *,
        client_id: str,
        submission_nonce: str,
        required_extra_data: dict[str, str] | None = None,
    ):
        self.find_calls += 1
        provider = (
            required_extra_data.get("provider")
            if required_extra_data is not None
            else None
        )
        workflow_digest = (
            required_extra_data.get("workflow_digest")
            if required_extra_data is not None
            else None
        )
        self.find_identities.append(
            (client_id, submission_nonce, provider, workflow_digest)
        )
        if provider is not None and workflow_digest is not None:
            return self.task_by_identity.get(
                (client_id, submission_nonce, provider, workflow_digest)
            )
        return next(
            (
                prompt_id
                for identity, prompt_id in self.task_by_identity.items()
                if identity[:2] == (client_id, submission_nonce)
            ),
            None,
        )

    def observe(self, prompt_id: str):
        return self.states[prompt_id], {
            "prompt_id": prompt_id,
            "debug_path": "/workspace/private/model.py",
            "debug_url": "http://10.0.0.5/admin",
        }


def _workflow() -> dict[str, object]:
    return {"15": {"class_type": "SaveVideo", "inputs": {}}}


def _workflow_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _grant(invocation_id, action):
    from datetime import datetime, timezone

    return new_grant(
        invocation_id,
        action,
        granted_by_actor="worker.h3.test",
        reason="durable H3 reconcile test",
        granted_at=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
    )


def test_h3_lost_submit_response_reconciles_after_restart_without_resubmission() -> None:
    comfy = _RecoverableComfy()
    workflow = _workflow()
    workflow_digest = _workflow_digest(workflow)
    persisted_nonce = UUID(hex="b" * 32)
    transport = H3DurableComfyTransport(
        comfy=comfy,
        workflow=workflow,
        workflow_digest=workflow_digest,
        submission_nonce="b" * 32,
        attempt_stage="initial",
    )
    assert transport.provider_name == "local-minimax-h3-comfy.initial"
    workflow["15"] = {"class_type": "LoadFromURL", "inputs": {"url": "http://external.invalid"}}
    exposed = transport.workflow
    exposed["15"] = {"class_type": "LoadFromURL", "inputs": {"url": "http://external.invalid"}}
    store = InMemoryDurableProviderStore()
    invocation_id = uuid4()
    coordinator = DurableProviderCoordinator(store=store, transport=transport)
    coordinator.prepare(
        invocation_id=invocation_id,
        project_id=uuid4(),
        operation_run_id=uuid4(),
        operation_attempt_id=uuid4(),
        client_token="h3-client-token-0000000000000001",
        submission_nonce=persisted_nonce,
        request_payload={
            "workflow_digest": workflow_digest,
            "submission_nonce": persisted_nonce.hex,
        },
    )
    unknown = coordinator.submit(
        invocation_id,
        grant=_grant(invocation_id, ProviderGrantAction.SUBMIT),
    )
    assert unknown.phase is ProviderInvocationPhase.OUTCOME_UNKNOWN
    assert comfy.submit_calls == 1
    assert comfy.submitted_providers == ["local-minimax-h3-comfy.initial"]

    restarted = DurableProviderCoordinator(store=store, transport=transport)
    recovered = restarted.reconcile(
        invocation_id,
        grant=_grant(invocation_id, ProviderGrantAction.RECONCILE),
    )
    assert recovered.phase is ProviderInvocationPhase.SUBMITTED
    assert recovered.provider_task_id == "h3-prompt-1"
    assert comfy.submit_calls == 1

    comfy.states["h3-prompt-1"] = ComfyObservation.SUCCESS
    terminal = restarted.reconcile(
        invocation_id,
        grant=_grant(invocation_id, ProviderGrantAction.RECONCILE),
    )
    serialized_result = json.dumps(terminal.result, sort_keys=True)
    assert "/workspace" not in serialized_result
    assert "10.0.0.5" not in serialized_result


def test_h3_durable_transport_binds_workflow_digest_and_persisted_nonce() -> None:
    workflow = _workflow()
    digest = _workflow_digest(workflow)
    comfy = _RecoverableComfy()
    with pytest.raises(H3AmdRuntimeError, match="digest"):
        H3DurableComfyTransport(
            comfy=comfy,
            workflow=workflow,
            workflow_digest="0" * 64,
            submission_nonce="b" * 32,
            attempt_stage="initial",
        )

    transport = H3DurableComfyTransport(
        comfy=comfy,
        workflow=workflow,
        workflow_digest=digest,
        submission_nonce="b" * 32,
        attempt_stage="initial",
    )
    with pytest.raises(H3AmdRuntimeError, match="nonce|request"):
        transport.submit(
            {"workflow_digest": digest, "submission_nonce": "c" * 32},
            client_token="h3-client-token-0000000000000001",
        )

    coordinator = DurableProviderCoordinator(
        store=InMemoryDurableProviderStore(),
        transport=transport,
    )
    with pytest.raises(ProviderStateConflict, match="nonce"):
        coordinator.prepare(
            invocation_id=uuid4(),
            project_id=uuid4(),
            operation_run_id=uuid4(),
            operation_attempt_id=uuid4(),
            client_token="h3-client-token-0000000000000001",
            submission_nonce=UUID(hex="c" * 32),
            request_payload={
                "workflow_digest": digest,
                "submission_nonce": "b" * 32,
            },
        )


@pytest.mark.parametrize(
    ("attempt_stage", "provider_name"),
    [
        ("initial", "local-minimax-h3-comfy.initial"),
        ("repair", "local-minimax-h3-comfy.repair"),
    ],
)
def test_h3_durable_transport_pins_attempt_stage_provider_identity(
    attempt_stage: str,
    provider_name: str,
) -> None:
    workflow = _workflow()
    transport = H3DurableComfyTransport(
        comfy=_RecoverableComfy(),
        workflow=workflow,
        workflow_digest=_workflow_digest(workflow),
        submission_nonce="b" * 32,
        attempt_stage=attempt_stage,
    )

    assert transport.provider_name == provider_name


@pytest.mark.parametrize(
    "attempt_stage",
    ["", "INITIAL", "retry", "repair/../initial", None, True],
)
def test_h3_durable_transport_rejects_unpinned_attempt_stage(
    attempt_stage: object,
) -> None:
    workflow = _workflow()

    with pytest.raises(H3AmdRuntimeError, match="stage"):
        H3DurableComfyTransport(
            comfy=_RecoverableComfy(),
            workflow=workflow,
            workflow_digest=_workflow_digest(workflow),
            submission_nonce="b" * 32,
            attempt_stage=attempt_stage,
        )


def test_h3_recovery_matches_stage_and_workflow_inside_comfy_metadata() -> None:
    comfy = _RecoverableComfy()
    workflow = _workflow()
    workflow_digest = _workflow_digest(workflow)
    transports = {
        stage: H3DurableComfyTransport(
            comfy=comfy,
            workflow=workflow,
            workflow_digest=workflow_digest,
            submission_nonce="b" * 32,
            attempt_stage=stage,
        )
        for stage in ("initial", "repair")
    }
    for transport in transports.values():
        with pytest.raises(ComfySubmissionOutcomeUnknown):
            transport.submit(
                {
                    "workflow_digest": workflow_digest,
                    "submission_nonce": "b" * 32,
                },
                client_token="h3-client-token-0000000000000001",
            )

    initial = transports["initial"].query(
        client_token="h3-client-token-0000000000000001",
        provider_task_id=None,
    )
    repair = transports["repair"].query(
        client_token="h3-client-token-0000000000000001",
        provider_task_id=None,
    )

    assert initial.provider_task_id == "h3-prompt-1"
    assert repair.provider_task_id == "h3-prompt-2"
    assert comfy.find_identities == [
        (
            "h3-client-token-0000000000000001",
            "b" * 32,
            "local-minimax-h3-comfy.initial",
            workflow_digest,
        ),
        (
            "h3-client-token-0000000000000001",
            "b" * 32,
            "local-minimax-h3-comfy.repair",
            workflow_digest,
        ),
    ]


@pytest.mark.parametrize(
    ("persisted_stage", "restarted_stage"),
    [("initial", "repair"), ("repair", "initial")],
)
@pytest.mark.parametrize("action", ["submit", "reconcile"])
def test_durable_provider_rejects_cross_stage_h3_transport_after_restart(
    persisted_stage: str,
    restarted_stage: str,
    action: str,
) -> None:
    comfy = _RecoverableComfy()
    workflow = _workflow()
    workflow_digest = _workflow_digest(workflow)
    persisted = H3DurableComfyTransport(
        comfy=comfy,
        workflow=workflow,
        workflow_digest=workflow_digest,
        submission_nonce="b" * 32,
        attempt_stage=persisted_stage,
    )
    restarted = H3DurableComfyTransport(
        comfy=comfy,
        workflow=workflow,
        workflow_digest=workflow_digest,
        submission_nonce="b" * 32,
        attempt_stage=restarted_stage,
    )
    store = InMemoryDurableProviderStore()
    invocation_id = uuid4()
    persisted_coordinator = DurableProviderCoordinator(
        store=store,
        transport=persisted,
    )
    persisted_coordinator.prepare(
        invocation_id=invocation_id,
        project_id=uuid4(),
        operation_run_id=uuid4(),
        operation_attempt_id=uuid4(),
        client_token="h3-client-token-0000000000000001",
        submission_nonce=UUID(hex="b" * 32),
        request_payload={
            "workflow_digest": workflow_digest,
            "submission_nonce": "b" * 32,
        },
    )
    restarted_coordinator = DurableProviderCoordinator(
        store=store,
        transport=restarted,
    )

    if action == "reconcile":
        persisted_coordinator.submit(
            invocation_id,
            grant=_grant(invocation_id, ProviderGrantAction.SUBMIT),
        )
        assert comfy.submit_calls == 1
    with pytest.raises(ProviderStateConflict, match="provider"):
        if action == "submit":
            restarted_coordinator.submit(
                invocation_id,
                grant=_grant(invocation_id, ProviderGrantAction.SUBMIT),
            )
        else:
            restarted_coordinator.reconcile(
                invocation_id,
                grant=_grant(invocation_id, ProviderGrantAction.RECONCILE),
            )

    assert comfy.submit_calls == (1 if action == "reconcile" else 0)
    assert comfy.find_calls == 0


@pytest.mark.parametrize("mismatch", ["workflow", "nonce"])
def test_durable_provider_rejects_changed_h3_transport_fingerprint_on_restart(
    mismatch: str,
) -> None:
    comfy = _RecoverableComfy()
    workflow = _workflow()
    workflow_digest = _workflow_digest(workflow)
    persisted = H3DurableComfyTransport(
        comfy=comfy,
        workflow=workflow,
        workflow_digest=workflow_digest,
        submission_nonce="b" * 32,
        attempt_stage="initial",
    )
    store = InMemoryDurableProviderStore()
    invocation_id = uuid4()
    coordinator = DurableProviderCoordinator(store=store, transport=persisted)
    coordinator.prepare(
        invocation_id=invocation_id,
        project_id=uuid4(),
        operation_run_id=uuid4(),
        operation_attempt_id=uuid4(),
        client_token="h3-client-token-0000000000000001",
        submission_nonce=UUID(hex="b" * 32),
        request_payload={
            "workflow_digest": workflow_digest,
            "submission_nonce": "b" * 32,
        },
    )
    coordinator.submit(
        invocation_id,
        grant=_grant(invocation_id, ProviderGrantAction.SUBMIT),
    )
    restarted_workflow = (
        {"15": {"class_type": "SaveVideo", "inputs": {"prefix": "other"}}}
        if mismatch == "workflow"
        else workflow
    )
    restarted = H3DurableComfyTransport(
        comfy=comfy,
        workflow=restarted_workflow,
        workflow_digest=_workflow_digest(restarted_workflow),
        submission_nonce=("c" * 32 if mismatch == "nonce" else "b" * 32),
        attempt_stage="initial",
    )

    with pytest.raises(ProviderStateConflict, match="workflow|nonce|request"):
        DurableProviderCoordinator(
            store=store,
            transport=restarted,
        ).reconcile(
            invocation_id,
            grant=_grant(invocation_id, ProviderGrantAction.RECONCILE),
        )

    assert comfy.find_calls == 0


@pytest.mark.parametrize(
    ("persisted_stage", "restarted_stage"),
    [("initial", "repair"), ("repair", "initial")],
)
@pytest.mark.parametrize("action", ["callback", "materialize"])
def test_durable_provider_rejects_cross_stage_callback_and_materialization(
    persisted_stage: str,
    restarted_stage: str,
    action: str,
) -> None:
    comfy = _RecoverableComfy()
    workflow = _workflow()
    workflow_digest = _workflow_digest(workflow)
    store = InMemoryDurableProviderStore()
    invocation_id = uuid4()
    persisted = H3DurableComfyTransport(
        comfy=comfy,
        workflow=workflow,
        workflow_digest=workflow_digest,
        submission_nonce="b" * 32,
        attempt_stage=persisted_stage,
    )
    coordinator = DurableProviderCoordinator(store=store, transport=persisted)
    coordinator.prepare(
        invocation_id=invocation_id,
        project_id=uuid4(),
        operation_run_id=uuid4(),
        operation_attempt_id=uuid4(),
        client_token="h3-client-token-0000000000000001",
        submission_nonce=UUID(hex="b" * 32),
        request_payload={
            "workflow_digest": workflow_digest,
            "submission_nonce": "b" * 32,
        },
    )
    if action == "materialize":
        coordinator.submit(
            invocation_id,
            grant=_grant(invocation_id, ProviderGrantAction.SUBMIT),
        )
        comfy.states["h3-prompt-1"] = ComfyObservation.SUCCESS
        terminal = coordinator.reconcile(
            invocation_id,
            grant=_grant(invocation_id, ProviderGrantAction.RECONCILE),
        )
        assert terminal.phase is ProviderInvocationPhase.OBSERVED_TERMINAL
    before = store.get(invocation_id)
    restarted = DurableProviderCoordinator(
        store=store,
        transport=H3DurableComfyTransport(
            comfy=comfy,
            workflow=workflow,
            workflow_digest=workflow_digest,
            submission_nonce="b" * 32,
            attempt_stage=restarted_stage,
        ),
    )
    materializer_calls: list[object] = []

    with pytest.raises(ProviderStateConflict, match="provider"):
        if action == "callback":
            restarted.callback(
                invocation_id,
                callback_id="h3-callback-1",
                observation=ProviderObservation(
                    state=ProviderObservationState.PENDING,
                    provider_task_id="h3-prompt-1",
                ),
            )
        else:
            restarted.materialize(
                invocation_id,
                grant=_grant(invocation_id, ProviderGrantAction.MATERIALIZE),
                materializer=lambda record: (
                    materializer_calls.append(record) or {"committed": True}
                ),
            )

    assert store.get(invocation_id) == before
    assert materializer_calls == []


def test_h3_http_ambiguous_2xx_is_outcome_unknown() -> None:
    class _AmbiguousResponse:
        status_code = 200
        text = ""

        def __init__(self, value: object, *, malformed: bool = False) -> None:
            self.value = value
            self.malformed = malformed

        def json(self) -> object:
            if self.malformed:
                raise ValueError("truncated json")
            return self.value

    class _PromptSession:
        def __init__(self, response: _AmbiguousResponse) -> None:
            self.response = response

        def post(self, *_args: object, **_kwargs: object) -> _AmbiguousResponse:
            return self.response

    for response in (_AmbiguousResponse({}), _AmbiguousResponse(None, malformed=True)):
        transport = H3RequestsComfyTransport(
            "http://127.0.0.1:18188",
            session=_PromptSession(response),
        )
        with pytest.raises(ComfySubmissionOutcomeUnknown):
            transport.submit(
                _workflow(),
                client_id="h3-client-token-0000000000000001",
                extra_data={"submission_nonce": "b" * 32},
            )


def test_h3_http_recovery_filters_exact_provider_and_workflow_metadata() -> None:
    workflow_digest = "d" * 64
    client_id = "h3-client-token-0000000000000001"
    nonce = "b" * 32

    class _Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.payload

    class _Session:
        def get(self, url: str, **_kwargs: object) -> _Response:
            if url.endswith("/queue"):
                return _Response(
                    {
                        "h3-prompt-initial": {
                            "client_id": client_id,
                            "extra_data": {
                                "submission_nonce": nonce,
                                "provider": "local-minimax-h3-comfy.initial",
                                "workflow_digest": workflow_digest,
                            },
                        },
                        "h3-prompt-repair": {
                            "client_id": client_id,
                            "extra_data": {
                                "submission_nonce": nonce,
                                "provider": "local-minimax-h3-comfy.repair",
                                "workflow_digest": workflow_digest,
                            },
                        },
                    }
                )
            return _Response({})

    transport = H3RequestsComfyTransport(
        "http://127.0.0.1:18188",
        session=_Session(),
    )

    assert transport.find_submission(
        client_id=client_id,
        submission_nonce=nonce,
        required_extra_data={
            "provider": "local-minimax-h3-comfy.repair",
            "workflow_digest": workflow_digest,
        },
    ) == "h3-prompt-repair"
