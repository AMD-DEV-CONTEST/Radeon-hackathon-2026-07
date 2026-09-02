from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from shidu_api.competition_runtime_wiring import (
    CgroupMemoryAdmissionGate,
    ExactPosixPageCacheReclaimer,
    LoopbackComfySession,
    POSIX_FADV_DONTNEED,
    PersistentH3AuthorityFactory,
    ProductionComfyProcessController,
    RuntimeWiringError,
    _runner_module,
    create_runner,
    probe_h3_media,
)


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "ops" / "amd" / "run-three-second-vertical-slice.py"
FLUX_MANIFEST = (
    ROOT / "drama_factory" / "config" / "flux2_dev_fp8mixed_amd_capability.json"
)
FLUX_WORKFLOWS = ROOT / "drama_factory" / "workflows"
H3_MANIFEST = ROOT / "drama_factory" / "config" / "h3_ref2va_amd_capability.json"
H3_TEMPLATE = ROOT / "drama_factory" / "workflows" / "h3_ref2va_amd_api.json"


@pytest.fixture(autouse=True)
def _trusted_release_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMD_RELEASE_DIR", str(ROOT))


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write(path: Path, value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_clean_process_loads_pinned_runner_from_release_root(tmp_path: Path) -> None:
    release = tmp_path / "release"
    runner = release / "ops" / "amd" / RUNNER_PATH.name
    runner.parent.mkdir(parents=True)
    shutil.copyfile(RUNNER_PATH, runner)
    runner_sha256 = hashlib.sha256(runner.read_bytes()).hexdigest()
    _write(
        release / "deploy" / "amd" / "release-manifest.json",
        {
            "runtime": {
                "competitionRunner": {
                    "relativePath": "ops/amd/run-three-second-vertical-slice.py",
                    "sha256": runner_sha256,
                }
            }
        },
    )
    environment = os.environ.copy()
    environment["AMD_RELEASE_DIR"] = str(release)
    environment["PYTHONPATH"] = os.pathsep.join(
        str(entry) for entry in sys.path if isinstance(entry, str) and entry
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "from shidu_api.competition_runtime_wiring import _runner_module; "
                "module = _runner_module(); "
                "print(Path(module.__file__).resolve())"
            ),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert Path(completed.stdout.strip()) == runner.resolve()


def test_repository_release_manifest_pins_exact_runner_bytes() -> None:
    manifest = json.loads(
        (ROOT / "deploy" / "amd" / "release-manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["runtime"]["competitionRunner"] == {
        "relativePath": "ops/amd/run-three-second-vertical-slice.py",
        "sha256": hashlib.sha256(RUNNER_PATH.read_bytes()).hexdigest(),
    }


def test_create_runner_loads_flux_authority_without_touching_gpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_identity = {
        "schemaVersion": "amd.three-second-vertical-slice.v1",
        "requestedDurationSeconds": 3.0,
        "frameCount": 73,
        "fps": 24,
        "nativeAudio": True,
        "subtitles": False,
        "fluxReferenceGeneration": {
            "schemaVersion": "amd.flux-prompt-single-reference-generation.v1",
            "referenceProfile": "competition-prompt-single-view-v1",
            "sourceMode": "prompt_synthesized",
            "requiredImages": 1,
            "view": "front_three_quarter",
            "prompt": "single historical portrait",
            "promptSha256": hashlib.sha256(
                b"single historical portrait"
            ).hexdigest(),
            "seed": 11,
            "workflowSha256": "6029c0b8d2fe9133b354f01b2d693fa83622ebc1135b4638ab3f884065589618",
            "generationInvocationCount": 1,
            "technicalRetryLimit": 1,
        },
    }
    workflow_identity["fluxReferenceGeneration"]["authoritySha256"] = _digest(
        workflow_identity["fluxReferenceGeneration"]
    )
    workflow_path = tmp_path / "prepared-workflow.json"
    workflow_sha = _write(workflow_path, workflow_identity)
    click_path = tmp_path / "click.json"
    _write(click_path, {"workflowPath": str(workflow_path), "workflowSha256": workflow_sha})
    monkeypatch.setenv("AMD_RUNTIME_ROOT", "/workspace/amd-runtime-cache")
    monkeypatch.setenv("AMD_ROCM_PYTHON", "/workspace/amd-runtime-cache/venvs/rocm/bin/python")
    monkeypatch.setenv("AMD_ROOT", "/persistent/douyin-amd")

    args = SimpleNamespace(
        persistent_root=tmp_path,
        click_authority=click_path,
        checkpoint=tmp_path / "checkpoint.json",
        evidence_root=tmp_path / "evidence",
        output=tmp_path / "output.mp4",
        flux_manifest=FLUX_MANIFEST,
        flux_workflow_root=FLUX_WORKFLOWS,
        h3_manifest=tmp_path / "not-created-until-after-flux.json",
        h3_template=FLUX_WORKFLOWS / "h3_ref2va_amd_api.json",
    )

    result = create_runner(args)
    runner_module = _runner_module()

    assert isinstance(result, runner_module.VerticalSliceRunner)
    assert result.flux_authority.reference_profile == "competition-prompt-single-view-v1"
    assert result.flux_authority.view == "front_three_quarter"
    assert result.flux_authority.prompt == "single historical portrait"
    assert result.flux_authority.seed == 11
    assert not args.h3_manifest.exists()


def test_single_reference_stage_authority_builds_real_h3_workflow_and_binds_compiled_sha(
    tmp_path: Path,
) -> None:
    persistent_root = tmp_path / "persistent" / "douyin-amd"
    manifest = persistent_root / "config" / "h3-capability.json"
    template = persistent_root / "workflows" / H3_TEMPLATE.name
    manifest.parent.mkdir(parents=True)
    template.parent.mkdir(parents=True)
    shutil.copyfile(H3_MANIFEST, manifest)
    shutil.copyfile(H3_TEMPLATE, template)
    prompt = "One calm historically grounded performance with native audio."
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    compiled_flux_sha = "c" * 64
    reference_sha = "d" * 64
    reference_id = uuid4()
    workflow_run_id = uuid4()
    plan = {
        "schemaVersion": "amd.competition-single-reference-h3-plan.v1",
        "referenceProfile": "competition-prompt-single-view-v1",
        "sourceMode": "prompt_synthesized",
        "requiredImages": 1,
        "view": "front_three_quarter",
        "requestedDurationSeconds": 3.0,
        "frameCount": 73,
        "fps": 24,
        "prompt": prompt,
        "promptSha256": prompt_sha,
    }
    identity = {
        "schemaVersion": "amd.h3-execution-authority.v1",
        "capabilityManifestPath": str(manifest.resolve()),
        "capabilityManifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "plan": plan,
        "planSha256": _digest(plan),
        "referenceArtifacts": [
            {
                "viewName": "front_three_quarter",
                "assetId": str(reference_id),
                "artifactRef": f"cas://sha256/{reference_sha}",
                "sha256": reference_sha,
                "remoteName": "h3/reference-front-three-quarter.png",
                "compiledWorkflowSha256": compiled_flux_sha,
            }
        ],
        "seed": 20260806,
        "jobAuthorityDigest": "a" * 64,
        "inputAuthorityDigest": "b" * 64,
        "workflowRunId": str(workflow_run_id),
    }
    authority_path = persistent_root / "authorities" / "h3-execution.json"
    _write(authority_path, {**identity, "authoritySha256": _digest(identity)})
    generated = SimpleNamespace(
        view_name="front_three_quarter",
        sha256=reference_sha,
        compiled_workflow_sha256=compiled_flux_sha,
    )
    factory = PersistentH3AuthorityFactory(
        manifest_path=authority_path,
        template_path=template,
        persistent_root=persistent_root,
    )

    built = factory((generated,))

    assert built.reference_profile == "competition-prompt-single-view-v1"
    assert len(built.staged_references) == 1
    assert built.staged_references[0].sha256 == reference_sha
    assert built.concrete.workflow_digest == _digest(built.concrete.workflow)
    h3_nodes = [
        node
        for node in built.concrete.workflow.values()
        if isinstance(node, dict)
        and node.get("class_type") == "MiniMaxH3ReferenceToVideo"
    ]
    assert len(h3_nodes) == 1
    assert h3_nodes[0]["inputs"]["length"] == 73

    mismatched = SimpleNamespace(
        view_name="front_three_quarter",
        sha256=reference_sha,
        compiled_workflow_sha256="e" * 64,
    )
    with pytest.raises(RuntimeWiringError, match="diverges"):
        factory((mismatched,))


def test_process_controller_pins_single_loopback_comfy_and_safe_flux_flags(
    tmp_path: Path,
) -> None:
    controller = ProductionComfyProcessController(
        python_path=Path("/runtime/rocm/python"),
        comfy_root=Path("/persistent/douyin-amd/comfyui/0.30.0-6f7cd7fc"),
        runtime_root=Path("/workspace/amd-runtime-cache"),
        port=18188,
        process_scanner=lambda: (),
        gpu_snapshot=lambda: {"usePercent": 0, "vramUsedBytes": 0},
    )

    flux = controller.command_for("flux", ("--highvram", "--cache-none", "--reserve-vram", "2"))
    h3 = controller.command_for("h3", ())

    for command in (flux, h3):
        assert command.count("--highvram") == 1
        assert command.count("--cache-none") == 1
        assert command[command.index("--reserve-vram") + 1] == "2"
        assert command[command.index("--listen") + 1] == "127.0.0.1"
        assert command[command.index("--port") + 1] == "18188"
        assert "--lowvram" not in command
        assert "--disable-mmap" not in command

    with pytest.raises(RuntimeWiringError, match="runner arguments"):
        controller.command_for("flux", ("--lowvram",))


def test_memory_gate_uses_cgroup_file_cache_pvc_and_process_authorities(
    tmp_path: Path,
) -> None:
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.current").write_text(str(43 * 1024**3), encoding="utf-8")
    (cgroup / "memory.max").write_text("59055800320", encoding="utf-8")
    (cgroup / "memory.swap.current").write_text("0", encoding="utf-8")
    (cgroup / "memory.swap.max").write_text("0", encoding="utf-8")
    (cgroup / "memory.stat").write_text("anon 100\nfile 200\n", encoding="utf-8")
    (cgroup / "memory.events.local").write_text("low 0\nhigh 0\nmax 7\noom 0\noom_kill 0\n", encoding="utf-8")
    gate = CgroupMemoryAdmissionGate(
        cgroup_root=cgroup,
        persistent_root=tmp_path,
        available_bytes=lambda _: 6 * 1024**3,
        process_scanner=lambda: (),
    )

    evidence = gate.capture_and_require_go("flux")

    assert evidence["memoryCurrentBytes"] == 43 * 1024**3
    assert evidence["fileCacheBytes"] == 200
    assert evidence["pvcAvailableBytes"] == 6 * 1024**3
    assert evidence["memoryEventsLocal"]["max"] == 7

    (cgroup / "memory.current").write_text(str(44 * 1024**3), encoding="utf-8")
    with pytest.raises(RuntimeWiringError, match="memory.current"):
        gate.capture_and_require_go("h3")


def test_page_cache_reclaimer_accepts_only_exact_manifest_bound_files(
    tmp_path: Path,
) -> None:
    weight = tmp_path / "weight.safetensors"
    weight.write_bytes(b"weight")
    digest = "a" * 64
    advised: list[tuple[int, int, int, int]] = []
    reclaimer = ExactPosixPageCacheReclaimer(
        allowed_weights=((str(weight.resolve()), digest),),
        persistent_root=tmp_path,
        advise=lambda fd, offset, length, advice: advised.append(
            (fd, offset, length, advice)
        ),
        memory_snapshot=lambda: {"memoryCurrentBytes": 1, "fileCacheBytes": 2},
        wait_seconds=0,
    )

    evidence = reclaimer.reclaim(((str(weight.resolve()), digest),))

    assert len(advised) == 1
    assert advised[0][1:] == (0, 0, POSIX_FADV_DONTNEED)
    assert evidence["files"][0]["sha256"] == digest
    with pytest.raises(RuntimeWiringError, match="manifest-bound"):
        reclaimer.reclaim(((str(weight.resolve()), "b" * 64),))


def test_loopback_comfy_session_recovers_submits_downloads_and_unloads(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    output_root.mkdir()
    source = tmp_path / "source.png"
    source.write_bytes(b"png-source")
    output = output_root / "result.png"
    output.write_bytes(b"png-result")
    submitted: list[dict[str, object]] = []
    posts: list[tuple[str, object]] = []
    metadata = {
        "submission_nonce": "n" * 32,
        "workflow_sha256": "a" * 64,
        "assets_sha256": "b" * 64,
    }
    history = {
        "prompt-1": {
            "prompt": [17, "prompt-1", {}, {"extra_data": metadata}],
            "status": {"completed": True, "status_str": "success"},
            "extra_data": metadata,
            "outputs": {"13": {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}]}},
        }
    }

    def request(method: str, path: str, payload: object | None, timeout: float):
        del timeout
        if method == "GET" and path == "/history/prompt-1":
            return history
        if method == "GET" and path == "/queue":
            return {"queue_running": [], "queue_pending": []}
        if method == "POST" and path == "/prompt":
            assert isinstance(payload, dict)
            submitted.append(payload)
            return {"prompt_id": "prompt-1", "number": 17, "node_errors": {}}
        if method == "POST" and path == "/free":
            posts.append((path, payload))
            return {}
        raise AssertionError((method, path, payload))

    session = LoopbackComfySession(
        base_url="http://127.0.0.1:18188",
        input_root=input_root,
        output_root=output_root,
        request=request,
        sleep=lambda _: None,
        timeout_seconds=1,
    )
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    session.stage_input(source, "safe/source.png", source_sha)
    assert (input_root / "safe" / "source.png").read_bytes() == source.read_bytes()
    assert session.recover_submission(
        prompt_id="prompt-1",
        client_id="client",
        submission_nonce="n" * 32,
        required_metadata=metadata,
    ) == "prompt-1"
    assert session.queue_id_for_prompt("prompt-1") == 17
    assert session.submit(
        {"1": {"class_type": "Node", "inputs": {}}},
        client_id="client",
        submission_nonce="n" * 32,
        extra_data=metadata,
    ) == "prompt-1"
    session.wait_success("prompt-1")
    destination = tmp_path / "download.png.partial"
    assert session.download("prompt-1", destination) == destination
    assert destination.read_bytes() == output.read_bytes()
    session.unload_models()
    assert posts == [("/free", {"unload_models": True, "free_memory": True})]
    assert submitted[0]["extra_data"] == metadata


def test_ffprobe_accepts_competition_media_range_but_keeps_audio_hard_gate(
    tmp_path: Path,
) -> None:
    media = tmp_path / "slice.mp4"
    media.write_bytes(b"media")
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "avg_frame_rate": "24/1",
                "nb_read_frames": "73",
            },
            {"codec_type": "audio"},
        ],
        "format": {"duration": "3.041667", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
    }

    summary = probe_h3_media(
        media,
        command_runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(probe),
            stderr="",
        ),
        ffprobe_path="ffprobe",
    )

    assert summary.frame_count == 73
    assert summary.fps == 24.0
    assert summary.audio_streams == 1
    assert summary.subtitle_streams == 0

    probe["streams"].append({"codec_type": "subtitle"})
    with pytest.raises(RuntimeWiringError, match="subtitle"):
        probe_h3_media(
            media,
            command_runner=lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout=json.dumps(probe),
                stderr="",
            ),
            ffprobe_path="ffprobe",
        )

    probe["streams"].pop()
    probe["streams"][0]["nb_read_frames"] = "72"
    summary = probe_h3_media(
        media,
        command_runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(probe),
            stderr="",
        ),
        ffprobe_path="ffprobe",
    )
    assert summary.frame_count == 72

    probe["streams"][0]["nb_read_frames"] = "107"
    probe["format"]["duration"] = "4.458333"
    with pytest.raises(RuntimeWiringError, match="duration|frame"):
        probe_h3_media(
            media,
            command_runner=lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout=json.dumps(probe),
                stderr="",
            ),
            ffprobe_path="ffprobe",
        )
