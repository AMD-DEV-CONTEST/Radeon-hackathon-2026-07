#!/usr/bin/env bash
# Record the AMD DevMaster demo video against the live Radeon instance.
#
#   VULCAN_API_KEY=sk-... bash scripts/record-demo.sh
#
# The key is per-instance and only visible to a logged-in browser session, so
# it cannot be fetched from here. Grab it from the Radeon Cloud instance page.
# Everything else is derived or already committed.
set -euo pipefail

cd "$(dirname "$0")/.."

# .env is gitignored; see .env.example for the shape. Keeping the key in a
# file rather than on the command line keeps it out of shell history.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

: "${VULCAN_API_KEY:?Set VULCAN_API_KEY in .env (see .env.example) to the Radeon instance key}"

# No default: the instance id is per-launch and does not belong in the repo.
: "${VULCAN_BASE_URL:?set VULCAN_BASE_URL in .env to the current instance endpoint}"
export VULCAN_MODEL="${VULCAN_MODEL:-Qwen/Qwen3-8B}"
export VULCAN_ENABLE_THINKING="${VULCAN_ENABLE_THINKING:-false}"

# Generation on the GPU, embeddings local: a task=generate vLLM server has no
# /v1/embeddings route, and Radeon Cloud allows one active instance.
export VULCAN_EMBED_BASE_URL="${VULCAN_EMBED_BASE_URL:-http://localhost:11434/v1}"
export VULCAN_EMBED_API_KEY="${VULCAN_EMBED_API_KEY:-local}"
export VULCAN_EMBED_MODEL="${VULCAN_EMBED_MODEL:-mxbai-embed-large}"

# The tape runs `vulcan` in a fresh shell, so make the project venv win.
if [ -x ".venv/bin/vulcan" ]; then
  export PATH="$PWD/.venv/bin:$PATH"
elif ! command -v vulcan >/dev/null; then
  echo "FAILED: no vulcan binary. Run: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

echo "==> checking the Radeon endpoint"
served=$(curl -sf -m 20 "$VULCAN_BASE_URL/models" -H "Authorization: Bearer $VULCAN_API_KEY" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])') || {
  echo "FAILED: $VULCAN_BASE_URL did not answer. The instance may have been destroyed;" >&2
  echo "relaunch it and re-export VULCAN_BASE_URL and VULCAN_API_KEY." >&2
  exit 1
}
echo "    serving: $served"

echo "==> checking the embeddings endpoint"
curl -sf -m 20 "$VULCAN_EMBED_BASE_URL/models" -H "Authorization: Bearer $VULCAN_EMBED_API_KEY" >/dev/null || {
  echo "FAILED: no embeddings endpoint at $VULCAN_EMBED_BASE_URL. Start Ollama, or set" >&2
  echo "VULCAN_EMBED_BASE_URL to an embeddings-capable server." >&2
  exit 1
}
echo "    ok"

echo "==> preparing the demo repo"
[ -d "$HOME/demo-repo" ] || git clone --depth 1 https://github.com/pallets/flask "$HOME/demo-repo"

echo "==> recording (this runs the real commands, expect ~5 minutes)"
vhs scripts/demo.tape

echo
echo "==> wrote demo-raw.mp4"
ls -lh demo-raw.mp4
