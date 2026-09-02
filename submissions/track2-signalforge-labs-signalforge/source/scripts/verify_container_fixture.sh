#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

image="${SIGNALFORGE_TEST_IMAGE:-signalforge:fixture-check}"
container="signalforge-fixture-check-$$"
volume="signalforge-fixture-check-$$"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ "${SIGNALFORGE_SKIP_BUILD:-0}" != "1" ]]; then
  docker build \
    --platform linux/amd64 \
    --build-arg "SOURCE_COMMIT=$(git rev-parse --verify HEAD)" \
    --tag "$image" .
else
  docker pull "$image"
fi

architecture="$(docker image inspect "$image" --format '{{.Architecture}}/{{.Os}}')"
[[ "$architecture" == "amd64/linux" ]] || {
  echo "Unexpected image architecture: $architecture" >&2
  exit 1
}

license_label="$(docker image inspect "$image" \
  --format '{{ index .Config.Labels "org.opencontainers.image.licenses" }}')"
source_label="$(docker image inspect "$image" \
  --format '{{ index .Config.Labels "org.opencontainers.image.source" }}')"
revision_label="$(docker image inspect "$image" \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
version_label="$(docker image inspect "$image" \
  --format '{{ index .Config.Labels "org.opencontainers.image.version" }}')"

[[ "$license_label" == "Apache-2.0" ]]
[[ "$source_label" == "https://github.com/rvbernucci/signalforge" ]]
expected_revision="${SIGNALFORGE_EXPECTED_SOURCE_COMMIT:-$(git rev-parse --verify HEAD)}"
[[ "$revision_label" == "$expected_revision" ]] || {
  echo "Unexpected OCI revision: $revision_label" >&2
  exit 1
}
if [[ -n "${SIGNALFORGE_EXPECTED_VERSION:-}" ]]; then
  [[ "$version_label" == "$SIGNALFORGE_EXPECTED_VERSION" ]] || {
    echo "Unexpected OCI version: $version_label" >&2
    exit 1
  }
fi

docker volume create "$volume" >/dev/null
docker run -d \
  --name "$container" \
  --network none \
  --read-only \
  --tmpfs /tmp:size=64m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --volume "$volume:/var/lib/signalforge" \
  "$image" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$container" wget -q -O /tmp/health.json http://127.0.0.1:8080/health/ready; then
    break
  fi
  sleep 1
done

health="$(docker exec "$container" cat /tmp/health.json)"
jq -e '.status == "ready" and .mode == "fixture" and .dependencies.model_runtime == "not_required"' <<<"$health" >/dev/null

docker exec "$container" sh -ec '
  cd /app/licenses
  test -r project/LICENSE
  test -r project/NOTICE
  test -r project/THIRD_PARTY_NOTICES.md
  test -r fonts/ibm-plex-mono/OFL-1.1.txt
  test -r fonts/newsreader/OFL-1.1.txt
  test -r GO_MODULES.tsv
  test "$(wc -l < GO_MODULES.tsv)" -ge 30
  sha256sum -c SHA256SUMS >/dev/null
'

run_view="$(docker exec "$container" wget -q -O - \
  --header='Content-Type: application/json' \
  --post-data='{"question":"Compare Microsoft and NVIDIA.","scenario":{}}' \
  http://127.0.0.1:8080/api/v1/runs)"
run_id="$(jq -er '.run_id' <<<"$run_view")"

for _ in $(seq 1 30); do
  result="$(docker exec "$container" wget -q -O - "http://127.0.0.1:8080/api/v1/runs/$run_id")"
  [[ "$(jq -r '.status' <<<"$result")" == "completed" ]] && break
  sleep 1
done
jq -e '.status == "completed" and .result.status == "completed"' <<<"$result" >/dev/null

lineage="$(docker exec "$container" wget -q -O - "http://127.0.0.1:8080/api/v1/runs/$run_id/intelligence")"
jq -e '.schema_version == "signalforge/intelligence-lineage/v1" and .capture.status == "disabled" and .release.status == "released"' <<<"$lineage" >/dev/null

metrics="$(docker exec "$container" wget -q -O - http://127.0.0.1:8080/metrics)"
grep -q '^signalforge_journeys_total' <<<"$metrics"

if grep -R -E 'FIREWORKS_API_KEY|hf_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9_-]{20,}' \
  Dockerfile compose.yaml deploy container.env.example; then
  echo "Potential credential embedded in container configuration" >&2
  exit 1
fi

echo "SignalForge linux/amd64 fixture image passed network-disabled clean-room verification"
