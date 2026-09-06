#!/usr/bin/env bash
# Assemble the demo video: title, what the model is given, the terminal run,
# the three creatives, the generated clip with its audio, and the finding.
#
#   bash scripts/record-demo.sh   # first, produces demo-terminal.mp4
#   bash scripts/make-video.sh
#
# Needs ffmpeg. Every frame comes from a real run; nothing is mocked up.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v ffmpeg >/dev/null || { echo "FAILED: ffmpeg missing" >&2; exit 1; }
# A half-written capture has no moov atom and fails much later with a confusing
# error, so the input is checked properly rather than just for being non-empty.
ffprobe -v error -show_entries format=duration -of csv=p=0 demo-terminal.mp4 >/dev/null 2>&1 || {
  echo "FAILED: demo-terminal.mp4 is missing or incomplete. Run scripts/record-demo.sh and let vhs finish." >&2
  exit 1
}

SRC="${SRC:-out/brass-ewer}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "==> slides"
.venv/bin/python scripts/slides.py "$WORK/slides" "$SRC" >/dev/null

# Every segment gets a silent stereo track at the same rate, so the concat
# demuxer can stream-copy instead of re-encoding mismatched inputs.
SILENCE=(-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000)
VSCALE="scale=1400:800:force_original_aspect_ratio=decrease,pad=1400:800:(ow-iw)/2:(oh-ih)/2:0x111115,fps=30,format=yuv420p"

still() { # png seconds output
  ffmpeg -y -loglevel error -loop 1 -i "$1" "${SILENCE[@]}" -t "$2" \
    -vf "$VSCALE" -c:v libx264 -preset medium -crf 20 -c:a aac -shortest "$3"
}

echo "==> clip with its generated audio"
# The clip is ~2 s at 25 fps, so it is looped to be watchable. The audio is the
# model's own output, looped with it.
clip() { # frames-glob wav loops output
  ffmpeg -y -loglevel error -stream_loop "$3" -framerate 25 -i "$1" \
    -stream_loop "$3" -i "$2" \
    -vf "scale=800:800,pad=1400:800:(ow-iw)/2:(oh-ih)/2:0x111115,fps=30,format=yuv420p" \
    -c:v libx264 -preset medium -crf 20 -c:a aac -shortest "$4"
}

STYLE=$(basename "$(ls "$SRC"/*_manifest.json | head -1)" _manifest.json)
clip "$SRC/${STYLE}_clip_frames/%03d.png" "$SRC/${STYLE}_clip.wav" 7 "$WORK/clip.mp4"

# A second product's clip, so the sound is not a one-off.
ALT=$(ls -d out/*/ | grep -v "$(basename "$SRC")" | head -1)
ALT_STYLE=$(basename "$(ls "$ALT"/*_manifest.json | head -1)" _manifest.json)
clip "$ALT/${ALT_STYLE}_clip_frames/%03d.png" "$ALT/${ALT_STYLE}_clip.wav" 4 "$WORK/clip2.mp4"

# The browser-UI half, captured by scripts/capture-ui.py against the live
# Radeon endpoint. VHS records terminals only, so the UI states come in as
# stills of real pages showing real output.
UISHOTS="${UISHOTS:-/tmp/uishots}"
if ls "$UISHOTS"/*.png >/dev/null 2>&1; then
  echo "==> browser UI segment"
  i=0
  for f in "$UISHOTS"/*.png; do
    i=$((i+1))
    case "$(basename "$f")" in
      *generating*|*moment*) secs=5 ;;
      *) secs=6 ;;
    esac
    still "$f" "$secs" "$WORK/ui$(printf '%02d' $i).mp4"
  done
fi

still "$WORK/slides/01-title.png"      8 "$WORK/01.mp4"
still "$WORK/slides/02-pipeline.png"  12 "$WORK/02.mp4"
still "$WORK/slides/03-formats.png"   15 "$WORK/04.mp4"
still "$WORK/slides/04-gallery.png"   14 "$WORK/05.mp4"
still "$WORK/slides/05-styles.png"    14 "$WORK/06.mp4"
still "$WORK/slides/06-finding.png"   16 "$WORK/07.mp4"
still "$WORK/slides/07-fix.png"       17 "$WORK/08.mp4"
still "$WORK/slides/08-batching.png"  14 "$WORK/09.mp4"

echo "==> terminal segment"
# Normalise the vhs capture to the same size, frame rate and a silent track so
# the concat demuxer does not have to re-encode mismatched streams.
ffmpeg -y -loglevel error -i demo-terminal.mp4 "${SILENCE[@]}" \
  -vf "$VSCALE" -c:v libx264 -preset medium -crf 20 -c:a aac -shortest "$WORK/03.mp4"

{
  printf "file '%s/01.mp4'\n" "$WORK"
  for u in "$WORK"/ui*.mp4; do [ -e "$u" ] && printf "file '%s'\n" "$u"; done
  for f in 02 03 04 clip 05 clip2 06 07 08 09; do
    [ -e "$WORK/$f.mp4" ] && printf "file '%s/%s.mp4'\n" "$WORK" "$f"
  done
} > "$WORK/list.txt"

echo "==> concat"
ffmpeg -y -loglevel error -f concat -safe 0 -i "$WORK/list.txt" -c copy demo.mp4
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 demo.mp4)
printf 'demo.mp4  %.0f s  %s\n' "$DUR" "$(du -h demo.mp4 | cut -f1)"
awk -v d="$DUR" 'BEGIN{ if (d < 180 || d > 300) { print "WARNING: outside the 3-5 minute guidance"; } }'
