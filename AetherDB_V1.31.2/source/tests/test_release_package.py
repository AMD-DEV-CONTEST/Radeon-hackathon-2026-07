import json
import zipfile
from datetime import datetime, timezone

import pytest

from scripts.build_sanitized_source_package import (
    ReleasePackageError,
    _is_forbidden,
    build_package,
    verify_package,
)


def test_release_path_filter_rejects_private_runtime_and_weights():
    forbidden = (
        ".api_keys.json",
        ".env.txt",
        "api_keys.json.txt",
        "config.yaml",
        "config.local.yaml",
        "app_data/world.db",
        "logs/runtime.log",
        "models/bge-m3/model.safetensors",
        "frontend/node_modules/package/index.js",
    )
    assert all(_is_forbidden(__import__("pathlib").Path(path)) for path in forbidden)
    assert not _is_forbidden(__import__("pathlib").Path(".env.example"))
    assert not _is_forbidden(__import__("pathlib").Path("config.example.yaml"))


def test_test_requirements_are_pinned_for_clean_clone_validation():
    requirements = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "requirements-test.txt"
    ).read_text(encoding="utf-8")
    assert "-r requirements.txt" in requirements
    assert "pytest==9.1.1" in requirements


def test_pytest_does_not_collect_manual_database_scripts():
    config = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "pytest.ini"
    ).read_text(encoding="utf-8")
    assert "testpaths = tests" in config
    assert "norecursedirs = manual" in config


def test_build_package_includes_source_and_excludes_local_data(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    (source / "api").mkdir(parents=True)
    (source / "app_data").mkdir()
    (source / "models").mkdir()
    (source / "api" / "sample.py").write_text("VALUE = 'public'\n", encoding="utf-8")
    (source / "main.py").write_text("APP = True\n", encoding="utf-8")
    (source / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    (source / "config.example.yaml").write_text("api_key: null\n", encoding="utf-8")
    (source / ".api_keys.json").write_text(
        json.dumps({"admin": "private-test-value-12345"}),
        encoding="utf-8",
    )
    (source / "config.yaml").write_text(
        "api_key: private-test-value-12345\n",
        encoding="utf-8",
    )
    (source / "app_data" / "world.db").write_bytes(b"private database")
    (source / "models" / "model.safetensors").write_bytes(b"private weights")

    archive, result = build_package(
        source,
        output,
        version="1.31.2",
        timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )

    assert result["verified"] is True
    assert verify_package(archive)["verified"] is True
    assert result["file_count"] == 4
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        prefix = "aetherdb-v1.31.2-source/"
        assert prefix + "api/sample.py" in names
        assert prefix + "main.py" in names
        assert prefix + ".env.example" in names
        assert prefix + "config.example.yaml" in names
        assert prefix + "SOURCE_PACKAGE_MANIFEST.json" in names
        assert all("app_data" not in name for name in names)
        assert all("config.yaml" not in name for name in names)
        assert all(".api_keys.json" not in name for name in names)
        assert all("safetensors" not in name for name in names)


def test_build_package_blocks_a_local_secret_repeated_in_source(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    (source / "api").mkdir(parents=True)
    (source / ".api_keys.json").write_text(
        json.dumps({"admin": "private-test-value-67890"}),
        encoding="utf-8",
    )
    (source / "api" / "bad.py").write_text(
        "VALUE = 'private-test-value-67890'\n",
        encoding="utf-8",
    )

    with pytest.raises(ReleasePackageError, match="local credential"):
        build_package(source, output, version="1.31.2")
