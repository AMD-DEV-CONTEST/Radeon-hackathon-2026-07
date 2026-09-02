# -*- coding: utf-8 -*-
"""
世界观数据库管理系统 v1.31.2 中文版
使用 FastAPI + Jinja2 模板
"""


import sys, site
# Auto-add system site-packages when running in virtual environment
if sys.prefix != sys.base_prefix:
    for p in site.getsitepackages():
        if p not in sys.path:
            sys.path.insert(0, p)
import uvicorn
import time
import json
import secrets
import socket
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.responses import JSONResponse
from services.logger import init_logging, get_logger, log_access
from services.db import init_db, close_connection
from services.embedding import create_embedding_provider
from services.vector_store import VectorStore, set_default_vector_store
from services.database_registry import init_registry
from app.config import DB_PATH, get_resource_path, get_runtime_path
from app.version import APP_VERSION, APP_VERSION_TAG
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from api.search_semantic import router as semantic_router
from api.rag_context import router as rag_router
from api.consistency_check import router as consistency_router
from api.translate import router as translate_router
from api.backup import router as backup_router
from api.entity import router as entity_router
from api.relation import router as relation_router
from api.search import router as search_router
from api.stats import router as stats_router
from api.import_endpoints import router as import_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from api.databases import router as databases_router
from api.books import router as books_router
from api.chapters import router as chapters_router
from api.ai_engine import router as ai_engine_router
from api.prompt_profiles import router as prompt_router
from api.model_registry import router as model_registry_router
from api.model_packages import router as model_packages_router
from api.model_runtime import router as model_runtime_router
from api.model_execution import router as model_execution_router
from api.model_security import router as model_security_router
from api.context import router as context_router
from api.auth_status import router as auth_status_router
from api.global_index import router as gi_router
from api.global_search import router as gs_router
from api.vector_index import router as vector_index_router
from api.ollama import router as ollama_router
from api.temporal import context_router as temporal_context_router, router as temporal_router
from api.media_assets import router as media_assets_router
from api.media_vision import router as media_vision_router
from api.media_generation import router as media_generation_router
from api.audio_contract import router as audio_contract_router
from api.logs import router as logs_router
from routes.web import router as web_router
from fastapi.templating import Jinja2Templates
from app.config import get_runtime_config_path

# ============================================================
# 安全密钥管理
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.database_ready = False
    app.state.startup_error = None
    try:
        initialize_runtime()
        app.state.database_ready = True
        yield
    except Exception as exc:
        app.state.startup_error = type(exc).__name__
        raise
    finally:
        app.state.database_ready = False
        from services.ollama_management import shutdown_managed_runtime
        from services.model_runtime.manager import shutdown_worker_manager

        shutdown_worker_manager()
        shutdown_managed_runtime()
        close_connection()


app = FastAPI(
    title=f"世界观数据库管理系统 {APP_VERSION_TAG}",
    version=APP_VERSION,
    description="支持 AI 协作的世界观数据库系统",
    lifespan=lifespan,
)

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BODY_BYTES = MAX_INPUT_BYTES

# V-012: CORS — mode-based (dev=loose, prod=tight)
import os as _os
_CORS_MODE = _os.environ.get("WORLDVIEW_CORS", "development")
if _CORS_MODE == "development":
    _origins = ["tauri://localhost"]
    _origin_regex = r"^http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?$"
elif _CORS_MODE == "desktop":
    _origins = [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",
    ]
    _origin_regex = None
else:
    _origins = ["tauri://localhost"]
    _origin_regex = None
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(get_resource_path("static"))), name="static")

# 设置模板
templates = Jinja2Templates(directory=str(get_resource_path("templates")))
templates.env.filters["from_json"] = json.loads

app.state.vector_store = None
app.state.db_path = DB_PATH
app.state.database_ready = False
app.state.startup_error = None


