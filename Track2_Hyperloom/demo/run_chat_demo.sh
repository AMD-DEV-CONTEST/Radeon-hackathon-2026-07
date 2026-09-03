#!/usr/bin/env bash
# Multi-turn conversation with Hyperloom, live on the card.
cd "$(dirname "$0")/.."
clear
cat <<'HDR'

  ════════════════════════════════════════════════════════════════
    HYPERLOOM — a conversation, not a script
  ════════════════════════════════════════════════════════════════

  Four turns, one context. The brain is a 35B tool-calling model
  resident on the Radeon GPU. Every tool below executes for real on
  this machine. Nothing on the model's side is pre-written.

HDR
sleep 4
python3 demo/chat_session.py
echo
sleep 3
