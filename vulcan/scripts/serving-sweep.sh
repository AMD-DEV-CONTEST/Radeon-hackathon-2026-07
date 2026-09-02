#!/usr/bin/env bash
# vLLM serving-config sweep on the Radeon.
#
# The concurrency result in this submission (7.63x aggregate throughput at 8x
# load) was measured on vLLM's stock settings. That makes it a floor, not a
# tuned figure, and leaves an obvious question unanswered: is the default
# already right for an agent workload, or was throughput left on the table?
#
# This script answers it by benching the same harness against the same model at
# two serving configurations.
#
#   1. Set the template's Serve Command to the config under test.
#   2. Launch the instance, put its API key in .env.
#   3. bash scripts/serving-sweep.sh <label>
#
# Repeat for each config, then compare with `vulcan bench-compare`.
#
# The instance rotates its API key on every launch, so .env has to be updated
# each time. There is no ssh into these instances (port 31200 refuses), so the
# serve flags can only be changed through the template editor in the console.
set -euo pipefail
cd "$(dirname "$0")/.."

LABEL="${1:?usage: serving-sweep.sh <label>, e.g. maxseqs-256}"
[ -f .env ] && set -a && . ./.env && set +a
: "${VULCAN_BASE_URL:?set VULCAN_BASE_URL in .env}"
: "${VULCAN_API_KEY:?set VULCAN_API_KEY in .env to the current instance key}"

echo "==> checking the endpoint answers before spending time on it"
code=$(curl -sS -o /tmp/vulcan-models.json -w "%{http_code}" --max-time 40 \
  -H "Authorization: Bearer $VULCAN_API_KEY" "${VULCAN_BASE_URL%/}/models")
if [ "$code" != "200" ]; then
  echo "FAILED: ${VULCAN_BASE_URL%/}/models returned $code" >&2
  echo "        The key rotates on every instance launch; copy the current one" >&2
  echo "        from the Radeon Cloud console into .env as VULCAN_API_KEY." >&2
  exit 1
fi
python3 -c "import json;print('    serving:', [m['id'] for m in json.load(open('/tmp/vulcan-models.json'))['data']])"

# Both commands derive the output filename from --label, so they need
# different ones or the second silently overwrites the first.
echo "==> concurrency sweep, 1 / 4 / 8"
.venv/bin/vulcan bench-concurrency --label "${LABEL}-conc" --levels 1,4,8

echo "==> decode, 5 repeats"
.venv/bin/vulcan bench --label "${LABEL}-decode" --repeats 5

echo
echo "wrote bench-results/${LABEL}*.json"
ls -1 bench-results/ | grep -- "$LABEL" || true
