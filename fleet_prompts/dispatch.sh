#!/usr/bin/env bash
# Dispatch a prompt file to a koboldcpp endpoint, return JSON content to stdout.
# Usage: dispatch.sh <endpoint> <prompt_file> <out_file>
set -e
ENDPOINT="$1"
PROMPT_FILE="$2"
OUT_FILE="$3"

# Build JSON request with prompt content as user message
PAYLOAD=$(jq -Rs --arg sys "You are an expert systems programmer. Output complete working code, no truncation, no placeholders, no explanations between code blocks. Use the exact OUTPUT FORMAT requested." \
  '{model:"x", messages:[{role:"system",content:$sys},{role:"user",content:.}], max_tokens:8192, temperature:0.2}' < "$PROMPT_FILE")

curl -sS --max-time 1800 -X POST "$ENDPOINT/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" > "$OUT_FILE.raw"

# Extract message content
jq -r '.choices[0].message.content' < "$OUT_FILE.raw" > "$OUT_FILE"
echo "DONE: $OUT_FILE ($(wc -c < "$OUT_FILE") bytes)"
