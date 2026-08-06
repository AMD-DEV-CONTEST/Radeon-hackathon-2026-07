#!/usr/bin/env bash
# One-time system packages for Reachy Mini daemon audio (GStreamer GstApp).
# Run once: sudo bash scripts/setup-reachy-audio.sh
set -euo pipefail
apt-get update -qq
apt-get install -y \
  gir1.2-gst-plugins-base-1.0 \
  python3-gi \
  gstreamer1.0-alsa \
  gstreamer1.0-pulseaudio
echo "Done. Restart Reachy daemon: curl -X POST http://127.0.0.1:8002/api/reachy/seeed-conversation/setup"
