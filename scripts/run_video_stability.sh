#!/usr/bin/env bash
set -euo pipefail

API_URL="${BUILDGUARD_API_URL:-http://127.0.0.1:8000}"
CAMERA_ID="${BUILDGUARD_CAMERA_ID:-}"
DURATION="${BUILDGUARD_VIDEO_STABILITY_SECONDS:-7200}"

case "$API_URL" in
  http://127.0.0.1:*|http://localhost:*) ;;
  *)
    echo "BUILDGUARD_API_URL must be a localhost HTTP endpoint." >&2
    exit 2
    ;;
esac

if [ -z "$CAMERA_ID" ]; then
  echo "Set BUILDGUARD_CAMERA_ID to a configured local camera." >&2
  exit 2
fi

case "$CAMERA_ID" in
  *[!A-Za-z0-9_.-]*)
    echo "BUILDGUARD_CAMERA_ID contains invalid characters." >&2
    exit 2
    ;;
esac

case "$DURATION" in
  ''|*[!0-9]*)
    echo "BUILDGUARD_VIDEO_STABILITY_SECONDS must be a positive integer." >&2
    exit 2
    ;;
esac

if [ "$DURATION" -le 0 ]; then
  echo "BUILDGUARD_VIDEO_STABILITY_SECONDS must be positive." >&2
  exit 2
fi

curl --fail --silent --show-error \
  -X POST "$API_URL/cameras/$CAMERA_ID/start?confirmed=true"
sleep "$DURATION"
curl --fail --silent --show-error "$API_URL/cameras"
curl --fail --silent --show-error \
  -X POST "$API_URL/cameras/$CAMERA_ID/stop?confirmed=true"
