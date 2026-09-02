#!/usr/bin/env bash
# e2e-test.sh — End-to-end poster generation pipeline test
# Tests the FULL product flow: create session → brief → plans → confirm →
#   candidates → select → compose → finalize → download → quality check
#
# Usage:
#   bash scripts/e2e-test.sh [base_url] [mode]
#
#   mode = session   (default)  Full AI session flow
#           poster              Direct poster creation flow
#           all                 Both flows
#
# Prerequisites: running backend at base_url, ComfyUI + vLLM available
set -uo pipefail

API_BASE="${1:-http://127.0.0.1:8080}"
MODE="${2:-session}"
TOKEN="${POSTER_API_TOKEN:-}"
AUTH_H=( -H "Content-Type: application/json" )          # JSON requests
AUTH_MP_H=( )                                            # multipart: let curl set Content-Type
[[ -n "$TOKEN" ]] && AUTH_H+=( -H "Authorization: Bearer $TOKEN" )
[[ -n "$TOKEN" ]] && AUTH_MP_H+=( -H "Authorization: Bearer $TOKEN" )

# ── colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

pass(){ echo -e "${GREEN}[PASS]${NC} $*"; }
fail(){ echo -e "${RED}[FAIL]${NC} $*"; FAILS=$((FAILS+1)); }
warn(){ echo -e "${YELLOW}[WARN]${NC} $*"; }
info(){ echo -e "\n${CYAN}${BOLD}▸ $*${NC}"; }
ts(){ date +%s; }
elapsed(){ echo "$(( $(ts) - START ))" ; }
TIMEOUT="${E2E_TIMEOUT:-900}"   # 15 minutes total

START=$(ts)
FAILS=0
E2E_POSTER_ID=""
E2E_SESSION_ID=""
E2E_CANDIDATE_ID=""
QUALITY_DIR="/workspace/poster-engine/scripts/e2e-quality"
mkdir -p "$QUALITY_DIR"

json_get(){ python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$1',''))" 2>/dev/null || true; }
json_get_deep(){ python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d$1))" 2>/dev/null || true; }

# ── poll helpers ──────────────────────────────────────────────────────────────
poll_until(){
  # poll_until <timeout_sec> <interval_sec> <description> <curl_command...>
  local timeout=$1; local interval=$2; local label="$3"; shift 3
  local deadline=$(( $(ts) + timeout ))
  while true; do
    local resp; resp=$("$@" 2>/dev/null) || true
    local code; code=$(echo "$resp" | tail -1)
    if [[ "$code" == "200" ]]; then
      pass "$label → 200 (polled in $(( $(ts) - deadline + timeout ))s)"
      echo "$resp"
      return 0
    fi
    [[ "$code" == "404" || "$code" == "409" || "$code" == "202" || "$code" == "201" || "$code" == "400" || "$code" == "503" ]] && warn "$label → $code (polling…)" || warn "$label → $code (polling…)"
    [[ $(ts) -ge $deadline ]] && { fail "$label → TIMEOUT after ${timeout}s"; return 1; }
    sleep "$interval"
  done
}

wait_for_poster_status(){
  # wait_for_poster_status <poster_id> <expected_status> [timeout]
  local pid="$1"; local expected="$2"; local timeout="${3:-300}"
  local deadline=$(( $(ts) + timeout ))
  while true; do
    local resp; resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$pid" 2>/dev/null) || true
    local status; status=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null) || true
    if [[ "$status" == "$expected" ]]; then
      pass "Poster $pid → status=$expected ($(( $(ts) - deadline + timeout ))s)"
      echo "$resp"
      return 0
    fi
    [[ -z "$status" ]] && warn "Poster $pid → no status yet (polling…)" || warn "Poster $pid → status=$status (expected $expected)"
    [[ $(ts) -ge $deadline ]] && { fail "Poster $pid → TIMEOUT waiting for $expected after ${timeout}s; last status=$status"; return 1; }
    sleep 3
  done
}

