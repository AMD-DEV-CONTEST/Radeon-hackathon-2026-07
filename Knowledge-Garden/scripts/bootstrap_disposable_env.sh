#!/bin/bash
# bootstrap_disposable_env.sh — run a command inside a DISPOSABLE worktree copy (Todo 11/F1-F4).
#
#   bootstrap_disposable_env.sh <workdir> <db-path> <model-port> <api-port> <web-port> \
#       --canonical-root <abs-path> [--export <worktree-relative-source>:<abs-canonical-destination> ...] \
#       -- <command...>
#
# Guarantees:
#   - Copies the repo to <workdir> (cp -a), then copies the canonical evidence tree
#     <canonical-root>/.omo/evidence/qwen3-learning-flow INTO
#     <workdir>/.omo/evidence/qwen3-learning-flow BEFORE running the command.
#   - Exports E2E_BASE_URL=http://127.0.0.1:<web-port> into the inner environment.
#   - Runs the supplied command (with optional inner --help).
#   - Exports designated artifacts ATOMICALLY (temp + fsync + os.replace + fsync dir +
#     sha256 recorded in an export manifest), rejecting absolute sources, '..' traversal,
#     destination collisions, and unlisted destinations.
#   - Tears down: asserts live paths/PIDs/ports untouched and that pre-existing evidence
#     inputs are NOT modified (only explicitly listed final artifacts may be created).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

WORKDIR=""
DB=""
MODEL_PORT=""
API_PORT=""
WEB_PORT=""
CANON_ROOT=""
EXPORTS=()
INNER=()

while [ $# -gt 0 ]; do
  case "$1" in
    --canonical-root) CANON_ROOT="$2"; shift 2;;
    --export) EXPORTS+=("$2"); shift 2;;
    --) shift; INNER=("$@"); break;;
    -h|--help) sed -n '2,14p' "$0"; exit 0;;
    *)
      if [ -z "$WORKDIR" ]; then WORKDIR="$1"
      elif [ -z "$DB" ]; then DB="$1"
      elif [ -z "$MODEL_PORT" ]; then MODEL_PORT="$1"
      elif [ -z "$API_PORT" ]; then API_PORT="$1"
      elif [ -z "$WEB_PORT" ]; then WEB_PORT="$1"
      else echo "unknown arg: $1" >&2; exit 2; fi
      shift;;
  esac
done

