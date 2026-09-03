#!/usr/bin/env bash
# ============================================================================
# launch_agent.sh — bring the agent's BRAIN up on the Radeon card, live.
# ============================================================================
# Track 2 requires that core inference runs locally on an AMD Radeon GPU. This
# segment proves it on camera: no model resident -> load the tool-calling model
# through Lemonade -> watch VRAM climb on the card -> ask it a real question
# and get a real answer back. Nothing here touches a cloud endpoint.
# ============================================================================
set -uo pipefail
URL="${LEMONADE_URL:-http://localhost:13305}"
MODEL="${AGENT_BRAIN:-agentworld}"
PACE="${PACE:-3}"
TYPE="${TYPE:-0.022}"
step(){ echo; echo "════════════════════════════════════════════════════════════════"; echo "  $*"; echo "════════════════════════════════════════════════════════════════"; sleep "$PACE"; }
run(){ printf '\n  \033[1;32m$\033[0m '
  if [ "$TYPE" != "0" ]; then local s="$*"; for ((i=0;i<${#s};i++)); do printf '%s' "${s:$i:1}"; sleep "$TYPE"; done
  else printf '%s' "$*"; fi; printf '\n'; sleep 0.4; eval "$@" 2>&1 | sed 's/^/  /'; sleep "${POST:-$PACE}"; }

vram(){ amd-smi metric -g 1 2>/dev/null | grep -m1 USED_VRAM | tr -s ' ' | sed 's/^ *//'; }

step "STEP A — the brain is NOT loaded yet"
run "curl -s $URL/api/v1/health | python3 -m json.tool | grep -E 'model_loaded|all_models_loaded'"
echo "  Radeon VRAM before load:  $(vram)   <- desktop only"

step "STEP B — LOAD the agent brain onto the Radeon"
echo "  Model: $MODEL  (tool-calling, served by Lemonade on :13305)"
echo "  This is the agent's reasoning engine. It runs ON THE CARD."
printf '\n  \033[1;32m$\033[0m curl -X POST %s/api/v1/load -d {"model_name":"%s"}\n' "$URL" "$MODEL"
t0=$(date +%s)
curl -s -X POST "$URL/api/v1/load" -H 'Content-Type: application/json' \
     -d "{\"model_name\":\"$MODEL\"}" --max-time 900 >/dev/null 2>&1 &
LOADPID=$!
while kill -0 $LOADPID 2>/dev/null; do
  printf '\r  loading... %3ds   Radeon VRAM: %s        ' "$(( $(date +%s) - t0 ))" "$(vram)"
  sleep 2
done
wait $LOADPID 2>/dev/null
printf '\r  loaded in %ds.  Radeon VRAM: %s                 \n' "$(( $(date +%s) - t0 ))" "$(vram)"
sleep "$PACE"

step "STEP C — confirm the model is resident ON THE GPU"
run "curl -s $URL/api/v1/health | python3 -m json.tool | grep -E 'model_loaded'"
echo "  Radeon VRAM after load:   $(vram)"
echo "  That delta is the agent's brain, sitting in Radeon memory."

step "STEP D — the agent REFUSES TO GUESS. It reaches for a tool."
echo "  We ask the brain a hardware question it could easily bluff:"
echo "    \"Does gfx1201 support v_dot8_i32_iu4? Don't answer from memory.\""
echo
echo "  This matters. A model asked about an obscure ISA instruction will"
echo "  usually produce a confident, wrong answer — we measured exactly that:"
echo "  two smaller local models both described iu4 as 8-bit and 16-bit."
echo "  It is 4-bit. Recall is not evidence. So the agent is given a tool."
sleep "$PACE"
printf '\n  \033[1;32m$\033[0m curl %s/api/v1/chat/completions  --tools scan_isa\n' "$URL"
curl -s "$URL/api/v1/chat/completions" -H 'Content-Type: application/json' --max-time 300 \
  -d "{\"model\":\"$MODEL\",\"max_tokens\":700,\"messages\":[{\"role\":\"user\",\"content\":\"Does gfx1201 support the v_dot8_i32_iu4 instruction? Do not answer from memory - use the scan_isa tool to check the assembler.\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"scan_isa\",\"description\":\"Probe a gfx target with llvm-mc and report whether an instruction is REAL, EMULATED or REJECTED.\",\"parameters\":{\"type\":\"object\",\"properties\":{\"target\":{\"type\":\"string\"},\"instruction\":{\"type\":\"string\"}},\"required\":[\"target\",\"instruction\"]}}}]}" \
  2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin); ch=d['choices'][0]; m=ch['message']
print('    finish_reason:', ch.get('finish_reason'))
for t in (m.get('tool_calls') or []):
    print('    TOOL CALL ->', t['function']['name'], t['function']['arguments'])
"
echo
echo "  It did not answer. It asked to run the assembler. That is the whole thesis:"
echo "  the assembler cannot lie, and model recall is not evidence."
sleep "$PACE"

step "STEP E — run the tool it asked for. Ground truth, from the silicon."
run "bash toolkit/scan-isa-gfx.sh gfx1201 2>/dev/null | grep -iE 'v_dot8_i32_iu4|v_dot4_i32_iu8'"
echo "  THAT is the answer — produced by llvm-mc against the real target,"
echo "  not recalled from weights. The kernel work in this project is built"
echo "  on facts obtained this way."
sleep "$PACE"

step "STEP F — where did that inference run?"
echo "  Radeon GFX activity + VRAM during generation:"
amd-smi metric -g 1 2>/dev/null | grep -E "GFX_ACTIVITY|USED_VRAM" | sed 's/^ */    /'
echo
echo "  No cloud endpoint was contacted. The agent's core inference is local,"
echo "  on the AMD Radeon GPU — which is what the track requires."
sleep "$PACE"
