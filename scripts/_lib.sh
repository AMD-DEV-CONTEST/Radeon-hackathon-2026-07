#!/bin/bash
# scripts/_lib.sh — shared utility function library: step timing, heartbeat monitoring, status query, elapsed-time summary
#
# Usage: source scripts/_lib.sh
#
# Provided functions:
#   step_start "step name" ["estimated time"]   — start timing, print start time and estimated time
#   step_end                                     — end timing, print actual elapsed time and estimate deviation
#   pip_install_watch <cmd>                      — pip install with heartbeat monitoring (no timeout kill)
#   run_watch <cmd> <desc>                       — run any command with heartbeat monitoring (no timeout kill)
#   monitor_check                                — query current monitoring status + last 10 log lines
#   script_total_time                            — return the script total elapsed-time string
#   script_summary                               — print the elapsed-time summary table of all steps
#   estimate_total <min> <max> [desc]            — print the script estimated total-time range
#
# How to query (in another terminal):
#   source scripts/_lib.sh && monitor_check

# ── global variables ──
_STEP_START_TIME=""
_STEP_NAME=""
_STEP_ESTIMATE=""
_SCRIPT_START_TIME=$(date +%s)

# monitor status file (fixed path, convenient for querying from another terminal)
MONITOR_STATUS_FILE="/tmp/rag_monitor_status.txt"
MONITOR_LOG_TAIL_FILE="/tmp/rag_monitor_tail.txt"

# step elapsed-time record array (for the final summary)
declare -a _SUMMARY_NAMES=()
declare -a _SUMMARY_TIMES=()
declare -a _SUMMARY_ESTIMATES=()
declare -a _SUMMARY_STATUS=()

# ── step timing ──
# Usage: step_start "Step 1: create virtual environment" "estimated <30s"
#        step_start "Step 3: install vLLM" "estimated 5-15 min"
step_start() {
    _STEP_NAME="$1"
    _STEP_ESTIMATE="${2:-unknown}"
    _STEP_START_TIME=$(date +%s)
    local now=$(date '+%Y-%m-%d %H:%M:%S')
    echo ""
    echo "┌──────────────────────────────────────────────────────────"
    echo "│ [$now] START: $_STEP_NAME"
    echo "│ Estimated time: $_STEP_ESTIMATE"
    echo "└──────────────────────────────────────────────────────────"
}

step_end() {
    local now_epoch=$(date +%s)
    local now=$(date '+%Y-%m-%d %H:%M:%S')
    local elapsed=$((now_epoch - _STEP_START_TIME))
    local mins=$((elapsed / 60))
    local secs=$((elapsed % 60))
    local time_str="${mins}m ${secs}s"

    echo ""
    echo "┌──────────────────────────────────────────────────────────"
    echo "│ [$now] DONE: $_STEP_NAME"
    echo "│ Actual time: $time_str  (estimate: $_STEP_ESTIMATE)"
    echo "└──────────────────────────────────────────────────────────"

    # record into the summary array
    _SUMMARY_NAMES+=("$_STEP_NAME")
    _SUMMARY_TIMES+=("$time_str")
    _SUMMARY_ESTIMATES+=("$_STEP_ESTIMATE")
    _SUMMARY_STATUS+=("OK")
}

# ── record on step failure ──
step_fail() {
    local now_epoch=$(date +%s)
    local elapsed=$((now_epoch - _STEP_START_TIME))
    local mins=$((elapsed / 60))
    local secs=$((elapsed % 60))
    local time_str="${mins}m ${secs}s"

    _SUMMARY_NAMES+=("$_STEP_NAME")
    _SUMMARY_TIMES+=("$time_str")
    _SUMMARY_ESTIMATES+=("$_STEP_ESTIMATE")
    _SUMMARY_STATUS+=("FAIL")
}

# ── script total elapsed time ──
script_total_time() {
    local now_epoch=$(date +%s)
    local elapsed=$((now_epoch - _SCRIPT_START_TIME))
    local hours=$((elapsed / 3600))
    local mins=$(( (elapsed % 3600) / 60 ))
    local secs=$((elapsed % 60))
    if [ $hours -gt 0 ]; then
        echo "${hours}h ${mins}m ${secs}s"
    else
        echo "${mins}m ${secs}s"
    fi
}

