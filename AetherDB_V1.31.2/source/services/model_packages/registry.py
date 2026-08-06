"""Persistent catalog, license, installation, and operation repositories."""

from __future__ import annotations

import json
import os
import platform
import re
import uuid
from pathlib import Path

from app.config import get_resource_path
from services.database_registry import _get_registry_conn
from services.model_packages.manifest import ModelPackageManifest, load_package_manifest


ACTIVE_OPERATION_STATUSES = {"queued", "downloading", "verifying", "installing"}
INSTALLATION_STATUSES = {
    "not_installed",
    "install_available",
    "downloading",
    "verifying",
    "installing",
    "installed",
    "repair_required",
    "incompatible",
    "disabled",
    "uninstalling",
    "failed",
}
OPERATION_STATUSES = {
    "queued",
    "downloading",
    "verifying",
    "installing",
    "installed",
    "verified",
    "failed",
    "cancelled",
}
OPERATION_MUTABLE_FIELDS = {
    "status",
    "progress",
    "completed_bytes",
    "total_bytes",
    "cancel_requested",
    "error_code",
    "error_message",
    "completed_at",
}
INSTALLATION_MUTABLE_FIELDS = {
    "package_version",
    "manifest_digest",
    "status",
    "install_ref",
    "storage_scope",
    "verified_files",
    "total_files",
    "installed_size_bytes",
    "error_code",
    "error_message",
    "installed_at",
    "verified_at",
}
SAFE_SOURCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
NATIVE_WORKER_PROVIDER_ID = "aetherdb-native-worker"
NATIVE_MODEL_TYPES = {
    "text_to_speech": "tts",
}


class ModelPackageRegistryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


def catalog_root() -> Path:
    override = os.environ.get("AETHERDB_MODEL_PACKAGE_CATALOG", "").strip()
    return Path(override).expanduser().resolve() if override else get_resource_path(
        "resources", "model_packages"
    )


def normalize_platform(value: str | None = None) -> str:
    aliases = {
        "windows": "windows",
        "linux": "linux",
        "darwin": "macos",
        "macos": "macos",
    }
    normalized = (value or platform.system()).strip().lower()
    return aliases.get(normalized, normalized)


def normalize_architecture(value: str | None = None) -> str:
    aliases = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    normalized = (value or platform.machine()).strip().lower()
    return aliases.get(normalized, normalized)


