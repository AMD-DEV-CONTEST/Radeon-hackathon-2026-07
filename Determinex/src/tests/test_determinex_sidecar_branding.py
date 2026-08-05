from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tauri_bundles_determinex_hive_sidecar():
    config = (ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")

    assert "bin/determinex-hive" in config


def test_tauri_cargo_package_names_the_installed_executable():
    cargo_toml = (ROOT / "frontend" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")

    assert 'name = "determinex"' in cargo_toml
    assert 'default-run = "determinex"' in cargo_toml
    assert 'name = "app"' not in cargo_toml
    assert 'default-run = "app"' not in cargo_toml


def test_sidecar_builder_outputs_determinex_hive():
    script = (ROOT / "bundler" / "build_hive_sidecar.py").read_text(encoding="utf-8")

    assert 'SIDECAR_BASENAME = "determinex-hive"' in script
    assert "pyinstaller_name = SIDECAR_BASENAME" in script
    assert "Build the Determinex Hive sidecar binary" in script


def test_tauri_resolver_prefers_determinex_hive_with_legacy_fallback():
    source = (ROOT / "frontend" / "src-tauri" / "src" / "ipc_hive" / "mod.rs").read_text(
        encoding="utf-8"
    )

    assert '"determinex-hive-{}{}"' in source
    assert '"determinex-hive-{}{}"' in source
    assert "Determinex Hive sidecar not found" in source
    assert "Failed to spawn Determinex Hive" in source
