from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict[str, object]:
    return yaml.safe_load((ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8"))


def _assert_hardened(service: dict[str, object], *, user: str) -> None:
    assert service["user"] == user
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert "/tmp" in service["tmpfs"]
    assert service["healthcheck"]["test"]


def test_compose_has_independent_hardened_shidu_services() -> None:
    compose = _compose()
    services = compose["services"]
    assert {"shidu-api", "consumer-web"} <= set(services)

    api = services["shidu-api"]
    web = services["consumer-web"]
    _assert_hardened(api, user="10001:10001")
    _assert_hardened(web, user="101:101")
    assert api["build"]["dockerfile"] == "deploy/Dockerfile.shidu-api"
    assert web["build"]["dockerfile"] == "deploy/Dockerfile.consumer-web"
    assert api["expose"] == ["8082"]
    assert "ports" not in api
    assert web["ports"] == ["127.0.0.1:14289:4289"]


def test_shidu_api_depends_on_migrations_and_uses_file_backed_authority() -> None:
    compose = _compose()
    api = compose["services"]["shidu-api"]

    assert api["depends_on"]["creative-hub-migrate"]["condition"] == "service_completed_successfully"
    assert api["depends_on"]["creative-orchestration-migrate"]["condition"] == "service_completed_successfully"
    assert api["environment"] == {
        "CREATIVE_ORCHESTRATION_POSTGRES_USER_FILE": "/run/secrets/postgres-orchestration-user",
        "CREATIVE_ORCHESTRATION_POSTGRES_PASSWORD_FILE": "/run/secrets/postgres-orchestration-password",
        "CREATIVE_ORCHESTRATION_POSTGRES_DB_FILE": "/run/secrets/postgres-db",
        "CREATIVE_HUB_ARTIFACT_STORE_ROOT": "/runtime/creative-hub/artifacts",
        "SHIDU_SIGNING_SECRET_FILE": "/run/secrets/shidu-signing-secret",
        "SHIDU_AUDIO_AUTHORITY_FILE": "/run/secrets/shidu-audio-authority",
        "SHIDU_PROJECT_ID": "${SHIDU_PROJECT_ID:?SHIDU_PROJECT_ID must be set}",
        "SHIDU_VOICE_PRESET_REVISION_ID": "${SHIDU_VOICE_PRESET_REVISION_ID:?SHIDU_VOICE_PRESET_REVISION_ID must be set}",
        "SHIDU_ACTOR_ID": "${SHIDU_ACTOR_ID:?SHIDU_ACTOR_ID must be set}",
        "SHIDU_SERVICE_FACTORY": "shidu_api.deployment:create_service",
        "SHIDU_ARTIFACT_GATEWAY_FACTORY": "shidu_api.deployment:create_artifact_gateway",
        "TZ": "Asia/Shanghai",
    }
    assert set(api["secrets"]) == {
        "postgres-orchestration-user",
        "postgres-orchestration-password",
        "postgres-db",
        "shidu-signing-secret",
        "shidu-audio-authority",
    }
    assert api["volumes"] == [
        "${CREATIVE_HUB_ARTIFACT_STORE_SOURCE:-${RUNTIME_ROOT:?RUNTIME_ROOT must be set}/creative-hub/artifacts}:/runtime/creative-hub/artifacts:ro"
    ]
    assert "F:/douyi_mcp" not in str(api)
    assert "SHIDU_SIGNING_SECRET" not in api["environment"]


def test_shidu_and_creative_workers_share_one_artifact_store_source() -> None:
    compose = _compose()
    services = compose["services"]
    writable = (
        "${CREATIVE_HUB_ARTIFACT_STORE_SOURCE:-${RUNTIME_ROOT:?RUNTIME_ROOT must be set}/creative-hub/artifacts}"
        ":/runtime/creative-hub/artifacts"
    )
    readonly = f"{writable}:ro"

    assert writable in services["creative-hub-dag-worker-video-0"]["volumes"]
    assert services["shidu-api"]["volumes"] == [readonly]


def test_creative_hub_product_surface_is_retired() -> None:
    compose = _compose()
    services = compose["services"]

    assert {
        "creative-hub-api",
        "creative-hub-web",
        "creative-hub-product-backfill",
    }.isdisjoint(services)
    assert services["consumer-web"]["ports"] == ["127.0.0.1:14289:4289"]

    published_ports = {
        str(port)
        for service in services.values()
        for port in service.get("ports", [])
    }
    assert all(":4288" not in port for port in published_ports)
    assert all(":8000" not in port for port in published_ports)


def test_retired_product_files_and_commands_are_absent() -> None:
    for relative_path in (
        "frontend",
        "deploy/Dockerfile.creative-hub-web",
        "deploy/creative-hub-nginx.conf",
        "creative_hub/src/creative_hub/api.py",
        "creative_hub/src/creative_hub/dev_main.py",
        "creative_hub/src/creative_hub/main.py",
        "creative_hub/src/creative_hub/product_api_v2.py",
        "creative_hub/src/creative_hub/product_command_ledger.py",
        "creative_hub/src/creative_hub/product_source_store.py",
        "creative_hub/src/creative_hub/product_v2.py",
        "creative_hub/src/creative_hub/human_review.py",
        "creative_hub/src/creative_hub/document_formats.py",
        "creative_hub/src/creative_hub/document_parsers.py",
        "creative_hub/src/creative_hub/document_pdf_worker.py",
        "creative_hub/src/creative_hub/document_role_suggester.py",
        "creative_hub/src/creative_hub/novel_episode_suggester.py",
        "creative_hub/src/creative_hub/product_backfill.py",
        "creative_hub/src/creative_hub/product_backfill_cli.py",
        "creative_hub/src/creative_hub/shidu/repair_service.py",
        "creative_hub/tests/test_api.py",
        "creative_hub/tests/test_dev_main.py",
        "creative_hub/tests/test_human_review.py",
        "creative_hub/tests/test_human_review_postgres.py",
        "creative_hub/tests/test_episode_compiler.py",
        "creative_hub/tests/test_product_api_v2.py",
        "creative_hub/tests/test_product_api_v2_projection_zero_regression.py",
        "creative_hub/tests/test_product_docx_api.py",
        "creative_hub/tests/test_product_models.py",
        "creative_hub/tests/test_product_security.py",
        "creative_hub/tests/test_product_source_store.py",
        "creative_hub/tests/test_product_v2.py",
        "creative_hub/tests/test_product_v2_postgres.py",
        "creative_hub/tests/test_product_backfill.py",
        "creative_hub/tests/test_product_backfill_postgres.py",
        "creative_hub/tests/test_shidu_derived_repair.py",
    ):
        assert not (ROOT / relative_path).exists(), relative_path

    project = (ROOT / "creative_hub" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "creative-hub-api =" not in project
    assert "creative-hub-dev-api =" not in project
    assert "creative-hub-product-backfill =" not in project
    assert (
        'creative-hub-migrate = "creative_hub.migrations:migrate_hub"'
        in project
    )
    assert (
        "creative-orchestration-migrate = "
        '"creative_hub.migrations:migrate_orchestration"'
        in project
    )


def test_retired_analysis_bridge_closure_is_absent() -> None:
    for relative_path in (
        "analysis/src/douyin_analysis/credential_client.py",
        "analysis/src/douyin_analysis/knowledge_bridge.py",
        "analysis/src/douyin_analysis/semantic_worker.py",
        "analysis/src/douyin_analysis/drama_worker.py",
    ):
        assert not (ROOT / relative_path).exists(), relative_path

    compose = _compose()
    services = compose["services"]
    assert {"analysis-api", "mcp", "mcp-gateway"}.isdisjoint(services)
    assert "creative-hub-internal-token" not in compose["secrets"]
    assert "douyin-mcp-token" not in compose["secrets"]
    assert {"mcp-internal", "mcp-publish"}.isdisjoint(compose["networks"])

    main = (ROOT / "analysis" / "src" / "douyin_analysis" / "main.py").read_text(
        encoding="utf-8"
    )
    entrypoint = (ROOT / "deploy" / "analysis-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    creative_package = (
        ROOT / "creative_hub" / "src" / "creative_hub" / "__init__.py"
    ).read_text(encoding="utf-8")
    secret_bootstrap = (
        ROOT / "ops" / "windows" / "bootstrap-postgres-secrets.ps1"
    ).read_text(encoding="utf-8")
    dag_worker = (
        ROOT / "creative_hub" / "src" / "creative_hub" / "dag_worker.py"
    ).read_text(encoding="utf-8")

    for retired_command in (
        "semantic-worker",
        "semantic-health",
        "drama-worker",
        "drama-health",
    ):
        assert retired_command not in main
        assert retired_command not in entrypoint
    assert "CREATIVE_HUB_INTERNAL_SERVICE_TOKEN" not in main
    assert "from .knowledge import" not in creative_package
    assert "from .repository import KnowledgeRepository" not in creative_package
    assert "creative-hub-internal-token" not in secret_bootstrap
    assert "ProductionSemanticAtomicBackend" in dag_worker


def test_shidu_runtime_import_closure_remains_available() -> None:
    from creative_hub import dag_worker
    from creative_hub.migrations import migrate_hub, migrate_orchestration
    from creative_hub.shidu import research_worker
    from creative_hub.runtime_bootstrap import (
        database_url,
        load_atomic_capability_registry,
        load_cost_budget_policy,
    )
    from creative_hub.workflow_catalog import default_workflow_catalog
    from shidu_api import deployment

    assert callable(dag_worker.main)
    assert callable(database_url)
    assert callable(load_atomic_capability_registry)
    assert callable(load_cost_budget_policy)
    assert callable(migrate_hub)
    assert callable(migrate_orchestration)
    assert callable(research_worker.main)
    assert callable(default_workflow_catalog)
    assert callable(deployment.create_service)


def test_migration_launcher_only_manages_shidu_owned_surfaces() -> None:
    launcher = (ROOT / "ops" / "windows" / "start-platform.ps1").read_text(
        encoding="utf-8"
    )

    for service in (
        "shidu-api",
        "consumer-web",
        "shidu-search-mcp",
        "shidu-reader-mcp",
    ):
        assert f"'{service}'" in launcher
    managed = launcher.split("$managedServices = @(", 1)[1].split(")", 1)[0]
    for external in (
        "postgres",
        "shidu-research-worker",
        "creative-hub-dag-worker-video-0",
        "creative-hub-dag-worker-video-1",
        "creative-hub-dag-worker-factory",
        "creative-hub-dag-worker-quality",
    ):
        assert f"'{external}'" not in managed
    assert "up -d --no-deps $buildOption" in launcher
    assert "127.0.0.1:4289" in launcher
    assert "127.0.0.1:14289" in launcher
    assert "SHIDU_LAN_ADDRESS" in launcher
    assert "Start-ShiduLanProxy" in launcher
    assert "ops\\wsl\\loopback-forward.py" in launcher
    assert "Shidu (LAN)" in launcher
    assert "'--target-port', '14289'" in launcher
    assert "127.0.0.1:4288" not in launcher
    assert "docker compose stop" not in launcher
    assert "docker compose down" not in launcher
    assert "force-recreate" not in launcher
    assert "F:\\doyin_mcp_AMD" in launcher
    assert "F:\\douyi_mcp" in launcher
    assert "$wslRuntime = Convert-ToWslPath -WindowsPath $RuntimeRoot" in launcher
    assert (
        "$wslShiduRuntime = Convert-ToWslPath -WindowsPath $ShiduRuntimeRoot"
        in launcher
    )
    boundary = (
        ROOT / "docs" / "architecture" / "shidu-runtime-retention.md"
    ).read_text(encoding="utf-8")
    assert "F:\\douyi_mcp" in boundary
    assert "不属于本次清理范围" in boundary


def test_factory_workers_receive_live_shidu_audio_dependencies() -> None:
    service = _compose()["services"]["creative-hub-dag-worker-video-0"]

    assert service["environment"]["SHIDU_PROJECT_ID"] == (
        "${SHIDU_PROJECT_ID:?SHIDU_PROJECT_ID must be set}"
    )
    assert service["environment"]["SHIDU_TTS_MCP_ENDPOINT"] == (
        "${SHIDU_TTS_MCP_ENDPOINT:-http://host.docker.internal:28789/mcp}"
    )
    assert service["environment"]["SHIDU_AUDIO_AUTHORITY_FILE"] == (
        "/run/secrets/shidu-audio-authority"
    )
    assert "shidu-audio-authority" in service["secrets"]
    assert (
        "${CREATIVE_HUB_COST_BUDGET_POLICY_SOURCE:-"
        "./shidu/cost-budgets.example.json}:"
        "/etc/creative-hub/cost-budgets.json:ro"
    ) in service["volumes"]
    assert (ROOT / "deploy" / "shidu" / "cost-budgets.example.json").is_file()


def test_shidu_network_only_publishes_consumer_web() -> None:
    compose = _compose()
    api = compose["services"]["shidu-api"]
    web = compose["services"]["consumer-web"]

    assert api["networks"] == [
        "default",
        "shidu-consumer-internal",
        "shidu-search-internal",
        "shidu-reader-internal",
    ]
    assert web["networks"] == [
        "shidu-consumer-internal",
        "shidu-consumer-publish",
    ]
    assert compose["networks"]["shidu-consumer-internal"] == {"internal": True}
    assert compose["networks"]["shidu-consumer-publish"] == {
        "driver": "bridge",
        "internal": False,
    }
    assert web["depends_on"] == {"shidu-api": {"condition": "service_healthy"}}
    assert api["depends_on"]["shidu-search-mcp"] == {
        "condition": "service_healthy"
    }
    assert api["depends_on"]["shidu-reader-mcp"] == {
        "condition": "service_healthy"
    }


def test_consumer_nginx_keeps_frozen_csp_and_only_two_proxy_surfaces() -> None:
    nginx = (ROOT / "deploy" / "consumer-web-nginx.conf").read_text(encoding="utf-8")
    assert 'listen 4289;' in nginx
    for directive in (
        "client_body_temp_path /tmp/client-body;",
        "fastcgi_temp_path /tmp/fastcgi;",
        "proxy_temp_path /tmp/proxy;",
        "scgi_temp_path /tmp/scgi;",
        "uwsgi_temp_path /tmp/uwsgi;",
    ):
        assert directive in nginx
    assert (
        'Content-Security-Policy "default-src \'self\'; img-src \'self\' data:; '
        "media-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'\" always;"
    ) in nginx
    assert nginx.count("proxy_pass ") == 2
    assert "location /api/" in nginx
    assert "location /artifacts/" in nginx
    assert nginx.count("proxy_pass http://shidu-api:8082;") == 2


def test_shidu_api_image_installs_real_packages_and_runs_non_root() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile.shidu-api").read_text(encoding="utf-8")
    assert "COPY creative_hub /workspace/creative_hub" in dockerfile
    assert "COPY drama_factory /workspace/drama_factory" in dockerfile
    assert "COPY shidu_api /workspace/shidu_api" in dockerfile
    assert "/workspace/creative_hub" in dockerfile
    assert "/workspace/drama_factory" in dockerfile
    assert "/workspace/shidu_api" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["shidu-api"]' in dockerfile


def test_configured_factories_are_real_importable_callables() -> None:
    from shidu_api.deployment import create_artifact_gateway, create_service

    assert callable(create_service)
    assert callable(create_artifact_gateway)


def test_provider_mcps_use_dedicated_loopback_ports_and_file_backed_search_key() -> None:
    compose = _compose()
    services = compose["services"]
    assert {"shidu-search-mcp", "shidu-reader-mcp"} <= set(services)

    search = services["shidu-search-mcp"]
    reader = services["shidu-reader-mcp"]
    for service, role, port in (
        (search, "search", "18110"),
        (reader, "reader", "18111"),
    ):
        _assert_hardened(service, user="10001:10001")
        assert service["build"]["dockerfile"] == "deploy/Dockerfile.shidu-provider-mcp"
        assert service["command"] == [role]
        assert service["ports"] == [f"127.0.0.1:{port}:{port}"]
        assert service["environment"]["SHIDU_PROVIDER_MCP_HOST"] == "0.0.0.0"
        assert service["networks"] == [
            f"shidu-{role}-egress",
            f"shidu-{role}-internal",
        ]

    assert search["environment"]["SHIDU_ZHIPU_CODING_PLAN_API_KEY_FILE"] == (
        "/run/secrets/shidu-zhipu-api-key"
    )
    assert search["environment"]["SHIDU_GOOGLE_BOOKS_API_KEY_FILE"] == (
        "/run/secrets/shidu-google-books-api-key"
    )
    assert search["secrets"] == [
        "shidu-zhipu-api-key",
        "shidu-google-books-api-key",
    ]
    assert reader["environment"]["SHIDU_GOOGLE_BOOKS_API_KEY_FILE"] == (
        "/run/secrets/shidu-google-books-api-key"
    )
    assert reader["secrets"] == ["shidu-google-books-api-key"]
    assert compose["secrets"]["shidu-zhipu-api-key"]["file"] == (
        "${SHIDU_RUNTIME_ROOT:?SHIDU_RUNTIME_ROOT must be set}/secrets/zhipu-web-search-api-key"
    )
    assert compose["secrets"]["shidu-google-books-api-key"]["file"] == (
        "${SHIDU_RUNTIME_ROOT:?SHIDU_RUNTIME_ROOT must be set}/secrets/google-books-api-key"
    )
    assert compose["networks"]["shidu-search-egress"] == {
        "driver": "bridge",
        "internal": False,
    }
    assert compose["networks"]["shidu-reader-egress"] == {
        "driver": "bridge",
        "internal": False,
    }
    assert "shidu-provider-egress" not in compose["networks"]


def test_research_worker_is_atomic_hardened_and_network_isolated() -> None:
    compose = _compose()
    services = compose["services"]
    worker = services["shidu-research-worker"]

    _assert_hardened(worker, user="10001:10001")
    assert worker["build"]["dockerfile"] == "deploy/Dockerfile.creative-hub"
    assert worker["command"] == [
        "creative-hub-shidu-research-worker",
        "--poll-interval",
        "2",
    ]
    assert "ports" not in worker and "expose" not in worker
    assert set(worker["secrets"]) == {
        "postgres-orchestration-user",
        "postgres-orchestration-password",
        "postgres-db",
        "shidu-zhipu-api-key",
        "shidu-qwen-api-key",
    }
    assert worker["environment"]["SHIDU_ZHIPU_API_KEY_FILE"] == (
        "/run/secrets/shidu-zhipu-api-key"
    )
    assert worker["environment"]["SHIDU_QWEN_API_KEY_FILE"] == (
        "/run/secrets/shidu-qwen-api-key"
    )
    assert compose["secrets"]["shidu-qwen-api-key"]["file"] == (
        "${SHIDU_RUNTIME_ROOT:?SHIDU_RUNTIME_ROOT must be set}/secrets/qwen-api-key"
    )
    assert worker["environment"]["SHIDU_SEARCH_MCP_ENDPOINT"] == (
        "http://shidu-search-mcp:18110/invoke"
    )
    assert worker["environment"]["SHIDU_READER_MCP_ENDPOINT"] == (
        "http://shidu-reader-mcp:18111/invoke"
    )
    assert worker["networks"] == [
        "shidu-research-db-internal",
        "shidu-search-internal",
        "shidu-reader-internal",
        "shidu-research-model-egress",
    ]
    assert "shidu-search-egress" not in worker["networks"]
    assert "shidu-reader-egress" not in worker["networks"]
    for name in (
        "shidu-research-db-internal",
        "shidu-search-internal",
        "shidu-reader-internal",
    ):
        assert compose["networks"][name] == {"internal": True}
    assert compose["networks"]["shidu-research-model-egress"] == {
        "driver": "bridge",
        "internal": False,
    }
    assert "shidu-research-db-internal" in services["postgres"]["networks"]
    assert worker["depends_on"] == {
        "postgres": {"condition": "service_healthy"},
        "creative-orchestration-migrate": {
            "condition": "service_completed_successfully"
        },
        "shidu-search-mcp": {"condition": "service_healthy"},
        "shidu-reader-mcp": {"condition": "service_healthy"},
    }


def test_provider_mcp_image_installs_only_the_provider_package() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile.shidu-provider-mcp").read_text(
        encoding="utf-8"
    )
    assert "COPY shidu_provider_mcp /workspace/shidu_provider_mcp" in dockerfile
    assert "/workspace/shidu_provider_mcp" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert '["shidu-provider-mcp"]' in dockerfile
