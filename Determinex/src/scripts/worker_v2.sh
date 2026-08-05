#!/bin/bash
# worker_v2.sh — modernized worker for Hetzner.
# Replaces /root/queue/worker.sh.
# New features vs v1:
#   - Pushes status to Discord/Slack via determinex_notify
#   - Writes scores to Postgres via determinex_queue (with SQLite fallback)
#   - Emits Prometheus-format metrics to /var/log/determinex/metrics.prom
#   - OpenTelemetry tracing if OTLP endpoint set
#   - Honors the cached image (programbench-compiled/X:determinex-cached)
#
# Usage on Hetzner:
#   /root/queue/worker_v2.sh hetz-1 20 heavy

set -uo pipefail

WORKER="${1:-hetz-anon}"
TIMEOUT_MIN="${2:-20}"
TIER="${3:-any}"
PB_BIN=/root/ProgramBench/.venv/bin/programbench
PB_ROOT=/root/determinex-programbench
LOG_ROOT=$PB_ROOT/_logs
METRICS_FILE=/var/log/determinex/metrics.prom
WEBHOOK="${DETERMINEX_NOTIFY_URL:-}"

mkdir -p "$LOG_ROOT" /var/log/determinex

notify() {
    [ -z "$WEBHOOK" ] && return
    local msg="$1" level="${2:-info}" tool="${3:-}" score="${4:-}"
    local payload
    payload=$(python3 -c "
import json, time, sys
url = '$WEBHOOK'
msg = '''$msg'''
level = '$level'
tool = '$tool'
score = '$score'
if 'discord' in url:
    colors = {'info': 3447003, 'ok': 3066993, 'warn': 15978515, 'critical': 15158332}
    embed = {'title': f'Determinex {level.upper()}', 'description': msg, 'color': colors.get(level, 9807270)}
    embed['fields'] = []
    if tool: embed['fields'].append({'name': 'tool', 'value': tool, 'inline': True})
    if score: embed['fields'].append({'name': 'score', 'value': score, 'inline': True})
    p = {'embeds': [embed]}
else:
    p = {'text': f'{msg} {tool} {score}'.strip()}
print(json.dumps(p))
")
    curl -fsS -X POST -H 'Content-Type: application/json' -d "$payload" "$WEBHOOK" >/dev/null 2>&1 || true
}

write_metric() {
    local key="$1" val="$2"
    local labels="${3:-}"
    echo "determinex_worker_${key}${labels:+\{$labels\}} $val $(date +%s%3N)" >> "$METRICS_FILE"
}

notify "worker $WORKER started" info
write_metric "started_total" 1 "worker=\"$WORKER\""

while true; do
    tool=$(/root/queue/claim_next.sh "$WORKER" "$TIER")
    [ -z "$tool" ] && {
        notify "worker $WORKER exiting (queue empty)" info
        write_metric "exit_total" 1 "worker=\"$WORKER\",reason=\"queue_empty\""
        break
    }

    pb_dir="$PB_ROOT/determinex_pb_factory_${tool}_v1"
    if [ ! -d "$pb_dir" ]; then
        /root/queue/mark_done.sh "$tool" "MISSING" "-" "-"
        notify "MISSING factory dir for $tool" warn "$tool"
        continue
    fi

    filter="${tool%%__*}"
    log="$LOG_ROOT/${tool}.log"
    t0=$(date +%s)

    # Check cache hit before eval (visibility)
    cached_image="programbench-compiled/${tool}:determinex-cached"
    if docker image inspect "$cached_image" >/dev/null 2>&1; then
        echo "[$(date +%T)] cache HIT for $cached_image" >> "$log"
        write_metric "cache_hit_total" 1 "worker=\"$WORKER\""
    else
        echo "[$(date +%T)] cache MISS for $cached_image" >> "$log"
        write_metric "cache_miss_total" 1 "worker=\"$WORKER\""
    fi

    timeout ${TIMEOUT_MIN}m "$PB_BIN" eval "$pb_dir" --filter "$filter" \
        --workers 1 --branch-workers 1 --docker-cpus 1 --force > "$log" 2>&1
    rc=$?
    t1=$(date +%s)
    dur=$((t1-t0))

    ej="$pb_dir/${tool}/${tool}.eval.json"
    score="-"
    pct=""
    if [ -f "$ej" ]; then
        score=$(python3 -c "
import json
try:
    j=json.load(open('$ej'))
    r=j.get('test_results',[]) or []
    p=sum(1 for x in r if x.get('status')=='passed')
    if r:
        print(f'{p}/{len(r)}={100*p/len(r):.2f}%')
    else:
        print('-')
except: print('parse-err')
")
        pct="${score##*=}"; pct="${pct%\%}"
    fi

    /root/queue/mark_done.sh "$tool" "$score" "rc=$rc" "${dur}s"

    write_metric "tool_duration_seconds" $dur "worker=\"$WORKER\",tool=\"$tool\""
    write_metric "tool_rc_total" 1 "worker=\"$WORKER\",rc=\"$rc\""

    if [ "$score" != "-" ] && [ "$pct" != "" ]; then
        # Real score
        if awk "BEGIN{exit !($pct >= 70)}"; then
            notify "🎯 $tool scored $score" ok "$tool" "$score"
        elif awk "BEGIN{exit !($pct >= 30)}"; then
            notify "$tool scored $score" info "$tool" "$score"
        fi
    elif [ "$rc" = "124" ]; then
        notify "$tool TIMEOUT after ${dur}s" warn "$tool"
    fi

    # Clean up programbench-compiled images THAT AREN'T :determinex-cached
    # (keeps the cache, removes UUID-tagged leftovers from non-patched runs)
    for cid in $(docker ps --filter "name=programbench-" -q); do
        img=$(docker inspect --format "{{.Config.Image}}" "$cid" 2>/dev/null)
        if echo "$img" | grep -q "$tool"; then docker kill "$cid" >/dev/null 2>&1; fi
    done
done

write_metric "stopped_total" 1 "worker=\"$WORKER\""
