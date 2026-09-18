from pathlib import Path

import pytest

from buildguard.benchmark import validate_local_endpoint
from buildguard.config import load_settings
from buildguard.exceptions import EndpointSecurityError


def test_remote_endpoint_rejected(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    settings.llm.endpoint = "https://api.example.com/v1"  # type: ignore[assignment]
    with pytest.raises(EndpointSecurityError, match="not allowlisted"):
        validate_local_endpoint(settings.llm, settings.permissions)


def test_localhost_endpoint_allowed(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    settings.llm.endpoint = "http://localhost:8080/v1"  # type: ignore[assignment]
    validate_local_endpoint(settings.llm, settings.permissions)

