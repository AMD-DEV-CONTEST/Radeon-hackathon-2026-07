#!/usr/bin/env bash
set -euo pipefail

# ModelScope serves Qwen3-0.6B as one range-capable 1,503,300,328-byte object.
# Parallel ranges make a resumable smoke-model download possible when a single
# CDN stream is throttled. Replace URL/size for a larger final judge artifact.
URL="${1:-https://www.modelscope.cn/models/Qwen/Qwen3-0.6B/resolve/master/model.safetensors}"
TOTAL="${2:-1503300328}"
OUT="${3:-/workspace/models/Qwen3-0.6B/model.safetensors}"
PARTS="${OUT}.parts"
CHUNK="${CHUNK_BYTES:-100000000}"

mkdir -p "$(dirname "$OUT")" "$PARTS"
for ((start=0; start<TOTAL; start+=CHUNK)); do
  end=$((start + CHUNK - 1))
  if ((end >= TOTAL)); then end=$((TOTAL - 1)); fi
  part="$PARTS/${start}-${end}.part"
  expected=$((end - start + 1))
  if [[ -f "$part" ]] && [[ "$(stat -c%s "$part")" == "$expected" ]]; then
    continue
  fi
  curl -L --fail --retry 5 --retry-delay 2 --range "${start}-${end}" "$URL" -o "$part" &
done
wait

for part in "$PARTS"/*.part; do
  [[ "$(stat -c%s "$part")" -gt 0 ]]
done

# The offsets are numeric; shell glob expansion is lexicographic and would
# place 1,000,000,000 before 250,000,000, corrupting multi-gigabyte files.
mapfile -t ordered_parts < <(find "$PARTS" -maxdepth 1 -type f -name '*.part' -printf '%f\n' | sort -n -t- -k1,1 | sed "s#^#$PARTS/#")
cat "${ordered_parts[@]}" > "$OUT"
[[ "$(stat -c%s "$OUT")" == "$TOTAL" ]]
echo "Downloaded $OUT ($(stat -c%s "$OUT") bytes)"