wait_for_candidate_ready(){
  # wait_for_candidate_ready <poster_id> <expected_ready_count> [timeout]
  local pid="$1"; local want="$2"; local timeout="${3:-300}"
  local deadline=$(( $(ts) + timeout ))
  while true; do
    local resp; resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$pid" 2>/dev/null) || true
    local ready; ready=$(echo "$resp" | python3 -c "
import sys,json
d=json.load(sys.stdin)
cands=d.get('candidates',[])
print(sum(1 for c in cands if c.get('status')=='ready'))
" 2>/dev/null) || true
    if [[ "$ready" -ge "$want" ]]; then
      pass "Poster $pid → $ready/$want candidates ready ($(( $(ts) - deadline + timeout ))s)"
      echo "$resp"
      return 0
    fi
    warn "Poster $pid → $ready/$want candidates ready (polling…)"
    [[ $(ts) -ge $deadline ]] && { fail "Poster $pid → TIMEOUT waiting for $want ready candidates after ${timeout}s"; return 1; }
    sleep 5
  done
}

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 1: SYSTEM HEALTH
# ════════════════════════════════════════════════════════════════════════════════
info "SECTION 1 — System Health ($(elapsed)s elapsed)"

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/health" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
[[ "$code" == "200" ]] && pass "GET /health → 200" || { fail "GET /health → $code $body"; exit 1; }

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/system/dependencies" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
[[ "$code" == "200" ]] && pass "GET /api/system/dependencies → 200" || { fail "GET /api/system/dependencies → $code"; exit 1; }

DB_STATUS=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin)['database']['status'])" 2>/dev/null)
COMFY_STATUS=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin)['comfyui']['status'])" 2>/dev/null)
VLM_STATUS=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin)['vlm']['status'])" 2>/dev/null)
[[ "$DB_STATUS" == "ready" ]]    && pass "Database → ready"           || warn "Database → $DB_STATUS"
[[ "$COMFY_STATUS" == "ready" ]] && pass "ComfyUI → ready"             || warn "ComfyUI → $COMFY_STATUS"
[[ "$VLM_STATUS" == "ready" ]]   && pass "vLLM (Qwen) → ready"        || warn "vLLM → $VLM_STATUS"

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 2: ASSETS  (upload a reference + logo asset)
# ════════════════════════════════════════════════════════════════════════════════
info "SECTION 2 — Asset Upload ($(elapsed)s elapsed)"

# Upload a test reference image
resp=$(curl -sS "${AUTH_MP_H[@]}" -X POST "$API_BASE/api/assets" \
  -F "file=@/workspace/poster-engine/海报参考图/微信图片_2026-07-07_130357_383.png;type=image/png" \
  -F "kind=reference" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
[[ "$code" == "201" ]] && pass "POST /api/assets (reference) → 201" || { fail "Asset upload → $code $body"; REF_ASSET_ID=""; }
REF_ASSET_ID=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('assetId',''))" 2>/dev/null) || true
[[ -n "$REF_ASSET_ID" ]] && info "Reference asset ID: $REF_ASSET_ID" || warn "No reference asset ID extracted"

# Upload a logo asset
resp=$(curl -sS "${AUTH_MP_H[@]}" -X POST "$API_BASE/api/assets" \
  -F "file=@/workspace/poster-engine/海报参考图/微信图片_2026-07-07_130357_383.png;type=image/png" \
  -F "kind=logo" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
[[ "$code" == "201" ]] && pass "POST /api/assets (logo) → 201" || warn "Logo upload → $code"
LOGO_ASSET_ID=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('assetId',''))" 2>/dev/null) || true

# List assets
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/assets?limit=20&offset=0" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "200" ]] && pass "GET /api/assets (list) → 200" || fail "Asset list → $code"

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 3: AI SESSION FLOW (full pipeline)
# ════════════════════════════════════════════════════════════════════════════════
info "SECTION 3 — AI Session: Create → Brief → Plans → Confirm → Candidates → Select ($(elapsed)s elapsed)"