def manifest_is_compatible(
    manifest: ModelPackageManifest,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> bool:
    return (
        normalize_platform(system) in manifest.supported_platforms
        and normalize_architecture(machine) in manifest.supported_architectures
    )


def _version_key(value: str) -> tuple:
    core, _, suffix = value.partition("-")
    return (*tuple(int(part) for part in core.split(".")), 1 if not suffix else 0, suffix)


def _canonical_manifest_json(manifest: ModelPackageManifest) -> str:
    return json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _storage_scope(manifest: ModelPackageManifest) -> str:
    if manifest.package_id == "aetherdb.bge-m3" and os.environ.get(
        "AETHERDB_MODEL_ROOT", ""
    ).strip():
        return "external_override"
    return "managed"


def _sync_native_worker_profiles(
    conn,
    manifests: list[ModelPackageManifest],
) -> None:
    routed = [item for item in manifests if item.model_profile_id]
    if not routed:
        return
    conn.execute(
        "INSERT INTO model_providers "
        "(id,display_name,provider_type,base_url,api_format,credential_ref,"
        "models_endpoint,enabled,health_status,supports_model_discovery) "
        "VALUES (?,?,?,?,?,NULL,NULL,1,'healthy',0) "
        "ON CONFLICT(id) DO UPDATE SET "
        "display_name=excluded.display_name,provider_type=excluded.provider_type,"
        "base_url=excluded.base_url,api_format=excluded.api_format,"
        "credential_ref=NULL,models_endpoint=NULL,enabled=1,"
        "health_status='healthy',supports_model_discovery=0,"
        "updated_at=CURRENT_TIMESTAMP",
        (
            NATIVE_WORKER_PROVIDER_ID,
            "AetherDB Native Model Workers",
            "aetherdb_worker",
            "http://127.0.0.1",
            "aetherdb_worker_v1",
        ),
    )
    for manifest in routed:
        model_type = NATIVE_MODEL_TYPES.get(manifest.package_kind)
        if not model_type:
            raise ModelPackageRegistryError(
                "PACKAGE_ROUTE_TYPE_UNSUPPORTED",
                "A routed model package declares an unsupported package kind",
            )
        installation = conn.execute(
            "SELECT package_version,manifest_digest,status "
            "FROM model_package_installations WHERE package_id=?",
            (manifest.package_id,),
        ).fetchone()
        installed = bool(
            installation
            and installation["package_version"] == manifest.package_version
            and installation["manifest_digest"] == manifest.digest()
            and installation["status"] == "installed"
        )
        conn.execute(
            "INSERT INTO model_profiles "
            "(id,provider_id,provider_model_name,display_name,model_type,enabled,"
            "supports_streaming,supports_tools,supports_json_mode,cost_level,"
            "privacy_level,health_status,remote_status) "
            "VALUES (?,?,?,?,?,1,0,0,0,'free','local_only',?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "provider_id=excluded.provider_id,"
            "provider_model_name=excluded.provider_model_name,"
            "display_name=excluded.display_name,model_type=excluded.model_type,"
            "enabled=1,supports_streaming=0,supports_tools=0,"
            "supports_json_mode=0,cost_level='free',privacy_level='local_only',"
            "health_status=excluded.health_status,"
            "remote_status=excluded.remote_status,updated_at=CURRENT_TIMESTAMP",
            (
                manifest.model_profile_id,
                NATIVE_WORKER_PROVIDER_ID,
                manifest.package_id,
                manifest.display_name,
                model_type,
                "healthy" if installed else "unknown",
                "available" if installed else "unavailable",
            ),
        )


def sync_catalog() -> list[dict]:
    root = catalog_root()
    if not root.is_dir():
        raise ModelPackageRegistryError(
            "CATALOG_MISSING", "Trusted model package catalog is unavailable"
        )
    manifests = [load_package_manifest(path) for path in sorted(root.glob("*.json"))]
    if not manifests:
        raise ModelPackageRegistryError(
            "CATALOG_EMPTY", "Trusted model package catalog contains no manifests"
        )
    identities = [(item.package_id, item.package_version) for item in manifests]
    if len(identities) != len(set(identities)):
        raise ModelPackageRegistryError(
            "CATALOG_DUPLICATE", "Trusted model package catalog contains duplicates"
        )

    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for manifest in manifests:
            digest = manifest.digest()
            conn.execute(
                "INSERT INTO model_package_catalog "
                "(package_id,package_version,display_name,package_kind,core_required,"
                "model_profile_id,manifest_digest,manifest_json,license_id,"
                "redistribution_allowed,source_kind,enabled) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,1) "
                "ON CONFLICT(package_id,package_version) DO UPDATE SET "
                "display_name=excluded.display_name,package_kind=excluded.package_kind,"
                "core_required=excluded.core_required,model_profile_id=excluded.model_profile_id,"
                "manifest_digest=excluded.manifest_digest,manifest_json=excluded.manifest_json,"
                "license_id=excluded.license_id,"
                "redistribution_allowed=excluded.redistribution_allowed,"
                "source_kind=excluded.source_kind,enabled=1,updated_at=CURRENT_TIMESTAMP",
                (
                    manifest.package_id,
                    manifest.package_version,
                    manifest.display_name,
                    manifest.package_kind,
                    int(manifest.core_required),
                    manifest.model_profile_id,
                    digest,
                    _canonical_manifest_json(manifest),
                    manifest.license.license_id,
                    int(manifest.license.redistribution_allowed),
                    manifest.source.kind,
                ),
            )
            conn.execute(
                "DELETE FROM model_package_files WHERE package_id=? AND package_version=?",
                (manifest.package_id, manifest.package_version),
            )
            conn.executemany(
                "INSERT INTO model_package_files "
                "(package_id,package_version,relative_path,role,size_bytes,sha256) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (
                        manifest.package_id,
                        manifest.package_version,
                        item.path,
                        item.role,
                        item.size,
                        item.sha256,
                    )
                    for item in manifest.files
                ],
            )
            existing = conn.execute(
                "SELECT package_version,status FROM model_package_installations "
                "WHERE package_id=?",
                (manifest.package_id,),
            ).fetchone()
            compatible = manifest_is_compatible(manifest)
            initial_status = "install_available" if compatible else "incompatible"
            if existing is None:
                conn.execute(
                    "INSERT INTO model_package_installations "
                    "(package_id,package_version,manifest_digest,status,install_ref,"
                    "storage_scope,total_files) VALUES (?,?,?,?,?,?,?)",
                    (
                        manifest.package_id,
                        manifest.package_version,
                        digest,
                        initial_status,
                        manifest.install_subdir,
                        _storage_scope(manifest),
                        len(manifest.files),
                    ),
                )
            elif (
                existing["package_version"] != manifest.package_version
                and existing["status"]
                in {"not_installed", "install_available", "incompatible", "failed"}
            ):
                conn.execute(
                    "UPDATE model_package_installations SET package_version=?,"
                    "manifest_digest=?,status=?,install_ref=?,storage_scope=?,"
                    "verified_files=0,total_files=?,installed_size_bytes=0,error_code=NULL,"
                    "error_message=NULL,updated_at=CURRENT_TIMESTAMP WHERE package_id=?",
                    (
                        manifest.package_version,
                        digest,
                        initial_status,
                        manifest.install_subdir,
                        _storage_scope(manifest),
                        len(manifest.files),
                        manifest.package_id,
                    ),
                )
        _sync_native_worker_profiles(conn, manifests)
        conn.commit()
    finally:
        conn.close()
    return list_packages(sync=False)


