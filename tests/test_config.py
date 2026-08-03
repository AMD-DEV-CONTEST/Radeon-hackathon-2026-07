from xianglens.config import Settings


def test_comma_separated_allowed_origins_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "XIANG_ALLOWED_ORIGINS",
        "http://127.0.0.1:3000, https://ld0574.github.io",
    )

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == [
        "http://127.0.0.1:3000",
        "https://ld0574.github.io",
    ]


def test_submission_local_topology_is_recognized(monkeypatch) -> None:
    monkeypatch.setenv("XIANG_DEPLOYMENT_MODE", "submission-local")
    monkeypatch.setenv("XIANG_LLM_BASE_URL", "http://127.0.0.1:8000/v1")

    settings = Settings(_env_file=None)

    assert settings.submission_topology_compliant is True
