#!/usr/bin/env bash
# ============================================================================
# intro_amd.sh — open on the AMD hardware itself. Provenance before claims.
# ============================================================================
# Establishes, on camera and from AMD's own tooling, exactly what silicon every
# number in this submission was produced on. No stock footage, no logos — the
# card identifying itself.
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"; unset ROCR_VISIBLE_DEVICES 2>/dev/null || true
PACE="${PACE:-3}"; TYPE="${TYPE:-0.022}"
R=$'\033[1;31m'; G=$'\033[1;32m'; W=$'\033[1;37m'; D=$'\033[2m'; O=$'\033[0m'
run(){ printf '\n  %s$%s ' "$G" "$O"
  if [ "$TYPE" != "0" ]; then local s="$*"; for ((i=0;i<${#s};i++)); do printf '%s' "${s:$i:1}"; sleep "$TYPE"; done
  else printf '%s' "$*"; fi; printf '\n'; sleep 0.4; eval "$@" 2>&1 | sed 's/^/  /'; sleep "${POST:-$PACE}"; }

clear
cat <<EOF

     ${R}█▀▀▀▄ ${W}HYPERLOOM${O}
     ${R}█▄▄▄▀${O}  an autonomous ROCm kernel-optimizer agent
     ${R}█   █${O}  for ${R}AMD Radeon${O}

     ${D}AMD AI DevMaster Hackathon  ·  Track 2: Agentic AI${O}

EOF
sleep "$PACE"

echo "  Before any claim, the hardware. This is AMD's own tooling reporting"
echo "  the card that produced every number in this submission."
sleep "$PACE"

run "amd-smi static -g 0 | grep -E 'MARKET_NAME|VENDOR_NAME|TARGET_GRAPHICS_VERSION'"
run "rocminfo | grep -B1 'Marketing Name:  *AMD' | grep -E 'Name:' | head -2"
run "\$HOME/.local/bin/hipcc --version | head -2"

echo
echo "  ${W}AMD Radeon AI PRO R9700${O} — ${W}gfx1201${O}, RDNA4, 32 GB."
echo "  Two of them in this workstation. Everything that follows runs here:"
echo "  the agent's own brain, the kernels it writes, and the measurements."
sleep "$PACE"
echo
echo "  ${D}Three results, all correctness-gated, all reproducible on this card:${O}"
echo "    ${G}decode${O}   int4 GEMV at ${W}97% of the measured memory roofline${O}"
echo "    ${G}prefill${O}  int4 2:4-sparse SWMMAC, ${W}3.67x${O} vs int8 WMMA"
echo "    ${G}comms${O}    INT6 compressed all-reduce, ${W}2.46x${O} smaller than fp16"
sleep "$PACE"
echo
echo "  How it gets there, start to finish:"
sleep "$PACE"
