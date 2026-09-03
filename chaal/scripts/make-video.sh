#!/usr/bin/env bash
# Assemble the demo video from the rendered clips and the result slides.
#
#   python scripts/render_clips.py runs/go2-4096/model_499.pt 15   # on the Radeon
#   bash scripts/make-video.sh
#
# Every frame comes from a real run. The clips are the trained policy rendered
# from its checkpoint, and the slides are generated from the committed JSON in
# bench-results/, so nothing on screen is typed in by hand.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v ffmpeg >/dev/null || { echo "FAILED: ffmpeg missing" >&2; exit 1; }

OUT="${OUT:-demo-video.mp4}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

FONT="/System/Library/Fonts/HelveticaNeue.ttc"
[ -f "$FONT" ] || FONT="/System/Library/Fonts/Helvetica.ttc"

echo "==> slides"
python scripts/slides.py "$WORK/slides" >/dev/null

# One shared geometry and a silent stereo track on every segment, so concat can
# stream-copy rather than re-encode mismatched inputs.
W=1400; H=800
SILENCE=(-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000)
VF="scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:0x111115,fps=30,format=yuv420p"

still() { # png seconds output
  ffmpeg -nostdin -y -loglevel error -loop 1 -i "$1" "${SILENCE[@]}" -t "$2" \
    -vf "$VF" -c:v libx264 -preset medium -crf 20 -c:a aac -shortest "$3"
}

clip() { # mp4 caption detail output
  local esc_c="${2//:/\\:}" esc_d="${3//:/\\:}"
  ffmpeg -nostdin -y -loglevel error -i "$1" "${SILENCE[@]}" \
    -vf "${VF},drawtext=fontfile=${FONT}:text='${esc_c}':x=48:y=H-104:fontsize=34:fontcolor=white:box=1:boxcolor=0x111115@0.72:boxborderw=14,drawtext=fontfile=${FONT}:text='${esc_d}':x=48:y=H-58:fontsize=25:fontcolor=0x9a9aa6:box=1:boxcolor=0x111115@0.72:boxborderw=12" \
    -c:v libx264 -preset medium -crf 20 -c:a aac -shortest "$4"
}

echo "==> segments"
still "$WORK/slides/01-title.png"      6  "$WORK/a01.mp4"

# Clip captions come out of bench-results/clips.json, which render_clips.py
# wrote during the render. Typing them here by hand is how a caption ends up
# quoting a number from a different run than the footage it sits on.
i=2
while IFS=$'\t' read -r file caption detail; do
  clip "$file" "$caption" "$detail" "$WORK/a$(printf '%02d' $i).mp4"
  i=$((i + 1))
done < <(python - <<'PY'
import json
d = json.load(open("bench-results/clips.json"))
for c in d["clips"]:
    vx, vy, wz = c["command"]
    parts = []
    if vx: parts.append(f"{vx} m/s forward" if vx > 0 else f"{abs(vx)} m/s backwards")
    if vy: parts.append(f"{abs(vy)} m/s sideways")
    if wz: parts.append(f"{wz} rad/s turn")
    print(f"{c['file']}\tCommanded {', '.join(parts)}\t"
          f"tracking error {c['mean_tracking_error_ms']:.3f} m/s")
PY
)

still "$WORK/slides/02-training.png"   20 "$WORK/a$(printf '%02d' $i).mp4"; i=$((i+1))
still "$WORK/slides/03-scaling.png" 32 "$WORK/a$(printf '%02d' $i).mp4"; i=$((i+1))
still "$WORK/slides/04-robustness.png" 26 "$WORK/a$(printf '%02d' $i).mp4"; i=$((i+1))
still "$WORK/slides/05-friction.png" 32 "$WORK/a$(printf '%02d' $i).mp4"; i=$((i+1))
still "$WORK/slides/06-egl.png" 26 "$WORK/a$(printf '%02d' $i).mp4"; i=$((i+1))
still "$WORK/slides/07-close.png" 14 "$WORK/a$(printf '%02d' $i).mp4"; i=$((i+1))

echo "==> concat"
: > "$WORK/list.txt"
for f in "$WORK"/a*.mp4; do printf "file '%s'\n" "$f" >> "$WORK/list.txt"; done
ffmpeg -nostdin -y -loglevel error -f concat -safe 0 -i "$WORK/list.txt" -c copy "$OUT"

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")
ls -lh "$OUT"

# Track 3 asks for 3 to 5 minutes. Fail loudly rather than submit a short one.
python - "$OUT" "$DUR" <<'PY'
import sys
name, d = sys.argv[1], float(sys.argv[2])
print(f"{name}  {d:.0f} s  ({int(d // 60)}:{int(d % 60):02d})")
if not 180 <= d <= 300:
    sys.exit(f"FAILED: demo video is {d:.0f}s, outside the required 3 to 5 minutes")
print("duration is within the required 3 to 5 minutes")
PY
