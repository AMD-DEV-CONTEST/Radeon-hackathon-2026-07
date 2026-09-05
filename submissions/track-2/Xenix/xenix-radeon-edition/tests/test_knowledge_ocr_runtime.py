from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_knowledge_ocr_runtime.py"


def _build_module():
    name = "xenix_knowledge_ocr_build_for_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _lock() -> SimpleNamespace:
    return SimpleNamespace(
        protocol_version=2,
        runtime_id="runtime-id",
        model_pack_id="model-pack-id",
    )


def _runtime(build, root: Path, *, worker: bytes = b"worker") -> Path:
    runtime = root / build.RUNTIME_DIRECTORY
    _write(runtime / "xenix-ocr.exe", worker)
    _write(runtime / "dependency.dll", b"dependency")
    _write(runtime / "models/detection/inference.yml", b"detection")
    _write(runtime / "models/recognition/inference.yml", b"recognition")
    manifest = {
        "schema_version": 1,
        "protocol_version": 2,
        "runtime_id": "runtime-id",
        "model_pack_id": "model-pack-id",
        "files": [
            build._file_entry(path, runtime)
            for path in sorted(runtime.rglob("*"))
            if path.is_file()
        ],
    }
    (runtime / build.RUNTIME_MANIFEST_NAME).write_text(
        json.dumps(manifest), encoding="utf-8", newline="\n"
    )
    return runtime