def _serialize_catalog_row(row: dict) -> dict:
    manifest = ModelPackageManifest.model_validate_json(row.pop("manifest_json"))
    payload = manifest.public_dict()
    payload["enabled"] = bool(row["enabled"])
    payload["profile_registered"] = bool(row.get("profile_registered"))
    payload["installation"] = row.get("installation")
    payload["license_accepted"] = bool(row.get("license_accepted"))
    return payload


def _catalog_rows() -> list[dict]:
    conn = _get_registry_conn()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT c.*,CASE WHEN p.id IS NULL THEN 0 ELSE 1 END AS profile_registered "
                "FROM model_package_catalog c "
                "LEFT JOIN model_profiles p ON p.id=c.model_profile_id "
                "WHERE c.enabled=1 ORDER BY c.package_id,c.package_version"
            )
        ]
        installations = {
            row["package_id"]: _serialize_installation(dict(row))
            for row in conn.execute("SELECT * FROM model_package_installations")
        }
        acceptances = {
            (row["package_id"], row["package_version"], row["manifest_digest"])
            for row in conn.execute(
                "SELECT package_id,package_version,manifest_digest "
                "FROM model_package_license_acceptances"
            )
        }
    finally:
        conn.close()
    for row in rows:
        row["installation"] = installations.get(row["package_id"])
        row["license_accepted"] = (
            row["package_id"],
            row["package_version"],
            row["manifest_digest"],
        ) in acceptances
    return rows


def list_packages(*, sync: bool = True) -> list[dict]:
    if sync:
        sync_catalog()
    latest = {}
    for row in _catalog_rows():
        current = latest.get(row["package_id"])
        if current is None or _version_key(row["package_version"]) > _version_key(
            current["package_version"]
        ):
            latest[row["package_id"]] = row
    return [_serialize_catalog_row(latest[key]) for key in sorted(latest)]


def get_package(
    package_id: str,
    package_version: str | None = None,
    *,
    sync: bool = True,
) -> dict | None:
    packages = list_packages(sync=sync)
    item = next((value for value in packages if value["package_id"] == package_id), None)
    if item is None or (
        package_version is not None and item["package_version"] != package_version
    ):
        return None
    return item