[ -n "$WORKDIR" ] && [ -n "$DB" ] && [ -n "$MODEL_PORT" ] && [ -n "$API_PORT" ] && [ -n "$WEB_PORT" ] && [ -n "$CANON_ROOT" ] && [ ${#INNER[@]} -gt 0 ] || {
  echo "usage: bootstrap_disposable_env.sh <workdir> <db-path> <model-port> <api-port> <web-port> --canonical-root <abs> [--export s:d ...] -- <cmd...>" >&2
  exit 2; }
[ -d "$CANON_ROOT" ] || { echo "canonical root missing: $CANON_ROOT" >&2; exit 2; }
case "$CANON_ROOT" in /*) ;; *) echo "canonical root must be absolute" >&2; exit 2;; esac

# snapshot live endpoint PIDs to assert untouched at teardown
LIVE_PIDS_BEFORE=""
for port in "$MODEL_PORT" "$API_PORT" "$WEB_PORT"; do
  pid="$(bash "$ROOT/scripts/find_listener_pid.sh" "$port" 2>/dev/null || true)"
  LIVE_PIDS_BEFORE="$LIVE_PIDS_BEFORE $port=$pid"
done

# --- copy repo to worktree ---
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
cp -a "$ROOT/." "$WORKDIR/" 2>/dev/null
# copy canonical evidence tree IN (pre-copy so inner F-verifiers never same-file cp)
EVDIR_REL=".omo/evidence/qwen3-learning-flow"
if [ -d "$CANON_ROOT/$EVDIR_REL" ]; then
  mkdir -p "$WORKDIR/.omo/evidence"
  cp -a "$CANON_ROOT/$EVDIR_REL" "$WORKDIR/.omo/evidence/qwen3-learning-flow"
fi
# hash of pre-existing evidence inputs (immutable-evidence invariant)
# NOTE: only files present in the BEFORE snapshot are tracked; explicitly exported
# final artifacts (baseline gate / verdicts) are ALLOWED to be newly created.
EVIDENCE_SNAPSHOT="$WORKDIR/evidence-before.sha256"
: > "$EVIDENCE_SNAPSHOT"
( cd "$CANON_ROOT" && find "$EVDIR_REL" -type f -print0 2>/dev/null | sort -z \
  | while IFS= read -r -d '' f; do printf '%s ' "$f"; sha256sum "$f"; done ) >> "$EVIDENCE_SNAPSHOT" 2>/dev/null || true

# --- start disposable API on api-port (uvicorn on the worktree copy) ---
API_PID=""
if command -v uvicorn >/dev/null 2>&1; then
  UVICORN_BIN="uvicorn"
elif [ -x /opt/venv/bin/uvicorn ]; then
  UVICORN_BIN="/opt/venv/bin/uvicorn"
else
  UVICORN_BIN=""
fi
if [ -n "$UVICORN_BIN" ]; then
  (
    cd "$WORKDIR"
    LC_DB_PATH="$DB" LC_EXTRACT_STUB=verify \
    LC_DRAIN_STATE_FILE="$WORKDIR/drain.state.json" \
    LC_DRAIN_LOCK_FILE="$WORKDIR/drain.lock" \
    LC_WRITER_COUNT_FILE="$WORKDIR/writer_count.json" \
    LC_MAINTENANCE_LOCK_FILE="$WORKDIR/maintenance.lock" \
    setsid "$UVICORN_BIN" app.main:app --host 127.0.0.1 --port "$API_PORT" \
      > "$WORKDIR/api.log" 2>&1 < /dev/null &
  )
  for i in $(seq 1 40); do
    curl -fsS --max-time 2 "http://127.0.0.1:$API_PORT/api/stats" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS --max-time 3 "http://127.0.0.1:$API_PORT/api/stats" >/dev/null 2>&1 \
    && API_PID="$(bash "$ROOT/scripts/find_listener_pid.sh" "$API_PORT" 2>/dev/null || true)" \
    && echo "DISPOSABLE_API_READY: :$API_PORT pid=$API_PID" \
    || echo "DISPOSABLE_API_WARN: :$API_PORT not ready" >&2
fi

# --- run inner command with E2E_BASE_URL + disposable env ---
RC=1
(
  cd "$WORKDIR"
  export PATH="/opt/venv/bin:$PATH"   # inner `python` resolves to the venv (jsonschema etc.)
  export LC_DB_PATH="$DB"
  export LC_EXTRACT_STUB=verify
  export E2E_BASE_URL="http://127.0.0.1:$WEB_PORT"
  export LC_API_URL="http://127.0.0.1:$API_PORT"
  export LC_DRAIN_STATE_FILE="$WORKDIR/drain.state.json"
  export LC_DRAIN_LOCK_FILE="$WORKDIR/drain.lock"
  export LC_WRITER_COUNT_FILE="$WORKDIR/writer_count.json"
  export LC_MAINTENANCE_LOCK_FILE="$WORKDIR/maintenance.lock"
  "${INNER[@]}"
)
RC=$?

# --- teardown disposable API ---
if [ -n "$API_PID" ]; then
  kill "$API_PID" 2>/dev/null || kill -9 "$API_PID" 2>/dev/null || true
  sleep 1
  bash "$ROOT/scripts/find_listener_pid.sh" "$API_PORT" >/dev/null 2>&1 \
    && { pkill -9 -f "uvicorn app.main:app.*$API_PORT" 2>/dev/null || true; sleep 1; }
fi

# --- atomic export of designated artifacts ---
if [ ${#EXPORTS[@]} -gt 0 ]; then
  EXPORT_MANIFEST="$WORKDIR/export-manifest.json"
  : > "$EXPORT_MANIFEST"
  for spec in "${EXPORTS[@]}"; do
    SRC="${spec%%:*}"; DST="${spec#*:}"
    case "$SRC" in /*) echo "EXPORT_REJECT: absolute source $SRC" >&2; RC=2; continue;; esac
    case "$SRC" in *".."*) echo "EXPORT_REJECT: traversal $SRC" >&2; RC=2; continue;; esac
    case "$DST" in "$CANON_ROOT"/*) ;; *) echo "EXPORT_REJECT: unlisted destination $DST" >&2; RC=2; continue;; esac
    [ -f "$WORKDIR/$SRC" ] || { echo "EXPORT_REJECT: missing source $WORKDIR/$SRC" >&2; RC=2; continue; }
    if [ -e "$DST" ]; then echo "EXPORT_REJECT: destination collision $DST" >&2; RC=2; continue; fi
    mkdir -p "$(dirname "$DST")"
    TMP="$DST.tmp"
    cp "$WORKDIR/$SRC" "$TMP"
    # fsync file
    /opt/venv/bin/python - "$TMP" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDWR); os.fsync(fd); os.close(fd)
PY
    os_replace() { :; }
    /opt/venv/bin/python - "$TMP" "$DST" <<'PY'
import os, sys
os.replace(sys.argv[1], sys.argv[2])
PY
    # fsync parent dir
    /opt/venv/bin/python - "$(dirname "$DST")" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDONLY); os.fsync(fd); os.close(fd)
PY
    SHA="$(sha256sum "$DST" | cut -d' ' -f1)"
    /opt/venv/bin/python - "$EXPORT_MANIFEST" "$SRC" "$DST" "$SHA" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])) if __import__("os").path.getsize(sys.argv[1]) else {}
m[sys.argv[2]] = {"destination": sys.argv[3], "sha256": sys.argv[4]}
json.dump(m, open(sys.argv[1], "w"), indent=2)
PY
    echo "EXPORT_OK: $SRC -> $DST sha256=$SHA"
  done
fi

# --- teardown invariants ---
# 1. live PIDs/ports untouched
for port in "$MODEL_PORT" "$API_PORT" "$WEB_PORT"; do
  now="$(bash "$ROOT/scripts/find_listener_pid.sh" "$port" 2>/dev/null || true)"
  before="$(echo "$LIVE_PIDS_BEFORE" | tr ' ' '\n' | grep "^$port=" | cut -d= -f2)"
  if [ -n "$before" ] && [ "$now" != "$before" ]; then
    echo "TEARDOWN_FAIL: port $port pid changed ($before -> $now)" >&2; RC=2
  fi
done
# 2. immutable evidence inputs: live tree unchanged except exported final artifacts
# (only files that existed in the BEFORE snapshot must have identical hashes now;
#  newly exported final artifacts such as baseline gate / verdicts are allowed)
EVIDENCE_AFTER="$WORKDIR/evidence-after.sha256"
: > "$EVIDENCE_AFTER"
( cd "$CANON_ROOT" && find "$EVDIR_REL" -type f -print0 2>/dev/null | sort -z \
  | while IFS= read -r -d '' f; do printf '%s ' "$f"; sha256sum "$f"; done ) >> "$EVIDENCE_AFTER" 2>/dev/null || true
# compare only the BEFORE file set
EVIDENCE_DIFF="$WORKDIR/evidence-diff.txt"
: > "$EVIDENCE_DIFF"
/opt/venv/bin/python - "$EVIDENCE_SNAPSHOT" "$EVIDENCE_AFTER" "$EVIDENCE_DIFF" <<'PY'
import sys
before = {}
for line in open(sys.argv[1], encoding="utf-8"):
    parts = line.rstrip("\n").split(" ", 1)
    if len(parts) == 2:
        before[parts[0]] = parts[1].strip()
after = {}
for line in open(sys.argv[2], encoding="utf-8"):
    parts = line.rstrip("\n").split(" ", 1)
    if len(parts) == 2:
        after[parts[0]] = parts[1].strip()
changed = [p for p in before if p in after and before[p] != after[p]]
missing = [p for p in before if p not in after]
with open(sys.argv[3], "w", encoding="utf-8") as f:
    for p in changed:
        f.write(f"CHANGED {p}\n")
    for p in missing:
        f.write(f"MISSING {p}\n")
PY
if [ -s "$EVIDENCE_DIFF" ]; then
  echo "TEARDOWN_FAIL: live evidence inputs modified:" >&2
  cat "$EVIDENCE_DIFF" >&2
  RC=2
fi

# --- teardown: remove disposable worktree ---
rm -rf "$WORKDIR" 2>/dev/null || true

exit $RC
