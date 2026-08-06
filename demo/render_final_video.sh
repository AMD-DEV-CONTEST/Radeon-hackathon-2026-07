#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUTPUT="${1:-demo/Local-Incident-Commander-demo.mp4}"
FFMPEG_BIN="${FFMPEG_BIN:-/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg}"

if [[ ! -x "$FFMPEG_BIN" ]]; then
  FFMPEG_BIN="$(command -v ffmpeg)"
fi

"$FFMPEG_BIN" -y \
  -i demo/ui-capture.webm \
  -i demo/radeon-terminal-capture.mp4 \
  -i demo/radeon-workflow-capture.mp4 \
  -i demo/demo-narration.aiff \
  -filter_complex "\
[0:v]trim=start=0:end=22.44,setpts=PTS-STARTPTS,fps=25,scale=1600:900,setsar=1[v0];\
[1:v]trim=start=0:end=16.12,setpts=PTS-STARTPTS,fps=25,scale=1600:900,setsar=1[v1];\
[2:v]trim=start=0:end=69.64,setpts=PTS-STARTPTS,fps=25,scale=1600:900,setsar=1[v2];\
[0:v]trim=start=108.20:end=235.92,setpts=PTS-STARTPTS,fps=25,scale=1600:900,setsar=1[v3];\
[v0][v1][v2][v3]concat=n=4:v=1:a=0,\
subtitles=demo/DEMO_SUBTITLES.srt:force_style='FontName=Arial,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=1,Outline=2,Shadow=0,MarginV=26',\
format=yuv420p[v]" \
  -map "[v]" -map 3:a:0 \
  -c:v libx264 -preset medium -crf 18 -profile:v high -level 4.0 \
  -pix_fmt yuv420p -r 25 \
  -c:a aac -b:a 160k -ar 44100 \
  -t 235.920 -movflags +faststart \
  "$OUTPUT"
