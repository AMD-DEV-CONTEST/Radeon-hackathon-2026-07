#!/bin/bash
# manage_learning_db.sh — non-destructive backup/verify/restore + gated reset.
# Uses the SQLite online backup API (destination connection) under the cross-process
# maintenance lock; restore uses the drain lease. Destructive reset requires a verified
# backup AND a validated routing-decision.json (Todo 8 wires those gates; this script
# implements the operations the gates call).
set -uo pipefail

COMMAND="${1:-help}"
shift || true

DB="${LC_DB_PATH:-/persistent/learning-companion/data/learning.db}"
BACKUP_DIR="${LC_BACKUP_DIR:-/persistent/learning-companion/data/backups}"
ROOT="/persistent/learning-companion"

case "$COMMAND" in
  dry-run)
    echo "DRYRUN_OK: no changes made (db=$DB)"
    exit 0
    ;;
  backup)
    DB_ARG=""; OUT_ARG=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --db) DB="$2"; shift 2;;
        --artifact-out) OUT_ARG="$2"; shift 2;;
        *) echo "backup: unknown arg $1" >&2; exit 2;;
      esac
    done
    mkdir -p "$BACKUP_DIR"
    STAMP="$(date +%Y%m%dT%H%M%SZ)"
    TMPF="$BACKUP_DIR/.tmp-$STAMP"
    FINAL="$BACKUP_DIR/backup-$STAMP.sqlite"
    # exclusive maintenance lock (short; serializes backup-vs-backup/restore)
    LOCKFD="$(python3 - "$ROOT" <<'PY'
import fcntl, os, sys
root = sys.argv[1]
os.makedirs(f"{root}/data", exist_ok=True)
fd = os.open(f"{root}/data/maintenance.lock", os.O_RDWR | os.O_CREAT)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print(fd)
except OSError:
    os.close(fd)
    print("")
PY
)"
    if [ -z "$LOCKFD" ]; then echo "backup: maintenance.lock held by another op" >&2; exit 1; fi
    python3 - "$DB" "$TMPF" <<'PY' || { kill -0 $$ 2>/dev/null; python3 -c "import os; os.close($LOCKFD)" 2>/dev/null; echo "backup: online backup failed" >&2; exit 1; }
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
dest = sqlite3.connect(dst)
source.backup(dest)
dest.close(); source.close()
PY
    # verify integrity + logical digests
    python3 - "$TMPF" <<'PY' || { echo "backup: integrity verify failed" >&2; exit 1; }
import sqlite3, sys, json, hashlib
con = sqlite3.connect(sys.argv[1])
row = con.execute("PRAGMA integrity_check").fetchone()
assert row[0] == "ok", row
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
digests = {}
for t in tables:
    rows = [tuple(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1")]
    cols = [d[0] for d in con.execute(f"PRAGMA table_info({t})")]
    canon = json.dumps([{"cols": cols, "rows": rows}], ensure_ascii=False, sort_keys=True)
    digests[t] = hashlib.sha256(canon.encode()).hexdigest()
con.close()
manifest = {"path": sys.argv[1], "tables": digests}
open(sys.argv[1] + ".manifest.json", "w").write(json.dumps(manifest))
print("BACKUP_VERIFY_OK")
PY
    mv "$TMPF" "$FINAL"
    mv "$TMPF.manifest.json" "$FINAL.manifest.json"
    SHA="$(sha256sum "$FINAL" | cut -d' ' -f1)"
    python3 - "$FINAL.manifest.json" "$SHA" <<'PY' || true
import json, sys
m = json.load(open(sys.argv[1])); m["artifact_sha256"] = sys.argv[2]
json.dump(m, open(sys.argv[1], "w"))
PY
    python3 -c "import os; os.close($LOCKFD)" 2>/dev/null
    if [ -n "$OUT_ARG" ]; then echo "$FINAL" > "$OUT_ARG"; fi
    echo "BACKUP_OK: $FINAL sha256=$SHA"
    exit 0
    ;;
  verify)
    ART="${1:?verify requires artifact path}"
    [ -f "$ART" ] || { echo "verify: artifact not found $ART" >&2; exit 1; }
    python3 - "$ART" <<'PY' || exit 1
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
row = con.execute("PRAGMA integrity_check").fetchone()
assert row[0] == "ok", row
print("VERIFY_OK: integrity ok")
PY
    exit 0
    ;;
  restore)
    ART=""; TO=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --to) TO="$2"; shift 2;;
        *) if [ -z "$ART" ]; then ART="$1"; else echo "restore: unknown arg $1" >&2; exit 2; fi; shift;;
      esac
    done
    [ -n "$ART" ] && [ -f "$ART" ] || { echo "restore: artifact required" >&2; exit 1; }
    [ -n "$TO" ] || { echo "restore: --to required" >&2; exit 1; }
    # drain lease + maintenance lock per contract lock order
    python3 - "$ART" "$TO" <<'PY' || exit 1
