#!/usr/bin/env bash
# Build the exact product provider used by the application before GPU model startup.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [[ -z "${PRIVATEPLATE_C0B_OUT_DIR:-}" ]]; then
  if [[ -z "${PRIVATEPLATE_RUN_ID:-}" ]]; then
    echo "PRIVATEPLATE_RUN_ID or PRIVATEPLATE_C0B_OUT_DIR is required." >&2
    exit 1
  fi
  PRIVATEPLATE_C0B_OUT_DIR="${ROOT}/benchmarks/c0/stage-b/${PRIVATEPLATE_RUN_ID}"
fi
ENVIRONMENT_PATH="${PRIVATEPLATE_C0B_OUT_DIR}/environment.json"
cd "${ROOT}"

node scripts/c0/stage-b/source-integrity.mjs \
  verify-environment \
  "${ROOT}" \
  "${ENVIRONMENT_PATH}" >/dev/null

if [[ ! -f package-lock.json ]]; then
  echo "package-lock.json is required to build the product provider reproducibly." >&2
  exit 1
fi

if [[ ! -d node_modules/zod ]] || [[ ! -x node_modules/.bin/tsc ]]; then
  echo "Installing locked Node dependencies for the product provider..."
  npm ci
fi

echo "Building product contracts, domain types and agent provider..."
npm run build -w @privateplate/contracts
npm run build -w @privateplate/domain
npm run build -w @privateplate/agent-runtime

PROVIDER_MODULE="${ROOT}/packages/agent-runtime/dist/model/provider.js"
TOOL_MODULE="${ROOT}/packages/agent-runtime/dist/model/tool-definitions.js"
if [[ ! -f "${PROVIDER_MODULE}" ]] || [[ ! -f "${TOOL_MODULE}" ]]; then
  echo "Compiled product provider or tool definitions are missing after build." >&2
  exit 1
fi

node -e 'const { pathToFileURL } = await import("node:url"); await import(pathToFileURL(process.argv[1]).href); await import(pathToFileURL(process.argv[2]).href);' \
  "${PROVIDER_MODULE}" "${TOOL_MODULE}"
node scripts/c0/stage-b/source-integrity.mjs \
  verify-environment \
  "${ROOT}" \
  "${ENVIRONMENT_PATH}" >/dev/null
echo "Compiled product provider is ready."
