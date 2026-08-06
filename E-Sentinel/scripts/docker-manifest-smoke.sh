#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_PATH="${ROOT_DIR}/deploy/dify-openai-adapter/manifest.json"

command -v jq >/dev/null 2>&1 || {
  echo "docker manifest smoke: jq is required" >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "docker manifest smoke: python3 is required" >&2
  exit 1
}

schema_version="$(jq -er '.schemaVersion | numbers' "$MANIFEST_PATH")"
[[ "$schema_version" == "1" ]] || {
  echo "docker manifest smoke: unsupported schemaVersion ${schema_version}" >&2
  exit 1
}

context_rel="$(jq -er '.context | strings' "$MANIFEST_PATH")"
dockerfile_rel="$(jq -er '.dockerfile | strings' "$MANIFEST_PATH")"
port="$(jq -er '.port | numbers' "$MANIFEST_PATH")"
health_path="$(jq -er '.healthPath | strings' "$MANIFEST_PATH")"
image_repo="$(jq -er '.image | strings' "$MANIFEST_PATH")"

case "$context_rel" in
  /*|../*|*/../*|*'/.'*)
    echo "docker manifest smoke: context escapes repository: ${context_rel}" >&2
    exit 1
    ;;
esac
case "$dockerfile_rel" in
  /*|../*|*/../*|*'/.'*)
    echo "docker manifest smoke: Dockerfile escapes context: ${dockerfile_rel}" >&2
    exit 1
    ;;
esac

context_dir="${ROOT_DIR}/${context_rel}"
dockerfile_path="${context_dir}/${dockerfile_rel}"
test -d "$context_dir"
test -f "$dockerfile_path"

while IFS= read -r required_file; do
  case "$required_file" in
    /*|../*|*/../*|*'/.'*)
      echo "docker manifest smoke: required file escapes context: ${required_file}" >&2
      exit 1
      ;;
  esac
  test -f "${context_dir}/${required_file}"
done < <(jq -er '.requiredFiles[] | strings' "$MANIFEST_PATH")

grep -Eq "^[[:space:]]*EXPOSE[[:space:]]+${port}([[:space:]]|$)" "$dockerfile_path"
grep -Eq "^[[:space:]]*HEALTHCHECK.*${health_path}" "$dockerfile_path"
grep -Eq '^[[:space:]]*USER[[:space:]]+appuser([[:space:]]|$)' "$dockerfile_path"
grep -Eq '^[[:space:]]*CMD[[:space:]].*python' "$dockerfile_path"
python3 -m py_compile "${context_dir}/app.py"

if ! docker info >/dev/null 2>&1; then
  if [[ "${REQUIRE_DOCKER_BUILD:-false}" == "true" ]]; then
    echo "docker manifest smoke: Docker daemon is required in this environment" >&2
    exit 1
  fi
  echo "docker manifest smoke: static checks passed; Docker daemon unavailable, build skipped"
  exit 0
fi

image_tag="${DOCKER_IMAGE_TAG:-${image_repo}:smoke-${GITHUB_SHA:-local}}"
container_id=""
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker rm -f "$container_id" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker build --file "$dockerfile_path" --tag "$image_tag" "$context_dir"
container_id="$(docker run --detach --publish 127.0.0.1::${port} "$image_tag")"
host_port="$(docker port "$container_id" "${port}/tcp" | sed -E 's/.*:([0-9]+)$/\1/')"

for attempt in $(seq 1 30); do
  if response="$(curl --fail --silent "http://127.0.0.1:${host_port}${health_path}")"; then
    RESPONSE="$response" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE"])
if payload.get("status") != "ok":
    raise SystemExit(f"unexpected health response: {payload!r}")
PY
    echo "docker manifest smoke passed: ${image_tag}"
    exit 0
  fi
  sleep 1
done

echo "docker manifest smoke: health endpoint did not become ready" >&2
docker logs "$container_id" >&2 || true
exit 1
