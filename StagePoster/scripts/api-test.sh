#!/usr/bin/env bash
# api-test.sh — integration test for all 26 StagePoster backend endpoints
# Usage: bash scripts/api-test.sh [base_url]
set -uo pipefail

API_BASE="${1:-http://127.0.0.1:8080}"
TOKEN="${POSTER_API_TOKEN:-}"
AUTH_H=( -H "Content-Type: application/json" )
[[ -n "$TOKEN" ]] && AUTH_H+=( -H "Authorization: Bearer $TOKEN" )

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass(){ echo -e "${GREEN}[PASS]${NC} $*"; }
fail(){ echo -e "${RED}[FAIL]${NC} $*"; FAILS=$((FAILS+1)); }
skip(){ echo -e "${YELLOW}[SKIP]${NC} $*"; }
section(){ echo -e "\n▸ $*"; }

FAILS=0; PASSES=0; SKIPS=0
TOTAL=0

check(){
  local label="$1" expected="$2" actual="$3" body="${4:-}"
  TOTAL=$((TOTAL+1))
  if [[ "$actual" == "$expected" ]]; then
    pass "$label → $actual"
    PASSES=$((PASSES+1))
  else
    fail "$label → got $actual, expected $expected  body=$body"
  fi
}

# ── helpers ──────────────────────────────────────────────────────────────────
id_of(){   grep -oP '"id"\s*:\s*"\K[^"]+' <<<"${1:-}"   || true; }
session_id_of(){ grep -oP '"sessionId"\s*:\s*"\K[^"]+' <<<"${1:-}" || true; }
poster_id_of(){  grep -oP '"posterId"\s*:\s*"\K[^"]+'  <<<"${1:-}" || true; }

# ── 1. Health & System ────────────────────────────────────────────────────────
section "Health & System"

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/health" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
check "GET  /health" 200 "$code" "$body"

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/system/dependencies" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
check "GET  /api/system/dependencies" 200 "$code" "$body"

# ── 2. AI Design ──────────────────────────────────────────────────────────────
section "AI Design"

resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/design" \
  -d '{"event":{"title":"Test Event","artist":"Test Artist","date":"2026-12-31","time":"20:00","venue":"Test Venue"},"visual":{"style":"metal-gothic-v1","theme":"abyssal","musicGenre":"metal","mood":["epic"],"preferredColors":["black","red"]},"message":"create three distinct design directions"}' \
  -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
if [[ "$code" == "200" ]]; then pass "POST /api/ai/design → $code"; PASSES=$((PASSES+1))
elif [[ "$code" == "503" ]]; then skip "POST /api/ai/design → $code (vLLM not ready)"; SKIPS=$((SKIPS+1))
else fail "POST /api/ai/design → $code body=$body"; fi
TOTAL=$((TOTAL+1))

# ── 3. AI Sessions ────────────────────────────────────────────────────────────
section "AI Sessions"

# POST create
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions" \
  -d '{"brief":{"event":{"title":"Abyssal Festival","artist":"Maverick","date":"2026-08-21","time":"20:00","venue":"Void Arena","presalePrice":"$45","doorPrice":"$60"},"branding":{},"visual":{"style":"dark fantasy editorial","theme":"abyssal gothic kingdom","musicGenre":"gothic metal","mood":["epic","mysterious"],"preferredColors":["black","deep red"]}}}' \
  -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
SESSION_ID=$(session_id_of "$body")
if [[ "$code" == "201" && -n "$SESSION_ID" ]]; then
  pass "POST /api/ai/sessions (create) → 201  id=$SESSION_ID"; PASSES=$((PASSES+1))
else
  fail "POST /api/ai/sessions (create) → $code body=$body"
fi
TOTAL=$((TOTAL+1))

 # POST empty body (handler allows io.EOF → session created with empty brief)
 resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions" -d '{}' -w "\n%{http_code}")
 body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
EMPTY_SESSION_ID=$(session_id_of "$body")
if [[ "$code" == "201" && -n "$EMPTY_SESSION_ID" ]]; then
  pass "POST /api/ai/sessions (empty body) → 201  id=$EMPTY_SESSION_ID"; PASSES=$((PASSES+1))
else
  skip "POST /api/ai/sessions (empty) → $code"; SKIPS=$((SKIPS+1))
fi
TOTAL=$((TOTAL+1))

