#!/usr/bin/env bash
# ============================================================
# Conductor loop — dispatch → extract → compile-check → fix
#
# Usage:
#   ./fleet_prompts/conductor.sh <task_id> <endpoint> <prompt_file> [max_rounds]
#
# Example:
#   ./fleet_prompts/conductor.sh E http://localhost:5001 fleet_prompts/E_matvec_vec4_coarsen.md 3
#
# What it does:
#   1. Dispatch prompt to endpoint
#   2. Extract code blocks from response into src/ and shaders/
#   3. Run cargo build --release
#   4. If build fails: send errors back to same endpoint with context, retry
#   5. If build passes: WIP commit and report
#
# Max rounds default: 3 (usually 1-2 is enough for syntax fixes)
# ============================================================

set -e

TASK_ID="$1"
ENDPOINT="$2"
PROMPT_FILE="$3"
MAX_ROUNDS="${4:-3}"
WORK_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "$TASK_ID" ] || [ -z "$ENDPOINT" ] || [ -z "$PROMPT_FILE" ]; then
    echo "Usage: $0 <task_id> <endpoint> <prompt_file> [max_rounds]"
    exit 1
fi

RESPONSE_FILE="fleet_prompts/${TASK_ID}_response.md"
EXTRACT_LOG="fleet_prompts/${TASK_ID}_extract.log"
BUILD_LOG="fleet_prompts/${TASK_ID}_build.log"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  Conductor: Task $TASK_ID → $ENDPOINT"
echo "╚══════════════════════════════════════════════════════╝"

for round in $(seq 1 $MAX_ROUNDS); do
    echo ""
    echo "── Round $round/$MAX_ROUNDS ──────────────────────────────────"

    # ── Step 1: Dispatch ──────────────────────────────────────────────────
    if [ "$round" -eq 1 ]; then
        echo "Dispatching: $PROMPT_FILE → $ENDPOINT"
        ./fleet_prompts/dispatch.sh "$ENDPOINT" "$PROMPT_FILE" "$RESPONSE_FILE"
    else
        echo "Re-dispatching with build errors..."
        ./fleet_prompts/dispatch.sh "$ENDPOINT" "fleet_prompts/${TASK_ID}_retry_${round}.md" "$RESPONSE_FILE"
    fi

    echo "Response: $(wc -c < "$RESPONSE_FILE") bytes"

    # ── Step 2: Extract code blocks ───────────────────────────────────────
    echo "Extracting code blocks..."
    python3 fleet_prompts/extract_code.py "$RESPONSE_FILE" "$WORK_DIR" > "$EXTRACT_LOG" 2>&1
    echo "Extracted: $(cat "$EXTRACT_LOG")"

    # ── Step 3: Compile check ─────────────────────────────────────────────
    echo "Building..."
    if cargo build --release 2>"$BUILD_LOG"; then
        echo ""
        echo "✅ BUILD PASSED on round $round"
        echo "Committing WIP..."
        git add -A
        git -c user.name=cesarops -c user.email=cesarops@local commit -m \
            "WIP: Task $TASK_ID — auto-compiled (round $round, conductor loop)" -q 2>/dev/null || true
        echo "✅ Committed."
        exit 0
    fi

    # ── Step 4: Build failed — prepare retry prompt ───────────────────────
    ERRORS=$(grep '^error' "$BUILD_LOG" | head -20)
    ERROR_COUNT=$(grep -c '^error' "$BUILD_LOG" 2>/dev/null || echo 0)
    echo "❌ Build failed: $ERROR_COUNT errors"
    echo "$ERRORS" | head -5

    if [ "$round" -ge "$MAX_ROUNDS" ]; then
        echo ""
        echo "⚠️  Max rounds reached. Errors saved to $BUILD_LOG"
        echo "Manual fix needed. Key errors:"
        grep '^error' "$BUILD_LOG" | head -10
        exit 1
    fi

    # Build retry prompt with errors
    NEXT_ROUND=$((round + 1))
    RETRY_FILE="fleet_prompts/${TASK_ID}_retry_${NEXT_ROUND}.md"

    cat > "$RETRY_FILE" << RETRY_PROMPT
The code you wrote in the previous round has compile errors. Fix ONLY the errors listed below.
Output the complete corrected files in the same format as before (// === FILE: path ===).
Do not change anything that compiled correctly.

## Build errors (cargo build --release):
\`\`\`
$(cat "$BUILD_LOG" | grep -E '^error|^\s+-->' | head -40)
\`\`\`

## Your previous response (for context):
$(cat "$RESPONSE_FILE" | head -200)

Fix the errors and output the corrected files.
RETRY_PROMPT

    echo "Retry prompt written: $RETRY_FILE"
done

echo "Failed after $MAX_ROUNDS rounds."
exit 1
