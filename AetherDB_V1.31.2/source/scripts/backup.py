"""
Data Backup CLI — Exports all database content as portable JSON.
Focus: entities and their relationships (not project source code).

Usage:
    python scripts/backup.py                    # Create data backup
    python scripts/backup.py --list              # List 备份内容
    python scripts/backup.py --restore NAME      # Restore from backup
    python scripts/backup.py --cleanup --keep 10 # Cleanup old 备份内容
"""
import os, sys, json, shutil, argparse
from datetime import datetime
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_runtime_config_path, get_writable_config_path

DB_PATH = 'novel_world_zh.db'
BACKUP_DIR = '备份内容'

TABLES = {
    'entities': 'SELECT * FROM entities WHERE is_active = 1 ORDER BY entity_id',
    'relations': 'SELECT * FROM relations ORDER BY id',
    'timeline_events': 'SELECT * FROM timeline_events ORDER BY year',
    'tag_index': 'SELECT * FROM tag_index ORDER BY id',
    'references_map': 'SELECT * FROM references_map ORDER BY id',
    'entity_versions': 'SELECT * FROM entity_versions ORDER BY id',
}

def export_data(db_path=DB_PATH):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    data = {}
    for table, query in TABLES.items():
        rows = conn.execute(query).fetchall()
        data[table] = [dict(r) for r in rows]
    conn.close()
    return data

def import_data(data, db_path=DB_PATH):
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

def create_backup(description=''):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = f'worldview_data_{timestamp}'
    path = os.path.join(BACKUP_DIR, name)
    os.makedirs(path, exist_ok=True)

    data = export_data()
    for table, rows in data.items():
        with open(os.path.join(path, f'{table}.json'), 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)

    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, os.path.join(path, 'database_snapshot.db'))

    total_entities = len(data.get('entities', []))
    total_relations = len(data.get('relations', []))
    with get_runtime_config_path().open(encoding='utf-8') as cf:
        cfg = yaml.safe_load(cf)
    workspace_id = cfg.get('app', {}).get('workspace_id', 'default')
    meta = {
        'name': name, 'timestamp': timestamp,
        'version': 'v1.31.2', 'workspace_id': workspace_id, 'description': description or 'CLI data backup',
        'counts': {t: len(r) for t, r in data.items()},
        'total_entities': total_entities,
        'total_relations': total_relations,
    }
    with open(os.path.join(path, 'backup_metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f'[OK] Backup created: {name}')
    print(f'     Entities: {total_entities}, Relations: {total_relations}')
    print(f'     Total files: {len(data)} JSON + optional DB snapshot')
    return meta

def list_备份内容():
    if not os.path.exists(BACKUP_DIR):
        print('No 备份内容 found.'); return
    备份内容 = sorted(os.listdir(BACKUP_DIR), reverse=True)
    data_备份内容 = [b for b in 备份内容 if b.startswith('worldview_data_')]
    if not data_备份内容:
        print('No data 备份内容 found.'); return
    print(f'Data Backups ({len(data_备份内容)} total):')
    print('-' * 80)
    for b in data_备份内容:
        mp = os.path.join(BACKUP_DIR, b, 'backup_metadata.json')
        if os.path.exists(mp):
            with open(mp, encoding='utf-8') as f:
                m = json.load(f)
            ents = m.get('total_entities', '?')
            rels = m.get('total_relations', '?')
            desc = m.get('description', '')
            ts = m.get('timestamp', b.replace('worldview_data_', ''))
            print(f'  {ts}  E:{ents} R:{rels}  {desc}')

def restore(name):
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.isdir(path):
        print(f'[ERR] Backup not found: {name}'); return
    data = {}
    for table in TABLES:
        fp = os.path.join(path, f'{table}.json')
        if os.path.exists(fp):
            with open(fp, encoding='utf-8') as f:
                data[table] = json.load(f)
        else:
            data[table] = []
    counts = import_data(data)
    print(f'[OK] Restored from: {name}')
    for t, c in counts.items():
        print(f'     {t}: {c}')
    return counts

def cleanup(keep=10):
    if not os.path.exists(BACKUP_DIR):
        return
    备份内容 = sorted([b for b in os.listdir(BACKUP_DIR) if b.startswith('worldview_data_')], reverse=True)
    if len(备份内容) <= keep:
        print(f'Only {len(备份内容)} 备份内容, no cleanup needed.'); return
    for b in 备份内容[keep:]:
        shutil.rmtree(os.path.join(BACKUP_DIR, b), ignore_errors=True)
        print(f'Removed: {b}')
    print(f'Cleanup done. Kept {keep}, removed {len(备份内容)-keep}.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Worldview Data Backup Tool')
    parser.add_argument('--list', '-l', action='store_true', help='List 备份内容')
    parser.add_argument('--restore', type=str, help='Backup name to restore')
    parser.add_argument('--cleanup', action='store_true', help='Remove old 备份内容')
    parser.add_argument('--keep', type=int, default=10, help='Number to keep')
    parser.add_argument('--desc', '-d', default='', help='Backup description')
    args = parser.parse_args()
    if args.list: list_备份内容()
    elif args.restore: restore(args.restore)
    elif args.cleanup: cleanup(args.keep)
    elif args.auto_backup:
        with get_runtime_config_path().open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if "backup" not in cfg:
            cfg["backup"] = {}
        cfg["backup"]["auto_backup_on_startup"] = (args.auto_backup == "on")
        config_path = get_writable_config_path()
        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        print("Auto-backup set to: " + args.auto_backup)
    else: create_backup(args.desc)
