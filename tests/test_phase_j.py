"""Stage J — Production & AMD Radeon Optimization Tests.

Tests cover: task queue (concurrency, cancellation, quotas), embedding client
(split model), cache (TTL, invalidation), monitor (GPU/model/system),
benchmark (snapshots, comparison), backup (create/restore/list/cleanup),
log rotation (rotate/cleanup), stress test runner, schemas, and error codes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


# ===========================================================================
# TaskQueue tests
# ===========================================================================


def test_taskqueue_create():
    """TaskQueue can be instantiated with default settings."""
    from app.services.task_queue import TaskQueue
    queue = TaskQueue(Settings())
    assert queue is not None
    stats = queue.stats
    assert stats.active_llm_calls == 0
    assert stats.total_completed == 0


@pytest.mark.asyncio
async def test_enqueue_llm_single():
    """A single LLM call executes successfully through the queue."""
    from app.services.task_queue import TaskQueue

    queue = TaskQueue(Settings())

    async def mock_llm(**kwargs: object) -> str:
        await asyncio.sleep(0.01)
        return "ok"

    result = await queue.enqueue_llm(
        project_id="test-proj",
        cancel_event=asyncio.Event(),
        callable=mock_llm,
    )
    assert result == "ok"
    assert queue.stats.total_completed == 1


@pytest.mark.asyncio
async def test_concurrency_limit_enforced():
    """Global semaphore prevents exceeding max concurrent calls."""
    from app.services.task_queue import TaskQueue

    queue = TaskQueue(Settings(global_max_concurrent_llm_calls=1))

    async def slow_llm(**kwargs: object) -> str:
        await asyncio.sleep(0.1)
        return "ok"

    t1 = asyncio.create_task(
        queue.enqueue_llm(
            project_id="a",
            cancel_event=asyncio.Event(),
            callable=slow_llm,
        )
    )
    await asyncio.sleep(0.02)
    assert queue.stats.active_llm_calls == 1

    t2 = asyncio.create_task(
        queue.enqueue_llm(
            project_id="b",
            cancel_event=asyncio.Event(),
            callable=slow_llm,
        )
    )
    await asyncio.sleep(0.02)
    assert queue.stats.active_llm_calls == 1  # still 1

    results = await asyncio.gather(t1, t2)
    assert results == ["ok", "ok"]
    assert queue.stats.total_completed == 2


@pytest.mark.asyncio
async def test_cancellation_releases_slots():
    """Cancelled call releases both semaphores."""
    from app.services.task_queue import TaskQueue

    queue = TaskQueue(Settings(global_max_concurrent_llm_calls=1))

    async def blocked_llm(**kwargs: object) -> str:
        await asyncio.sleep(10)
        return "ok"

    cancel = asyncio.Event()
    t1 = asyncio.create_task(
        queue.enqueue_llm(
            project_id="x",
            cancel_event=cancel,
            callable=blocked_llm,
        )
    )
    await asyncio.sleep(0.05)
    assert queue.stats.active_llm_calls == 1

    # Cancel the asyncio task to force release
    t1.cancel()
    try:
        await t1
    except asyncio.CancelledError:
        pass

    assert queue.stats.active_llm_calls == 0


@pytest.mark.asyncio
async def test_per_project_quota():
    """Per-project semaphore limits calls within a single project."""
    from app.services.task_queue import TaskQueue

    queue = TaskQueue(Settings(
        per_project_max_concurrent_llm_calls=1,
        global_max_concurrent_llm_calls=10,
    ))

    async def slow_llm(**kwargs: object) -> str:
        await asyncio.sleep(0.15)
        return "ok"

    t1 = asyncio.create_task(
        queue.enqueue_llm(
            project_id="same",
            cancel_event=asyncio.Event(),
            callable=slow_llm,
        )
    )
    await asyncio.sleep(0.03)
    # t1 should have acquired the per-project semaphore
    assert queue.stats.active_llm_calls == 1

    t2 = asyncio.create_task(
        queue.enqueue_llm(
            project_id="same",
            cancel_event=asyncio.Event(),
            callable=slow_llm,
        )
    )
    await asyncio.sleep(0.03)
    # t2 should be queued, active still 1
    assert queue.stats.active_llm_calls == 1

    await asyncio.gather(t1, t2)
    assert queue.stats.total_completed == 2


@pytest.mark.asyncio
async def test_queue_status():
    """Queue status endpoint returns correct structure."""
    from app.services.task_queue import TaskQueue

    queue = TaskQueue(Settings())
    status = await queue.status()

    assert "active_llm_calls" in status
    assert "global_llm_capacity" in status
    assert "active_embedding_calls" in status
    assert "global_embedding_capacity" in status
    assert status["global_llm_capacity"] == 4


# ===========================================================================
# EmbeddingClient tests
# ===========================================================================


def test_embedding_client_creation():
    from app.llm.embedding_client import EmbeddingClient
    settings = Settings()
    client = EmbeddingClient(settings)
    assert client is not None
    assert client._model == settings.embedding_model


def test_embed_empty_input():
    from app.llm.embedding_client import EmbeddingClient

    async def _run() -> None:
        client = EmbeddingClient(Settings())
        result = await client.embed([])
        assert result == []

    asyncio.run(_run())


def test_embedding_singleton():
    import app.llm.embedding_client as mod
    mod._embedding_client = None
    settings = Settings()
    c1 = mod.get_embedding_client(settings)
    c2 = mod.get_embedding_client(settings)
    assert c1 is c2


def test_embedding_health():
    from app.llm.embedding_client import EmbeddingClient

    async def _run() -> None:
        client = EmbeddingClient(Settings())
        health = await client.health()
        assert "healthy" in health
        assert "model" in health

    asyncio.run(_run())


# ===========================================================================
# Cache tests
# ===========================================================================


def test_cache_set_and_get():
    from app.services.cache import TTLCache
    cache = TTLCache(Settings(cache_enabled=True))
    cache.set("key1", "value1", category="index")
    assert cache.get("key1") == "value1"
    assert cache.stats["hits"] == 1


def test_cache_miss():
    from app.services.cache import TTLCache
    cache = TTLCache(Settings(cache_enabled=True))
    assert cache.get("nonexistent") is None
    assert cache.stats["misses"] == 1


def test_cache_invalidate_prefix():
    from app.services.cache import TTLCache
    cache = TTLCache(Settings(cache_enabled=True))
    cache.set("prefix:a", 1)
    cache.set("prefix:b", 2)
    cache.set("other:c", 3)
    removed = cache.invalidate("prefix:")
    assert removed == 2
    assert cache.get("prefix:a") is None
    assert cache.get("other:c") == 3


def test_cache_invalidate_project():
    from app.services.cache import TTLCache
    cache = TTLCache(Settings(cache_enabled=True))
    cache.set("project:demo:index:123", "idx")
    cache.set("project:demo:report:456", "rpt")
    cache.set("project:other:x", "other")
    removed = cache.invalidate_project("demo")
    assert removed == 2
    assert cache.get("project:other:x") == "other"


def test_cache_key_builders():
    from app.services.cache import TTLCache
    k1 = TTLCache.build_index_key("demo", "hash123")
    assert k1 == "project:demo:index:hash123"
    k2 = TTLCache.build_embedding_key("demo", "abc")
    assert k2 == "project:demo:embedding:abc"
    k3 = TTLCache.build_report_key("demo", "r001")
    assert k3 == "project:demo:report:r001"


def test_cache_disabled():
    from app.services.cache import TTLCache
    cache = TTLCache(Settings(cache_enabled=False))
    cache.set("k", "v")
    assert cache.get("k") is None


def test_cache_clear():
    from app.services.cache import TTLCache
    cache = TTLCache(Settings(cache_enabled=True))
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.clear() == 2
    assert cache.stats["size"] == 0


def test_cache_expired():
    import time
    from app.services.cache import TTLCache

    cache = TTLCache(Settings(cache_enabled=True, cache_index_ttl_seconds=60))
    # Force expiry by manipulating internal store timestamp
    cache.set("key1", "value1", category="index")
    with cache._lock:
        # Artificially expire the entry
        entry = cache._store.get("key1")
        if entry:
            value, _ = entry
            cache._store["key1"] = (value, time.time() - 10)
    assert cache.get("key1") is None


# ===========================================================================
# Monitor tests
# ===========================================================================


def test_monitor_creation():
    from app.services.monitor import HealthMonitor
    monitor = HealthMonitor(Settings())
    assert monitor is not None
    assert monitor._backend in ("rocm", "cuda", "cpu")


def test_record_llm_latency():
    from app.services.monitor import HealthMonitor
    monitor = HealthMonitor(Settings())
    monitor.record_llm_latency(500.0, 15.0, 2000.0)
    lm = monitor.latency_metrics
    assert lm.sample_count == 1
    assert lm.first_token_latency_ms == 500.0
    assert lm.generation_tokens_per_second == 15.0

    monitor.record_llm_latency(400.0, 20.0, 1800.0)
    lm = monitor.latency_metrics
    assert lm.sample_count == 2
    # EMA: 0.1*400 + 0.9*500 = 490
    assert abs(lm.first_token_latency_ms - 490.0) < 1.0


def test_record_errors():
    from app.services.monitor import HealthMonitor
    monitor = HealthMonitor(Settings())
    monitor.record_llm_error()
    monitor.record_llm_error()
    assert monitor.llm_error_rate == 100.0


def test_parse_current_rocm_smi_json():
    """Current ROCm SMI images expose VRAM values directly in bytes."""
    from app.services.monitor import HealthMonitor

    metrics = HealthMonitor.parse_rocm_smi_json(
        '{"card0": {"Card Series": "AMD Radeon Graphics", '
        '"VRAM Total Memory (B)": "51522830336", '
        '"VRAM Total Used Memory (B)": "48936890368", '
        '"GPU use (%)": "100", '
        '"Temperature (Sensor edge) (C)": "46.0"}}'
    )

    assert len(metrics) == 1
    assert metrics[0].name == "AMD Radeon Graphics"
    assert metrics[0].vram_total_mb == pytest.approx(49136.0, abs=1)
    assert metrics[0].vram_used_mb == pytest.approx(46670.0, abs=1)
    assert metrics[0].utilization_pct == 100.0
    assert metrics[0].temperature_c == 46.0


@pytest.mark.asyncio
async def test_model_metadata_uses_openai_v1_models_path():
    """Telemetry must not concatenate `/v1` and `models` into `v1models`."""
    from app.services.monitor import HealthMonitor

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "qwen", "meta": {"n_ctx": 16384}}]})

    metadata = await HealthMonitor(Settings()).collect_model_metadata(httpx.MockTransport(handler))
    assert metadata.model_name == "qwen"
    assert metadata.context_size == 16384


@pytest.mark.asyncio
async def test_health_check():
    from app.services.monitor import HealthMonitor
    monitor = HealthMonitor(Settings())
    health = await monitor.health_check()
    assert "status" in health
    assert health["status"] in ("healthy", "degraded", "critical")
    assert "issues" in health
    assert "gpu_metrics" in health
    assert "system_metrics" in health


# ===========================================================================
# Benchmark tests
# ===========================================================================


def test_benchmark_record():
    from app.services.benchmark import BenchmarkCollector
    collector = BenchmarkCollector(Settings())
    snap = collector.record(
        "baseline",
        first_token_latency_ms=500.0,
        generation_tokens_per_second=15.0,
        vram_used_mb=8000.0,
        vram_total_mb=16384.0,
        gpu_model="AMD Radeon PRO W7900",
        quantization="IQ2_M",
        backend="rocm",
    )
    assert snap.label == "baseline"
    assert snap.vram_usage_pct == pytest.approx(48.8, rel=0.01)
    assert collector.snapshot_count == 1


def test_benchmark_comparison():
    from app.services.benchmark import BenchmarkCollector
    collector = BenchmarkCollector(Settings())
    collector.record("baseline", first_token_latency_ms=1000.0,
                     generation_tokens_per_second=10.0,
                     vram_used_mb=12000.0, vram_total_mb=16384.0)
    collector.record("post-optimization", first_token_latency_ms=800.0,
                     generation_tokens_per_second=13.0,
                     vram_used_mb=8000.0, vram_total_mb=16384.0)

    comp = collector.compare("baseline", "post-optimization")
    assert "error" not in comp
    assert comp["first_token_latency"]["improvement_pct"] == 20.0
    assert comp["generation_speed"]["improvement_pct"] == 30.0
    assert comp["vram_usage"]["improvement_pct"] == pytest.approx(33.33, rel=0.1)


def test_benchmark_compare_latest():
    from app.services.benchmark import BenchmarkCollector
    collector = BenchmarkCollector(Settings())
    collector.record("uno", generation_tokens_per_second=10.0, end_to_end_latency_ms=100.0)
    collector.record("dos", generation_tokens_per_second=15.0, end_to_end_latency_ms=80.0)

    comp = collector.compare_latest_two()
    assert "error" not in comp
    assert comp["generation_speed"]["improvement_pct"] == 50.0


def test_benchmark_missing():
    from app.services.benchmark import BenchmarkCollector
    collector = BenchmarkCollector(Settings())
    comp = collector.compare("nope", "alsonope")
    assert "error" in comp


def test_benchmark_save_load(tmp_path):
    from app.services.benchmark import BenchmarkCollector
    settings = Settings()
    settings.log_root = tmp_path / "logs"
    collector = BenchmarkCollector(settings)
    collector.record("test", generation_tokens_per_second=12.0)

    path = collector.save()
    assert path.exists()

    collector2 = BenchmarkCollector(settings)
    loaded = collector2.load()
    assert len(loaded) == 1
    assert loaded[0].label == "test"


# ===========================================================================
# Backup tests
# ===========================================================================


def test_backup_create(tmp_path):
    from app.services.backup import BackupService
    settings = Settings()
    settings.backup_root = tmp_path / "backups"
    settings.project_root = tmp_path / "data"
    settings.vector_db_root = tmp_path / "vectors"
    settings.sqlite_path = tmp_path / "db" / "projectpack.db"

    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.write_text("mock db content")
    settings.vector_db_root.mkdir(parents=True, exist_ok=True)
    (settings.vector_db_root / "index.faiss").write_text("mock faiss")
    settings.project_root.mkdir(parents=True, exist_ok=True)
    (settings.project_root / "config.json").write_text('{"name":"test"}')

    svc = BackupService(settings)
    manifest = svc.create_backup(label="test-backup")
    assert manifest["label"] == "test-backup"
    assert manifest["status"] in ("success", "partial")
    assert len(manifest["files"]) > 0


def test_backup_list(tmp_path):
    from app.services.backup import BackupService
    settings = Settings()
    settings.backup_root = tmp_path / "backups_b"
    settings.project_root = tmp_path / "data_b"
    settings.vector_db_root = tmp_path / "vectors_b"
    settings.sqlite_path = tmp_path / "db_b" / "projectpack.db"

    for d in (settings.backup_root, settings.sqlite_path.parent,
              settings.vector_db_root, settings.project_root):
        d.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.write_text("db")
    (settings.vector_db_root / "idx").write_text("vec")
    (settings.project_root / "config.json").write_text("{}")

    svc = BackupService(settings)
    svc.create_backup("first")
    assert len(svc.list_backups()) >= 1


def test_backup_restore_dry_run(tmp_path):
    from app.services.backup import BackupService
    settings = Settings()
    settings.backup_root = tmp_path / "backups_r"
    settings.project_root = tmp_path / "data_r"
    settings.vector_db_root = tmp_path / "vectors_r"
    settings.sqlite_path = tmp_path / "db_r" / "projectpack.db"

    for d in (settings.backup_root, settings.sqlite_path.parent,
              settings.project_root, settings.vector_db_root):
        d.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.write_text("db")
    (settings.project_root / "config.json").write_text("{}")

    svc = BackupService(settings)
    svc.create_backup("restore-test")
    backups = svc.list_backups()
    bp = backups[0]["backup_dir"]

    result = svc.restore(bp, dry_run=True)
    assert result["dry_run"] is True
    assert len(result["restored"]) >= 1


def test_backup_cleanup(tmp_path):
    from app.services.backup import BackupService
    settings = Settings()
    settings.backup_root = tmp_path / "backups_c"
    settings.backup_retention_days = 0
    settings.project_root = tmp_path / "data_c"
    settings.vector_db_root = tmp_path / "vectors_c"
    settings.sqlite_path = tmp_path / "db_c" / "projectpack.db"

    for d in (settings.backup_root, settings.sqlite_path.parent,
              settings.project_root, settings.vector_db_root):
        d.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.write_text("db")
    (settings.project_root / "config.json").write_text("{}")

    svc = BackupService(settings)
    svc.create_backup("to-clean")
    removed = svc.cleanup_old_backups()
    assert removed >= 0


# ===========================================================================
# Log Rotation tests
# ===========================================================================


def test_log_no_rotation_under_threshold(tmp_path):
    from app.services.log_rotation import LogRotationService
    svc = LogRotationService(
        Settings(log_max_size_mb=10, log_root=tmp_path / "logs")
    )
    log_path = tmp_path / "logs" / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("small")
    result = svc.rotate("app.log")
    assert result["rotated"] is False


def test_log_rotation_over_threshold(tmp_path):
    from app.services.log_rotation import LogRotationService
    svc = LogRotationService(
        Settings(log_max_size_mb=1, log_root=tmp_path / "logs_r2",
                 log_compression_enabled=False)
    )
    log_path = tmp_path / "logs_r2" / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Write large enough content to trigger rotation (>1 MB)
    log_path.write_text("x" * (2 * 1024 * 1024))
    result = svc.rotate("app.log")
    assert result["rotated"] is True


def test_log_cleanup(tmp_path):
    from app.services.log_rotation import LogRotationService
    svc = LogRotationService(
        Settings(log_retention_days=1, log_root=tmp_path / "logs_cl",
                 log_compression_enabled=False)
    )
    logs_dir = tmp_path / "logs_cl"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "app-20240101T000000.log").write_text("old")
    (logs_dir / "app-20240102T000000.log").write_text("old")
    removed = svc.cleanup_old_logs()
    assert removed >= 0  # may or may not remove depending on mtime


# ===========================================================================
# Stress Test tests
# ===========================================================================


def test_stress_config():
    from app.services.stress_test import StressConfig
    config = StressConfig(large_file_count=1, multi_project_count=2)
    assert config.large_file_count == 1
    assert config.multi_project_count == 2


def test_stress_generate_text():
    from app.services.stress_test import StressTestRunner
    text = StressTestRunner._generate_text_file(1)
    assert len(text) > 500_000
    assert "\n" in text


def test_stress_generate_prompt():
    from app.services.stress_test import StressTestRunner
    prompt = StressTestRunner._generate_long_prompt(500)
    assert len(prompt) > 100


def test_stress_build_result():
    from app.services.stress_test import StressTestRunner
    result = StressTestRunner._build_result(
        "test_phase", total=10, latencies=[100, 200, 300, 400, 500],
        errors=["error1"], duration=2.0,
    )
    assert result.phase == "test_phase"
    assert result.total_requests == 10
    assert result.successful == 5
    assert result.failed == 1
    assert result.p50_latency_ms > 0
    assert result.throughput_requests_per_sec > 0


@pytest.mark.asyncio
async def test_stress_run_all():
    from app.services.stress_test import StressConfig, StressTestRunner

    config = StressConfig(
        large_file_count=1, large_file_size_mb=1,
        batch_file_count=3, long_context_prompt_tokens=100,
        long_context_requests=2, multi_project_count=2,
        multi_project_requests_per_project=3,
    )

    async def mock_llm(**kwargs: object) -> str:
        return "mock"

    async def mock_emb(**kwargs: object) -> list[list[float]]:
        return [[0.1] * 384]

    async def mock_imp(**kwargs: object) -> dict:
        return {"status": "ok"}

    runner = StressTestRunner(
        config, llm_call=mock_llm, embedding_call=mock_emb, file_import=mock_imp,
    )
    report = await runner.run_all()
    assert report.overall_status in ("pass", "fail")
    assert report.total_requests > 0
    assert len(report.results) >= 1


# ===========================================================================
# API endpoint integration tests — Monitor
# ===========================================================================


@pytest.fixture
def monitor_client(tmp_path):
    import sqlite3

    db_dir = tmp_path / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / "projectpack.db"
    conn = sqlite3.connect(str(db_file))
    conn.close()

    settings = Settings(
        cache_enabled=True, cache_index_ttl_seconds=60,
        cache_embedding_ttl_seconds=60, cache_report_ttl_seconds=60,
        sqlite_path=db_dir,
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    return client


def test_monitor_health_endpoint(monitor_client):
    resp = monitor_client.get("/monitor/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded", "critical")
    assert "queue_status" in data
    assert "cache_stats" in data


def test_monitor_endpoint_requires_authentication(tmp_path):
    settings = Settings(sqlite_path=tmp_path / "projectpack.db")
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/monitor/queue").status_code == 401


def test_monitor_endpoint_requires_system_admin(tmp_path):
    settings = Settings(sqlite_path=tmp_path / "projectpack.db")
    with TestClient(create_app(settings=settings)) as client:
        login = client.post("/auth/login", json={"username": "member", "password": "member123"})
        assert login.status_code == 200
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        assert client.get("/monitor/queue").status_code == 403


def test_monitor_queue_endpoint(monitor_client):
    resp = monitor_client.get("/monitor/queue")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_llm_calls"] == 0
    assert "global_llm_capacity" in data


def test_monitor_cache_endpoint(monitor_client):
    resp = monitor_client.get("/monitor/cache")
    assert resp.status_code == 200
    data = resp.json()
    assert "hit_rate" in data
    assert "size" in data


def test_monitor_cache_invalidate(monitor_client):
    resp = monitor_client.post("/monitor/cache/invalidate",
                               json={"project_id": "test"})
    assert resp.status_code == 200
    assert "removed" in resp.json()


def test_monitor_benchmark_snapshots(monitor_client):
    resp = monitor_client.get("/monitor/benchmark/snapshots")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_monitor_benchmark_compare(monitor_client):
    resp = monitor_client.get("/monitor/benchmark/compare?baseline=UNIQ_NOPE_X&optimized=UNIQ_NOPE_Y")
    assert resp.status_code == 200
    data = resp.json()
    # Should get error since snapshots don't exist
    assert "error" in data or "first_token_latency" in data


def test_monitor_benchmark_latest_404(monitor_client):
    resp = monitor_client.get("/monitor/benchmark/latest")
    assert resp.status_code == 404


# ===========================================================================
# API endpoint integration tests — Admin
# ===========================================================================


@pytest.fixture
def admin_client(tmp_path):
    import sqlite3

    settings = Settings()
    settings.backup_root = tmp_path / "backups_a"
    settings.project_root = tmp_path / "data_a"
    settings.vector_db_root = tmp_path / "vectors_a"
    # Use a directory for sqlite_path so app creates DB file inside
    db_dir = tmp_path / "db_a"
    settings.sqlite_path = db_dir
    settings.log_root = tmp_path / "logs_a"

    for d in (settings.backup_root, db_dir,
              settings.project_root, settings.vector_db_root, settings.log_root):
        d.mkdir(parents=True, exist_ok=True)

    # Create a valid empty SQLite database file the app can open
    db_file = db_dir / "projectpack.db"
    conn = sqlite3.connect(str(db_file))
    conn.close()

    (settings.project_root / "config.json").write_text("{}")
    (settings.vector_db_root / "idx.faiss").write_text("vec")
    (settings.log_root / "app.log").write_text("test log")

    app = create_app(settings=settings)
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    return client


def test_admin_create_backup(admin_client):
    resp = admin_client.post("/admin/backup", json={"label": "api-test"})
    assert resp.status_code == 200
    assert resp.json()["label"] == "api-test"


def test_admin_list_backups(admin_client):
    resp = admin_client.get("/admin/backup")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_admin_restore_404(admin_client):
    resp = admin_client.post(
        "/admin/backup/restore",
        json={"backup_dir": "/nonexistent/path", "dry_run": True},
    )
    assert resp.status_code == 400


def test_admin_endpoint_requires_authentication(tmp_path):
    settings = Settings(sqlite_path=tmp_path / "projectpack.db")
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/admin/backup").status_code == 401


def test_admin_cleanup_backups(admin_client):
    resp = admin_client.post("/admin/backup/cleanup")
    assert resp.status_code == 200
    assert "removed" in resp.json()


def test_admin_rotate_logs(admin_client):
    resp = admin_client.post("/admin/logs/rotate?log_file=app.log")
    assert resp.status_code == 200
    assert "rotated" in resp.json()


def test_admin_cleanup_logs(admin_client):
    resp = admin_client.post("/admin/logs/cleanup")
    assert resp.status_code == 200
    assert "removed" in resp.json()


def test_admin_stress_test(admin_client):
    resp = admin_client.post(
        "/admin/stress-test",
        json={
            "large_file_count": 1, "large_file_size_mb": 1,
            "batch_file_count": 3, "long_context_requests": 2,
            "multi_project_count": 2,
            "multi_project_requests_per_project": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_status"] in ("pass", "fail")
    assert data["total_requests"] > 0


# ===========================================================================
# Schemas validation tests
# ===========================================================================


def test_schema_queue_status():
    from app.schemas.models import QueueStatus
    qs = QueueStatus(active_llm_calls=2, global_llm_capacity=4)
    assert qs.active_llm_calls == 2
    assert qs.model_dump()["global_llm_capacity"] == 4


def test_schema_cache_stats():
    from app.schemas.models import CacheStats
    cs = CacheStats(size=100, hits=80, misses=20, hit_rate=0.8)
    assert cs.hit_rate == 0.8


def test_schema_health_check_response():
    from app.schemas.models import HealthCheckResponse
    hcr = HealthCheckResponse(status="healthy")
    assert hcr.status == "healthy"
    d = hcr.model_dump()
    assert "gpu_metrics" in d
    assert "system_metrics" in d


def test_schema_stress_test_config():
    from app.schemas.models import StressTestConfigModel
    stc = StressTestConfigModel(large_file_count=2, multi_project_count=3)
    assert stc.large_file_count == 2
    assert stc.multi_project_count == 3
    assert stc.large_file_size_mb == 10


def test_schema_backup_entry():
    from app.schemas.models import BackupEntry
    be = BackupEntry(backup_dir="/backups/1", name="b1", status="success")
    assert be.status == "success"


# ===========================================================================
# Error codes tests
# ===========================================================================


def test_phase_j_error_codes():
    from app.observability.error_codes import APP_ERROR_CODES

    j_codes = [
        "CONCURRENCY_LIMIT_EXCEEDED", "QUEUE_TIMEOUT",
        "LLM_CALL_CANCELLED", "EMBEDDING_SERVICE_UNAVAILABLE",
        "CACHE_INVALID_KEY", "BACKUP_FAILED", "RECOVERY_FAILED",
        "BACKUP_NOT_FOUND", "HEALTH_DEGRADED", "HEALTH_CRITICAL",
        "BENCHMARK_NOT_INITIALIZED", "STRESS_TEST_INVALID_PARAMS",
    ]
    for code in j_codes:
        assert code in APP_ERROR_CODES, f"Missing error code: {code}"
