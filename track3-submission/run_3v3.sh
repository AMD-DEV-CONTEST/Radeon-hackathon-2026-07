#!/usr/bin/env bash
# Launch a distributed 3v3 match: 3 ONNX agents vs 3 rule-based agents.
# Usage: bash run_3v3.sh [onnx_path] [duration] [max_steps]
set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-/opt/venv/bin/python}"
ONNX_INPUT="${1:-models/chase_v8_policy.onnx}"
DURATION="${2:-25}"
MAX_STEPS="${3:-}"
PORT="${PORT:-9878}"
SYNC_HZ="${SYNC_HZ:-2}"

# TOTAL_TIMEOUT is a wall-clock deadline for the whole launcher, including
# worker startup.  It prevents coordinator's long accept timeout from
# turning a failed worker into a 600-second hang.
TOTAL_TIMEOUT="${TOTAL_TIMEOUT:-300}"
STARTUP_WAIT="${STARTUP_WAIT:-1}"
ALLOW_MAX_STEPS_EARLY_EXIT="${ALLOW_MAX_STEPS_EARLY_EXIT:-0}"

case "$ONNX_INPUT" in
    *.onnx) ;;
    *)
        echo "ERROR: the model argument must be a .onnx file: $ONNX_INPUT" >&2
        exit 2
        ;;
esac

