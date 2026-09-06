#!/usr/bin/env bash
# Record the terminal half of the demo video.
#
#   bash scripts/record-demo.sh
#
# The pack inside the tape runs for real against the Radeon box, so the elapsed
# time on screen is the actual GPU round trip. DUKAAN_INSTANCE comes from .env,
# which is gitignored; `dukaan doctor` masks the instance id on screen because
# the tunnel takes no credentials and the URL is therefore the credential.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && set -a && . ./.env && set +a
: "${DUKAAN_INSTANCE:?set DUKAAN_INSTANCE in .env first}"

command -v vhs >/dev/null || { echo "FAILED: vhs missing. brew install vhs" >&2; exit 1; }

# vhs writes relative to the working directory and rejects absolute Output paths.
rm -rf out/brass-ewer
vhs scripts/demo.tape
# vhs creates the file early and writes the moov atom last, so existence is not
# the signal that it is done. ffprobe reading a duration is.
ffprobe -v error -show_entries format=duration -of csv=p=0 demo-terminal.mp4 >/dev/null 2>&1 || {
  echo "FAILED: demo-terminal.mp4 was not produced or is incomplete" >&2; exit 1; }
ffprobe -v error -show_entries format=duration -of csv=p=0 demo-terminal.mp4