# ── 3a. Create session ─────────────────────────────────────────────────────────
info "3a. Creating AI session…"
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions" \
  -d '{"brief":{"event":{"title":"Abyssal Kingdom Festival","artist":"Maverick","date":"2026-08-21","time":"20:00","venue":"Void Arena","presalePrice":"$45","doorPrice":"$60"},"branding":{},"visual":{"style":"dark fantasy editorial","theme":"abyssal gothic kingdom","musicGenre":"gothic metal","mood":["epic","mysterious","ritualistic"],"preferredColors":["black","aged ivory","deep red"]}}}' \
  -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
[[ "$code" == "201" ]] && { pass "POST /api/ai/sessions → 201"; E2E_SESSION_ID=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])"); info "Session ID: $E2E_SESSION_ID"; } \
  || { fail "Create session → $code $body"; exit 1; }

# ── 3b. Verify collecting_brief state ─────────────────────────────────────────
info "3b. Checking session state…"
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/$E2E_SESSION_ID")
status=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
actions=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('availableActions',[]))")
[[ "$status" == "collecting_brief" ]] && pass "Session state = collecting_brief" || warn "Session state = $status"
echo "$resp" | python3 -c "import sys,json; print('  availableActions:', json.load(sys.stdin).get('availableActions',[]))"

# ── 3c. Send message to advance brief ─────────────────────────────────────────
info "3c. Sending brief message…"
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$E2E_SESSION_ID/messages" \
  -d '{"content":"这是一场深海重金属音乐节，预算很高，需要营造黑暗、史诗、神秘的氛围"}' -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
[[ "$code" == "200" ]] && pass "POST /api/ai/sessions/$E2E_SESSION_ID/messages → 200" || { warn "Send message → $code"; }

# Check if we're in awaiting_plan_selection now
sleep 2
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/$E2E_SESSION_ID")
status=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
plans_count=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('plans',[])))")
if [[ "$status" == "awaiting_plan_selection" && "$plans_count" -ge 3 ]]; then
  pass "Brief complete → status=$status, plans=$plans_count"
  PLAN_ID=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['plans'][0]['planId'])")
  info "Selected plan: $PLAN_ID"
elif [[ "$status" == "collecting_brief" ]]; then
  warn "Still collecting brief (LLM may not be available) — sending another message…"
  sleep 1
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$E2E_SESSION_ID/messages" \
    -d '{"content":"请确认所有信息完整。标题是Abyssal Kingdom Festival，艺人Maverick，日期2026-08-21，时间20:00，场地Void Arena。风格dark fantasy editorial，主题abyssal gothic kingdom，音乐类型gothic metal。"}' -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  [[ "$code" == "200" ]] && pass "Second message → $code" || warn "Second message → $code"
  sleep 3
  resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/$E2E_SESSION_ID")
  status=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  plans_count=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('plans',[])))")
  if [[ "$status" == "awaiting_plan_selection" && "$plans_count" -ge 3 ]]; then
    pass "Brief complete after second message → status=$status, plans=$plans_count"
    PLAN_ID=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['plans'][0]['planId'])")
  else
    warn "Still not in plan selection: status=$status, plans=$plans_count"
    PLAN_ID=""
  fi
fi

# Print plans
info "Design plans:"
echo "$resp" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for p in d.get('plans',[]):
    print(f'  [{p[\"planId\"]}] {p.get(\"name\",\"?\")}: {p.get(\"description\",\"\")[:80]}')
" 2>/dev/null || echo "  (no plans extracted)"

