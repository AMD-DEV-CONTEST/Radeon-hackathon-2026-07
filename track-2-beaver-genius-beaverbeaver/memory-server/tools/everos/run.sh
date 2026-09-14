#!/bin/sh
set -eu

# Keep regular cloud HTTP(S) proxy support, but remove the non-standard
# `socks://` catch-all that httpx/OpenAI clients reject during construction.
unset ALL_PROXY all_proxy
export NO_PROXY="127.0.0.1,localhost,::1${NO_PROXY:+,${NO_PROXY}}"
export no_proxy="${NO_PROXY}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
RUNTIME_DIR=${EVEROS_RUNTIME_DIR:-"$PROJECT_ROOT/.runtime/everos"}
ENV_FILE=${EVEROS_ENV_FILE:-"$SCRIPT_DIR/everos.env"}

if [ ! -f "$ENV_FILE" ]; then
    echo "Missing $ENV_FILE; copy everos.env.example and configure provider keys." >&2
    exit 1
fi

if [ ! -x "$RUNTIME_DIR/.venv/bin/everos" ]; then
    echo "EverOS is not installed; run tools/everos/setup.sh first." >&2
    exit 1
fi

set -a
. "$ENV_FILE"
set +a

# Load explicit per-service keys from the ignored project .env.
PROJECT_ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$PROJECT_ENV_FILE" ]; then
    set -a
    . "$PROJECT_ENV_FILE"
    set +a
fi
cd "$PROJECT_ROOT"
exec "$RUNTIME_DIR/.venv/bin/everos" server start
