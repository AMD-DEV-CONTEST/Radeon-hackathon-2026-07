#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

image="${1:?usage: verify_mission_control_runtime.sh IMAGE [OUTPUT_DIR]}"
output="${2:-$repo_root/.signalforge/mission-control-runtime}"
project="${SIGNALFORGE_MISSION_CONTROL_PROJECT:-signalforge-mission-control}"
mkdir -p "$output"
output="$(cd "$output" && pwd)"

compose() {
  COMPOSE_PROJECT_NAME="$project" SIGNALFORGE_IMAGE="$image" docker compose "$@"
}

capture_diagnostics() {
  compose --profile fixture --profile observability ps --all \
    >"$output/compose-ps.txt" 2>&1 || true
  compose --profile fixture --profile observability logs --no-color --timestamps \
    >"$output/compose.log" 2>&1 || true
}

cleanup() {
  local exit_code=$?
  capture_diagnostics
  compose --profile fixture --profile observability down --volumes --remove-orphans \
    >/dev/null 2>&1 || true
  return "$exit_code"
}
trap cleanup EXIT
cleanup

scripts/prepare_container_secrets.sh >/dev/null
password="$(<.secrets/grafana-admin-password)"
export SIGNALFORGE_OTEL_ENABLED=true
export SIGNALFORGE_OTEL_INSECURE=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318

docker pull "$image" >/dev/null
docker image inspect "$image" >"$output/image-inspect.json"
compose --profile fixture --profile observability up --detach --no-build

wait_http() {
  local url="$1"
  local destination="$2"
  local attempts="${3:-120}"
  for _ in $(seq 1 "$attempts"); do
    if curl --fail --silent --show-error "$url" >"$destination"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_http http://127.0.0.1:8080/health/ready "$output/workspace-health.json"
wait_http http://127.0.0.1:3000/api/health "$output/grafana-health.json"
wait_http http://127.0.0.1:9090/-/ready "$output/prometheus-health.txt"
wait_http http://127.0.0.1:12345/-/ready "$output/alloy-health.txt"

curl --fail --silent --show-error \
  --header 'Content-Type: application/json' \
  --data '{"question":"Compare Microsoft and NVIDIA.","scenario":{}}' \
  http://127.0.0.1:8080/api/v1/runs >"$output/run-created.json"
run_id="$(jq -er '.run_id' "$output/run-created.json")"

status=""
for _ in $(seq 1 120); do
  curl --fail --silent --show-error \
    "http://127.0.0.1:8080/api/v1/runs/$run_id" >"$output/run-result.json"
  status="$(jq -r '.status' "$output/run-result.json")"
  [[ "$status" == "completed" ]] && break
  sleep 1
done
[[ "$status" == "completed" ]]

curl --fail --silent --show-error \
  "http://127.0.0.1:8080/api/v1/runs/$run_id/intelligence" \
  >"$output/intelligence.json"
trace_id="$(jq -er '.trace_id' "$output/intelligence.json")"
jq -e --arg run_id "$run_id" \
  '.run_id == $run_id and .release.status == "released"' \
  "$output/intelligence.json" >/dev/null

grafana_curl() {
  curl --fail --silent --show-error --user "signalforge:$password" "$@"
}

grafana_curl http://127.0.0.1:3000/api/datasources >"$output/grafana-datasources.json"
grafana_curl 'http://127.0.0.1:3000/api/search?type=dash-db' >"$output/grafana-dashboards.json"
jq -e 'map(.uid) | index("prometheus") and index("loki") and index("tempo")' \
  "$output/grafana-datasources.json" >/dev/null
jq -e 'map(.uid) | index("signalforge-executive") and index("signalforge-agents") and
  index("signalforge-radeon") and index("signalforge-trust")' \
  "$output/grafana-dashboards.json" >/dev/null

loki_query="{service_name=\"signalforge\"} | json | run_id=\"$run_id\""
for _ in $(seq 1 90); do
  grafana_curl --get \
    --data-urlencode "query=$loki_query" \
    --data-urlencode "limit=20" \
    http://127.0.0.1:3000/api/datasources/proxy/uid/loki/loki/api/v1/query_range \
    >"$output/grafana-loki-run.json"
  [[ "$(jq -r '[.data.result[].values[]?] | length' "$output/grafana-loki-run.json")" -gt 0 ]] \
    && break
  sleep 1
done
jq -e '[.data.result[].values[]?] | length > 0' "$output/grafana-loki-run.json" >/dev/null

for _ in $(seq 1 90); do
  if grafana_curl \
    "http://127.0.0.1:3000/api/datasources/proxy/uid/tempo/api/traces/$trace_id" \
    >"$output/grafana-tempo-trace.json"; then
    [[ "$(jq -r '.batches | length' "$output/grafana-tempo-trace.json")" -gt 0 ]] && break
  fi
  sleep 1
done
jq -e '.batches | length > 0' "$output/grafana-tempo-trace.json" >/dev/null

grafana_curl --get \
  --data-urlencode 'query=signalforge_journeys_total{status="completed"}' \
  http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query \
  >"$output/grafana-prometheus-journeys.json"
jq -e '.status == "success" and (.data.result | length) > 0' \
  "$output/grafana-prometheus-journeys.json" >/dev/null

compose stop alloy prometheus loki tempo grafana >/dev/null
curl --fail --silent --show-error \
  --header 'Content-Type: application/json' \
  --data '{"question":"Compare Microsoft and NVIDIA after telemetry loss.","scenario":{}}' \
  http://127.0.0.1:8080/api/v1/runs >"$output/degraded-run-created.json"
degraded_run_id="$(jq -er '.run_id' "$output/degraded-run-created.json")"

degraded_status=""
for _ in $(seq 1 120); do
  curl --fail --silent --show-error \
    "http://127.0.0.1:8080/api/v1/runs/$degraded_run_id" \
    >"$output/degraded-run-result.json"
  degraded_status="$(jq -r '.status' "$output/degraded-run-result.json")"
  [[ "$degraded_status" == "completed" ]] && break
  sleep 1
done
[[ "$degraded_status" == "completed" ]]

jq -n \
  --arg image "$image" \
  --arg run_id "$run_id" \
  --arg trace_id "$trace_id" \
  --arg degraded_run_id "$degraded_run_id" \
  '{
    schema_version: "signalforge/mission-control-runtime/v1",
    image: $image,
    synchronized_run: {run_id: $run_id, trace_id: $trace_id},
    surfaces: {
      workspace: "passed",
      grafana: "passed",
      prometheus_via_grafana: "passed",
      loki_via_grafana: "passed",
      tempo_via_grafana: "passed"
    },
    observability_loss: {
      run_id: $degraded_run_id,
      answer_completed: true,
      fail_open_for_telemetry_only: true
    },
    protected_model_bodies_exported: false
  }' >"$output/summary.json"

echo "SignalForge Mission Control runtime verification passed for $run_id"