import fcntl, json, os, sys, time
sys.path.insert(0, "/persistent/learning-companion")
from app import drain as D
src, dst = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(dst), exist_ok=True)
mfd = D.acquire_maintenance_lock()
try:
    with D.DrainLease("restore"):
        # temp copy + fsync + atomic replace + fsync dir
        tmp = dst + ".tmp"
        import shutil
        shutil.copyfile(src, tmp)
        fd = os.open(tmp, os.O_RDWR); os.fsync(fd); os.close(fd)
        os.replace(tmp, dst)
        dfd = os.open(os.path.dirname(dst), os.O_RDONLY); os.fsync(dfd); os.close(dfd)
        # reopen + validate
        import sqlite3
        con = sqlite3.connect(dst)
        row = con.execute("PRAGMA integrity_check").fetchone()
        con.close()
        assert row[0] == "ok", row
finally:
    D.release_maintenance_lock(mfd)
print("RESTORE_OK")
PY
    exit $?
    ;;
  reset)
    # Destructive gated reset (Todo 8): build a fresh DB from the target schema at
    # a temp path, atomically swap, and roll back to the verified backup on ANY
    # failure. Runs ONLY when BOTH machine-readable gates re-verify at reset time:
    #   (a) backup artifact manifest (artifact sha256 + per-table digests + integrity)
    #   (b) routing-decision.json recomputed by scripts/validate_routing_decision.py
    BACKUP=""; ROUTING=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --backup) BACKUP="$2"; shift 2;;
        --routing) ROUTING="$2"; shift 2;;
        --db) DB="$2"; shift 2;;
        *) echo "reset: unknown arg $1" >&2; exit 2;;
      esac
    done
    [ -n "$BACKUP" ] && [ -f "$BACKUP" ] || { echo "reset: --backup artifact required" >&2; exit 1; }
    [ -n "$ROUTING" ] && [ -f "$ROUTING" ] || { echo "reset: --routing decision required" >&2; exit 1; }
    MANIFEST="$BACKUP.manifest.json"
    [ -f "$MANIFEST" ] || { echo "reset: backup manifest missing $MANIFEST" >&2; exit 1; }
    # ---- gate (a): re-verify backup manifest (never assumed) ----
    python3 - "$BACKUP" "$MANIFEST" <<'PY' || { echo "reset: gate(a) backup manifest verification FAILED" >&2; exit 1; }
