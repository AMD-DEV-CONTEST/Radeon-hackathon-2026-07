import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.deployment import PublicationStatus, SyncDirection
from app.instance_identity import (
    INSTANCE_ID_PREFIX,
    InstanceIdentityError,
    get_or_create_source_instance_id,
)
from scripts.container_entrypoint import ContainerConfigurationError, build_command


ROOT = Path(__file__).resolve().parents[1]


def test_container_entrypoint_requires_configurable_nonlegacy_port(tmp_path):
    environment = {
        "AETHERDB_CONTAINER_PORT": "8765",
        "AETHERDB_RUNTIME_ROOT": str(tmp_path),
    }
    command = build_command(environment)
    assert command[-5:] == ["--port", "8765", "--workers", "1", "--no-access-log"]
    assert command[command.index("--host") + 1] == "0.0.0.0"

    with pytest.raises(ContainerConfigurationError):
        build_command({**environment, "AETHERDB_CONTAINER_PORT": "8000"})
    with pytest.raises(ContainerConfigurationError):
        build_command({**environment, "AETHERDB_CONTAINER_PORT": ""})


def test_docker_core_is_loopback_dynamic_and_has_no_sensitive_mounts():
    compose_path = ROOT / "deploy" / "docker" / "docker-compose.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    service = compose["services"]["aetherdb-core"]
    rendered = compose_path.read_text(encoding="utf-8").lower()

    assert service["image"] == "aetherdb-core:1.31.2"
    assert service["ports"][0]["host_ip"] == "127.0.0.1"
    assert service["ports"][0]["published"] == "${AETHERDB_HOST_PORT:-0}"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "config.yaml" not in rendered
    assert "latest" not in rendered
    assert "8000" not in rendered
    assert "api_key" not in rendered


def test_docker_build_context_excludes_private_runtime_and_weights():
    patterns = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    required = {
        ".api_keys.json",
        "config.yaml",
        "config.local.yaml",
        "app_data",
        "logs",
        "local_agent_runs",
        "*.onnx",
        "*.safetensors",
        "*.gguf",
    }
    assert required.issubset(set(patterns))
    dockerfile = (ROOT / "deploy" / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "chown -R aetherdb:aetherdb /var/lib/aetherdb /models" in dockerfile


def test_init_runtime_honors_separate_resource_and_runtime_roots(tmp_path):
    runtime_root = tmp_path / "fresh" / "runtime"
    assert not runtime_root.exists()
    environment = os.environ.copy()
    environment["AETHERDB_RESOURCE_ROOT"] = str(ROOT)
    environment["AETHERDB_RUNTIME_ROOT"] = str(runtime_root)
    environment["PYTHONUTF8"] = "1"
    for name in (
        "ADMIN_API_KEY",
        "USER_API_KEY",
        "NOVEL_ADMIN_KEY",
        "NOVEL_API_KEY",
    ):
        environment.pop(name, None)

    result = subprocess.run(
        [sys.executable, "scripts/init_runtime.py"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert (runtime_root / "config.local.yaml").is_file()
    assert (runtime_root / ".api_keys.json").is_file()
    identity_path = runtime_root / "app_data" / "instance.json"
    assert identity_path.is_file()
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    assert identity["source_instance_id"].startswith(INSTANCE_ID_PREFIX)
    assert (runtime_root / "app_data" / "databases").is_dir()
    assert "nvk_admin_" not in result.stdout
    assert "nvk_" not in result.stdout


def test_source_instance_identity_is_random_stable_and_fails_closed(tmp_path):
    first = get_or_create_source_instance_id(tmp_path)
    second = get_or_create_source_instance_id(tmp_path)
    assert first == second
    assert first.startswith(INSTANCE_ID_PREFIX)
    for environment_name in ("USERNAME", "COMPUTERNAME"):
        environment_value = os.environ.get(environment_name)
        if environment_value:
            assert environment_value not in first

    (tmp_path / "instance.json").write_text(
        '{"schema_version":1,"source_instance_id":"device-name"}',
        encoding="utf-8",
    )
    with pytest.raises(InstanceIdentityError):
        get_or_create_source_instance_id(tmp_path)


def test_publication_foundation_is_one_way_and_private_by_default():
    assert PublicationStatus.PRIVATE.value == "private"
    assert list(SyncDirection) == [SyncDirection.LOCAL_TO_CLOUD_PUBLISH]


def test_native_service_templates_are_loopback_only_and_fail_closed():
    linux_setup = (ROOT / "deploy" / "linux" / "setup.sh").read_text(
        encoding="utf-8"
    )
    systemd = (
        ROOT / "deploy" / "linux" / "systemd" / "worldview.service"
    ).read_text(encoding="utf-8")
    nginx = (
        ROOT / "deploy" / "linux" / "nginx" / "worldview.conf"
    ).read_text(encoding="utf-8")
    windows = (
        ROOT / "deploy" / "windows" / "install_service.ps1"
    ).read_text(encoding="utf-8")
    combined = "\n".join((linux_setup, systemd, nginx, windows)).lower()

    assert "port = 8000" not in combined
    assert "--port 8000" not in combined
    assert ":8000" not in combined
    assert "allow 8000" not in combined
    assert "0.0.0.0" not in combined
    assert "change-me" not in combined
    assert "admin_api_key=" not in combined
    assert "user_api_key=" not in combined
    assert "nssm.cc" not in combined
    assert "workers 4" not in combined
    assert 'aetherdb_host="127.0.0.1"' in linux_setup.lower()
    assert "aetherdb_host=127.0.0.1" in windows.lower()
    assert "aetherdb_deployment_mode=local_desktop" in windows.lower()
    assert "readwritepaths=@aetherdb_runtime_root@" in systemd.lower()
    assert "no nginx server, listen, or proxy directive" in nginx.lower()


def test_windows_service_scripts_have_bounded_waits_and_retain_runtime():
    install = (
        ROOT / "deploy" / "windows" / "install_service.ps1"
    ).read_text(encoding="utf-8")
    uninstall = (
        ROOT / "deploy" / "windows" / "uninstall_service.ps1"
    ).read_text(encoding="utf-8")

    assert "AddSeconds(120)" in install
    assert "AddSeconds(30)" in uninstall
    assert "ReplaceExisting" in install
    assert "Invoke-WebRequest" not in install.split("Get-NssmExecutable", 1)[1].split(
        "function Get-AvailableLoopbackPort", 1
    )[0]
    assert "Data removal is a separate, explicit operator action" in uninstall
