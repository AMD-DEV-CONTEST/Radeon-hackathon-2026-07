"""
Backup API — Data-Centric Backup for Entities and Relations.
Exports all database content (entities, relations, timeline, etc.) as portable JSON.
"""
import hashlib
import os, json, shutil, time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.dependencies.auth import require_admin
from services.logger import get_logger
from services.audit_log import log_event
from services.db import close_connection, get_db, init_db
from services.database_registry import get_active_database_id, get_active_book_id, get_db_path
from app.config import get_runtime_config_path, get_runtime_path, get_writable_config_path
from app.version import APP_VERSION_TAG

router = APIRouter(prefix="/api/backup", tags=["backup"])
BACKUP_DIR = str(get_runtime_path("备份内容"))
APP_VERSION = APP_VERSION_TAG
LOG = get_logger()
os.makedirs(BACKUP_DIR, exist_ok=True)

def _audit(event_type: str, description: str, details: str = ""):
    db = get_db()
    try:
        target = description.split()[1] if description.startswith("Backup ") else event_type
        log_event(
            db,
            event_type,
            description,
            details=details,
            target=target,
            database_id=get_active_database_id(),
            book_id=get_active_book_id(),
            success=True,
        )
    finally:
        db.close()

# ── Table query definitions ──
TABLES = {
    "books": "SELECT * FROM books ORDER BY book_id",
    "entities": "SELECT * FROM entities WHERE is_active = 1 ORDER BY entity_id",
    "relations": "SELECT * FROM relations ORDER BY id",
    "timeline_events": "SELECT * FROM timeline_events ORDER BY year",
    "tag_index": "SELECT * FROM tag_index ORDER BY id",
    "references_map": "SELECT * FROM references_map ORDER BY id",
    "entity_versions": "SELECT * FROM entity_versions ORDER BY id",
    "media_assets": "SELECT * FROM media_assets ORDER BY created_at, asset_id",
    "media_asset_versions": "SELECT * FROM media_asset_versions ORDER BY asset_id, version_number",
    "media_asset_derivatives": "SELECT * FROM media_asset_derivatives ORDER BY asset_id, created_at",
    "media_annotations": "SELECT * FROM media_annotations ORDER BY asset_id, created_at",
    "media_asset_bindings": "SELECT * FROM media_asset_bindings ORDER BY asset_id, sort_order, created_at",
}

# ── Helper functions ──

def _export_data(db_path):
    '''Export all tables to dict of lists. Returns {table_name: [rows]}.'''
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    data = {}
    existing = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for table, query in TABLES.items():
        rows = conn.execute(query).fetchall() if table in existing else []
        data[table] = [dict(r) for r in rows]
    conn.close()
    return data

def _import_data(data: dict, db_path):
    '''Import data dict back into database. Returns {table: count}.'''
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    counts = {}
    for table, rows in data.items():
        if not rows:
            counts[table] = 0
            continue
        columns = list(rows[0].keys())
        placeholders = ', '.join(['?' for _ in columns])
        col_names = ', '.join(columns)
        sql = f'INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})'
        for row in rows:
            values = [row.get(col) for col in columns]
            cursor.execute(sql, values)
        conn.commit()
        counts[table] = len(rows)
    conn.close()
    return counts

def _copy_database_snapshot(source_path: str, target_path: str):
    import sqlite3

    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _safe_relative_media_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("Unsafe media path in backup manifest")
    return path


def _media_manifest(data: dict) -> list[dict]:
    records = {}
    for table in ("media_assets", "media_asset_versions", "media_asset_derivatives"):
        for row in data.get(table, []):
            relative_path = row.get("relative_path")
            content_hash = row.get("content_hash")
            if not relative_path or not content_hash:
                continue
            _safe_relative_media_path(relative_path)
            records[relative_path] = {
                "relative_path": relative_path,
                "content_hash": content_hash,
                "file_size_bytes": int(row.get("file_size_bytes") or 0),
            }
    return sorted(records.values(), key=lambda item: item["relative_path"])


def _copy_media_payloads(db_path: str, backup_path: str, manifest: list[dict]) -> int:
    source_root = (Path(db_path).resolve().parent / "assets").resolve()
    target_root = Path(backup_path) / "media_files"
    copied = 0
    for item in manifest:
        relative = _safe_relative_media_path(item["relative_path"])
        source = source_root.joinpath(*relative.parts).resolve()
        try:
            source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError("Unsafe media source path") from exc
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError("A referenced media object is unavailable")
        if source.stat().st_size != item["file_size_bytes"]:
            raise ValueError("Media size changed while creating backup")
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != item["content_hash"]:
            raise ValueError("Media hash changed while creating backup")
        target = target_root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def _verify_media_payload(path: Path, item: dict):
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("A referenced media object is unavailable")
    if path.stat().st_size != item["file_size_bytes"]:
        raise ValueError("Media payload size does not match the manifest")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != item["content_hash"]:
        raise ValueError("Media payload hash does not match the manifest")


