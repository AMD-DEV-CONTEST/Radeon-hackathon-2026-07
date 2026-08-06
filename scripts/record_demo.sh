#!/usr/bin/env bash
# 3DGenerateFlow headless screen recorder for AMD Radeon / ROCm demo videos.
# Uses Xvfb + fluxbox + ffmpeg x11grab so it works on a remote GPU instance without a monitor.

set -euo pipefail

# Configuration
DISPLAY_NUM=99
RES="1920x1080"
FPS=30
OUTPUT_DIR="${OUTPUT_DIR:-/tmp}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="${OUTPUT_DIR}/3dgf_demo_${TIMESTAMP}.mp4"
DURATION="${DURATION:-300}"  # default 5 minutes; set DURATION=0 for manual stop

# Make sure dependencies exist
if ! command -v Xvfb &> /dev/null || ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: Xvfb and ffmpeg are required."
    echo "Install with: apt-get update && apt-get install -y xvfb fluxbox ffmpeg"
    exit 1
fi

echo "========================================="
echo " 3DGenerateFlow Headless Demo Recorder"
echo "========================================="
echo "Resolution: ${RES}"
echo "FPS:        ${FPS}"
echo "Output:     ${OUTPUT_FILE}"
echo "Duration:   ${DURATION}s (0 = record until Ctrl+C)"
echo ""

# Start virtual display
Xvfb ":${DISPLAY_NUM}" -screen 0 "${RES}x24" +extension GLX +render -noreset &
XVFB_PID=$!
export DISPLAY=":${DISPLAY_NUM}"
sleep 2

# Start a lightweight window manager so browsers look normal
if command -v fluxbox &> /dev/null; then
    fluxbox &
    FLUXBOX_PID=$!
    sleep 1
fi

echo "Virtual display :${DISPLAY_NUM} is ready."
echo "You can now open a browser or start the frontend dev server."
echo "Example: cd apps/web && npm run dev"
echo ""

# Start ffmpeg recording
if [ "${DURATION}" -gt 0 ]; then
    echo "Recording for ${DURATION} seconds..."
    ffmpeg -f x11grab -r "${FPS}" -s "${RES}" -i ":${DISPLAY_NUM}.0" \
        -c:v libx264 -preset fast -pix_fmt yuv420p -t "${DURATION}" "${OUTPUT_FILE}" -y
else
    echo "Recording indefinitely. Press Ctrl+C to stop."
    ffmpeg -f x11grab -r "${FPS}" -s "${RES}" -i ":${DISPLAY_NUM}.0" \
        -c:v libx264 -preset fast -pix_fmt yuv420p "${OUTPUT_FILE}" -y
fi

# Cleanup
kill "${FLUXBOX_PID:-}" 2>/dev/null || true
kill "${XVFB_PID}" 2>/dev/null || true

echo ""
echo "========================================="
echo " Recording saved to:"
echo " ${OUTPUT_FILE}"
echo "========================================="