def _runtime_instance_id() -> str:
    configured = _os.environ.get("AETHERDB_RUNTIME_INSTANCE_ID", "").strip()
    if configured:
        if (
            not configured.startswith("aether_runtime_")
            or len(configured) != 47
            or any(character not in "0123456789abcdef" for character in configured[15:])
        ):
            raise RuntimeError("AETHERDB_RUNTIME_INSTANCE_ID is malformed")
        return configured
    return f"aether_runtime_{secrets.token_hex(16)}"


RUNTIME_INSTANCE_ID = _runtime_instance_id()


def _validated_build_id(value: str) -> str:
    build_id = value.strip()
    if (
        not 3 <= len(build_id) <= 128
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in build_id)
    ):
        raise RuntimeError("AetherDB build identity is malformed")
    return build_id


def _backend_build_id() -> str:
    manifest_path = get_resource_path("build-manifest.json")
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return _validated_build_id(str(payload["build_id"]))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Packaged AetherDB build manifest is invalid") from exc
    configured = _os.environ.get("AETHERDB_BUILD_ID", "")
    if configured:
        return _validated_build_id(configured)
    return f"dev-{APP_VERSION}"


BACKEND_BUILD_ID = _backend_build_id()


def backend_health_payload():
    database_ready = bool(app.state.database_ready)
    return {
        "status": "ok" if database_ready else "starting",
        "service": "aetherdb-backend",
        "version": app.version,
        "build_id": BACKEND_BUILD_ID,
        "instance_id": RUNTIME_INSTANCE_ID,
        "database_ready": database_ready,
    }


@app.get("/health", include_in_schema=False)
def backend_health():
    """Expose only the non-sensitive state required by launch supervision."""
    return backend_health_payload()


def require_desktop_handshake(request: Request) -> None:
    """Authenticate the private Tauri-to-sidecar identity probe."""
    expected = _os.environ.get("AETHERDB_DESKTOP_HANDSHAKE", "")
    provided = request.headers.get("x-aetherdb-desktop-handshake", "")
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=404, detail="Not found")


@app.get(
    "/.well-known/aetherdb-desktop",
    include_in_schema=False,
    dependencies=[Depends(require_desktop_handshake)],
)
def desktop_handshake():
    """Prove the dynamically launched loopback sidecar belongs to this Tauri process."""
    return {
        **backend_health_payload(),
        "product": "AetherDB",
        "protocol_version": "1.0",
        "transport": "dynamic_loopback",
    }


@app.post(
    "/.well-known/aetherdb-desktop/shutdown",
    include_in_schema=False,
    dependencies=[Depends(require_desktop_handshake)],
    status_code=202,
)
async def desktop_shutdown():
    """Gracefully stop only the uvicorn server owned by this desktop process."""
    import asyncio

    server = getattr(app.state, "uvicorn_server", None)
    if server is None:
        raise HTTPException(status_code=409, detail="Desktop-managed server is unavailable")
    asyncio.get_running_loop().call_later(0.1, setattr, server, "should_exit", True)
    return {"status": "stopping", "instance_id": RUNTIME_INSTANCE_ID}

app.include_router(semantic_router)
app.include_router(rag_router)
app.include_router(consistency_router)
app.include_router(translate_router)
app.include_router(web_router)
app.include_router(backup_router)
app.include_router(entity_router)
app.include_router(relation_router)
app.include_router(search_router)
app.include_router(stats_router)
app.include_router(import_router)
app.include_router(databases_router)
app.include_router(books_router)
app.include_router(chapters_router)
app.include_router(ai_engine_router)
app.include_router(prompt_router)
app.include_router(model_registry_router)
app.include_router(model_packages_router)
app.include_router(model_runtime_router)
app.include_router(model_execution_router)
app.include_router(model_security_router)
app.include_router(context_router)
app.include_router(auth_status_router)
app.include_router(gi_router)
app.include_router(gs_router)
app.include_router(vector_index_router)
app.include_router(ollama_router)
app.include_router(temporal_router)
app.include_router(temporal_context_router)
app.include_router(media_assets_router)
app.include_router(media_vision_router)
app.include_router(media_generation_router)
app.include_router(audio_contract_router)
app.include_router(logs_router)