def get_package_for_model_profile(
    model_profile_id: str,
    *,
    sync: bool = True,
) -> dict | None:
    return next(
        (
            item
            for item in list_packages(sync=sync)
            if item.get("model_profile_id") == model_profile_id
        ),
        None,
    )


def get_manifest(
    package_id: str,
    package_version: str | None = None,
    *,
    sync: bool = True,
) -> ModelPackageManifest:
    if sync:
        sync_catalog()
    conn = _get_registry_conn()
    try:
        if package_version:
            row = conn.execute(
                "SELECT manifest_json FROM model_package_catalog "
                "WHERE package_id=? AND package_version=? AND enabled=1",
                (package_id, package_version),
            ).fetchone()
        else:
            rows = conn.execute(
                "SELECT package_version,manifest_json FROM model_package_catalog "
                "WHERE package_id=? AND enabled=1",
                (package_id,),
            ).fetchall()
            row = (
                max(rows, key=lambda value: _version_key(value["package_version"]))
                if rows
                else None
            )
    finally:
        conn.close()
    if row is None:
        raise KeyError(package_id)
    return ModelPackageManifest.model_validate_json(row["manifest_json"])


def accept_license(
    package_id: str,
    package_version: str,
    *,
    manifest_digest: str,
    license_id: str,
    accepted_by: str,
) -> dict:
    manifest = get_manifest(package_id, package_version)
    if manifest.digest() != manifest_digest or manifest.license.license_id != license_id:
        raise ModelPackageRegistryError(
            "LICENSE_CONFIRMATION_MISMATCH",
            "License confirmation does not match the trusted package manifest",
        )
    conn = _get_registry_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO model_package_license_acceptances "
            "(package_id,package_version,manifest_digest,license_id,accepted_by) "
            "VALUES (?,?,?,?,?)",
            (
                package_id,
                package_version,
                manifest_digest,
                license_id,
                accepted_by,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "package_id": package_id,
        "package_version": package_version,
        "manifest_digest": manifest_digest,
        "license_id": license_id,
        "accepted": True,
    }


def license_is_accepted(manifest: ModelPackageManifest) -> bool:
    if not manifest.license.requires_acceptance:
        return True
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM model_package_license_acceptances "
            "WHERE package_id=? AND package_version=? AND manifest_digest=?",
            (manifest.package_id, manifest.package_version, manifest.digest()),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def check_distribution_eligibility(
    selections: list[tuple[str, str]],
) -> dict:
    sync_catalog()
    results = []
    for package_id, package_version in selections:
        blockers = []
        try:
            manifest = get_manifest(
                package_id,
                package_version,
                sync=False,
            )
        except KeyError:
            results.append(
                {
                    "package_id": package_id,
                    "package_version": package_version,
                    "eligible": False,
                    "blockers": ["PACKAGE_NOT_IN_TRUSTED_CATALOG"],
                }
            )
            continue
        installation = get_installation(package_id)
        if not manifest.license.redistribution_allowed:
            blockers.append("REDISTRIBUTION_NOT_ALLOWED")
        if not license_is_accepted(manifest):
            blockers.append("LICENSE_ACCEPTANCE_REQUIRED")
        if (
            installation is None
            or installation["package_version"] != manifest.package_version
            or installation["manifest_digest"] != manifest.digest()
            or installation["status"] != "installed"
            or installation["verified_files"] != len(manifest.files)
            or installation["installed_size_bytes"] != manifest.install_size_bytes
        ):
            blockers.append("PACKAGE_NOT_VERIFIED")
        results.append(
            {
                "package_id": package_id,
                "package_version": package_version,
                "manifest_digest": manifest.digest(),
                "license_id": manifest.license.license_id,
                "eligible": not blockers,
                "blockers": blockers,
            }
        )
    return {
        "eligible": bool(results) and all(item["eligible"] for item in results),
        "packages": results,
    }


def _serialize_installation(row: dict) -> dict:
    for key in ("verified_files", "total_files", "installed_size_bytes"):
        row[key] = int(row.get(key) or 0)
    return row


