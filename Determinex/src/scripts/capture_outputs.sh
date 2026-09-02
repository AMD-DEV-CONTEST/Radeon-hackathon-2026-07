#!/bin/bash
# Captures each write of rosetta_training.jsonl before next generator overwrites it
# Handles up to N generators writing to the same file sequentially

DETERMINEX_ROOT="${DETERMINEX_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
OUTPUT="$DETERMINEX_ROOT/data/rosetta_training.jsonl"
BACKUP_DIR="$DETERMINEX_ROOT/data/corpus_captures"
mkdir -p "$BACKUP_DIR"

echo "[$(date +%H:%M:%S)] Capture monitor started. Watching for $OUTPUT..."
echo "Will save each version before it gets overwritten."

CAPTURE_NUM=0
LAST_MOD=""
MAX_CAPTURES=10  # handle up to 10 generator runs

while [ "$CAPTURE_NUM" -lt "$MAX_CAPTURES" ]; do
    if [ -f "$OUTPUT" ]; then
        CURRENT_MOD=$(stat -c "%Y" "$OUTPUT" 2>/dev/null)
        CURRENT_SIZE=$(wc -l < "$OUTPUT" 2>/dev/null || echo 0)

        if [ "$CURRENT_MOD" != "$LAST_MOD" ] && [ "$CURRENT_SIZE" -gt 100 ]; then
            CAPTURE_NUM=$((CAPTURE_NUM + 1))
            DEST="$BACKUP_DIR/rosetta_training_${CAPTURE_NUM}.jsonl"
            cp "$OUTPUT" "$DEST"
            echo "[$(date +%H:%M:%S)] CAPTURED run $CAPTURE_NUM — $CURRENT_SIZE lines → $(basename $DEST)"
            LAST_MOD="$CURRENT_MOD"

            # Check if any generators still alive
            GEN_COUNT=$(tasklist 2>/dev/null | grep -c "python")
            echo "[$(date +%H:%M:%S)] Python processes still running: $GEN_COUNT"
        fi
    fi
    sleep 8
done

echo "[$(date +%H:%M:%S)] Capture phase done ($CAPTURE_NUM captures). Merging..."
merge_corpus
