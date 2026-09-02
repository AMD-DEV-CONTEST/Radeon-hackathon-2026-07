import hashlib
import json
import math
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.model_integrity as model_integrity
from services.embedding import (
    MockEmbeddingProvider,
    UnavailableEmbeddingProvider,
    WorkerEmbeddingProvider,
    create_embedding_provider,
)
from services.embedding_runtime import DEFAULT_MANIFEST_PATH, EmbeddingRuntimeUnavailable, load_bge_m3_manifest
from services.embedding_runtime import BgeM3OnnxRuntime, select_execution_providers
from services.embedding_runtime.manifest import BgeM3Manifest, ModelArtifact
from services.model_runtime.worker_process import BgeM3WorkerAdapter
from tests.asgi_client import asgi_request
from scripts.install_embedding_runtime import (
    ORT_VERSION,
    ROCM_INDEX,
    ROCM_RELEASE,
    build_install_plan,
    detect_rocm_release,
)


def test_bge_m3_manifest_freezes_multilingual_dense_runtime_contract():
    manifest = load_bge_m3_manifest()

    assert manifest.model_id == "BAAI/bge-m3"
    assert manifest.dimensions == 1024
    assert manifest.max_tokens == 8192
    assert manifest.normalization == "l2"
    assert "dense" in manifest.output_modes
    assert manifest.provider_preference == (
        "MIGraphXExecutionProvider",
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    )
    assert len(manifest.artifacts) == 8
    assert all(len(artifact.sha256) == 64 for artifact in manifest.artifacts)


def test_bge_m3_worker_runs_model_operations_on_main_thread(tmp_path):
    adapter = BgeM3WorkerAdapter(tmp_path)

    assert adapter.run_operations_on_main_thread is True


def test_manifest_rejects_artifact_path_escape(tmp_path):
    payload = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["artifacts"][0]["path"] = "../model.onnx"
    invalid_manifest = tmp_path / "manifest.json"
    invalid_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="inside model root"):
        load_bge_m3_manifest(invalid_manifest)


def test_production_factory_never_uses_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHERDB_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("AETHERDB_ENV", "production")

    provider = create_embedding_provider(model_root=tmp_path)

    assert isinstance(provider, UnavailableEmbeddingProvider)
    assert provider.status().available is False
    with pytest.raises(EmbeddingRuntimeUnavailable):
        provider.embed("must not become a fake production vector")


def test_mock_is_explicit_test_only_and_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHERDB_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("AETHERDB_ENV", "test")

    provider = create_embedding_provider(model_root=tmp_path)
    first = provider.embed("多语言 semantic retrieval")
    second = provider.embed("多语言 semantic retrieval")

    assert isinstance(provider, MockEmbeddingProvider)
    assert first == second
    assert len(first) == 1024
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


def test_missing_model_artifacts_report_stable_unavailable_state(monkeypatch, tmp_path):
    monkeypatch.delenv("AETHERDB_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("AETHERDB_ENV", raising=False)

    provider = create_embedding_provider(model_root=tmp_path)
    status = provider.status()

    assert isinstance(provider, UnavailableEmbeddingProvider)
    assert status.available is False
    assert status.model_id == "BAAI/bge-m3"
    assert status.dimensions == 1024
    assert status.detail == "BGE-M3 model artifacts are missing (8 files)"


def test_production_factory_keeps_verified_bge_runtime_out_of_api_process(
    monkeypatch, tmp_path
):
    artifact = tmp_path / "onnx" / "model.onnx"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"worker-owned-model")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = BgeM3Manifest(
        model_id="BAAI/bge-m3",
        revision="b" * 40,
        license="MIT",
        dimensions=1024,
        max_tokens=8192,
        output_modes=("dense",),
        normalization="l2",
        provider_preference=("CPUExecutionProvider",),
        artifacts=(
            ModelArtifact(
                "onnx/model.onnx",
                artifact.stat().st_size,
                digest,
            ),
        ),
    )
    manifest.write_verification_record(tmp_path)
    monkeypatch.setattr("services.embedding.load_bge_m3_manifest", lambda _path: manifest)
    monkeypatch.setenv("AETHERDB_EMBEDDING_PROVIDER", "bge-m3")
    monkeypatch.setenv("AETHERDB_ENV", "production")

    provider = create_embedding_provider(model_root=tmp_path)

    assert isinstance(provider, WorkerEmbeddingProvider)
    assert provider.status().available is True
    assert not hasattr(provider, "runtime")


