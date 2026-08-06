#!/usr/bin/env bash
# Camera-facing terminal view: prove the hardware, then stream the live
# agent session log. Run on the instance (via ssh -t).
cd /root/rocm-autopilot
echo "=============================================================="
echo " rocm-autopilot · self-optimizing LLM deployment · Act II"
echo "=============================================================="
echo
echo "── GPU (measured, not assumed) ──────────────────────────────"
rocminfo 2>/dev/null | grep -m1 "gfx1100" | sed "s/^ *//"
rocm-smi 2>/dev/null | sed -n "7,9p"
echo
echo "── vLLM deployment ──────────────────────────────────────────"
curl -sf http://localhost:8000/v1/models | python3 -c "import json,sys; d=json.load(sys.stdin); print('serving:', d['data'][0]['id'])" 2>/dev/null
echo
echo "── waiting for agent session… ───────────────────────────────"
while true; do
  NEWEST=$(ls -t runs/session-*.log 2>/dev/null | head -1)
  [ -n "$NEWEST" ] && [ $(( $(date +%s) - $(stat -c %Y "$NEWEST") )) -lt 30 ] && break
  sleep 2
done
exec tail -F "$NEWEST"
