from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_docker_image_is_self_contained_and_has_runtime_entrypoint() -> None:
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text()
    assert "COPY . ." in dockerfile
    assert 'PYOPENGL_PLATFORM=egl' in dockerfile
    assert 'ENTRYPOINT ["/workspace/radeonvla-reflex/docker/entrypoint.sh"]' in dockerfile
    assert "python -m pytest" in dockerfile
    assert "python -m radeonvla.submission_audit" in dockerfile
    assert "ARG BASE_IMAGE=docker.io/rocm/dev-ubuntu-24.04:7.2.1-complete@sha256:" in dockerfile
    assert "str(torch.version.hip).startswith('7.2')" in dockerfile
    assert "startswith('7.2.1')" not in dockerfile
    assert '"/tmp/rocm-wheels/$TORCH_WHL"' in dockerfile
    assert "cd /tmp/rocm-wheels" not in dockerfile


def test_compose_exposes_one_amd_gpu_and_persistent_outputs() -> None:
    compose = yaml.safe_load((ROOT / "docker" / "compose.yaml").read_text())
    service = compose["services"]["radeonvla"]
    assert "/dev/kfd:/dev/kfd" in service["devices"]
    assert "/dev/dri:/dev/dri" in service["devices"]
    assert service["environment"]["HIP_VISIBLE_DEVICES"] == "${HIP_VISIBLE_DEVICES:-0}"
    assert service["environment"]["EPISODES"] == "${EPISODES:-200}"
    assert service["environment"]["SKIP_RECORD"] == "${SKIP_RECORD:-0}"
    assert service["environment"]["DR_REBUILD_EVERY"] == "${DR_REBUILD_EVERY:-20}"
    assert service["environment"]["HF_ENDPOINT"] == "${HF_ENDPOINT:-https://huggingface.co}"
    mounts = set(service["volumes"])
    assert "../datasets:/workspace/radeonvla-reflex/datasets" in mounts
    assert "../artifacts:/workspace/radeonvla-reflex/artifacts" in mounts
    assert "hf-cache:/root/.cache/huggingface" in mounts


def test_dockerignore_keeps_required_assets_and_schema() -> None:
    patterns = (ROOT / ".dockerignore").read_text().splitlines()
    assert "assets" not in patterns
    assert "!artifacts/evaluation.schema.json" in patterns
    assert "datasets" in patterns
    assert "_local" in patterns
