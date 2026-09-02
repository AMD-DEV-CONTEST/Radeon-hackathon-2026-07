import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "frontend" / "src-tauri"


def _json(name):
    return json.loads((TAURI / name).read_text(encoding="utf-8"))


def test_graphical_bundle_targets_exist_for_all_three_desktop_hosts():
    assert _json("tauri.windows.conf.json")["bundle"]["targets"] == ["nsis"]
    assert _json("tauri.macos.conf.json")["bundle"]["targets"] == ["app", "dmg"]
    assert _json("tauri.linux.conf.json")["bundle"]["targets"] == ["deb", "appimage"]
    base = _json("tauri.conf.json")
    assert base["version"] == "1.31.2"
    assert base["bundle"]["active"] is True


def test_host_native_sidecar_paths_and_assets_are_frozen():
    rust = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_desktop_sidecar.py").read_text(
        encoding="utf-8"
    )
    assert 'join("Scripts").join("python.exe")' in rust
    assert 'join("bin").join("python")' in rust
    assert 'Path("resources") / "model_packages"' in builder
    assert 'Path("config.example.yaml")' in builder
    assert '"config.yaml",' in builder.split("SENSITIVE_NAMES", 1)[1]


def test_desktop_release_template_uses_dynamic_port_and_single_worker():
    release = (ROOT / "scripts" / "package_desktop_release.ps1").read_text(
        encoding="utf-8"
    )
    assert 'port: 0' in release
    assert 'workers: 1' in release
    assert 'port: 8000' not in release


def test_desktop_launcher_gates_startup_and_records_backend_failures():
    rust = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "src" / "components" / "DesktopBootstrap.vue").read_text(
        encoding="utf-8"
    )
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")

    assert "tauri_plugin_single_instance::init" in rust
    assert "start_backend" in rust
    assert "backend-runtime.json" in rust
    assert "launcher.log" in rust and "backend.log" in rust
    assert "BACKEND_PORT_IN_USE" in rust
    assert "MAX_PORT_ATTEMPTS" in rust
    assert "LEGACY_BACKEND_PORT: u16 = 1042" in rust
    assert '.setup(|app|' in rust
    assert '"AETHERDB_PORT", "0"' in rust
    assert "AETHERDB_STARTUP_DESCRIPTOR" in rust
    assert "AETHERDB_DESKTOP_RUNTIME_ROOT" in rust
    assert "BACKEND_BUILD_MISMATCH" in rust
    assert "read_startup_descriptor" in rust
    assert "tauri-plugin-single-instance" in cargo
    assert 'startBackend(command = "start_backend")' in frontend
    assert 'recheckBackend();' in frontend
    assert 'window.setInterval(monitorBackend, 3000)' in frontend
    assert 'window.addEventListener("aetherdb:backend-unavailable"' in frontend


def test_release_build_identity_is_shared_and_fail_closed():
    sidecar = (ROOT / "scripts" / "build_desktop_sidecar.py").read_text(
        encoding="utf-8"
    )
    host = (ROOT / "frontend" / "scripts" / "build-desktop-host.mjs").read_text(
        encoding="utf-8"
    )
    release = (ROOT / "scripts" / "package_desktop_release.ps1").read_text(
        encoding="utf-8"
    )
    vite = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")

    assert "AETHERDB_BUILD_ID" in sidecar
    assert "build-manifest.json" in sidecar
    assert "AETHERDB_BUILD_ID" in host
    assert "build-manifest.json" in host
    assert '$HostManifest.build_id -ne $BackendManifest.build_id' in release
    assert "__BUILD_ID__" in vite


def test_desktop_smoke_test_reserves_reported_conflict_port_1042():
    smoke = (ROOT / "scripts" / "check_desktop_backend.py").read_text(encoding="utf-8")
    assert "REPORTED_CONFLICT_PORT = 1042" in smoke
    assert "reported_conflict_port_1042_guarded=" in smoke
    assert "reported_conflict_port_1042_bypassed=true" in smoke


def test_windows_webview_origin_is_allowed_in_desktop_cors_mode():
    backend = (ROOT / "main.py").read_text(encoding="utf-8-sig")
    assert '"http://tauri.localhost"' in backend
    assert '"https://tauri.localhost"' in backend
