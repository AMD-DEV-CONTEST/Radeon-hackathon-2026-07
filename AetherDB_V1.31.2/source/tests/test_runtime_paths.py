import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_separates_read_only_resources_from_user_data(tmp_path):
    resource_root = tmp_path / "installed-resources"
    runtime_root = tmp_path / "user-data"
    (resource_root / "prompts").mkdir(parents=True)
    (resource_root / "resources" / "model_manifests").mkdir(parents=True)
    (resource_root / "config.example.yaml").write_text("app:\n  name: test\n", encoding="utf-8")
    (resource_root / "prompts" / "sample.txt").write_text("resource prompt", encoding="utf-8")
    (resource_root / "resources" / "model_manifests" / "bge-m3.json").write_text(
        "{}", encoding="utf-8"
    )

    script = """
import json
from app.config import DB_PATH, get_runtime_config_path, get_writable_config_path
from app.dependencies import auth
from services.embedding_runtime.manifest import DEFAULT_MANIFEST_PATH
from services.prompt_engine.templates import load_template

writable = get_writable_config_path()
print(json.dumps({
    "runtime_config": str(get_runtime_config_path()),
    "writable_config": str(writable),
    "db_path": DB_PATH,
    "key_file": auth._KEY_FILE,
    "key_exists": auth.os.path.isfile(auth._KEY_FILE),
    "manifest": str(DEFAULT_MANIFEST_PATH),
    "prompt": load_template("sample"),
}))
"""
    env = os.environ.copy()
    env.update(
        {
            "AETHERDB_RESOURCE_ROOT": str(resource_root),
            "AETHERDB_RUNTIME_ROOT": str(runtime_root),
            "PYTHONPATH": str(PROJECT_ROOT),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert Path(payload["runtime_config"]) == runtime_root / "config.local.yaml"
    assert Path(payload["writable_config"]) == runtime_root / "config.local.yaml"
    assert Path(payload["db_path"]) == runtime_root / "novel_world_zh.db"
    assert Path(payload["key_file"]) == runtime_root / ".api_keys.json"
    assert payload["key_exists"] is True
    assert Path(payload["manifest"]) == resource_root / "resources" / "model_manifests" / "bge-m3.json"
    assert payload["prompt"] == "resource prompt"
    assert not (resource_root / ".api_keys.json").exists()
    assert not (resource_root / "config.local.yaml").exists()


def test_standalone_server_selects_dynamic_loopback_port(monkeypatch):
    from main import create_server_socket

    monkeypatch.setenv("AETHERDB_HOST", "127.0.0.1")
    monkeypatch.delenv("AETHERDB_PORT", raising=False)
    host, port, listener = create_server_socket()
    try:
        assert host == "127.0.0.1"
        assert 1 <= port <= 65535
        assert port != 8000
        assert listener.getsockname()[1] == port
    finally:
        listener.close()


def test_standalone_server_honors_explicit_nondefault_port(monkeypatch):
    from main import get_server_endpoint

    monkeypatch.setenv("AETHERDB_HOST", "127.0.0.1")
    monkeypatch.setenv("AETHERDB_PORT", "43127")

    assert get_server_endpoint() == ("127.0.0.1", 43127)


def test_desktop_startup_descriptor_announces_sidecar_owned_port(
    monkeypatch, tmp_path
):
    import main

    descriptor = tmp_path / f"backend-startup-{main.RUNTIME_INSTANCE_ID}.json"
    monkeypatch.setattr(main, "get_runtime_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setenv("AETHERDB_STARTUP_DESCRIPTOR", str(descriptor))

    written = main.publish_startup_descriptor(43127)
    payload = json.loads(descriptor.read_text(encoding="utf-8"))

    assert written == descriptor
    assert payload["port"] == 43127
    assert payload["pid"] == os.getpid()
    assert payload["instance_id"] == main.RUNTIME_INSTANCE_ID
    assert payload["build_id"] == main.BACKEND_BUILD_ID
    assert "token" not in descriptor.read_text(encoding="utf-8").lower()

    main.remove_startup_descriptor(descriptor)
    assert not descriptor.exists()


def test_startup_banner_never_prints_api_key_material(capsys):
    from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
    from main import print_startup_banner

    print_startup_banner("127.0.0.1", 43127)
    output = capsys.readouterr().out

    assert ADMIN_API_KEY not in output
    assert USER_API_KEY not in output
    assert ADMIN_API_KEY[:8] not in output
    assert USER_API_KEY[:8] not in output