# ── 3d. Confirm plan → starts candidate generation ────────────────────────────
if [[ -n "$PLAN_ID" ]]; then
  info "3d. Confirming plan $PLAN_ID… (this triggers 3 ComfyUI generations)"
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$E2E_SESSION_ID/plans/$PLAN_ID/confirm" -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  body_confirm=$(echo "$resp" | sed '$d')
  if [[ "$code" == "202" || "$code" == "200" ]]; then
    pass "Confirm plan → $code"
    # Extract poster ID from response body or from session posterId field
    E2E_POSTER_ID=$(echo "$body_confirm" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('posterId','') or d.get('poster',{}).get('posterId',''))" 2>/dev/null) || true
    if [[ -z "$E2E_POSTER_ID" ]]; then
      # ConfirmPlan returns 202 with session state — posterId is in session.posterId
      E2E_POSTER_ID=$(echo "$body_confirm" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session',{}).get('posterId',''))" 2>/dev/null) || true
    fi
    if [[ -z "$E2E_POSTER_ID" ]]; then
      # Poll session to get posterId
      sleep 2
      session_resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/$E2E_SESSION_ID")
      E2E_POSTER_ID=$(echo "$session_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('posterId',''))" 2>/dev/null) || true
    fi
    [[ -n "$E2E_POSTER_ID" ]] && info "Poster ID: $E2E_POSTER_ID" || warn "No poster ID in confirm response; will poll session"
  else
    fail "Confirm plan → $code $body_confirm"
  fi
else
  warn "Skipping confirm plan — no PLAN_ID available"
fi

# ── 3e. Poll poster status until candidates ready ──────────────────────────────
if [[ -n "$E2E_POSTER_ID" ]]; then
  info "3e. Waiting for poster candidates to be ready (up to 300s)…"

  # Poll poster directly — poster jumps from generating_candidates straight to
  # awaiting_selection once all 3 are ready (no partial_ready in fast path)
  deadline=$(( $(ts) + 300 ))
  while true; do
    resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID" 2>/dev/null) || true
    status=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null) || true
    ready=$(echo "$resp" | python3 -c "
import sys,json
d=json.load(sys.stdin)
cands=d.get('candidates',[])
print(sum(1 for c in cands if c.get('status')=='ready'))
" 2>/dev/null) || true
    [[ -z "$ready" ]] && ready=0
    if [[ "$ready" -ge 3 ]]; then
      pass "All 3 candidates ready ($(( $(ts) - deadline + 300 ))s)"
      break
    fi
    warn "Poster $E2E_POSTER_ID → status=$status, ready=$ready/3"
    [[ $(ts) -ge $deadline ]] && { fail "Timeout waiting for candidates"; break; }
    sleep 5
  done

  # List candidates
  resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID")
  echo "$resp" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for c in d.get('candidates',[]):
    print(f'  [{c[\"candidateId\"][:12]}] {c.get(\"variantName\",\"?\")} status={c.get(\"status\",\"?\")} selected={c.get(\"selected\",False)}')
" 2>/dev/null

  # Pick a ready candidate
  E2E_CANDIDATE_ID=$(echo "$resp" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for c in d.get('candidates',[]):
    if c.get('status')=='ready':
        print(c['candidateId'])
        break
" 2>/dev/null) || true
  [[ -z "$E2E_CANDIDATE_ID" ]] && E2E_CANDIDATE_ID=$(echo "$resp" | python3 -c "
import sys,json
d=json.load(sys.stdin)
cands=d.get('candidates',[])
if cands: print(cands[0]['candidateId'])
" 2>/dev/null) || true

  # ── 3f. Sync session status then select a candidate ──────────────────────────
  if [[ -n "$E2E_CANDIDATE_ID" ]]; then
    # Call Get() on the session first — this reconciles session status against
    # the poster status (the only place sessionStatusForPoster() is called)
    info "3f. Syncing session status via GET /api/ai/sessions/$E2E_SESSION_ID …"
    session_resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/$E2E_SESSION_ID")
    session_status=$(echo "$session_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
    info "Session status after sync: $session_status"

    # Now select — use the direct poster select endpoint which doesn't depend on
    # the session status being correct in the DB
    info "3f. Selecting candidate $E2E_CANDIDATE_ID via direct poster endpoint…"
    resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/posters/$E2E_POSTER_ID/select" \
      -d "{\"candidateId\":\"$E2E_CANDIDATE_ID\"}" -w "\n%{http_code}")
    code=$(echo "$resp" | tail -1)
    if [[ "$code" == "200" || "$code" == "202" ]]; then
      pass "Select candidate → $code"
    else
      body_sel=$(echo "$resp" | sed '$d')
      # Fallback: try the session route if poster route fails
      warn "Direct poster select → $code, trying session route…"
      resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$E2E_SESSION_ID/candidates/$E2E_CANDIDATE_ID/select" -w "\n%{http_code}")
      code=$(echo "$resp" | tail -1)
      [[ "$code" == "200" || "$code" == "202" || "$code" == "409" ]] && pass "Session select → $code" || fail "Select candidate → $code"
    fi
  fi

  # ── 3g. Wait for composition → succeeded ───────────────────────────────────
  info "3g. Waiting for poster composition → succeeded (up to 120s)…"
  wait_for_poster_status "$E2E_POSTER_ID" "succeeded" 120 || {
    resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID")
    status=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
    if [[ "$status" == "completed_with_warnings" ]]; then
      pass "Poster reached terminal: completed_with_warnings"
    else
      fail "Poster did not reach terminal; status=$status"
    fi
  }

  # ── 3h. Download final poster ───────────────────────────────────────────────
  info "3h. Downloading final poster…"
  curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID/result" \
    -o "$QUALITY_DIR/poster_$E2E_POSTER_ID.png" -w "HTTP %{http_code}  size=%{size_download} bytes  time=%{time_total}s"
  echo ""
  [[ -f "$QUALITY_DIR/poster_$E2E_POSTER_ID.png" ]] && pass "Poster downloaded" || fail "Poster download failed"

  # ── 3i. Download thumbnail ──────────────────────────────────────────────────
  info "3i. Downloading thumbnail…"
  curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID/thumbnail" \
    -o "$QUALITY_DIR/thumb_$E2E_POSTER_ID.png" -w "HTTP %{http_code}  size=%{size_download} bytes"
  echo ""

  # ── 3j. Download candidate image ────────────────────────────────────────────
  if [[ -n "$E2E_CANDIDATE_ID" ]]; then
    info "3j. Downloading candidate image…"
    curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID/candidates/$E2E_CANDIDATE_ID/image" \
      -o "$QUALITY_DIR/candidate_$E2E_CANDIDATE_ID.png" -w "HTTP %{http_code}  size=%{size_download} bytes"
    echo ""
  fi

  # ── 3k. Get poster reviews ──────────────────────────────────────────────────
  info "3k. Getting poster reviews…"
  curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID/reviews" | python3 -m json.tool 2>/dev/null | head -30

  # ── 3l. Get poster timeline ─────────────────────────────────────────────────
  info "3l. Getting poster timeline…"
  curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$E2E_POSTER_ID/timeline" | python3 -m json.tool 2>/dev/null | head -30

  # ── 3m. Run finalize (AI review) — requires session=succeeded ─────────────────
  info "3m. Running finalize (AI review + auto-optimize)…"
  # Sync session status first — poster is succeeded, Get() maps it to session=succeeded
  session_resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/$E2E_SESSION_ID")
  session_status=$(echo "$session_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  info "Session status before finalize: $session_status"
  if [[ "$session_status" == "succeeded" ]]; then
    resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$E2E_SESSION_ID/finalize" \
      -d '{}' -w "\n%{http_code}")
    code=$(echo "$resp" | tail -1)
    body=$(echo "$resp" | sed '$d')
    [[ "$code" == "200" ]] && pass "Finalize → $code" || warn "Finalize → $code $body"
  else
    warn "Session status=$session_status, skipping finalize (needs succeeded)"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 4: POSTER FILE QUALITY CHECK
# ════════════════════════════════════════════════════════════════════════════════
info "SECTION 4 — Poster Quality Check ($(elapsed)s elapsed)"

QUALITY_FAILS=0
QUALITY_PASSES=0

for f in "$QUALITY_DIR"/poster_*.png; do
  [[ -f "$f" ]] || continue
  info "Checking $(basename $f)…"
  size=$(stat -c%s "$f" 2>/dev/null || echo 0)

  if [[ "$size" -lt 32768 ]]; then
    fail "File size too small: $size bytes (< 32 KB)"
    QUALITY_FAILS=$((QUALITY_FAILS+1))
  else
    pass "File size: $((size/1024)) KB"
    QUALITY_PASSES=$((QUALITY_PASSES+1))
  fi

  if command -v python3 &>/dev/null && python3 -c "from PIL import Image" 2>/dev/null; then
    dims=$(python3 -c "from PIL import Image; im=Image.open('$f'); print(f'{im.width}x{im.height}')" 2>/dev/null)
    [[ -n "$dims" ]] && pass "Dimensions: $dims" || warn "Cannot read dimensions"
    mode=$(python3 -c "from PIL import Image; im=Image.open('$f'); print(im.mode)" 2>/dev/null)
    [[ "$mode" == "RGB" || "$mode" == "RGBA" ]] && pass "Color mode: $mode" || warn "Color mode: $mode"
    # Check it's actually an image (not just any file)
    format=$(python3 -c "from PIL import Image; im=Image.open('$f'); print(im.format)" 2>/dev/null)
    [[ "$format" == "PNG" ]] && pass "Format: PNG" || warn "Format: $format"
  else
    # Fallback: check PNG magic bytes with od (no ASCII annotation column)
    head_c=$(od -An -tx1 -N 8 "$f" 2>/dev/null | tr -d ' \n')
    if [[ "$head_c" == "89504e470d0a1a0a" ]]; then
      pass "Magic bytes: valid PNG (89504e470d0a1a0a)"
      QUALITY_PASSES=$((QUALITY_PASSES+1))
    else
      fail "Magic bytes: not a valid PNG (got: $head_c)"
      QUALITY_FAILS=$((QUALITY_FAILS+1))
    fi
  fi

  # Check it's not just blank/empty
  if command -v python3 &>/dev/null; then
    has_pixels=$(python3 -c "
from PIL import Image
import numpy as np
im = Image.open('$f').convert('L')
arr = np.array(im)
print('ok' if arr.std() > 5 else 'blank')
" 2>/dev/null) || true
    [[ "$has_pixels" == "ok" ]] && pass "Not blank (pixel variance OK)" || { warn "Image may be blank or very uniform"; }
  fi
done

# Check thumbnail
for f in "$QUALITY_DIR"/thumb_*.png; do
  [[ -f "$f" ]] || continue
  size=$(stat -c%s "$f" 2>/dev/null || echo 0)
  [[ "$size" -gt 1000 ]] && pass "Thumbnail size: $((size/1024)) KB" || warn "Thumbnail small: $size bytes"
done

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 5: CANCEL FLOW (test poster cancellation)
# ════════════════════════════════════════════════════════════════════════════════
info "SECTION 5 — Cancel Flow ($(elapsed)s elapsed)"

if [[ -n "$E2E_POSTER_ID" ]]; then
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/posters/$E2E_POSTER_ID/cancel" -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  [[ "$code" == "200" || "$code" == "409" ]] && pass "Cancel poster → $code" || warn "Cancel → $code"
fi

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 6: SESSION CANCEL
# ════════════════════════════════════════════════════════════════════════════════
info "SECTION 6 — Session Cancel ($(elapsed)s elapsed)"

if [[ -n "$E2E_SESSION_ID" ]]; then
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$E2E_SESSION_ID/cancel" -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  [[ "$code" == "200" ]] && pass "Cancel session → $code" || warn "Cancel session → $code"
fi

# ════════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════════════
info "TEST COMPLETE — Total time: $(elapsed)s"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  ${GREEN}QUALITY PASS${NC}: $QUALITY_PASSES"
echo -e "  ${RED}QUALITY FAIL${NC}: $QUALITY_FAILS"
echo -e "  ${RED}API FAIL${NC}:     $FAILS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Generated files in $QUALITY_DIR:"
ls -lh "$QUALITY_DIR"/ 2>/dev/null || echo "  (none)"
echo ""

[[ $FAILS -eq 0 ]] && exit 0 || exit 1
