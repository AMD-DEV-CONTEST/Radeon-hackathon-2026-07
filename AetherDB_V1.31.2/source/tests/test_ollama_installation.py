import json
from pathlib import Path

import pytest

from services.ollama_installation import (
    DEFAULT_MANIFEST_PATH,
    OllamaInstallationError,
    load_trusted_manifest,
    resolve_install_plan,
)


def test_stable_manifest_pins_official_v0320_assets_and_verification():
    manifest = load_trusted_manifest()

    assert manifest.version == "0.32.0"
    assert manifest.tag == "v0.32.0"
    assert manifest.channel == "stable"
    assert len(manifest.assets) == 7
    assert all(item.url.startswith("https://github.com/ollama/ollama/releases/download/v0.32.0/") for item in manifest.assets)
    assert all(len(item.sha256) == 64 and item.size > 0 for item in manifest.assets)
    assert all("sha256" in item.verification for item in manifest.assets)
    assert all(item.requires_user_confirmation for item in manifest.assets)


@pytest.mark.parametrize(
    ("system", "machine", "expected_id"),
    [
        ("Windows", "AMD64", "windows-x86_64-installer"),
        ("Windows", "ARM64", "windows-arm64-archive"),
        ("Darwin", "x86_64", "macos-universal-dmg"),
        ("Darwin", "arm64", "macos-universal-dmg"),
        ("Linux", "x86_64", "linux-x86_64-archive"),
        ("Linux", "aarch64", "linux-arm64-archive"),
    ],
)
def test_platform_resolver_has_one_primary_asset_for_each_supported_host(
    system, machine, expected_id
):
    plan = resolve_install_plan(system=system, machine=machine)

    assert [item.id for item in plan.artifacts] == [expected_id]
    assert plan.accelerator is None
    assert Path(plan.cache_root).parts[-5:] == (
        "app_data",
        "cache",
        "ollama",
        "installers",
        "v0.32.0",
    )


@pytest.mark.parametrize("system", ["Windows", "Linux"])
def test_rocm_is_an_optional_ollama_addon_only_on_x86_64(system):
    plan = resolve_install_plan(system=system, machine="AMD64", accelerator="rocm")

    assert len(plan.artifacts) == 2
    assert plan.artifacts[1].role == "accelerator_addon"
    assert plan.artifacts[1].accelerator == "rocm"
    assert "embedding" not in json.dumps(plan.to_dict()).lower()


def test_unsupported_accelerator_never_silently_changes_platform_policy():
    with pytest.raises(OllamaInstallationError) as error:
        resolve_install_plan(system="Linux", machine="aarch64", accelerator="rocm")

    assert error.value.code == "UNSUPPORTED_ACCELERATOR"


def test_manifest_rejects_arbitrary_urls_and_unsafe_filenames(tmp_path):
    payload = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["assets"][0]["url"] = "https://example.com/OllamaSetup.exe"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="untrusted asset URL"):
        load_trusted_manifest(invalid)

    payload = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["assets"][0]["filename"] = "../OllamaSetup.exe"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe filename"):
        load_trusted_manifest(invalid)


def test_install_plan_contains_no_shell_or_execution_fields():
    payload = resolve_install_plan(system="Windows", machine="AMD64").to_dict()
    serialized = json.dumps(payload).lower()

    assert "command" not in serialized
    assert "shell" not in serialized
    assert "powershell" not in serialized
    assert "install.ps1" not in serialized