def test_semantic_api_returns_503_before_search_when_runtime_is_unavailable(monkeypatch, tmp_path):
    from app.dependencies.auth import USER_API_KEY
    from main import app

    monkeypatch.delenv("AETHERDB_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("AETHERDB_ENV", raising=False)
    provider = create_embedding_provider(model_root=tmp_path)
    previous_store = app.state.vector_store
    app.state.vector_store = SimpleNamespace(embedding=provider)
    try:
        status_code, payload = asgi_request(
            app,
            "POST",
            "/api/search/semantic",
            headers={"x-api-key": USER_API_KEY},
            json_body={
                "query": "test",
                "database_id": "not-reached",
                "book_id": "not-reached",
            },
        )
    finally:
        app.state.vector_store = previous_store

    assert status_code == 503
    assert payload["detail"] == {
        "code": "EMBEDDING_RUNTIME_UNAVAILABLE",
        "message": "BGE-M3 model artifacts are missing (8 files)",
        "model_id": "BAAI/bge-m3",
    }


def test_execution_provider_selection_prefers_migraphx_then_cuda_then_cpu():
    preference = (
        "MIGraphXExecutionProvider",
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    )

    assert select_execution_providers(
        ["CPUExecutionProvider", "CUDAExecutionProvider", "MIGraphXExecutionProvider"],
        preference,
    ) == ("MIGraphXExecutionProvider", "CPUExecutionProvider")
    assert select_execution_providers(
        ["CPUExecutionProvider", "CUDAExecutionProvider"],
        preference,
    ) == ("CUDAExecutionProvider", "CPUExecutionProvider")
    assert select_execution_providers(["CPUExecutionProvider"], preference) == (
        "CPUExecutionProvider",
    )


def test_explicit_unavailable_accelerator_does_not_silently_switch():
    with pytest.raises(EmbeddingRuntimeUnavailable, match="MIGraphXExecutionProvider"):
        select_execution_providers(
            ["CPUExecutionProvider"],
            ("MIGraphXExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"),
            requested="rocm",
        )


def test_migraphx_worker_resolves_external_data_from_verified_model_directory(tmp_path):
    model_root = tmp_path / "bge-m3"
    model_directory = model_root / "onnx"
    model_directory.mkdir(parents=True)
    observed = {}

    class Runtime:
        def embed_batch(self, texts):
            observed["cwd"] = Path.cwd()
            return SimpleNamespace(
                vectors=[[1.0] + [0.0] * 1023 for _ in texts],
                model_id="BAAI/bge-m3",
                revision="test",
                dimensions=1024,
                execution_provider="MIGraphXExecutionProvider",
                normalized=True,
                elapsed_ms=1.0,
            )

    original_directory = Path.cwd()
    adapter = BgeM3WorkerAdapter(model_root)
    adapter.runtime = Runtime()
    adapter.backend = "rocm_migraphx"

    result = adapter.infer(
        {"texts": ["multilingual worker probe"]},
        threading.Event(),
    )

    assert observed["cwd"] == model_directory.resolve()
    assert Path.cwd() == original_directory
    assert result["execution_provider"] == "MIGraphXExecutionProvider"
    assert result["effective_backend"] == "rocm_migraphx"


class _FakeEncoding:
    ids = [0, 7, 2]
    attention_mask = [1, 1, 1]
    type_ids = [0, 0, 0]


class _FakeTokenizer:
    @classmethod
    def from_file(cls, path):
        return cls()

    def enable_truncation(self, max_length):
        self.max_length = max_length

    def enable_padding(self, pad_id, pad_token):
        self.padding = (pad_id, pad_token)

    def encode_batch(self, texts):
        return [_FakeEncoding() for _ in texts]


class _FakeInput:
    def __init__(self, name):
        self.name = name


class _FakeSession:
    def __init__(self, model_path, providers):
        self.providers = providers

    def get_providers(self):
        return self.providers

    def get_inputs(self):
        return [_FakeInput("input_ids"), _FakeInput("attention_mask")]

    def run(self, output_names, feeds):
        import numpy as np

        batch = feeds["input_ids"].shape[0]
        hidden = np.zeros((batch, 3, 1024), dtype=np.float32)
        hidden[:, 0, 0] = 3.0
        hidden[:, 0, 1] = 4.0
        return [hidden]


class _FakeOrt:
    InferenceSession = _FakeSession

    @staticmethod
    def get_available_providers():
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_runtime_batches_cls_pools_and_l2_normalizes(tmp_path):
    import numpy as np

    manifest = load_bge_m3_manifest()
    fixture_artifacts = []
    for artifact in manifest.artifacts:
        path = tmp_path / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"fixture:{artifact.path}".encode("utf-8")
        path.write_bytes(payload)
        fixture_artifacts.append(
            ModelArtifact(
                artifact.path,
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
        )
    fixture_manifest = BgeM3Manifest(
        model_id=manifest.model_id,
        revision=manifest.revision,
        license=manifest.license,
        dimensions=manifest.dimensions,
        max_tokens=manifest.max_tokens,
        output_modes=manifest.output_modes,
        normalization=manifest.normalization,
        provider_preference=manifest.provider_preference,
        artifacts=tuple(fixture_artifacts),
    )
    fixture_manifest.write_verification_record(tmp_path)

    runtime = BgeM3OnnxRuntime(
        tmp_path,
        manifest=fixture_manifest,
        batch_size=2,
        ort_module=_FakeOrt,
        numpy_module=np,
        tokenizer_class=_FakeTokenizer,
    )
    result = runtime.embed_batch(["中文", "English", "日本語"])

    assert result.execution_provider == "CUDAExecutionProvider"
    assert result.dimensions == 1024
    assert len(result.vectors) == 3
    assert result.vectors[0][:3] == pytest.approx([0.6, 0.8, 0.0])
    assert all(
        math.isclose(sum(value * value for value in vector), 1.0, rel_tol=1e-6)
        for vector in result.vectors
    )


def test_verification_record_detects_model_changes(tmp_path):
    artifact_path = tmp_path / "onnx" / "model.onnx"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"verified fixture")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    manifest = BgeM3Manifest(
        model_id="BAAI/bge-m3",
        revision="a" * 40,
        license="MIT",
        dimensions=1024,
        max_tokens=8192,
        output_modes=("dense",),
        normalization="l2",
        provider_preference=(
            "MIGraphXExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ),
        artifacts=(ModelArtifact("onnx/model.onnx", artifact_path.stat().st_size, digest),),
    )

    assert manifest.verify_artifacts(tmp_path) == ()
    manifest.write_verification_record(tmp_path)
    assert manifest.verification_record_is_current(tmp_path) is True

    artifact_path.write_bytes(b"modified fixture")
    assert manifest.verification_record_is_current(tmp_path) is False


def test_integrity_hash_does_not_trust_unchanged_metadata_by_default(
    tmp_path, monkeypatch
):
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"first-content")
    signature = model_integrity._signature(artifact)
    first = model_integrity.sha256_file(artifact, use_cache=True)

    artifact.write_bytes(b"other-content")
    monkeypatch.setattr(model_integrity, "_signature", lambda _path: signature)

    assert model_integrity.sha256_file(artifact) != first


def test_runtime_install_plans_keep_cpu_cuda_and_rocm_mutually_exclusive():
    cpu = build_install_plan("cpu", system="Windows")
    cuda = build_install_plan("cuda", system="Windows")
    rocm = build_install_plan(
        "rocm",
        system="Linux",
        rocm_release=ROCM_RELEASE,
    )

    assert cpu[1][-1] == f"onnxruntime=={ORT_VERSION}"
    assert cuda[1][-1] == f"onnxruntime-gpu=={ORT_VERSION}"
    assert f"onnxruntime_migraphx=={ORT_VERSION}" in rocm[1]
    assert ROCM_INDEX in rocm[1]
    assert "--no-index" in rocm[1]
    assert "--find-links" in rocm[1]
    assert all("uninstall" in plan[0] for plan in (cpu, cuda, rocm))


def test_rocm_installer_uses_matching_host_patch_release(tmp_path):
    version = tmp_path / "version"
    version.write_text("7.2.1\n", encoding="utf-8")
    assert detect_rocm_release({}, (version,)) == "7.2.1"
    plan = build_install_plan("rocm", system="Linux", rocm_release="7.2.1")
    assert (
        "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/"
        in plan[1]
    )
    with pytest.raises(ValueError, match="major.minor.patch"):
        build_install_plan(
            "rocm",
            system="Linux",
            rocm_release="7.2.1/../../unsafe",
        )


def test_rocm_installer_rejects_windows_instead_of_installing_wrong_runtime():
    with pytest.raises(ValueError, match="Linux only"):
        build_install_plan("rocm", system="Windows")
