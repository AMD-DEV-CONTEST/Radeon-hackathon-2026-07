#!/usr/bin/env bash
# Wrap the raw VHS recording with a title and end card.
#
#   bash scripts/finish-video.sh
#
# The middle of the video is untouched: it is the real terminal session with
# real output. Only the bookends are generated, and they only state results
# that are already in bench-results/.
set -euo pipefail

cd "$(dirname "$0")/.."

RAW="${RAW:-demo-raw.mp4}"
# Second segment, recorded against the local backend. Optional: without it
# the video is exactly what it was before.
CAPS="${CAPS:-capabilities-raw.mp4}"
OUT="${OUT:-demo.mp4}"
FONT="${FONT:-/System/Library/Fonts/Supplemental/Arial.ttf}"
MONO="${MONO:-/System/Library/Fonts/Menlo.ttc}"

[ -f "$RAW" ] || { echo "no $RAW, run scripts/record-demo.sh first" >&2; exit 1; }

read -r W H FPS < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$RAW" \
  | awk -F, '{split($3,a,"/"); printf "%d %d %d\n", $1, $2, (a[2]?a[1]/a[2]:a[1])}')
echo "==> raw is ${W}x${H} @ ${FPS}fps"

card() { # text-file duration output
  local txt="$1" dur="$2" out="$3"
  ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i "color=c=0x1e1e2e:s=${W}x${H}:d=${dur}:r=${FPS}" \
    -vf "drawtext=fontfile=${FONT}:textfile=${txt}:fontcolor=0xcdd6f4:fontsize=$((H/22)):line_spacing=$((H/60)):x=(w-text_w)/2:y=(h-text_h)/2" \
    -c:v libx264 -pix_fmt yuv420p "$out"
}

cat > /tmp/vulcan-title.txt <<'EOF'
Vulcan

A codebase agent that never calls a third-party LLM API.
Generation runs on an AMD Radeon GPU via vLLM on ROCm.

AMD AI DevMaster Hackathon, Track 2, Private AI Agents
EOF

cat > /tmp/vulcan-end.txt <<'EOF'
Measured, not claimed

Continuous batching on the Radeon, 1 to 8 concurrent:
8.12x on stock settings, 4.07x with the batch capped at 4
The capped run scales to exactly its own cap

Retrieval: lexical weight swept, not guessed
top-1 5/7 dense only, 6/7 hybrid; 0.5 and 1.0 degrade

Task decomposition: built, measured, rejected
neither model ever used it, 18 to 21s slower

AWQ quantization: measured, rejected
0.68x of fp16 on a card with no memory pressure

Raw JSON for every number in bench-results/

github.com/himanshu748/vulcan
EOF

cat > /tmp/vulcan-caps.txt <<'EOF'
The same agent, on a second backend

Everything so far ran on the Radeon through vLLM on ROCm.
What follows runs against a local Ollama endpoint instead,
which is the backend-agnostic claim being exercised.

No code changes. One environment variable.
EOF

echo "==> rendering cards"
card /tmp/vulcan-title.txt 7 /tmp/vulcan-title.mp4
card /tmp/vulcan-end.txt 9 /tmp/vulcan-end.mp4

echo "==> normalising the recording"
ffmpeg -hide_banner -loglevel error -y -i "$RAW" \
  -c:v libx264 -pix_fmt yuv420p -r "$FPS" -an /tmp/vulcan-body.mp4

PARTS=(/tmp/vulcan-title.mp4 /tmp/vulcan-body.mp4)
if [ -f "$CAPS" ]; then
  echo "==> second segment"
  card /tmp/vulcan-caps.txt 6 /tmp/vulcan-caps.mp4
  # VHS pads the tail with idle black once output stops; trim it so the video
  # does not sit on a blank screen.
  caps_dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$CAPS" | cut -d. -f1)
  ffmpeg -hide_banner -loglevel error -y -i "$CAPS" -t "$((caps_dur - 3))" \
    -c:v libx264 -pix_fmt yuv420p -r "$FPS" -an -vf "scale=${W}:${H}" /tmp/vulcan-caps-body.mp4
  PARTS+=(/tmp/vulcan-caps.mp4 /tmp/vulcan-caps-body.mp4)
fi
PARTS+=(/tmp/vulcan-end.mp4)

echo "==> concatenating"
printf "file '%s'\n" "${PARTS[@]}" > /tmp/vulcan-concat.txt
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i /tmp/vulcan-concat.txt -c copy "$OUT"

dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" | cut -d. -f1)
echo
echo "==> $OUT  ($((dur/60))m $((dur%60))s)"
ls -lh "$OUT"
[ "$dur" -ge 180 ] && [ "$dur" -le 300 ] \
  && echo "    inside the 3 to 5 minute window" \
  || { echo "    FAILED: outside the 3 to 5 minute window"; exit 1; }
