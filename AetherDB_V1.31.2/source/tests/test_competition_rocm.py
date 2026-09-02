import json
import os
import re
from pathlib import Path

import pytest
import yaml

from scripts.verify_rocm import (
    PINNED_ROCM_BASE_IMAGE,
    RocmProbeError,
    _verified_model_rows,
    build_probe_report,
    persist_report,
    validate_competition_environment,
)
from services.model_runtime.contracts import (
    RuntimePolicyUpdate,
    SchedulingPolicy,
)
from services.model_runtime.hardware import parse_amd_smi_json
from services.model_runtime.scheduler import ResourceScheduler


ROOT = Path(__file__).resolve().parents[1]
FULL_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def competition_environment():
    return {
        "AETHERDB_EXECUTION_MODE": "competition",
        "REQUIRE_ROCM": "true",
        "ALLOW_SILENT_FALLBACK": "false",
        "ALLOW_UNVERIFIED_MODEL": "false",
        "AETHERDB_COMPETITION_IMAGE": (
            "registry.example/aetherdb-competition@sha256:" + "1" * 64
        ),
        "AETHERDB_ROCM_BASE_IMAGE_REF": PINNED_ROCM_BASE_IMAGE,
    }


def test_competition_environment_is_fail_closed_and_digest_pinned():
    policy = validate_competition_environment(competition_environment())
    assert policy["require_rocm"] is True
    assert policy["allow_silent_fallback"] is False
    assert FULL_DIGEST.search(policy["competition_image"])

    invalid = competition_environment()
    invalid["ALLOW_SILENT_FALLBACK"] = "true"
    with pytest.raises(RocmProbeError) as exc:
        validate_competition_environment(invalid)
    assert exc.value.code == "COMPETITION_POLICY_INVALID"

    invalid = competition_environment()
    invalid["AETHERDB_COMPETITION_IMAGE"] = "aetherdb-competition:latest"
    with pytest.raises(RocmProbeError) as exc:
        validate_competition_environment(invalid)
    assert exc.value.code == "COMPETITION_IMAGE_NOT_IMMUTABLE"


def test_rocm_dockerfile_and_compose_freeze_reproducible_contract():
    dockerfile = (
        ROOT / "deploy" / "docker" / "Dockerfile.rocm"
    ).read_text(encoding="utf-8")
    compose_path = ROOT / "deploy" / "docker" / "docker-compose.competition.yaml"
    compose_text = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    service = compose["services"]["aetherdb-competition"]

    from_line = next(line for line in dockerfile.splitlines() if line.startswith("FROM "))
    assert FULL_DIGEST.search(from_line)
    assert "rocm7.2.4_ubuntu22.04_py3.10_pytorch_release_2.9.1" in from_line
    assert "latest" not in dockerfile.lower()
    assert service["image"].startswith("${AETHERDB_COMPETITION_IMAGE:?")
    assert service["devices"] == ["/dev/kfd:/dev/kfd", "/dev/dri:/dev/dri"]
    assert service["ports"][0]["host_ip"] == "127.0.0.1"
    assert service["ports"][0]["published"] == "${AETHERDB_HOST_PORT:-0}"
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert "seccomp=unconfined" in service["security_opt"]
    assert service["environment"]["REQUIRE_ROCM"] == "true"
    assert service["environment"]["ALLOW_SILENT_FALLBACK"] == "false"
    assert service["environment"]["ALLOW_UNVERIFIED_MODEL"] == "false"
    assert "8000" not in compose_text
    assert "api_key" not in compose_text.lower()


def test_platform_probe_never_claims_model_readiness_without_worker_evidence():
    report = build_probe_report(
        policy={"execution_mode": "competition"},
        device={"verified": True},
        framework={"verified": True},
        compute={"verified": True},
        model_rows=[],
        required_packages=(),
    )
    assert report["platform_verified"] is True
    assert report["competition_ready"] is False
    assert report["model_evidence"]["verified"] is False

    report = build_probe_report(
        policy={"execution_mode": "competition"},
        device={"verified": True},
        framework={"verified": True},
        compute={"verified": True},
        model_rows=[{"package_id": "aetherdb-bge-m3"}],
        required_packages=("aetherdb-bge-m3",),
    )
    assert report["competition_ready"] is True


