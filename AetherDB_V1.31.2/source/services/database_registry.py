"""Database Registry — central connection routing and workspace management.

V1.21 Federated DB / Workspace layer.
"""
import sqlite3, os, shutil, json, logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from app.config import get_runtime_path

REGISTRY_PATH = str(get_runtime_path("app_data", "registry.db"))
DATABASES_ROOT = str(get_runtime_path("app_data", "databases"))
OLD_DB_PATH = str(get_runtime_path("novel_world_zh.db"))

log = logging.getLogger(__name__)

def _get_registry_conn():
    Path(os.path.dirname(REGISTRY_PATH)).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(REGISTRY_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# ── Registry tables ────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS databases (
    database_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    author TEXT DEFAULT '',
    description TEXT DEFAULT '',
    db_path TEXT NOT NULL,
    root_path TEXT NOT NULL,
    schema_version TEXT DEFAULT '1.0',
    status TEXT DEFAULT 'active',
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_opened_at TIMESTAMP,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS active_context (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS books_global (
    global_book_id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    description TEXT DEFAULT '',
    entity_count INTEGER DEFAULT 0,
    relation_count INTEGER DEFAULT 0,
    timeline_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    source_updated_at TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}',
    UNIQUE(database_id, book_id)
);

CREATE TABLE IF NOT EXISTS entities_global_index (
    global_id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content_preview TEXT DEFAULT '',
    ai_summary TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    importance INTEGER DEFAULT 5,
    is_active INTEGER DEFAULT 1,
    source_updated_at TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_hash TEXT DEFAULT '',
    UNIQUE(database_id, book_id, entity_id)
);

CREATE TABLE IF NOT EXISTS relations_global_index (
    global_relation_id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    description TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    source_updated_at TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS timeline_global_index (
    global_event_id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    timeline_year INTEGER,
    timeline_era TEXT DEFAULT '',
    source_updated_at TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(database_id, book_id, event_id)
);

CREATE TABLE IF NOT EXISTS sync_status (
    database_id TEXT PRIMARY KEY,
    status TEXT DEFAULT 'clean',
    last_full_sync_at TIMESTAMP,
    last_incremental_sync_at TIMESTAMP,
    last_error TEXT DEFAULT '',
    dirty_reason TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_providers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_format TEXT NOT NULL,
    credential_ref TEXT,
    models_endpoint TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    health_status TEXT NOT NULL DEFAULT 'unknown',
    supports_model_discovery INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_profiles (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    provider_model_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    model_type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    context_length INTEGER,
    max_output_tokens INTEGER,
    supports_streaming INTEGER NOT NULL DEFAULT 0,
    supports_tools INTEGER NOT NULL DEFAULT 0,
    supports_json_mode INTEGER NOT NULL DEFAULT 0,
    cost_level TEXT NOT NULL DEFAULT 'unknown',
    privacy_level TEXT NOT NULL DEFAULT 'cloud_upload',
    health_status TEXT NOT NULL DEFAULT 'unknown',
    remote_status TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider_id, provider_model_name),
    FOREIGN KEY(provider_id) REFERENCES model_providers(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_model_profiles_provider
ON model_profiles(provider_id, enabled);

CREATE TABLE IF NOT EXISTS model_task_bindings (
    id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL,
    scope_id TEXT,
    task_type TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'model_profile',
    target_id TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(target_id) REFERENCES model_profiles(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_model_task_bindings_lookup
ON model_task_bindings(task_type, scope_type, scope_id, enabled, priority);

CREATE TABLE IF NOT EXISTS model_usage_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_profile_id TEXT NOT NULL,
    provider_model_name TEXT NOT NULL,
    route_reason TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL,
    latency_ms INTEGER,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1,
    error_code TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, attempt_id)
);

CREATE TABLE IF NOT EXISTS model_recovery_tickets (
    id TEXT PRIMARY KEY,
    recovery_kind TEXT NOT NULL,
    owner_fingerprint TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    task_type TEXT NOT NULL,
    source_model_profile_id TEXT,
    candidate_model_ids_json TEXT NOT NULL,
    selected_model_profile_id TEXT,
    error_code TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    expires_at TEXT NOT NULL,
    confirmed_at TEXT,
    consumed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_recovery_ticket_lookup
ON model_recovery_tickets(owner_fingerprint, request_hash, recovery_kind, status, expires_at);

CREATE TABLE IF NOT EXISTS model_data_policies (
    model_profile_id TEXT PRIMARY KEY,
    permission_tier TEXT NOT NULL DEFAULT 'A_PURE_CREATION'
        CHECK(permission_tier IN ('A_PURE_CREATION','B_CONTEXT_ENHANCED','C_RESTRICTED_TOOLS')),
    allow_original_text INTEGER NOT NULL DEFAULT 1,
    allow_approved_context INTEGER NOT NULL DEFAULT 0,
    allow_selected_media INTEGER NOT NULL DEFAULT 0,
    max_payload_bytes INTEGER NOT NULL DEFAULT 2097152,
    updated_by TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(model_profile_id) REFERENCES model_profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_tool_registry (
    tool_name TEXT PRIMARY KEY,
    permission_tier TEXT NOT NULL
        CHECK(permission_tier IN ('A_PURE_CREATION','B_CONTEXT_ENHANCED','C_RESTRICTED_TOOLS')),
    handler_id TEXT NOT NULL,
    description TEXT NOT NULL,
    input_schema_json TEXT NOT NULL,
    output_schema_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_tool_policies (
    model_profile_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_by TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(model_profile_id, tool_name),
    FOREIGN KEY(model_profile_id) REFERENCES model_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY(tool_name) REFERENCES model_tool_registry(tool_name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_tool_executions (
    execution_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    model_profile_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    database_id TEXT NOT NULL,
    book_id TEXT,
    chapter_id TEXT,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(model_profile_id) REFERENCES model_profiles(id) ON DELETE RESTRICT,
    FOREIGN KEY(tool_name) REFERENCES model_tool_registry(tool_name) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_model_tool_executions_task
ON model_tool_executions(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS model_data_manifests (
    data_manifest_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    database_id TEXT NOT NULL,
    book_id TEXT,
    chapter_id TEXT,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    selected_text_hash TEXT NOT NULL,
    approved_context_ids_json TEXT NOT NULL DEFAULT '[]',
    selected_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    estimated_payload_size INTEGER NOT NULL,
    contains_original_text INTEGER NOT NULL DEFAULT 0,
    contains_media INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','confirmed','consumed','expired','revoked')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    confirmed_at TEXT,
    consumed_at TEXT,
    FOREIGN KEY(provider_id) REFERENCES model_providers(id) ON DELETE RESTRICT,
    FOREIGN KEY(model_id) REFERENCES model_profiles(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_model_data_manifests_owner
ON model_data_manifests(owner_id, task_id, status, expires_at);

CREATE TABLE IF NOT EXISTS embedding_tasks (
    id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    book_id TEXT,
    task_kind TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    requested_backend TEXT NOT NULL DEFAULT 'auto',
    effective_backend TEXT,
    backend_fallback_detected INTEGER NOT NULL DEFAULT 0,
    model_id TEXT,
    model_revision TEXT,
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    successful_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0,
    current_batch_size INTEGER NOT NULL DEFAULT 16,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    retry_of TEXT,
    target_space_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY(retry_of) REFERENCES embedding_tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_embedding_tasks_lookup
ON embedding_tasks(database_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS embedding_task_items (
    task_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(task_id, entity_id, operation),
    FOREIGN KEY(task_id) REFERENCES embedding_tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embedding_task_items_status
ON embedding_task_items(task_id, status, entity_id);

CREATE TABLE IF NOT EXISTS model_test_results (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    model_profile_id TEXT,
    test_type TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    capability_summary TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(provider_id) REFERENCES model_providers(id) ON DELETE CASCADE,
    FOREIGN KEY(model_profile_id) REFERENCES model_profiles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_model_test_results_lookup
ON model_test_results(provider_id, model_profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS model_package_catalog (
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    display_name TEXT NOT NULL,
    package_kind TEXT NOT NULL,
    core_required INTEGER NOT NULL DEFAULT 0,
    model_profile_id TEXT,
    manifest_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    license_id TEXT NOT NULL,
    redistribution_allowed INTEGER NOT NULL DEFAULT 0,
    source_kind TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(package_id, package_version)
);

CREATE INDEX IF NOT EXISTS idx_model_package_catalog_lookup
ON model_package_catalog(package_kind, enabled, package_id, package_version);

CREATE TABLE IF NOT EXISTS model_package_files (
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    role TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY(package_id, package_version, relative_path),
    FOREIGN KEY(package_id, package_version)
        REFERENCES model_package_catalog(package_id, package_version)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_package_installations (
    package_id TEXT PRIMARY KEY,
    package_version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'install_available'
        CHECK(status IN (
            'not_installed','install_available','downloading','verifying',
            'installing','installed','repair_required','incompatible',
            'disabled','uninstalling','failed'
        )),
    install_ref TEXT NOT NULL,
    storage_scope TEXT NOT NULL DEFAULT 'managed'
        CHECK(storage_scope IN ('managed','external_override')),
    verified_files INTEGER NOT NULL DEFAULT 0,
    total_files INTEGER NOT NULL DEFAULT 0,
    installed_size_bytes INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    installed_at TIMESTAMP,
    verified_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_package_installations_status
ON model_package_installations(status, package_id);

CREATE TABLE IF NOT EXISTS model_package_license_acceptances (
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    license_id TEXT NOT NULL,
    accepted_by TEXT NOT NULL,
    accepted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(package_id, package_version, manifest_digest)
);

CREATE TABLE IF NOT EXISTS model_package_operations (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    operation TEXT NOT NULL
        CHECK(operation IN ('install','repair','verify')),
    source_kind TEXT NOT NULL
        CHECK(source_kind IN ('catalog','offline_cache','installed')),
    source_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN (
            'queued','downloading','verifying','installing',
            'installed','verified','failed','cancelled'
        )),
    progress REAL NOT NULL DEFAULT 0,
    completed_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    retry_of TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY(retry_of) REFERENCES model_package_operations(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_model_package_operations_lookup
ON model_package_operations(package_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS model_runtime_policy (
    id TEXT PRIMARY KEY,
    scheduling_policy TEXT NOT NULL DEFAULT 'CONSERVATIVE',
    competition_mode INTEGER NOT NULL DEFAULT 0,
    lease_ttl_seconds INTEGER NOT NULL DEFAULT 30,
    pressure_free_vram_percent INTEGER NOT NULL DEFAULT 10,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_compute_snapshots (
    id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    platform TEXT NOT NULL,
    architecture TEXT NOT NULL,
    total_ram_mb INTEGER NOT NULL,
    available_ram_mb INTEGER NOT NULL,
    model_disk_total_mb INTEGER NOT NULL,
    model_disk_free_mb INTEGER NOT NULL,
    device_count INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_compute_snapshots_time
ON model_compute_snapshots(captured_at DESC);

CREATE TABLE IF NOT EXISTS model_resource_leases (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    device_fingerprint TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    model_package_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    lease_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_backend TEXT NOT NULL,
    reserved_vram_mb INTEGER NOT NULL,
    estimated_peak_vram_mb INTEGER NOT NULL,
    runtime_context_overhead_mb INTEGER NOT NULL,
    safety_margin_mb INTEGER NOT NULL,
    actual_vram_mb INTEGER,
    actual_peak_vram_mb INTEGER,
    priority INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_resource_leases_active
ON model_resource_leases(device_id, status, priority, acquired_at);

CREATE INDEX IF NOT EXISTS idx_model_resource_leases_worker
ON model_resource_leases(worker_id, status, acquired_at DESC);

CREATE TABLE IF NOT EXISTS model_resource_drift_events (
    id TEXT PRIMARY KEY,
    drift_code TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    lease_id TEXT,
    device_id TEXT,
    runtime_id TEXT,
    owner_type TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    details_json TEXT NOT NULL DEFAULT '{}',
    first_detected_at TEXT NOT NULL,
    last_detected_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_resource_drift_active
ON model_resource_drift_events(status, drift_code, last_detected_at DESC);

CREATE TABLE IF NOT EXISTS model_coexistence_evidence (
    id TEXT PRIMARY KEY,
    package_a TEXT NOT NULL,
    package_b TEXT NOT NULL,
    device_fingerprint TEXT NOT NULL,
    backend TEXT NOT NULL,
    benchmark_ref TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    expires_at TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_coexistence_lookup
ON model_coexistence_evidence(
    package_a, package_b, device_fingerprint, backend, verified, verified_at DESC
);

CREATE TABLE IF NOT EXISTS model_runtime_evidence (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    device_fingerprint TEXT NOT NULL,
    backend TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    probe_ref TEXT NOT NULL,
    benchmark_ref TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    verified_at TEXT,
    expires_at TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_runtime_evidence_lookup
ON model_runtime_evidence(
    package_id, package_version, manifest_digest, device_fingerprint,
    backend, verification_status, verified_at DESC
);

CREATE TABLE IF NOT EXISTS model_worker_instances (
    id TEXT PRIMARY KEY,
    replica_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    runtime_adapter TEXT NOT NULL,
    residency_mode TEXT NOT NULL,
    idle_unload_seconds INTEGER NOT NULL DEFAULT 300,
    state TEXT NOT NULL,
    process_id INTEGER,
    python_runtime TEXT NOT NULL,
    requested_backend TEXT,
    effective_backend TEXT,
    device_id TEXT,
    device_fingerprint TEXT,
    lease_id TEXT,
    started_at TEXT,
    loaded_at TEXT,
    last_used_at TEXT,
    last_heartbeat_at TEXT,
    stopped_at TEXT,
    exit_code INTEGER,
    restart_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_worker_instances_lookup
ON model_worker_instances(package_id, replica_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS model_runtime_jobs (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    requested_backend TEXT,
    effective_backend TEXT,
    device_id TEXT,
    lease_id TEXT,
    priority INTEGER NOT NULL DEFAULT 50,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    result_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(worker_id) REFERENCES model_worker_instances(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_model_runtime_jobs_lookup
ON model_runtime_jobs(worker_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS ollama_runtime_observations (
    runtime_id TEXT PRIMARY KEY,
    provider_id TEXT,
    base_url TEXT NOT NULL,
    ownership TEXT NOT NULL,
    state TEXT NOT NULL,
    installed INTEGER NOT NULL DEFAULT 0,
    running INTEGER NOT NULL DEFAULT 0,
    api_compatible INTEGER NOT NULL DEFAULT 0,
    version TEXT,
    compatibility TEXT NOT NULL DEFAULT 'unavailable',
    error_code TEXT,
    error_message TEXT,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ollama_model_observations (
    runtime_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    provider_id TEXT,
    model_profile_id TEXT,
    digest TEXT,
    previous_digest TEXT,
    discovery_status TEXT NOT NULL DEFAULT 'DETECTED',
    user_configured INTEGER NOT NULL DEFAULT 0,
    installed INTEGER NOT NULL DEFAULT 1,
    loaded INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    size_vram_bytes INTEGER NOT NULL DEFAULT 0,
    context_length INTEGER,
    expires_at TEXT,
    model_format TEXT,
    model_family TEXT,
    parameter_size TEXT,
    quantization_level TEXT,
    reported_capabilities_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'ollama_reported',
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(runtime_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_ollama_model_observations_loaded
ON ollama_model_observations(runtime_id, loaded, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS ollama_operations (
    id TEXT PRIMARY KEY,
    provider_id TEXT,
    operation TEXT NOT NULL,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    completed_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    status_message TEXT NOT NULL DEFAULT '',
    error_code TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    retry_of TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(provider_id) REFERENCES model_providers(id) ON DELETE SET NULL,
    FOREIGN KEY(retry_of) REFERENCES ollama_operations(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ollama_operations_status
ON ollama_operations(status, created_at DESC);

CREATE TABLE IF NOT EXISTS ollama_install_operations (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    platform TEXT NOT NULL,
    architecture TEXT NOT NULL,
    accelerator TEXT,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    completed_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    current_artifact_id TEXT,
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    cache_root TEXT NOT NULL,
    status_message TEXT NOT NULL DEFAULT '',
    error_code TEXT,
    provider_id TEXT,
    launch_method TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ollama_install_operations_status
ON ollama_install_operations(status, created_at DESC);

CREATE TABLE IF NOT EXISTS ollama_execution_tasks (
    execution_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_profile_id TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_hash TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN (
            'queued','admitted','running','cancel_requested','completed',
            'failed','cancelled','timed_out','interrupted'
        )),
    lease_id TEXT,
    queue_reason TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    tool_rounds INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    heartbeat_at TEXT,
    completed_at TEXT,
    FOREIGN KEY(provider_id) REFERENCES model_providers(id) ON DELETE RESTRICT,
    FOREIGN KEY(model_profile_id) REFERENCES model_profiles(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_ollama_execution_tasks_task
ON ollama_execution_tasks(task_id, owner_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ollama_execution_tasks_status
ON ollama_execution_tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS import_tasks (
    id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    requested_mode TEXT NOT NULL,
    detected_mode TEXT,
    source_format TEXT NOT NULL,
    source_text TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    total_items INTEGER NOT NULL DEFAULT 0,
    preview_json TEXT,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    retry_of TEXT,
    created_by TEXT NOT NULL DEFAULT 'admin',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(retry_of) REFERENCES import_tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_import_tasks_status
ON import_tasks(status, created_at DESC);

-- Drop and recreate to ensure correct tokenizer
DROP TABLE IF EXISTS fts_global;
CREATE VIRTUAL TABLE IF NOT EXISTS fts_global USING fts5(
    global_id UNINDEXED,
    database_id UNINDEXED,
    book_id UNINDEXED,
    entity_id UNINDEXED,
    entity_type UNINDEXED,
    title,
    content_preview,
    ai_summary,
    tags,
    tokenize='unicode61 remove_diacritics 2'
);
"""

def init_registry():
    """Initialize the registry database and directory structure.
    Safe to call multiple times. Creates tables if not exist.
    Also migrates the old novel_world_zh.db if present.
    """
    Path(DATABASES_ROOT).mkdir(parents=True, exist_ok=True)
    conn = _get_registry_conn()
    try:
        conn.executescript(SCHEMA_SQL)
        _ensure_registry_columns(conn)
        # Migrate old database
        existing = conn.execute("SELECT COUNT(*) FROM databases").fetchone()[0]
        if existing == 0 and os.path.exists(OLD_DB_PATH):
            _migrate_old_database(conn)
            existing = 1
        # Ensure default database exists
        if existing == 0:
            _ensure_default_database(conn)
        # Ensure active_context has defaults
        ctx = conn.execute("SELECT COUNT(*) FROM active_context").fetchone()[0]
        if ctx == 0:
            conn.execute("INSERT OR IGNORE INTO active_context (key, value) VALUES ('active_database_id', 'default')")
            conn.execute("INSERT OR IGNORE INTO active_context (key, value) VALUES ('default_database_id', 'default')")
            conn.execute("INSERT OR IGNORE INTO active_context (key, value) VALUES ('active_book_id', 'default')")
            conn.execute("INSERT OR IGNORE INTO active_context (key, value) VALUES ('workspace_id', 'default')")
            conn.commit()
    finally:
        conn.close()


def _ensure_registry_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(model_usage_log)")}
    additions = {
        "estimated_cost": "REAL",
        "latency_ms": "INTEGER",
        "fallback_used": "INTEGER NOT NULL DEFAULT 0",
        "error_code": "TEXT",
    }
    for name, ddl in additions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE model_usage_log ADD COLUMN {name} {ddl}")
    install_existing = {
        row[1] for row in conn.execute("PRAGMA table_info(ollama_install_operations)")
    }
    install_additions = {
        "provider_id": "TEXT",
        "launch_method": "TEXT",
    }
    for name, ddl in install_additions.items():
        if name not in install_existing:
            conn.execute(
                f"ALTER TABLE ollama_install_operations ADD COLUMN {name} {ddl}"
            )
    pull_existing = {
        row[1] for row in conn.execute("PRAGMA table_info(ollama_operations)")
    }
    if "cancel_requested" not in pull_existing:
        conn.execute(
            "ALTER TABLE ollama_operations ADD COLUMN "
            "cancel_requested INTEGER NOT NULL DEFAULT 0"
        )
    lease_existing = {
        row[1] for row in conn.execute("PRAGMA table_info(model_resource_leases)")
    }
    lease_additions = {
        "runtime_id": "TEXT",
        "model_id": "TEXT",
        "resource_class": "TEXT NOT NULL DEFAULT 'GPU_SHARED_LIGHT'",
        "estimated_ram_mb": "INTEGER NOT NULL DEFAULT 0",
        "owner_type": "TEXT NOT NULL DEFAULT 'aetherdb_worker'",
    }
    for name, ddl in lease_additions.items():
        if name not in lease_existing:
            conn.execute(
                f"ALTER TABLE model_resource_leases ADD COLUMN {name} {ddl}"
            )
    conn.execute(
        "UPDATE model_resource_leases SET resource_class="
        "CASE WHEN effective_backend='cpu' THEN 'CPU_PARALLEL' "
        "WHEN lease_mode='EXCLUSIVE' THEN 'GPU_EXCLUSIVE_HEAVY' "
        "ELSE resource_class END "
        "WHERE resource_class IS NULL OR resource_class='GPU_SHARED_LIGHT'"
    )
    embedding_task_existing = {
        row[1] for row in conn.execute("PRAGMA table_info(embedding_tasks)")
    }
    if "target_space_id" not in embedding_task_existing:
        conn.execute(
            "ALTER TABLE embedding_tasks ADD COLUMN target_space_id TEXT"
        )
    conn.commit()

def _migrate_old_database(conn):
    """Copy novel_world_zh.db to app_data/databases/default/worldview.db."""
    default_dir = Path(DATABASES_ROOT) / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    target = default_dir / "worldview.db"
    if not target.exists():
        log.info("Migrating: %s -> %s", OLD_DB_PATH, target)
        shutil.copy2(OLD_DB_PATH, target)
        log.info("Old database copied to %s; original kept as backup", target)
    # Register
    conn.execute("""
        INSERT INTO databases (database_id, name, author, description, db_path, root_path, is_default)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, ("default", "默认数据库", "", "自动迁移的旧版数据库",
          str(target), str(default_dir)))
    conn.commit()
    log.info("Default database registered")

def _ensure_default_database(conn):
    """Create a fresh default database if none exists."""
    row = conn.execute("SELECT COUNT(*) FROM databases WHERE database_id='default'").fetchone()
    if row[0] > 0:
        return
    default_dir = Path(DATABASES_ROOT) / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    target = default_dir / "worldview.db"
    # Create empty database with schema
    conn2 = sqlite3.connect(str(target))
    conn2.execute("PRAGMA journal_mode=WAL")
    conn2.execute("PRAGMA foreign_keys=ON")
    conn2.close()
    conn.execute("""
        INSERT INTO databases (database_id, name, author, description, db_path, root_path, is_default)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, ("default", "默认数据库", "", "自动创建的默认数据库",
          str(target), str(default_dir)))
    conn.commit()

def list_databases() -> List[dict]:
    conn = _get_registry_conn()
    try:
        rows = conn.execute("SELECT * FROM databases ORDER BY is_default DESC, name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_database(database_id: str) -> Optional[dict]:
    conn = _get_registry_conn()
    try:
        row = conn.execute("SELECT * FROM databases WHERE database_id = ?", (database_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_db_path(database_id: str = None) -> str:
    """Get the filesystem path of a database's worldview.db.
    If database_id is None, use the active database.
    """
    if database_id is None:
        database_id = get_active_database_id()
    db = get_database(database_id)
    if not db:
        raise ValueError("Database not found in registry")
    if not os.path.exists(db["db_path"]):
        raise FileNotFoundError(f"Database file not found (check registry)")
    return db["db_path"]

def get_active_database_id() -> str:
    conn = _get_registry_conn()
    try:
        row = conn.execute("SELECT value FROM active_context WHERE key = 'active_database_id'").fetchone()
        return row["value"] if row else "default"
    finally:
        conn.close()

def set_active_database_id(database_id: str):
    conn = _get_registry_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO active_context (key, value, updated_at) VALUES ('active_database_id', ?, CURRENT_TIMESTAMP)", (database_id,))
        conn.commit()
    finally:
        conn.close()

def get_default_database_id() -> str:
    conn = _get_registry_conn()
    try:
        row = conn.execute("SELECT database_id FROM databases WHERE is_default = 1").fetchone()
        return row["database_id"] if row else "default"
    finally:
        conn.close()

def validate_database(database_id: str) -> bool:
    try:
        db = get_database(database_id)
        if db:
            return os.path.exists(db["db_path"])
    except:
        pass
    return False

def create_database(name: str, author: str = "", description: str = "") -> dict:
    """Create a new business database."""
    import re
    database_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.lower().replace(" ", "_"))
    db_dir = Path(DATABASES_ROOT) / database_id
    if db_dir.exists():
        raise ValueError(f"Database '{database_id}' already exists")
    db_dir.mkdir(parents=True, exist_ok=True)
    target = db_dir / "worldview.db"
    conn = sqlite3.connect(str(target))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()
    reg = _get_registry_conn()
    try:
        reg.execute("""
            INSERT INTO databases (database_id, name, author, description, db_path, root_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (database_id, name, author, description, str(target), str(db_dir)))
        reg.commit()
        return {"database_id": database_id, "name": name, "db_path": str(target)}
    finally:
        reg.close()

def remove_database(database_id: str, delete_files: bool = False):
    if database_id == "default":
        raise ValueError("Cannot remove the default database")
    reg = _get_registry_conn()
    try:
        reg.execute("DELETE FROM active_context WHERE value = ?", (database_id,))
        reg.execute("DELETE FROM databases WHERE database_id = ?", (database_id,))
        reg.commit()
    finally:
        reg.close()
    if delete_files:
        db_dir = Path(DATABASES_ROOT) / database_id
        if db_dir.exists():
            shutil.rmtree(str(db_dir))

def get_active_book_id() -> str:
    conn = _get_registry_conn()
    try:
        row = conn.execute("SELECT value FROM active_context WHERE key = 'active_book_id'").fetchone()
        return row["value"] if row else "default"
    finally:
        conn.close()

def set_active_book_id(book_id: str):
    conn = _get_registry_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO active_context (key, value, updated_at) VALUES ('active_book_id', ?, CURRENT_TIMESTAMP)", (book_id,))
        conn.commit()
    finally:
        conn.close()

def get_workspace_id() -> str:
    """Get the current workspace_id. Alias for get_active_database_id()."""
    return get_active_database_id()

def set_workspace_id(workspace_id: str):
    """Set workspace_id in active_context."""
    conn = _get_registry_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO active_context (key, value, updated_at) VALUES ('workspace_id', ?, CURRENT_TIMESTAMP)", (workspace_id,))
        conn.commit()
    finally:
        conn.close()