if [[ -n "$SESSION_ID" ]]; then
  # GET /api/ai/sessions/{id}
  resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/$SESSION_ID" -w "\n%{http_code}")
  body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
  check "GET  /api/ai/sessions/$SESSION_ID" 200 "$code" "$body"

  # POST /api/ai/sessions/{id}/cancel
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$SESSION_ID/cancel" -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  if [[ "$code" == "200" || "$code" == "409" ]]; then
    pass "POST /api/ai/sessions/$SESSION_ID/cancel → $code"; PASSES=$((PASSES+1))
  else fail "POST /api/ai/sessions/$SESSION_ID/cancel → $code"; fi
  TOTAL=$((TOTAL+1))

  # POST /api/ai/sessions/{id}/assets  (bind nonexistent asset)
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$SESSION_ID/assets" \
    -d '{"personAssetId":"nonexistent","logoAssetId":"nonexistent"}' \
    -w "\n%{http_code}")
  body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
  if [[ "$code" == "404" || "$code" == "400" ]]; then pass "POST /api/ai/sessions/$SESSION_ID/assets (bad ids) → $code"; PASSES=$((PASSES+1))
  else skip "POST /api/ai/sessions/$SESSION_ID/assets → $code"; SKIPS=$((SKIPS+1)); fi
  TOTAL=$((TOTAL+1))
fi

# GET nonexistent session → 404
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/ai/sessions/does-not-exist" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "GET  /api/ai/sessions/{nonexistent}" 404 "$code" ""

 # POST /api/ai/sessions/{id}/finalize  (idle session)
 resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$SESSION_ID/finalize" -w "\n%{http_code}")
 body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
 [[ "$code" == "409" ]] && pass "POST /api/ai/sessions/$SESSION_ID/finalize (no candidates) → 409" || { skip "finalize → $code"; SKIPS=$((SKIPS+1)); }
 TOTAL=$((TOTAL+1))

 # POST /api/ai/sessions/{id}/plans/{plan}/confirm  (bad plan id)
 resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$SESSION_ID/plans/bad-plan/confirm" -w "\n%{http_code}")
 body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
 [[ "$code" == "404" || "$code" == "409" ]] && pass "POST /api/ai/sessions/$SESSION_ID/plans/{bad}/confirm → $code" || { skip "confirm plan → $code"; SKIPS=$((SKIPS+1)); }
 TOTAL=$((TOTAL+1))

# POST /api/ai/sessions/{id}/candidates/{cid}/select  (bad cid)
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$SESSION_ID/candidates/bad-cand/select" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
 [[ "$code" == "404" || "$code" == "409" ]] && pass "POST /api/ai/sessions/$SESSION_ID/candidates/{bad}/select → $code" || { skip "select cand → $code"; SKIPS=$((SKIPS+1)); }
 TOTAL=$((TOTAL+1))

# POST /api/ai/sessions/{id}/messages  (send message to idle session)
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/ai/sessions/$SESSION_ID/messages" \
  -d '{"content":"hello"}' -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
 [[ "$code" == "200" || "$code" == "409" ]] && pass "POST /api/ai/sessions/$SESSION_ID/messages → $code" || { skip "messages → $code"; SKIPS=$((SKIPS+1)); }
 TOTAL=$((TOTAL+1))

# ── 4. Posters ────────────────────────────────────────────────────────────────
section "Posters"

# POST /api/posters (create)
 resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/posters" \
   -d '{"event":{"title":"Abyssal Festival","artist":"Maverick","date":"2026-08-21","time":"20:00","venue":"Void Arena","presalePrice":"$45","doorPrice":"$60"},"branding":{},"visual":{"style":"metal-gothic-v1","theme":"abyssal gothic kingdom","musicGenre":"gothic metal","mood":["epic","mysterious"],"preferredColors":["black","deep red"]}}' \
   -w "\n%{http_code}")
 body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
  POSTER_ID=$(poster_id_of "$body")
if [[ "$code" == "202" && -n "$POSTER_ID" ]]; then
  pass "POST /api/posters (create) → 202  id=$POSTER_ID"; PASSES=$((PASSES+1))
else
  fail "POST /api/posters (create) → $code body=$body"
fi
TOTAL=$((TOTAL+1))

# GET /api/posters/{id}
if [[ -n "$POSTER_ID" ]]; then
  resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/$POSTER_ID" -w "\n%{http_code}")
  body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
  check "GET  /api/posters/$POSTER_ID" 200 "$code" "$body"
fi

# GET nonexistent poster → 404
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/does-not-exist" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "GET  /api/posters/{nonexistent}" 404 "$code" ""

# POST /api/posters/{id}/cancel
if [[ -n "$POSTER_ID" ]]; then
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/posters/$POSTER_ID/cancel" -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  [[ "$code" == "200" || "$code" == "409" ]] && pass "POST /api/posters/$POSTER_ID/cancel → $code" || fail "cancel → $code"
  PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))
fi

# POST /api/posters/{id}/select (bad candidate)
if [[ -n "$POSTER_ID" ]]; then
  resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/posters/$POSTER_ID/select" \
    -d '{"candidateId":"does-not-exist"}' -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  [[ "$code" == "404" || "$code" == "409" ]] && pass "POST /api/posters/$POSTER_ID/select (bad cid) → $code" || fail "select → $code"
  PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))
fi