def test_probe_report_is_written_only_below_private_runtime(tmp_path):
    report = {
        "platform_verified": True,
        "competition_ready": False,
        "policy": {"competition_image_digest": "sha256:" + "1" * 64},
    }
    target = persist_report(report, tmp_path.resolve())
    assert target == tmp_path / "evidence" / "rocm" / "competition-probe.json"
    assert json.loads(target.read_text(encoding="utf-8")) == report
    with pytest.raises(RocmProbeError):
        persist_report(report, Path("relative-runtime"))


def test_amd_smi_json_populates_scheduler_device_contract():
    listing = json.dumps(
        [{"gpu": 0, "uuid": "GPU-TEST-0"}]
    )
    static = json.dumps(
        [
            {
                "gpu": 0,
                "asic": {"market_name": "AMD Radeon PRO W7900"},
                "vram": {"size": {"value": 49136, "unit": "MB"}},
                "driver_version": "test-driver",
            }
        ]
    )
    metric = json.dumps(
        [
            {
                "gpu": 0,
                "vram_usage": {
                    "used": {"value": 1024, "unit": "MB"},
                    "free": {"value": 48112, "unit": "MB"},
                },
                "usage": {"gfx_activity": {"value": 25, "unit": "%"}},
            }
        ]
    )
    devices = parse_amd_smi_json(listing, static, metric)
    assert len(devices) == 1
    assert devices[0].source == "amd-smi"
    assert devices[0].name == "AMD Radeon PRO W7900"
    assert devices[0].total_vram_mb == 49136
    assert devices[0].used_vram_mb == 1024
    assert devices[0].utilization_percent == 25


def test_competition_environment_locks_scheduler_policy(tmp_path, monkeypatch):
    import services.database_registry as registry
    import services.model_runtime.scheduler as scheduler_module

    monkeypatch.setattr(registry, "REGISTRY_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setattr(
        scheduler_module,
        "_get_registry_conn",
        registry._get_registry_conn,
    )
    registry.init_registry()
    for name, value in competition_environment().items():
        monkeypatch.setenv(name, value)

    scheduler = ResourceScheduler()
    result = scheduler.update_policy(
        RuntimePolicyUpdate(
            scheduling_policy=SchedulingPolicy.PARALLEL,
            competition_mode=False,
        )
    )
    assert result["competition_mode"] is True


def test_model_readiness_accepts_only_current_worker_rocm_evidence(
    tmp_path,
    monkeypatch,
):
    import services.database_registry as registry
    from services.model_packages.registry import sync_catalog

    runtime_root = tmp_path.resolve()
    registry_path = runtime_root / "app_data" / "registry.db"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv(
        "AETHERDB_MODEL_PACKAGE_CATALOG",
        str(ROOT / "resources" / "model_packages"),
    )
    registry.init_registry()
    sync_catalog()

    fingerprint = "a" * 64
    scheduler = ResourceScheduler()
    scheduler.record_runtime_evidence(
        package_id="aetherdb.bge-m3",
        device_fingerprint=fingerprint,
        backend="rocm_migraphx",
        verification_status="VERIFIED_ROCM",
        probe_ref="worker:test-runtime",
    )

    rows = _verified_model_rows(
        ("aetherdb.bge-m3",),
        runtime_root,
        (fingerprint,),
    )
    assert rows[0]["package_id"] == "aetherdb.bge-m3"
    assert rows[0]["backend"] == "rocm_migraphx"
    assert rows[0]["probe_ref"] == "worker:test-runtime"

    with pytest.raises(RocmProbeError) as exc:
        _verified_model_rows(
            ("aetherdb.bge-m3",),
            runtime_root,
            ("b" * 64,),
        )
    assert exc.value.code == "MODEL_RUNTIME_UNVERIFIED"