@app.middleware("http")
async def access_log_middleware(request, call_next):
    content_length = request.headers.get("content-length")
    request_limit = MAX_REQUEST_BODY_BYTES
    if request.method == "POST" and request.url.path == "/api/media-assets":
        from services.media_assets import MAX_MEDIA_UPLOAD_BYTES

        request_limit = MAX_MEDIA_UPLOAD_BYTES + 1024 * 1024
    if content_length and int(content_length) > request_limit:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    log_access(request.method, request.url.path, response.status_code, duration_ms)
    return response


def initialize_runtime():
    """Initialize runtime services used by both uvicorn import and python main.py."""
    import yaml

    config_path = get_runtime_config_path()
    with config_path.open("r", encoding="utf-8") as cf:
        cfg = yaml.safe_load(cf) or {}

    log_level = cfg.get("logging", {}).get("level", "INFO")
    init_logging(level=log_level)
    log = get_logger()

    init_registry()
    from services.model_tools import sync_tool_registry
    sync_tool_registry()
    from services.model_packages.installer import recover_interrupted_operations as recover_model_package_operations
    from services.model_packages.registry import sync_catalog as sync_model_package_catalog
    from services.model_packages.verifier import reconcile_catalog_installations
    from services.ollama_management import recover_interrupted_operations
    from services.ollama_install_tasks import recover_interrupted_install_operations
    from services.import_tasks import recover_interrupted_import_tasks

    sync_model_package_catalog()
    reconcile_catalog_installations()
    recover_model_package_operations()
    from services.model_registry import reconcile_known_cloud_provider_defaults
    reconcile_known_cloud_provider_defaults()
    from services.model_runtime.scheduler import get_resource_scheduler
    get_resource_scheduler().cleanup_expired_leases()
    from services.ollama_execution import recover_interrupted_ollama_executions
    recover_interrupted_ollama_executions(get_resource_scheduler())
    from services.model_runtime.manager import get_worker_manager
    get_worker_manager()
    recover_interrupted_operations()
    recover_interrupted_install_operations()
    recover_interrupted_import_tasks()
    init_db()

    embedding_provider = create_embedding_provider()
    vector_store = VectorStore(DB_PATH, embedding_provider)
    vector_store.init_db()
    set_default_vector_store(vector_store)
    app.state.vector_store = vector_store
    app.state.db_path = DB_PATH

    from services.model_runtime.core_service import get_core_embedding_service
    core_embedding_status = get_core_embedding_service().initialize(
        embedding_provider
    )
    app.state.core_embedding_service = get_core_embedding_service()

    from services.embedding_tasks import recover_interrupted_embedding_tasks
    recover_interrupted_embedding_tasks()
    from services.media_generation import recover_interrupted_media_generation_tasks
    recover_interrupted_media_generation_tasks()
    from services.media_vision import recover_interrupted_visual_migrations
    recover_interrupted_visual_migrations()
    from services.tts_execution import recover_interrupted_audio_tasks
    recover_interrupted_audio_tasks()

    embedding_status = embedding_provider.status()
    if embedding_status.available:
        log.info(
            "Embedding runtime ready: %s via %s",
            embedding_status.model_id,
            embedding_status.execution_provider,
        )
    else:
        log.warning("Embedding runtime unavailable: %s", embedding_status.detail)
    log.info(
        "Core embedding service state: %s (%s)",
        core_embedding_status["state"],
        core_embedding_status["residency_state"],
    )

    log.info("Server starting - Worldview Database %s", APP_VERSION_TAG)

    if cfg.get("backup", {}).get("auto_backup_on_startup", True):
        from api.backup import create_data_backup
        try:
            meta = create_data_backup("Auto backup on server startup")
            log.info("Auto backup created: " + meta["name"])
        except Exception as e:
            log.warning("Auto backup skipped: " + str(e))