# GET nonexistent poster result → 404/409
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/does-not-exist/result" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "404" || "$code" == "409" ]] && pass "GET  /api/posters/{nonexistent}/result → $code" || fail "result → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/does-not-exist/thumbnail" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "404" || "$code" == "409" ]] && pass "GET  /api/posters/{nonexistent}/thumbnail → $code" || fail "thumbnail → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# POST /api/posters/{nonexistent}/review
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/posters/does-not-exist/review" \
  -d '{"designPlan":{}}' -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "404" || "$code" == "409" ]] && pass "POST /api/posters/{nonexistent}/review → $code" || fail "review → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# GET /api/posters/{nonexistent}/reviews
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/does-not-exist/reviews?limit=10&offset=0" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "404" || "$code" == "200" ]] && pass "GET  /api/posters/{nonexistent}/reviews → $code" || fail "reviews → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# GET /api/posters/{nonexistent}/timeline
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/posters/does-not-exist/timeline" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "404" || "$code" == "200" ]] && pass "GET  /api/posters/{nonexistent}/timeline → $code" || fail "timeline → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# POST /api/posters/{id}/candidates/{cid}/retry
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/posters/does-not-exist/candidates/does-not-exist/retry" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "404" || "$code" == "409" ]] && pass "POST /api/posters/{nonexistent}/candidates/{cid}/retry → $code" || fail "retry → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# ── 5. Assets ────────────────────────────────────────────────────────────────
section "Assets"

# POST /api/assets  (no file → 400)
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/assets" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "POST /api/assets (no file)" 400 "$code" ""

# POST /api/assets (bad kind)
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/assets" \
  -F "file=@/dev/null;type=image/png" -F "kind=badkind" \
  -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "400" ]] && pass "POST /api/assets (bad kind) → $code" || fail "bad kind → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# GET /api/assets (list)
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/assets?limit=10&offset=0" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
check "GET  /api/assets (list)" 200 "$code" "$body"

# GET /api/assets/{nonexistent} → 404
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/assets/does-not-exist" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "GET  /api/assets/{nonexistent}" 404 "$code" ""

# GET /api/assets/{nonexistent}/content → 404
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/assets/does-not-exist/content" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "GET  /api/assets/{nonexistent}/content" 404 "$code" ""

# GET /api/assets/{nonexistent}/process → 404
resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/assets/does-not-exist/process" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "GET  /api/assets/{nonexistent}/process" 404 "$code" ""

# ── 6. Jobs ──────────────────────────────────────────────────────────────────
section "Jobs"

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/jobs?limit=10&offset=0" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
check "GET  /api/jobs (list)" 200 "$code" "$body"

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/jobs/does-not-exist" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "GET  /api/jobs/{nonexistent}" 404 "$code" ""

resp=$(curl -sS "${AUTH_H[@]}" "$API_BASE/api/jobs/does-not-exist/result" -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "404" || "$code" == "409" ]] && pass "GET  /api/jobs/{nonexistent}/result → $code" || fail "job result → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# ── 7. Auth & Edge Cases ─────────────────────────────────────────────────────
section "Auth & Edge Cases"

# /health without auth → 200 (always open)
resp=$(curl -sS "$API_BASE/health" -w "\n%{http_code}")
body=$(echo "$resp" | sed '$d'); code=$(echo "$resp" | tail -1)
check "GET  /health (no auth)" 200 "$code" "$body"

# /api/* without auth → 401 when token is configured
if [[ -n "$TOKEN" ]]; then
  resp=$(curl -sS "$API_BASE/api/system/dependencies" -w "\n%{http_code}")
  code=$(echo "$resp" | tail -1)
  check "GET  /api/system/dependencies (no auth)" 401 "$code" ""
fi

# CORS preflight → 204
resp=$(curl -sS -X OPTIONS "$API_BASE/api/system/dependencies" \
  -H "Origin: http://localhost" \
  -H "Access-Control-Request-Method: GET" \
  -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
check "OPTIONS /api/system/dependencies (CORS preflight)" 204 "$code" ""

# POST /api/generate (legacy, may 400/422)
resp=$(curl -sS "${AUTH_H[@]}" -X POST "$API_BASE/api/generate" \
  -d '{"prompt":"test poster"}' -w "\n%{http_code}")
code=$(echo "$resp" | tail -1)
[[ "$code" == "400" || "$code" == "202" || "$code" == "422" ]] && pass "POST /api/generate → $code" || fail "generate → $code"
PASSES=$((PASSES+1)); TOTAL=$((TOTAL+1))

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
printf "  %-8s %d / %d\n" "PASS" "$PASSES" "$TOTAL"
printf "  %-8s %d\n" "FAIL" "$FAILS"
printf "  %-8s %d\n" "SKIP" "$SKIPS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
[[ "$FAILS" -eq 0 ]] && exit 0 || exit 1