def _prepare_restored_media(
    db_path: str,
    backup_path: str,
    manifest: list[dict],
    *,
    media_files_included: bool,
) -> list[tuple[Path, Path]]:
    target_root = (Path(db_path).resolve().parent / "assets").resolve()
    source_root = (
        (Path(backup_path) / "media_files").resolve()
        if media_files_included
        else target_root
    )
    copies = []
    for item in manifest:
        relative = _safe_relative_media_path(item["relative_path"])
        source = source_root.joinpath(*relative.parts).resolve()
        target = target_root.joinpath(*relative.parts).resolve()
        try:
            source.relative_to(source_root)
            target.relative_to(target_root)
        except ValueError as exc:
            raise ValueError("Unsafe media path in restore manifest") from exc
        _verify_media_payload(source, item)
        if media_files_included:
            copies.append((source, target, item))
    return copies


def create_data_backup(
    description="",
    *,
    database_id: str | None = None,
    include_media_files: bool = False,
):
    '''Create a timestamped backup of all database content as JSON.'''
    database_id = database_id or get_active_database_id()
    db_path = get_db_path(database_id)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = f'worldview_data_{timestamp}'
    backup_path = os.path.join(BACKUP_DIR, name)
    if os.path.exists(backup_path):
        name = f"{name}_{int(time.time_ns() % 1_000_000):06d}"
        backup_path = os.path.join(BACKUP_DIR, name)
    os.makedirs(backup_path, exist_ok=True)

    # Export all data to JSON
    data = _export_data(db_path)
    json_files = {}
    for table, rows in data.items():
        filepath = os.path.join(backup_path, f'{table}.json')
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        json_files[table] = filepath

    # Copy raw .db file
    db_copy = os.path.join(backup_path, 'database_snapshot.db')
    _copy_database_snapshot(db_path, db_copy)
    manifest = _media_manifest(data)
    copied_media_files = (
        _copy_media_payloads(db_path, backup_path, manifest)
        if include_media_files
        else 0
    )
    with open(os.path.join(backup_path, "media_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    # Write metadata
    total_entities = len(data.get('entities', []))
    total_relations = len(data.get('relations', []))
    import yaml
    with get_runtime_config_path().open(encoding='utf-8') as cf:
        cfg = yaml.safe_load(cf)
    workspace_id = cfg.get('app', {}).get('workspace_id', 'default')
    meta = {
        'name': name, 'timestamp': timestamp,
        'version': APP_VERSION, 'workspace_id': workspace_id,
        'database_id': database_id,
        'description': description or 'Data backup',
        'counts': {t: len(r) for t, r in data.items()},
        'total_entities': total_entities,
        'total_relations': total_relations,
        'has_db_snapshot': os.path.exists(db_copy),
        'files': {t: f'{t}.json' for t in data},
        'media_manifest': 'media_manifest.json',
        'media_object_count': len(manifest),
        'media_files_included': include_media_files,
        'copied_media_files': copied_media_files,
    }
    with open(os.path.join(backup_path, 'backup_metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    LOG.info('Data backup created: %s (%d entities, %d relations)',
             name, total_entities, total_relations)
    return meta

def list_data_backups():
    '''List all data backups sorted by date (newest first).'''
    backups = []
    for entry in sorted(os.listdir(BACKUP_DIR), reverse=True):
        entry_path = os.path.join(BACKUP_DIR, entry)
        if not os.path.isdir(entry_path) or not entry.startswith('worldview_data_'):
            continue
        meta_path = os.path.join(entry_path, 'backup_metadata.json')
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        else:
            meta = {'name': entry, 'timestamp': entry.replace('worldview_data_', ''),
                    'description': 'No metadata'}
            meta['size_bytes'] = sum(os.path.getsize(os.path.join(dp, f))
                                 for dp, dn, fns in os.walk(entry_path) for f in fns)
            meta['size_human'] = f'{meta["size_bytes"]/1024:.1f} KB'
        backups.append(meta)
    return backups


# ── API Endpoints ──

@router.post('/create')
async def create_backup(
    _: None = Depends(require_admin),
    description: str = Query('', description='Optional backup description'),
    database_id: str | None = Query(None, description='Database to back up; defaults to active'),
    include_media_files: bool = Query(False, description='Include binary media payloads'),
):
    '''Create a new data backup of all entities and relations.'''
    try:
        meta = create_data_backup(
            description,
            database_id=database_id,
            include_media_files=include_media_files,
        )
        _audit('backup.create', f"Backup {meta.get('name')} created", json.dumps({"description": description}, ensure_ascii=False))
        return {'status': 'ok', 'backup': meta}
    except Exception as e:
        LOG.error('Backup failed: %s', e)
        raise HTTPException(status_code=500, detail='Backup failed - check server logs')


@router.get('/list')
async def list_backups(_: None = Depends(require_admin)):
    '''List all available data backups.'''
    return {'backups': list_data_backups()}


@router.get('/stats')
async def backup_stats(_: None = Depends(require_admin)):
    '''Get backup statistics.'''
    backups = list_data_backups()
    total_size = sum(b.get('size_bytes', 0) for b in backups)
    latest = backups[0] if backups else None
    return {
        'total_backups': len(backups),
        'total_size_bytes': total_size,
        'total_size_human': f'{total_size/1024/1024:.1f} MB' if total_size > 0 else '0 B',
        'total_entities': latest['total_entities'] if latest else 0,
        'total_relations': latest['total_relations'] if latest else 0,
        'last_backup': latest,
    }


@router.post('/restore/{backup_name}')
async def restore_backup(backup_name: str, _: None = Depends(require_admin)):
    '''Restore data from a backup. Overwrites current database content.'''
    backup_root = Path(BACKUP_DIR).resolve()
    backup_path_obj = (backup_root / Path(backup_name).name).resolve()
    try:
        backup_path_obj.relative_to(backup_root)
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid backup name')
    if Path(backup_name).name != backup_name:
        raise HTTPException(status_code=400, detail='Invalid backup name')
    backup_path = str(backup_path_obj)
    if not os.path.exists(backup_path) or not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail='Backup not found')
    meta_path = os.path.join(backup_path, 'backup_metadata.json')
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=400, detail='Backup metadata not found')
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    database_id = meta.get("database_id") or get_active_database_id()
    db_path = get_db_path(database_id)
    try:
        manifest_path = os.path.join(backup_path, "media_manifest.json")
        manifest = []
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        media_copies = _prepare_restored_media(
            db_path,
            backup_path,
            manifest,
            media_files_included=bool(meta.get("media_files_included")),
        )
        snapshot = os.path.join(backup_path, "database_snapshot.db")
        if os.path.isfile(snapshot):
            close_connection()
            _copy_database_snapshot(snapshot, db_path)
            init_db(database_id)
            counts = dict(meta.get("counts") or {})
        else:
            data = {}
            for table in TABLES:
                filepath = os.path.join(backup_path, f'{table}.json')
                if os.path.exists(filepath):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data[table] = json.load(f)
                else:
                    data[table] = []
            counts = _import_data(data, db_path)
        for source, target, item in media_copies:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                try:
                    _verify_media_payload(target, item)
                    continue
                except (FileNotFoundError, ValueError):
                    pass
            temporary = target.with_name(f"{target.name}.restore-{time.time_ns()}")
            shutil.copy2(source, temporary)
            _verify_media_payload(temporary, item)
            os.replace(temporary, target)
        LOG.info('Restored from backup: %s (%d entities)',
                 backup_name, counts.get('entities', 0))
        _audit('backup.restore', f"Backup {backup_name} restored", json.dumps(counts, ensure_ascii=False))
        return {'status': 'ok', 'restored': counts, 'backup': meta}
    except HTTPException:
        raise
    except (FileNotFoundError, ValueError) as e:
        LOG.error('Restore media validation failed: %s', e)
        raise HTTPException(status_code=409, detail='Backup media payloads are incomplete or changed')
    except Exception as e:
        LOG.error('Restore failed: %s', e)
        raise HTTPException(status_code=500, detail='Restore failed - check server logs')


@router.post('/cleanup')
async def cleanup_backups(keep: int = Query(10, description='Number to keep'), _: None = Depends(require_admin)):
    '''Remove old backups, keeping only the N most recent.'''
    backups = list_data_backups()
    if len(backups) <= keep:
        return {'status': 'ok', 'removed': 0, 'message': 'No cleanup needed'}
    to_remove = backups[keep:]
    for b in to_remove:
        path = (Path(BACKUP_DIR).resolve() / Path(b['name']).name).resolve()
        if path.parent == Path(BACKUP_DIR).resolve() and path.exists():
            shutil.rmtree(path)
    LOG.info('Cleaned up %d old backups, kept %d', len(to_remove), keep)
    _audit('backup.cleanup', f'Removed {len(to_remove)} old backups, kept {keep}')
    return {'status': 'ok', 'removed': len(to_remove), 'kept': keep}

# ── Auto-backup Toggle ──

@router.get('/auto-backup')
async def get_auto_backup(_: None = Depends(require_admin)):
    '''Check whether auto-backup on startup is enabled.'''
    import yaml
    with get_runtime_config_path().open(encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    enabled = cfg.get('backup', {}).get('auto_backup_on_startup', True)
    return {'auto_backup_on_startup': enabled}


@router.post('/auto-backup')
async def set_auto_backup(enabled: bool = Query(..., description='true=enable, false=disable'), _: None = Depends(require_admin)):
    '''Enable or disable auto-backup on server startup.'''
    import yaml
    config_path = get_writable_config_path()
    with config_path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if 'backup' not in cfg:
        cfg['backup'] = {}
    cfg['backup']['auto_backup_on_startup'] = enabled
    with config_path.open('w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    status = 'enabled' if enabled else 'disabled'
    LOG.info('Auto-backup %s', status)
    _audit('backup.config.update', f'Auto-backup {status}')
    return {'auto_backup_on_startup': enabled, 'status': 'updated'}