# ── print estimated total elapsed time ──
# Usage: estimate_total 10 20  "10-20 minutes"
estimate_total() {
    local min_min="$1"
    local max_min="$2"
    local desc="${3:-${min_min}-${max_min} minutes}"
    echo ""
    echo "╔═══════════════════════════════════════════════════════════"
    echo "║  Script estimated total time: $desc"
    echo "║  Heartbeat monitoring: progress printed every 30 seconds"
    echo "║  Status query: in another terminal run source scripts/_lib.sh && monitor_check"
    echo "╚═══════════════════════════════════════════════════════════"
}

# ── write the monitor status file (internal function) ──
_monitor_write_status() {
    local status="$1"
    local pid="$2"
    local cmd="$3"
    local log_file="$4"
    local start_time="$5"
    local elapsed_str="$6"

    cat > "$MONITOR_STATUS_FILE" << EOF
Script:    $(basename "$0")
Step:      $_STEP_NAME
Status:    $status
PID:       $pid
Start time: $(date -d "@$start_time" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')
Elapsed:   $elapsed_str
Command:   $cmd
Log file:  $log_file
EOF
}

# ── update the log tail file (internal function) ──
_monitor_write_tail() {
    local log_file="$1"
    local lines="${2:-10}"
    tail -"$lines" "$log_file" 2>/dev/null > "$MONITOR_LOG_TAIL_FILE"
}

# ── query current monitor status + last 10 log lines ──
# Usage: monitor_check          — show status + last 10 lines
#        monitor_check 20       — show status + last 20 lines
monitor_check() {
    local tail_lines="${1:-10}"
    echo "╔═══════════════════════════════════════════════════════════"
    echo "║  Current monitor status"
    echo "╠═══════════════════════════════════════════════════════════"
    if [ -f "$MONITOR_STATUS_FILE" ]; then
        sed 's/^/║  /' "$MONITOR_STATUS_FILE"
    else
        echo "║  No active monitor (status file does not exist: $MONITOR_STATUS_FILE)"
    fi
    echo "╠═══════════════════════════════════════════════════════════"
    echo "║  Last ${tail_lines} log lines"
    echo "╠═══════════════════════════════════════════════════════════"
    if [ -f "$MONITOR_LOG_TAIL_FILE" ]; then
        sed 's/^/║  /' "$MONITOR_LOG_TAIL_FILE"
    else
        echo "║  No log (tail file does not exist: $MONITOR_LOG_TAIL_FILE)"
    fi
    echo "╚═══════════════════════════════════════════════════════════"
}

# ── pip install with heartbeat monitoring (no timeout kill) ──
# Usage: pip_install_watch "pip install -r requirements.txt"
#   $1: the full pip command (string)
pip_install_watch() {
    local cmd="$1"
    local heartbeat_interval=30

    local log_file=$(mktemp /tmp/pip_install_XXXXXX.log)
    local start_time=$(date +%s)

    echo "  Command: $cmd"
    echo "  Log: $log_file"
    echo "  Heartbeat interval: ${heartbeat_interval}s"
    echo "  Status query: in another terminal run source scripts/_lib.sh && monitor_check"
    echo ""

    # run pip install in the background, redirect output to the log file
    eval "$cmd" > "$log_file" 2>&1 &
    local pid=$!

    # heartbeat monitoring loop (no timeout, does not kill the process)
    while kill -0 $pid 2>/dev/null; do
        sleep $heartbeat_interval
        local now_epoch=$(date +%s)
        local elapsed=$((now_epoch - start_time))
        local elapsed_min=$((elapsed / 60))
        local elapsed_sec=$((elapsed % 60))
        local elapsed_str="${elapsed_min}m${elapsed_sec}s"

        # update the status file
        _monitor_write_status "running" "$pid" "$cmd" "$log_file" "$start_time" "$elapsed_str"

        # update the log tail file
        _monitor_write_tail "$log_file" 10

        # print the heartbeat
        local log_size=$(wc -c < "$log_file" 2>/dev/null || echo 0)
        local last_line=$(tail -1 "$log_file" 2>/dev/null | head -c 80)
        echo "  [HEARTBEAT] ${elapsed_str} | log ${log_size} bytes | $last_line"
    done

    # wait for the child process to finish, get the exit code
    wait $pid
    local exit_code=$?

    local now_epoch=$(date +%s)
    local elapsed=$((now_epoch - start_time))
    local elapsed_min=$((elapsed / 60))
    local elapsed_sec=$((elapsed % 60))
    local elapsed_str="${elapsed_min}m ${elapsed_sec}s"

    # update the status file to the final status
    if [ $exit_code -eq 0 ]; then
        _monitor_write_status "success" "$pid" "$cmd" "$log_file" "$start_time" "$elapsed_str"
        _monitor_write_tail "$log_file" 10
        echo "  [SUCCESS] pip install completed ($elapsed_str)"
    else
        _monitor_write_status "FAILED (exit=$exit_code)" "$pid" "$cmd" "$log_file" "$start_time" "$elapsed_str"
        _monitor_write_tail "$log_file" 20
        echo "  [FAILED] pip install failed (exit=$exit_code, $elapsed_str)"
        echo "  Last 20 log lines:"
        tail -20 "$log_file" 2>/dev/null | sed 's/^/    /'
        echo ""
        echo "  Full log: $log_file"
        return 1
    fi

    # clean up the temporary log (on success)
    rm -f "$log_file"
    return 0
}

# ── run any command with heartbeat monitoring (no timeout kill) ──
# Usage: run_watch "python scripts/build_index.py" "build index"
run_watch() {
    local cmd="$1"
    local desc="${2:-command}"
    local heartbeat_interval=30

    local log_file=$(mktemp /tmp/run_watch_XXXXXX.log)
    local start_time=$(date +%s)

    echo "  Description: $desc"
    echo "  Command: $cmd"
    echo "  Log: $log_file"
    echo "  Status query: in another terminal run source scripts/_lib.sh && monitor_check"
    echo ""

    # run in the background
    eval "$cmd" > "$log_file" 2>&1 &
    local pid=$!

    while kill -0 $pid 2>/dev/null; do
        sleep $heartbeat_interval
        local now_epoch=$(date +%s)
        local elapsed=$((now_epoch - start_time))
        local elapsed_min=$((elapsed / 60))
        local elapsed_sec=$((elapsed % 60))
        local elapsed_str="${elapsed_min}m${elapsed_sec}s"

        # update the status file
        _monitor_write_status "running" "$pid" "$cmd" "$log_file" "$start_time" "$elapsed_str"

        # update the log tail file
        _monitor_write_tail "$log_file" 10

        local last_line=$(tail -1 "$log_file" 2>/dev/null | head -c 80)
        echo "  [HEARTBEAT] ${elapsed_str} | $last_line"
    done

    wait $pid
    local exit_code=$?

    local now_epoch=$(date +%s)
    local elapsed=$((now_epoch - start_time))
    local elapsed_min=$((elapsed / 60))
    local elapsed_sec=$((elapsed % 60))
    local elapsed_str="${elapsed_min}m ${elapsed_sec}s"

    if [ $exit_code -eq 0 ]; then
        _monitor_write_status "success" "$pid" "$cmd" "$log_file" "$start_time" "$elapsed_str"
        _monitor_write_tail "$log_file" 10
        echo "  [SUCCESS] $desc completed ($elapsed_str)"
    else
        _monitor_write_status "FAILED (exit=$exit_code)" "$pid" "$cmd" "$log_file" "$start_time" "$elapsed_str"
        _monitor_write_tail "$log_file" 20
        echo "  [FAILED] $desc failed (exit=$exit_code, $elapsed_str)"
        echo "  Last 20 log lines:"
        tail -20 "$log_file" 2>/dev/null | sed 's/^/    /'
        return 1
    fi

    rm -f "$log_file"
    return 0
}

# ── step elapsed-time summary table ──
script_summary() {
    local script_name="$(basename "$0")"
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════════════"
    echo "║  $script_name step elapsed-time summary"
    echo "╠═══════════════════════════════════════════════════════════════════════"
    printf "║  %-3s %-40s %-12s %-15s %-6s\n" "#" "Step" "Actual time" "Estimate" "Status"
    echo "║  ────────────────────────────────────────────────────────────────────"

    local i=0
    for idx in "${!_SUMMARY_NAMES[@]}"; do
        local name="${_SUMMARY_NAMES[$idx]}"
        local time="${_SUMMARY_TIMES[$idx]}"
        local est="${_SUMMARY_ESTIMATES[$idx]}"
        local status="${_SUMMARY_STATUS[$idx]}"

        # truncate overly long step names
        if [ ${#name} -gt 40 ]; then
            name="${name:0:37}..."
        fi

        printf "║  %-3s %-40s %-12s %-15s %-6s\n" "$((i+1))" "$name" "$time" "$est" "$status"
        i=$((i+1))
    done

    echo "║  ────────────────────────────────────────────────────────────────────"
    echo "║  Total time: $(script_total_time)"
    echo "╚═══════════════════════════════════════════════════════════════════════"
}
