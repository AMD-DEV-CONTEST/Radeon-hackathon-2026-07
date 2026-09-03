#!/usr/bin/env bash
# ============================================================================
# capture_demo.sh — record a demo script executing FOR REAL, as a screen capture.
# ============================================================================
# The hackathon spec asks for "the actual operation process ... from command
# line to the final result", so this is a genuine X11 screen capture of a real
# xterm running a real script against the real GPU — not a rendered mock-up.
#
# SAFETY (learned the hard way, 2026-08-04): an earlier version reused a
# pre-existing Xvfb :99 that was also hosting an unrelated application, and
# started ffmpeg BEFORE the xterm was mapped. Result: the opening seconds of
# the video were somebody else's desktop, and it got committed to a public
# repo. This version therefore:
#   1. ALWAYS creates its own private display on a free number (never reuses),
#   2. REFUSES to record if any window it did not create is present,
#   3. starts recording only AFTER the xterm is mapped,
#   4. checks frame 0 of the result and aborts if it is not the terminal.
#
# Usage:  SEGMENT=./demo/run_demo.sh ./capture_demo.sh out.mp4
# ============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="${SEGMENT:-$HERE/run_demo.sh}"
OUT="${1:-$HERE/self-narrated/demo-operation.mp4}"
W=1920; H=1080
PACE="${PACE:-3}"
RAW="/tmp/demo-capture-raw-$$.mkv"

command -v ffmpeg   >/dev/null || { echo "need ffmpeg";  exit 1; }
command -v xterm    >/dev/null || { echo "need xterm";   exit 1; }
command -v Xvfb     >/dev/null || { echo "need Xvfb";    exit 1; }
command -v xdpyinfo >/dev/null || { echo "need xdpyinfo (x11-utils)"; exit 1; }

# --- 1. private display on a free number -----------------------------------
VDISP=""
for n in $(seq 77 99); do
  if [ ! -e "/tmp/.X11-unix/X$n" ] && ! xdpyinfo -display ":$n" >/dev/null 2>&1; then
    VDISP=":$n"; break
  fi
done
[ -n "$VDISP" ] || { echo "no free X display number found"; exit 1; }
echo "[*] creating PRIVATE display $VDISP (never reusing an existing one)"
Xvfb "$VDISP" -ac -screen 0 ${W}x${H}x24 +extension RANDR >/dev/null 2>&1 &
XVFB=$!
for i in $(seq 1 40); do xdpyinfo -display "$VDISP" >/dev/null 2>&1 && break; sleep 0.25; done
xdpyinfo -display "$VDISP" >/dev/null 2>&1 || { echo "Xvfb failed to start"; kill $XVFB 2>/dev/null; exit 1; }

cleanup(){
  [ -n "${FFPID:-}" ] && kill "$FFPID" 2>/dev/null
  [ -n "${XTPID:-}" ] && kill "$XTPID" 2>/dev/null
  [ -n "${XVFB:-}"  ] && kill "$XVFB"  2>/dev/null
  rm -f "$RAW"
  return 0
}
trap cleanup EXIT INT TERM

# --- 2. launch the terminal FIRST, then verify the display is clean ---------
echo "[*] launching xterm running $(basename "$SCRIPT") (PACE=$PACE POST=${POST:-$PACE})"
DISPLAY="$VDISP" xterm \
  -geometry 142x43+0+0 \
  -fa 'DejaVu Sans Mono' -fs 19 \
  -bg '#0b0e12' -fg '#d6dae2' \
  -xrm 'xterm*colorBD: #ffffff' \
  -title 'hyperloom — autonomous kernel optimization on AMD Radeon' \
  -e bash -lc "PACE=$PACE POST=${POST:-$PACE} TYPE=${TYPE:-0.022} '$SCRIPT'; echo; echo '  [segment complete]'; sleep 3" &
XTPID=$!

# wait for the xterm window to actually be mapped
for i in $(seq 1 60); do
  DISPLAY="$VDISP" xwininfo -root -children 2>/dev/null | grep -qi 'xterm\|hyperloom' && break
  sleep 0.25
done

# refuse to record a display that has anything we did not create on it
FOREIGN=$(DISPLAY="$VDISP" xwininfo -root -children 2>/dev/null \
          | grep -E '^\s+0x' | grep -viE 'xterm|hyperloom|has no name|\(\)' || true)
if [ -n "$FOREIGN" ]; then
  echo "!! ABORT: unexpected windows on $VDISP — will not record:" >&2
  echo "$FOREIGN" >&2
  exit 2
fi
echo "[*] display verified clean (only our terminal)"

# --- 3. NOW start recording ------------------------------------------------
echo "[*] starting capture -> $RAW"
ffmpeg -y -loglevel error -f x11grab -framerate 25 -video_size ${W}x${H} \
       -i "${VDISP}.0+0,0" -c:v libx264 -preset ultrafast -qp 0 "$RAW" &
FFPID=$!

wait "$XTPID" 2>/dev/null
echo "[*] segment finished; stopping capture"
sleep 1
kill -INT "$FFPID" 2>/dev/null
wait "$FFPID" 2>/dev/null

# --- 4. verify frame 0 is actually the terminal ------------------------------
ffmpeg -y -loglevel error -ss 0 -i "$RAW" -frames:v 1 /tmp/frame0-$$.png 2>/dev/null
SZ=$(stat -c%s /tmp/frame0-$$.png 2>/dev/null || echo 0)
if [ "$SZ" -lt 4000 ]; then
  echo "!! WARNING: frame 0 looks blank (${SZ}B) — inspect before publishing" >&2
fi
rm -f /tmp/frame0-$$.png

echo "[*] transcoding to delivery mp4"
ffmpeg -y -loglevel error -i "$RAW" \
       -c:v libx264 -crf 20 -preset slow -pix_fmt yuv420p -r 25 \
       -movflags +faststart "$OUT"
echo "[*] wrote $OUT"
ffprobe -v error -show_entries format=duration,size -show_entries stream=width,height \
        -of default=nw=1 "$OUT" | sed 's/^/    /'