import hashlib, json, sqlite3, sys
artifact, manifest_path = sys.argv[1], sys.argv[2]
manifest = json.load(open(manifest_path))
# artifact sha256 (byte-for-byte over the file)
sha = hashlib.sha256(open(artifact, "rb").read()).hexdigest()
assert manifest.get("artifact_sha256") == sha, "artifact sha256 mismatch"
con = sqlite3.connect(artifact)
row = con.execute("PRAGMA integrity_check").fetchone()
assert row[0] == "ok", row
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
digests = {}
for t in tables:
    rows = [tuple(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1")]
    cols = [d[0] for d in con.execute(f"PRAGMA table_info({t})")]
    canon = json.dumps([{"cols": cols, "rows": rows}], ensure_ascii=False, sort_keys=True)
    digests[t] = hashlib.sha256(canon.encode()).hexdigest()
con.close()
assert digests == manifest.get("tables", {}), "per-table digests mismatch"
print("RESET_GATE_A_OK: artifact sha256 + per-table digests + integrity verified")
PY
    # ---- gate (b): validate routing decision (recompute, never trust stored fields) ----
    /opt/venv/bin/python "$ROOT/scripts/validate_routing_decision.py" "$ROUTING" >/dev/null 2>&1 \
      || { echo "reset: gate(b) routing decision validation FAILED" >&2; exit 1; }
    echo "RESET_GATE_B_OK: routing decision recomputed and valid"
    # ---- lock-order protocol + temp-build + atomic swap + rollback on failure ----
    python3 - "$BACKUP" "$DB" "$ROOT" <<'PY' || exit 1
import os, shutil, sqlite3, sys
sys.path.insert(0, sys.argv[3])
from app import drain as D
backup, live_db, root = sys.argv[1], sys.argv[2], sys.argv[3]
migration = f"{root}/db/migrations/0001_initial.sql"
os.makedirs(os.path.dirname(live_db), exist_ok=True)
live_dir = os.path.dirname(live_db)
mfd = D.acquire_maintenance_lock()
try:
    with D.DrainLease("reset"):
        tmp = os.path.join(live_dir, ".reset-live.sqlite.tmp")
        try:
            # build the NEW DB at a temp path in the live DB directory
            con = sqlite3.connect(tmp)
            con.executescript(open(migration).read())
            con.commit(); con.close()
            fd = os.open(tmp, os.O_RDWR); os.fsync(fd); os.close(fd)
            # checkpoint/handle WAL of the old live DB before swap
            try:
                old = sqlite3.connect(live_db)
                old.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                old.close()
            except sqlite3.Error:
                pass
            os.replace(tmp, live_db)
            dfd = os.open(live_dir, os.O_RDONLY); os.fsync(dfd); os.close(dfd)
            # remove stale sidecars
            for side in (live_db + "-wal", live_db + "-shm", live_db + "-journal"):
                if os.path.exists(side):
                    try: os.unlink(side)
                    except OSError: pass
            # reopen + validate
            con = sqlite3.connect(live_db)
            row = con.execute("PRAGMA integrity_check").fetchone()
            con.close()
            assert row[0] == "ok", row
            print("RESET_SWAP_OK: fresh DB live and validated")
        except Exception as e:
            print(f"RESET_FAILURE: {e}; rolling back to verified backup", file=sys.stderr)
            # rollback: copy the verified backup to a temp file, validate + fsync,
            # replace the live DB, and fsync the directory
            rtmp = os.path.join(live_dir, ".rollback-live.sqlite.tmp")
            shutil.copyfile(backup, rtmp)
            fd = os.open(rtmp, os.O_RDWR); os.fsync(fd); os.close(fd)
            con = sqlite3.connect(rtmp)
            row = con.execute("PRAGMA integrity_check").fetchone()
            con.close()
            assert row[0] == "ok", "rollback artifact corrupted"
            os.replace(rtmp, live_db)
            dfd = os.open(live_dir, os.O_RDONLY); os.fsync(dfd); os.close(dfd)
            for side in (live_db + "-wal", live_db + "-shm", live_db + "-journal"):
                if os.path.exists(side):
                    try: os.unlink(side)
                    except OSError: pass
            print("RESET_ROLLBACK_OK: restored verified backup")
            raise
finally:
    D.release_maintenance_lock(mfd)
print("RESET_OK")
PY
    exit $?
    ;;
  help|*)
    echo "usage: manage_learning_db.sh <backup|verify|restore|dry-run|reset> [args]"
    exit 0
    ;;
esac
