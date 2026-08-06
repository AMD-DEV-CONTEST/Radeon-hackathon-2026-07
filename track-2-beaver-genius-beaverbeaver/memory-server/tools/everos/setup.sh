#!/bin/sh
set -eu

EVEROS_COMMIT="66a201e16416c3c628bb71bccba5f2da69ed5653"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$PROJECT_ROOT/.env"
    set +a
fi
RUNTIME_DIR=${EVEROS_RUNTIME_DIR:-"$PROJECT_ROOT/.runtime/everos"}
VENV_DIR="$RUNTIME_DIR/.venv"
EVEROS_ROOT=${EVEROS_ROOT:-"${MEMORY_DATA_ROOT:-$PROJECT_ROOT/.runtime}/everos"}
EVEROS_USE_POLLING_WATCHER=${EVEROS_USE_POLLING_WATCHER:-1}
EPISODE_PROMPT_SOURCE="$SCRIPT_DIR/prompt_slots/episode_extract.yaml"

mkdir -p "${MEMORY_DATA_ROOT:-$PROJECT_ROOT/.runtime}/raw-media"

if [ -e "$RUNTIME_DIR" ] && [ ! -d "$RUNTIME_DIR/.git" ]; then
    echo "EverOS runtime path exists but is not a git checkout: $RUNTIME_DIR" >&2
    exit 1
fi

if [ ! -d "$RUNTIME_DIR/.git" ]; then
    git clone --filter=blob:none https://github.com/EverMind-AI/EverOS.git "$RUNTIME_DIR"
    git -C "$RUNTIME_DIR" checkout --detach "$EVEROS_COMMIT"
else
    CURRENT_COMMIT=$(git -C "$RUNTIME_DIR" rev-parse HEAD)
    if [ "$CURRENT_COMMIT" != "$EVEROS_COMMIT" ]; then
        echo "EverOS checkout is at $CURRENT_COMMIT; expected $EVEROS_COMMIT" >&2
        exit 1
    fi
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    uv venv --python python3.12 "$VENV_DIR"
fi

# A copied project directory may carry uv's editable .pth pointing at the old
# checkout. Remove only this generated pointer so reinstall writes this repo.
for EDITABLE_PTH in "$VENV_DIR"/lib/python*/site-packages/_editable_impl_everos.pth; do
    [ -f "$EDITABLE_PTH" ] || continue
    if ! grep -F "$RUNTIME_DIR/src" "$EDITABLE_PTH" >/dev/null 2>&1; then
        rm -f "$EDITABLE_PTH"
    fi
done

uv pip install --python "$VENV_DIR/bin/python" -e "$RUNTIME_DIR[multimodal]"

for PATCH_FILE in "$SCRIPT_DIR"/patches/*.patch; do
    [ -f "$PATCH_FILE" ] || continue
    if git -C "$RUNTIME_DIR" apply --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
        continue
    fi
    git -C "$RUNTIME_DIR" apply --check "$PATCH_FILE"
    git -C "$RUNTIME_DIR" apply "$PATCH_FILE"
done

if [ -f "$EPISODE_PROMPT_SOURCE" ]; then
    install -m 0644 "$EPISODE_PROMPT_SOURCE" \
        "$RUNTIME_DIR/src/everos/config/prompt_slots/episode_extract.yaml"
fi

WATCHER_FILE="$RUNTIME_DIR/src/everos/memory/cascade/watcher.py"
if [ "$EVEROS_USE_POLLING_WATCHER" = "1" ] && [ -f "$WATCHER_FILE" ]; then
    python3 - "$WATCHER_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "from watchdog.observers import Observer"
new = "from watchdog.observers.polling import PollingObserver as Observer"
if old in text:
    path.write_text(text.replace(old, new), encoding="utf-8")
PY
fi

if [ ! -f "$EVEROS_ROOT/everos.toml" ]; then
    "$VENV_DIR/bin/everos" init --root "$EVEROS_ROOT"
fi

echo "EverOS runtime ready at $RUNTIME_DIR"
