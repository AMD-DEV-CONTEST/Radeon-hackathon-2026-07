import tomllib
from pathlib import Path


def test_phase_a_runtime_and_verification_dependencies_are_declared() -> None:
    with Path("pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    runtime = "\n".join(project["dependencies"])
    development = "\n".join(project["optional-dependencies"]["dev"])

    for package in ("pypdf", "python-docx", "openpyxl"):
        assert package in runtime
    assert "reportlab" in development


def test_stage_e_dependencies_are_declared() -> None:
    """Verify Stage E dependencies are in pyproject.toml."""
    with Path("pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    runtime = "\n".join(project["dependencies"])
    dev = "\n".join(project.get("optional-dependencies", {}).get("dev", ""))

    # Stage E requires httpx (already), gradio (already), pydantic-settings (already)
    # No new third-party packages are required for Stage E features.
    # Core features (background tasks, SSE/polling, error codes, cleanup)
    # use only stdlib and existing dependencies.

    # Verify fastapi is declared (required for background tasks)
    assert "fastapi" in runtime

    # Verify pydantic-settings is declared
    assert "pydantic-settings" in runtime or "pydantic_settings" in runtime or "pydantic" in runtime


def test_phase_f_dependencies_are_declared() -> None:
    """Verify Phase F dependencies are in pyproject.toml.

    Phase F requires:
    - openpyxl (already used by Phase C, reused for XLSX import)
    - fastapi (already used, reused for task API endpoints)
    - python-multipart (already used, reused for file upload in import)
    - No new third-party packages are required for Phase F.
    """
    with Path("pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    runtime = "\n".join(project["dependencies"])

    # openpyxl is needed for XLSX import
    assert "openpyxl" in runtime
    # fastapi is needed for task API
    assert "fastapi" in runtime
    # python-multipart is needed for file upload (import confirm)
    assert "python-multipart" in runtime


def test_stage_i_dependencies_are_declared() -> None:
    """Verify Stage I dependencies are in pyproject.toml.

    Stage I requires:
    - cryptography (new, for token encryption via AES-256-GCM)
    - fastapi (already used, reused for integration & automation task APIs)
    """
    with Path("pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    runtime = "\n".join(project["dependencies"])

    # cryptography is needed for token manager encryption
    assert "cryptography" in runtime
    # fastapi is needed for integration and automation task API endpoints
    assert "fastapi" in runtime