def get_server_endpoint():
    """Return the requested loopback endpoint; port 0 delegates allocation to the OS."""
    host = _os.environ.get("AETHERDB_HOST", "127.0.0.1").strip().lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("AETHERDB_HOST must be a loopback address")

    configured_port = _os.environ.get("AETHERDB_PORT", "").strip()
    if configured_port:
        try:
            port = int(configured_port)
        except ValueError as exc:
            raise RuntimeError("AETHERDB_PORT must be an integer") from exc
    else:
        port = 0
    if not 0 <= port <= 65535:
        raise RuntimeError("AETHERDB_PORT must be between 0 and 65535")
    return host, port


def create_server_socket():
    """Bind and retain the socket that Uvicorn will serve, eliminating port races."""
    host, requested_port = get_server_endpoint()
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    bind_host = "127.0.0.1" if host == "localhost" else host
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((bind_host, requested_port))
        listener.listen(2048)
        listener.set_inheritable(False)
        actual_port = int(listener.getsockname()[1])
        return host, actual_port, listener
    except Exception:
        listener.close()
        raise


def _startup_descriptor_path() -> Path | None:
    configured = _os.environ.get("AETHERDB_STARTUP_DESCRIPTOR", "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    runtime_root = get_runtime_path().resolve()
    if (
        path.parent != runtime_root
        or not path.name.startswith("backend-startup-")
        or path.suffix != ".json"
    ):
        raise RuntimeError("AETHERDB_STARTUP_DESCRIPTOR must be inside the runtime root")
    return path


def publish_startup_descriptor(port: int) -> Path | None:
    """Atomically announce the sidecar-owned port without persisting credentials."""
    path = _startup_descriptor_path()
    if path is None:
        return None
    payload = {
        "protocol_version": "1.0",
        "service": "aetherdb-backend",
        "pid": _os.getpid(),
        "port": port,
        "instance_id": RUNTIME_INSTANCE_ID,
        "build_id": BACKEND_BUILD_ID,
    }
    temporary = path.with_suffix(f".{_os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def remove_startup_descriptor(path: Path | None) -> None:
    if path is None:
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("instance_id") == RUNTIME_INSTANCE_ID:
            path.unlink()
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass


def print_startup_banner(host="127.0.0.1", port=0):
    print("=" * 60)
    print(f"  世界观数据库管理系统 {APP_VERSION_TAG} 中文版")
    print("=" * 60)
    print(f"  启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)
    print("  [i] API 密钥状态：")
    print("  管理员密钥: 已配置（内容不写入终端或日志）")
    print("  用户密钥:   已配置（内容不写入终端或日志）")
    print("  [!] 如使用自动生成的密钥，完整密钥保存在 .api_keys.json 文件中")
    print("-" * 60)
    display_host = "localhost" if host in {"127.0.0.1", "::1"} else host
    print(f"  [Web] 网页界面: http://{display_host}:{port}")
    print(f"  [DOC] API文档:  http://{display_host}:{port}/docs")
    print("=" * 60)


@app.exception_handler(Exception)
def universal_exception_handler(request, exc):
    """V-011: Return generic error. Log detailed traceback internally."""
    from services.logger import get_logger
    get_logger().error("Unhandled exception: %s", exc, exc_info=True)
    from starlette.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(sqlite3.OperationalError)
def database_operational_error_handler(request, exc):
    """Return a stable write/read failure without exposing database internals."""
    get_logger().error("Database operation failed: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "DATABASE_WRITE_FAILED",
                "message": "The local database is unavailable for this operation.",
            }
        },
    )


if __name__ == "__main__":
    server_host, server_port, server_socket = create_server_socket()
    startup_descriptor = publish_startup_descriptor(server_port)
    print_startup_banner(server_host, server_port)
    try:
        server_config = uvicorn.Config(
            app,
            host=server_host,
            port=server_port,
            log_config=None,
        )
        server = uvicorn.Server(server_config)
        app.state.uvicorn_server = server
        server.run(sockets=[server_socket])
    finally:
        app.state.uvicorn_server = None
        remove_startup_descriptor(startup_descriptor)
        server_socket.close()
        close_connection()
