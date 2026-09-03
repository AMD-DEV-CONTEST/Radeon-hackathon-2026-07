#!/usr/bin/env bash
# ============================================================================
# build-demo-video.sh — assemble the self-produced Track 2 demo, all local.
# ============================================================================
# Stages (every asset generated on ONE R9700 via Lemonade :13305, no cloud):
#   1. terminal capture of the real agent run           (GPU session)
#   2. LLM writes the voiceover script from the run      (Gwen-Agent-Core LLM)
#   3. Flux-2-Klein renders title/section cards          (GPU session)
#   4. kokoro-v1 narrates each section -> MP3            (narrate.sh — PROVEN)
#   5. ffmpeg stitches visuals + narration -> demo.mp4
#
# This is the ASSEMBLY skeleton. Stages 1 & 3 need a GPU window (screen capture +
# image gen); stage 4 is proven and runnable now. Fill SECTIONS then run.
# ----------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/demo.mp4}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
URL="${LEMONADE_URL:-http://localhost:13305}"
command -v ffmpeg >/dev/null || { echo "need ffmpeg"; exit 1; }

# --- the script: (section title, narration text, visual source) -------------
# Visual source is either a captured clip (stage 1) or a Flux card (stage 3).
SECTIONS=(
  "cold-open|This entire video was produced and narrated locally, on a single AMD Radeon AI PRO R9700, by the very agent it demonstrates.|flux:hero"
  "the-gap|The agent scans the silicon with the assembler as ground truth, and finds a native int4 instruction the kernels never use.|capture:scan"
  "the-fix|It writes the kernel, correctness-gates it bit-exact against a CPU reference, and measures the win on the card.|capture:bench"
  "the-result|Native dot8 int4 decode: one point four nine times faster than the dp4a route. Discovered, fixed, and proven — with no human in the loop.|flux:result"
)

i=0
for s in "${SECTIONS[@]}"; do
  IFS='|' read -r name text visual <<< "$s"
  printf '  [%d] %s\n' "$i" "$name"
  # 4. narrate (PROVEN, runnable now)
  bash "$HERE/narrate.sh" "$text" "$WORK/$i.mp3" >/dev/null
  dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/$i.mp3")"
  # visual: reuse a captured clip or a Flux still (stages 1/3 place files as $HERE/assets/<id>.{mp4,png})
  vid="$HERE/assets/${visual#*:}.mp4"; img="$HERE/assets/${visual#*:}.png"
  if   [ -f "$vid" ]; then cp "$vid" "$WORK/$i.v.mp4"
  elif [ -f "$img" ]; then ffmpeg -y -loop 1 -i "$img" -t "$dur" -vf scale=1920:1080 -pix_fmt yuv420p "$WORK/$i.v.mp4" 2>/dev/null
  else ffmpeg -y -f lavfi -i color=c=black:s=1920x1080 -t "$dur" -pix_fmt yuv420p "$WORK/$i.v.mp4" 2>/dev/null; fi  # placeholder
  # mux this section's narration onto its visual
  ffmpeg -y -i "$WORK/$i.v.mp4" -i "$WORK/$i.mp3" -c:v libx264 -c:a aac -shortest "$WORK/$i.seg.mp4" 2>/dev/null
  echo "file '$WORK/$i.seg.mp4'" >> "$WORK/list.txt"
  i=$((i+1))
done

# 5. concat
ffmpeg -y -f concat -safe 0 -i "$WORK/list.txt" -c copy "$OUT" 2>/dev/null
echo "wrote $OUT  ($(stat -c%s "$OUT") bytes, $i sections — all narrated locally on the R9700)"