def get_installation(package_id: str) -> dict | None:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT * FROM model_package_installations WHERE package_id=?",
            (package_id,),
        ).fetchone()
        return _serialize_installation(dict(row)) if row else None
    finally:
        conn.close()


def update_installation(package_id: str, **updates) -> dict:
    clean = {
        key: value for key, value in updates.items() if key in INSTALLATION_MUTABLE_FIELDS
    }
    if "status" in clean and clean["status"] not in INSTALLATION_STATUSES:
        raise ValueError("invalid installation status")
    if not clean:
        current = get_installation(package_id)
        if current is None:
            raise KeyError(package_id)
        return current
    columns = ",".join(f"{key}=?" for key in clean)
    conn = _get_registry_conn()
    try:
        cursor = conn.execute(
            f"UPDATE model_package_installations SET {columns},"
            "updated_at=CURRENT_TIMESTAMP WHERE package_id=?",
            (*clean.values(), package_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(package_id)
    finally:
        conn.close()
    return get_installation(package_id) or {}


def validate_source_ref(source_kind: str, source_ref: str | None) -> str:
    if source_kind == "catalog":
        return "catalog"
    value = (source_ref or "").strip()
    if source_kind != "offline_cache" or SAFE_SOURCE_REF_RE.fullmatch(value) is None:
        raise ModelPackageRegistryError(
            "INVALID_SOURCE",
            "Offline packages must use a safe file name from the managed inbox",
        )
    if not value.lower().endswith(".zip"):
        raise ModelPackageRegistryError(
            "INVALID_SOURCE", "Offline model packages must be ZIP archives"
        )
    return value


def create_operation(
    manifest: ModelPackageManifest,
    *,
    operation: str,
    source_kind: str,
    source_ref: str,
    retry_of: str | None = None,
) -> dict:
    if operation not in {"install", "repair", "verify"}:
        raise ValueError("invalid model package operation")
    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM model_package_operations WHERE package_id=? "
            "AND status IN ('queued','downloading','verifying','installing') "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (manifest.package_id,),
        ).fetchone()
        if existing:
            conn.commit()
            return _serialize_operation(dict(existing))
        operation_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO model_package_operations "
            "(id,package_id,package_version,manifest_digest,operation,source_kind,"
            "source_ref,status,total_bytes,retry_of) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                operation_id,
                manifest.package_id,
                manifest.package_version,
                manifest.digest(),
                operation,
                source_kind,
                source_ref,
                "queued",
                manifest.install_size_bytes if operation != "verify" else 0,
                retry_of,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_operation(operation_id) or {}


def _serialize_operation(row: dict) -> dict:
    row["cancel_requested"] = bool(row.get("cancel_requested"))
    row["progress"] = float(row.get("progress") or 0)
    row["completed_bytes"] = int(row.get("completed_bytes") or 0)
    row["total_bytes"] = int(row.get("total_bytes") or 0)
    return row


def get_operation(operation_id: str) -> dict | None:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT * FROM model_package_operations WHERE id=?", (operation_id,)
        ).fetchone()
        return _serialize_operation(dict(row)) if row else None
    finally:
        conn.close()


def list_operations(limit: int = 20) -> list[dict]:
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM model_package_operations "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [_serialize_operation(dict(row)) for row in rows]
    finally:
        conn.close()


def update_operation(operation_id: str, **updates) -> dict:
    clean = {key: value for key, value in updates.items() if key in OPERATION_MUTABLE_FIELDS}
    if "status" in clean and clean["status"] not in OPERATION_STATUSES:
        raise ValueError("invalid operation status")
    if not clean:
        current = get_operation(operation_id)
        if current is None:
            raise KeyError(operation_id)
        return current
    columns = ",".join(f"{key}=?" for key in clean)
    conn = _get_registry_conn()
    try:
        cursor = conn.execute(
            f"UPDATE model_package_operations SET {columns},"
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (*clean.values(), operation_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(operation_id)
    finally:
        conn.close()
    return get_operation(operation_id) or {}


def cancel_requested(operation_id: str) -> bool:
    operation = get_operation(operation_id)
    return bool(operation and operation["cancel_requested"])