def test_staged_runtime_excludes_pipeline_config_and_preserves_manifest_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    build = _build_module()
    work = tmp_path / "work"
    source = work / "PaddleOCR"
    _write(source / "LICENSE", b"paddle license")
    _write(
        source / "deploy/cpp_infer/third_party/abseil-cpp/LICENSE",
        b"abseil license",
    )
    _write(
        source / "deploy/cpp_infer/third_party/nlohmann/LICENSE.MIT",
        b"nlohmann license",
    )
    native_root = tmp_path / "native"
    _write(native_root / "THIRD_PARTY_NOTICES.txt", b"notices")
    monkeypatch.setattr(build, "NATIVE_ROOT", native_root)

    worker = _write(tmp_path / "xenix-ocr.exe", b"worker")
    vcomp = _write(tmp_path / "vcomp140.dll", b"vcomp")
    paddle_root = tmp_path / "paddle"
    _write(paddle_root / "dependency.dll", b"dependency")
    opencv_root = tmp_path / "opencv"
    _write(opencv_root / "LICENSE", b"opencv license")
    detection_model = tmp_path / "detection"
    recognition_model = tmp_path / "recognition"
    _write(detection_model / "inference.yml", b"detection")
    _write(recognition_model / "inference.yml", b"recognition")

    lock = SimpleNamespace(
        runtime_files=["xenix-ocr.exe", "vcomp140.dll", "dependency.dll"],
        protocol_version=2,
        runtime_id="runtime-id",
        model_pack_id="model-pack-id",
        toolchain=SimpleNamespace(
            vcomp140_bytes=vcomp.stat().st_size,
            vcomp140_sha256=hashlib.sha256(vcomp.read_bytes()).hexdigest(),
        ),
    )

    runtime = build._stage_runtime(
        lock,
        work=work,
        source=source,
        worker=worker,
        paddle_root=paddle_root,
        opencv_root=opencv_root,
        detection_model=detection_model,
        recognition_model=recognition_model,
        vcomp140=vcomp,
    )

    assert not (runtime / build.PIPELINE_CONFIG_NAME).exists()
    manifest = json.loads(
        (runtime / build.RUNTIME_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 1
    assert manifest["protocol_version"] == 2
    assert build.PIPELINE_CONFIG_NAME not in {
        entry["path"] for entry in manifest["files"]
    }


def test_consumer_archive_runs_from_foreign_cwd_after_source_removal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    build = _build_module()
    runtime = _runtime(build, tmp_path / "stage")
    archive = build.write_content_addressed_archive(
        runtime,
        tmp_path / "output",
        runtime_id="runtime-id",
    )
    source = tmp_path / "builder" / "PaddleOCR"
    source.mkdir(parents=True)
    shutil.rmtree(source)
    observed: list[tuple[Path, Path, Path]] = []

    def verify(staged_runtime: Path, golden_image: Path, *, cwd: Path) -> None:
        assert not source.exists()
        assert cwd != staged_runtime
        assert (cwd / build.PIPELINE_CONFIG_NAME).read_text(encoding="utf-8") == (
            "invalid_pipeline_config: true\n"
        )
        observed.append((staged_runtime, golden_image, cwd))

    monkeypatch.setattr(build, "verify_runtime", verify)
    golden = tmp_path / "golden.png"
    build.verify_consumer_archive(
        archive,
        golden,
        tmp_path / "verification",
        _lock(),
        unavailable_source=source,
    )

    assert len(observed) == 1
    staged_runtime, golden_image, cwd = observed[0]
    assert staged_runtime != runtime
    assert golden_image == golden
    assert cwd.name == "foreign-cwd"


def test_consumer_archive_rejects_pipeline_config_member(tmp_path: Path) -> None:
    build = _build_module()
    runtime = _runtime(build, tmp_path / "stage")
    _write(runtime / build.PIPELINE_CONFIG_NAME, b"pipeline_name: OCR\n")
    archive = build.write_content_addressed_archive(
        runtime,
        tmp_path / "output",
        runtime_id="runtime-id",
    )

    with pytest.raises(RuntimeError, match="must not contain a pipeline config"):
        build.verify_consumer_archive(
            archive,
            tmp_path / "golden.png",
            tmp_path / "verification",
            _lock(),
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"builder-nonce-123",
        "builder-nonce-123".encode("utf-16le"),
    ],
    ids=["ascii", "utf-16le"],
)
def test_binary_provenance_scan_rejects_build_markers(
    tmp_path: Path,
    payload: bytes,
) -> None:
    build = _build_module()
    runtime = tmp_path / build.RUNTIME_DIRECTORY
    _write(runtime / "xenix-ocr.exe", b"prefix" + payload + b"suffix")

    with pytest.raises(RuntimeError, match="forbidden build provenance"):
        build._verify_runtime_binary_provenance(runtime, ("builder-nonce-123",))


class _OpenCvProcess:
    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def wait(self, *, timeout: float) -> int | None:
        del timeout
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_opencv_root_requires_the_build_sdk_members(tmp_path: Path) -> None:
    build = _build_module()
    stage = tmp_path / "stage"
    root = stage / "opencv" / "build"
    _write(root / "x64/vc16/lib/OpenCVConfig.cmake", b"config")
    _write(root / "x64/vc16/lib/opencv_world470.lib", b"library")
    _write(root / "x64/vc16/bin/opencv_world470.dll", b"dll")

    assert build._opencv_root(stage) == root


def test_remove_tree_clears_a_generated_read_only_file(tmp_path: Path) -> None:
    build = _build_module()
    generated = tmp_path / "PaddleOCR"
    locked = _write(generated / ".git/objects/pack/locked.idx", b"index")
    locked.chmod(stat.S_IREAD)

    build._remove_tree(generated)

    assert not generated.exists()


def test_opencv_extractor_accepts_a_normally_completed_sdk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    build = _build_module()
    process = _OpenCvProcess(returncode=0)
    root = tmp_path / "opencv-sdk"
    monkeypatch.setattr(build.subprocess, "Popen", lambda _command: process)
    monkeypatch.setattr(build, "_opencv_root", lambda _stage: root)

    assert build._extract_opencv(tmp_path / "opencv.exe", tmp_path / "stage") == root
    assert not process.terminated
    assert not process.killed


def test_opencv_extractor_stops_a_completed_but_nonexiting_sdk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    build = _build_module()
    process = _OpenCvProcess(returncode=None)
    root = tmp_path / "opencv-sdk"
    timestamps = iter((0.0, 0.0, 1.0, 2.0))
    monkeypatch.setattr(build.subprocess, "Popen", lambda _command: process)
    monkeypatch.setattr(build, "_opencv_root", lambda _stage: root)
    monkeypatch.setattr(build.time, "monotonic", lambda: next(timestamps))
    monkeypatch.setattr(build.time, "sleep", lambda _seconds: None)

    assert build._extract_opencv(tmp_path / "opencv.exe", tmp_path / "stage") == root
    assert process.terminated
    assert not process.killed