if [[ "$ONNX_INPUT" = /* ]]; then
    ONNX="$ONNX_INPUT"
else
    ONNX="$SCRIPT_DIR/$ONNX_INPUT"
fi

if [[ ! -f "$ONNX" ]]; then
    echo "ERROR: ONNX model not found: $ONNX" >&2
    exit 2
fi

WALK_MODEL="$SCRIPT_DIR/models/pretrained/t1_walk.pt"
if [[ ! -f "$WALK_MODEL" ]]; then
    echo "ERROR: pretrained low-level walk model not found: $WALK_MODEL" >&2
    exit 2
fi

if ! [[ "$DURATION" =~ ^[0-9]+([.][0-9]+)?$ ]] || \
   ! awk -v value="$DURATION" 'BEGIN { exit !(value > 0) }'; then
    echo "ERROR: duration must be a positive number: $DURATION" >&2
    exit 2
fi

if ! [[ "$TOTAL_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: TOTAL_TIMEOUT must be a positive integer: $TOTAL_TIMEOUT" >&2
    exit 2
fi
if ! [[ "$STARTUP_WAIT" =~ ^[0-9]+([.][0-9]+)?$ ]] || \
   ! awk -v value="$STARTUP_WAIT" 'BEGIN { exit !(value >= 0) }'; then
    echo "ERROR: STARTUP_WAIT must be a non-negative number: $STARTUP_WAIT" >&2
    exit 2
fi
if ! [[ "$SYNC_HZ" =~ ^[0-9]+([.][0-9]+)?$ ]] || \
   ! awk -v value="$SYNC_HZ" 'BEGIN { exit !(value > 0) }'; then
    echo "ERROR: SYNC_HZ must be a positive number: $SYNC_HZ" >&2
    exit 2
fi
if [[ "$ALLOW_MAX_STEPS_EARLY_EXIT" != 0 && "$ALLOW_MAX_STEPS_EARLY_EXIT" != 1 ]]; then
    echo "ERROR: ALLOW_MAX_STEPS_EARLY_EXIT must be 0 or 1" >&2
    exit 2
fi
if [[ -n "$MAX_STEPS" && ! "$MAX_STEPS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: max_steps must be a positive integer: $MAX_STEPS" >&2
    exit 2
fi

STARTUP_WAIT_EFFECTIVE="$STARTUP_WAIT"
if awk -v startup="$STARTUP_WAIT" -v timeout="$TOTAL_TIMEOUT" \
    'BEGIN { exit !(startup > timeout) }'; then
    STARTUP_WAIT_EFFECTIVE="$TOTAL_TIMEOUT"
fi

cd "$SCRIPT_DIR"
mkdir -p match_logs

RUN_ID="${PPID}_$$"
COORD_STATUS_FILE="/tmp/track3_coord_${RUN_ID}.status"
COORD_CHILD_PID_FILE="/tmp/track3_coord_${RUN_ID}.pid"
WORKER_PIDS=()
WORKER_STATUSES=()
WORKER_STATUS_FILES=()
WORKER_CHILD_PID_FILES=()
WORKER_SEEN=()
for i in 0 1 2 3 4 5; do
    WORKER_STATUS_FILES[$i]="/tmp/track3_worker_${RUN_ID}_${i}.status"
    WORKER_CHILD_PID_FILES[$i]="/tmp/track3_worker_${RUN_ID}_${i}.pid"
    rm -f "${WORKER_STATUS_FILES[$i]}" "${WORKER_CHILD_PID_FILES[$i]}"
    WORKER_SEEN[$i]=0
done
rm -f "$COORD_STATUS_FILE" "$COORD_CHILD_PID_FILE"

echo "============================================"
echo "  3v3 Match: 3 ONNX agents vs 3 rule agents"
echo "============================================"
echo "  ONNX: $ONNX"
echo "  Low-level walk model: $WALK_MODEL"
echo "  Duration: ${DURATION}s"
if [[ -n "$MAX_STEPS" ]]; then
    echo "  Worker max steps: $MAX_STEPS"
    if [[ "$ALLOW_MAX_STEPS_EARLY_EXIT" -eq 1 ]]; then
        echo "  Max-step early exit: explicitly allowed (test mode)"
    else
        echo "  Max-step early exit: incomplete match"
    fi
else
    echo "  Worker max steps: coordinator MSG_END"
fi
echo "  Total timeout: ${TOTAL_TIMEOUT}s"
echo "  Port: $PORT"
echo "  Coordinator sync: ${SYNC_HZ}Hz"
echo "  Python: $PYTHON"
echo ""

kill_pid_file() {
    local pid_file="$1"
    local status_file="$2"
    local signal_name="$3"
    local child_pid=""
    [[ -f "$status_file" ]] && return 0
    [[ -f "$pid_file" ]] || return 0
    child_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ "$child_pid" =~ ^[0-9]+$ ]]; then
        kill -"$signal_name" "$child_pid" 2>/dev/null || true
    fi
}

stop_all_components() {
    local i
    # Stop the Python children first, then their waiting wrapper shells.
    kill_pid_file "$COORD_CHILD_PID_FILE" "$COORD_STATUS_FILE" TERM
    for i in 0 1 2 3 4 5; do
        kill_pid_file "${WORKER_CHILD_PID_FILES[$i]}" "${WORKER_STATUS_FILES[$i]}" TERM
    done
    if [[ -n "${COORD_PID:-}" && ! -f "$COORD_STATUS_FILE" ]]; then
        kill -TERM "$COORD_PID" 2>/dev/null || true
    fi
    for i in 0 1 2 3 4 5; do
        [[ -n "${WORKER_PIDS[$i]:-}" && ! -f "${WORKER_STATUS_FILES[$i]}" ]] || continue
        kill -TERM "${WORKER_PIDS[$i]}" 2>/dev/null || true
    done

    # Give wrapper traps time to forward TERM and reap their children.
    sleep 0.2

    # A child that ignores TERM must not survive the launcher deadline.
    kill_pid_file "$COORD_CHILD_PID_FILE" "$COORD_STATUS_FILE" KILL
    for i in 0 1 2 3 4 5; do
        kill_pid_file "${WORKER_CHILD_PID_FILES[$i]}" "${WORKER_STATUS_FILES[$i]}" KILL
    done
    if [[ -n "${COORD_PID:-}" && ! -f "$COORD_STATUS_FILE" ]]; then
        kill -KILL "$COORD_PID" 2>/dev/null || true
    fi
    for i in 0 1 2 3 4 5; do
        [[ -n "${WORKER_PIDS[$i]:-}" && ! -f "${WORKER_STATUS_FILES[$i]}" ]] || continue
        kill -KILL "${WORKER_PIDS[$i]}" 2>/dev/null || true
    done
}

wait_for_child() {
    local child_pid="$1"
    local wait_status=0
    while :; do
        if wait "$child_pid"; then
            return 0
        else
            wait_status=$?
        fi
        # A signal can interrupt wait while the child is still alive. Keep
        # the pidfile until it is genuinely reaped so cleanup can escalate.
        if ! kill -0 "$child_pid" 2>/dev/null; then
            return "$wait_status"
        fi
    done
}

CLEANUP_DONE=0
cleanup_children() {
    [[ "$CLEANUP_DONE" -eq 0 ]] || return 0
    CLEANUP_DONE=1
    stop_all_components
}

on_signal() {
    local exit_code="$1"
    cleanup_children
    trap - INT TERM
    exit "$exit_code"
}

on_exit() {
    local exit_code=$?
    trap - EXIT
    cleanup_children
    rm -f "$COORD_STATUS_FILE" "$COORD_CHILD_PID_FILE" \
        "${COORD_CHILD_PID_FILE}.tmp" \
        "${WORKER_STATUS_FILES[@]}" "${WORKER_CHILD_PID_FILES[@]}"
    for i in 0 1 2 3 4 5; do
        rm -f "${WORKER_STATUS_FILES[$i]}.tmp" "${WORKER_CHILD_PID_FILES[$i]}.tmp"
    done
    exit "$exit_code"
}

trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap on_exit EXIT

WORKER_MAX_STEPS_ARGS=()
if [[ -n "$MAX_STEPS" ]]; then
    WORKER_MAX_STEPS_ARGS=(--max-steps "$MAX_STEPS")
fi

start_coordinator() {
    (
        rc=0
        child_pid=""
        interrupted=0
        forward_signal() {
            interrupted=1
            [[ -n "${child_pid:-}" ]] && kill -TERM "$child_pid" 2>/dev/null || true
        }
        trap forward_signal INT TERM
        "$PYTHON" "$SCRIPT_DIR/match_coordinator.py" \
            --port "$PORT" --duration "$DURATION" --n-teams 2 --sync-hz "$SYNC_HZ" \
            > /tmp/coord.log 2>&1 &
        child_pid=$!
        printf '%s\n' "$child_pid" > "${COORD_CHILD_PID_FILE}.tmp"
        mv -f "${COORD_CHILD_PID_FILE}.tmp" "$COORD_CHILD_PID_FILE"
        if [[ "$interrupted" -ne 0 ]]; then
            kill -TERM "$child_pid" 2>/dev/null || true
            exit 143
        fi
        wait_for_child "$child_pid" || rc=$?
        trap - INT TERM
        rm -f "$COORD_CHILD_PID_FILE"
        printf '%s\n' "$rc" > "${COORD_STATUS_FILE}.tmp"
        mv -f "${COORD_STATUS_FILE}.tmp" "$COORD_STATUS_FILE"
        exit "$rc"
    ) &
    COORD_PID=$!
}

start_worker() {
    local index="$1"
    shift
    (
        rc=0
        child_pid=""
        interrupted=0
        forward_signal() {
            interrupted=1
            [[ -n "${child_pid:-}" ]] && kill -TERM "$child_pid" 2>/dev/null || true
        }
        trap forward_signal INT TERM
        "$PYTHON" "$SCRIPT_DIR/match_worker.py" "$@" \
            >"/tmp/worker_${index}.log" 2>&1 &
        child_pid=$!
        printf '%s\n' "$child_pid" > "${WORKER_CHILD_PID_FILES[$index]}.tmp"
        mv -f "${WORKER_CHILD_PID_FILES[$index]}.tmp" "${WORKER_CHILD_PID_FILES[$index]}"
        if [[ "$interrupted" -ne 0 ]]; then
            kill -TERM "$child_pid" 2>/dev/null || true
            exit 143
        fi
        wait_for_child "$child_pid" || rc=$?
        trap - INT TERM
        rm -f "${WORKER_CHILD_PID_FILES[$index]}"
        printf '%s\n' "$rc" > "${WORKER_STATUS_FILES[$index]}.tmp"
        mv -f "${WORKER_STATUS_FILES[$index]}.tmp" "${WORKER_STATUS_FILES[$index]}"
        exit "$rc"
    ) &
    WORKER_PIDS[$index]=$!
}

deadline_start=$SECONDS
start_coordinator
echo "Coordinator PID: $COORD_PID"
sleep "$STARTUP_WAIT_EFFECTIVE"

# Team A (left, attacks +x): all three workers run the ONNX policy.
start_worker 0 --role A_attacker --has-ball --port "$PORT" --onnx "$ONNX" \
    --init-pos 1.0 0.0 0.7 "${WORKER_MAX_STEPS_ARGS[@]}"
start_worker 1 --role A_defender --port "$PORT" --onnx "$ONNX" \
    --init-pos -1.0 1.5 0.7 "${WORKER_MAX_STEPS_ARGS[@]}"
start_worker 2 --role A_keeper --port "$PORT" --onnx "$ONNX" \
    --init-pos -5.0 0.0 0.7 "${WORKER_MAX_STEPS_ARGS[@]}"

# Team B (right, attacks -x): all three workers use the rule policy.
start_worker 3 --role B_attacker --port "$PORT" \
    --init-pos -1.0 -1.0 0.7 "${WORKER_MAX_STEPS_ARGS[@]}"
start_worker 4 --role B_defender --port "$PORT" \
    --init-pos 3.5 -1.5 0.7 "${WORKER_MAX_STEPS_ARGS[@]}"
start_worker 5 --role B_keeper --port "$PORT" \
    --init-pos 5.5 0.0 0.7 "${WORKER_MAX_STEPS_ARGS[@]}"

monitor_start="$deadline_start"
coord_seen=0
coord_status=0
failure_reason=""

while [[ -z "$failure_reason" ]]; do
    now=$SECONDS

    if [[ "$coord_seen" -eq 0 && -f "$COORD_STATUS_FILE" ]]; then
        candidate="$(cat "$COORD_STATUS_FILE" 2>/dev/null || true)"
        if [[ "$candidate" =~ ^[0-9]+$ ]]; then
            coord_status="$candidate"
            coord_seen=1
        fi
    fi

    for i in 0 1 2 3 4 5; do
        if [[ "${WORKER_SEEN[$i]}" -eq 0 && -f "${WORKER_STATUS_FILES[$i]}" ]]; then
            candidate="$(cat "${WORKER_STATUS_FILES[$i]}" 2>/dev/null || true)"
            if [[ "$candidate" =~ ^[0-9]+$ ]]; then
                WORKER_STATUSES[$i]="$candidate"
                WORKER_SEEN[$i]=1
                if [[ "$candidate" -ne 0 && \
                      ! ("$candidate" -eq 3 && "$ALLOW_MAX_STEPS_EARLY_EXIT" -eq 1 && -n "$MAX_STEPS") ]]; then
                    failure_reason="worker $i exited with status $candidate"
                    break
                fi
            fi
        fi
    done

    if [[ -z "$failure_reason" && "$coord_seen" -eq 1 && "$coord_status" -ne 0 ]]; then
        failure_reason="coordinator exited with status $coord_status"
    fi

    if [[ -z "$failure_reason" && "$coord_seen" -eq 1 ]]; then
        all_workers_seen=1
        for i in 0 1 2 3 4 5; do
            [[ "${WORKER_SEEN[$i]}" -eq 1 ]] || all_workers_seen=0
        done
        if [[ "$all_workers_seen" -eq 1 ]]; then
            break
        fi
    fi

    elapsed=$((now - monitor_start))
    if [[ -z "$failure_reason" ]] && (( elapsed >= TOTAL_TIMEOUT )); then
        failure_reason="launcher deadline exceeded (${TOTAL_TIMEOUT}s)"
        break
    fi
    sleep 1
done

if [[ -n "$failure_reason" ]]; then
    echo "ERROR: $failure_reason" >&2
    stop_all_components
fi

if wait "$COORD_PID"; then
    waited_coord_status=0
else
    waited_coord_status=$?
fi
coord_status="$waited_coord_status"

worker_failure_count=0
for i in 0 1 2 3 4 5; do
    status=0
    if wait "${WORKER_PIDS[$i]}"; then
        status=0
    else
        status=$?
    fi
    WORKER_STATUSES[$i]="$status"
    if [[ "$status" -ne 0 && \
          ! ("$status" -eq 3 && "$ALLOW_MAX_STEPS_EARLY_EXIT" -eq 1 && -n "$MAX_STEPS") ]]; then
        worker_failure_count=$((worker_failure_count + 1))
    fi
done

echo "=== SUMMARY ==="
for i in 0 1 2 3 4 5; do
    echo "--- Worker $i (exit ${WORKER_STATUSES[$i]}) ---"
    grep -E 'step|Finished|Incomplete|Connected|END|ERROR' "/tmp/worker_${i}.log" 2>/dev/null | tail -5 || true
done
echo "=== COORDINATOR (exit $coord_status) ==="
cat /tmp/coord.log
echo "=== LOG FILES ==="
ls -lh match_logs/ 2>/dev/null || true

if [[ -n "$failure_reason" || "$coord_status" -ne 0 || "$worker_failure_count" -ne 0 ]]; then
    echo "=== FAILED: coordinator or worker exited non-zero/incomplete ===" >&2
    exit 1
fi

echo "=== SUCCESS: coordinator and all 6 workers exited cleanly ==="
