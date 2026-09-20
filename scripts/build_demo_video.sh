#!/usr/bin/env bash
# Build the narrated 1080p Track 2 demo from verified browser captures.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRAMES="${ROOT}/output/video/frames"
AUDIO="${ROOT}/output/video/audio"
SEGMENTS="${ROOT}/output/video/segments"
OUTPUT="${ROOT}/output/video/track2_demo_1080p_ava.mp4"
FONT="/System/Library/Fonts/Supplemental/Arial.ttf"

mkdir -p "${SEGMENTS}"

frames=(
  "01-hero.jpg"
  "02-dashboard.jpg"
  "03-capabilities.jpg"
  "04-architecture.jpg"
  "05-proof.jpg"
  "06-result-dsl.jpg"
  "07-result-risk.jpg"
)
audio=(
  "01-hero-neural.wav"
  "02-dashboard-neural.wav"
  "03-capabilities-neural.wav"
  "04-architecture-neural.wav"
  "05-proof-neural.wav"
  "06-live-dsl-neural.wav"
  "07-risk-neural.wav"
)
# Each segment leaves roughly one second after the corresponding Ava voiceover.
durations=(33 40 39 41 30 38 42)
for i in "${!frames[@]}"; do
  n=$(printf '%02d' "$((i + 1))")
  duration="${durations[$i]}"
  fade_out=$((duration - 1))
  ffmpeg -hide_banner -loglevel error -stats -y \
    -loop 1 -framerate 30 -i "${FRAMES}/${frames[$i]}" \
    -i "${AUDIO}/${audio[$i]}" \
    -t "${duration}" \
    -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,zoompan=z='min(zoom+0.00012,1.035)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=$((duration * 30)):s=1920x1080:fps=30,fade=t=in:st=0:d=0.45,fade=t=out:st=${fade_out}:d=0.7,format=yuv420p" \
    -af "afade=t=in:st=0:d=0.35,afade=t=out:st=${fade_out}:d=0.7" \
    -c:v libx264 -preset medium -crf 21 -profile:v high \
    -c:a aac -b:a 160k -ar 48000 \
    -movflags +faststart \
    "${SEGMENTS}/${n}.mp4"
done

concat_file="${SEGMENTS}/concat.txt"
: > "${concat_file}"
for i in "${!frames[@]}"; do
  n=$(printf '%02d' "$((i + 1))")
  printf "file '%s/%s.mp4'\n" "${SEGMENTS}" "${n}" >> "${concat_file}"
done

ffmpeg -hide_banner -loglevel error -stats -y \
  -f concat -safe 0 -i "${concat_file}" \
  -c copy -movflags +faststart "${OUTPUT}"
echo "${OUTPUT}"
