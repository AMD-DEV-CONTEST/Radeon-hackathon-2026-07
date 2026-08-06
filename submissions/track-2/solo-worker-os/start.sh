#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Solo Worker OS — One-Click Launcher  (Bash / Git Bash / Mac)
#  Usage: bash start.sh   or   chmod +x start.sh && ./start.sh
# ─────────────────────────────────────────────────────────────

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ── Colors ────────────────────────────────────────────────────
AMBER='\033[38;2;251;191;36m'
GREEN='\033[38;2;52;211;153m'
RED='\033[38;2;248;113;113m'
DIM='\033[38;2;120;120;140m'
WHITE='\033[97m'
BOLD='\033[1m'
RST='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${RST}  $1"; }
warn() { echo -e "  ${AMBER}[..]${RST}  $1"; }
err()  { echo -e "  ${RED}[!!]${RST}  $1"; }
dim()  { echo -e "  ${DIM}      $1${RST}"; }
sep()  { echo -e "  ${AMBER}────────────────────────────────────────${RST}"; }

banner() {
  clear
  echo
  echo -e "  ${AMBER}${BOLD}╔══════════════════════════════════════════╗${RST}"
  echo -e "  ${AMBER}${BOLD}║                                          ║${RST}"
  echo -e "  ${AMBER}${BOLD}║   ${WHITE}Solo Worker OS${AMBER}  ·  Dev Launcher          ║${RST}"
  echo -e "  ${AMBER}${BOLD}║                                          ║${RST}"
  echo -e "  ${AMBER}${BOLD}╚══════════════════════════════════════════╝${RST}"
  echo
}

open_url() {
  local url="$1"
  if command -v xdg-open &>/dev/null; then
    xdg-open "$url" &>/dev/null &
  elif command -v open &>/dev/null; then
    open "$url" &
  elif command -v start &>/dev/null; then
    start "$url" &
  fi
}

# ── 1. Node.js ────────────────────────────────────────────────
banner

if ! command -v node &>/dev/null; then
  err "Node.js not found."
  dim "Install from https://nodejs.org (LTS recommended)"
  exit 1
fi

NODE_VER=$(node --version)
ok "Node.js $NODE_VER"

# ── 2. .env.local ─────────────────────────────────────────────
echo

if [ ! -f "$ROOT/.env.local" ]; then
  warn ".env.local not found — creating from template..."

  if [ -f "$ROOT/.env.example" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env.local"
    ok "Created .env.local"
  else
    err ".env.example missing. Create .env.local manually."
    exit 1
  fi

  echo
  echo -e "  ${WHITE}Fill in the following keys in .env.local:${RST}"
  dim "ANTHROPIC_API_KEY          = sk-ant-..."
  dim "NEXT_PUBLIC_SUPABASE_URL   = https://xxxx.supabase.co"
  dim "NEXT_PUBLIC_SUPABASE_ANON_KEY"
  dim "SUPABASE_SERVICE_ROLE_KEY"
  echo

  # Try to open in editor
  if command -v code &>/dev/null; then
    code "$ROOT/.env.local"
  elif [ -n "${EDITOR:-}" ]; then
    $EDITOR "$ROOT/.env.local"
  else
    echo -e "  ${AMBER}→ Edit $ROOT/.env.local then press Enter to continue${RST}"
  fi

  read -rp "  Press Enter after saving .env.local to continue..."
  echo

else
  ok ".env.local found"

  # Warn on placeholder values
  if grep -qE "sk-ant-xxxxxxxx|YOUR-PROJECT|your-anon-key|your-service-role" "$ROOT/.env.local" 2>/dev/null; then
    echo
    warn ".env.local still contains placeholder values!"
    dim "Edit the file with your real API keys."
    read -rp "  Continue anyway? (y/N) " ans
    [[ "$ans" =~ ^[Yy]$ ]] || exit 0
  fi
fi

# ── 3. Dependencies ────────────────────────────────────────────
if [ ! -d "$ROOT/node_modules" ]; then
  echo
  warn "node_modules not found — running npm install..."
  echo
  npm install
  echo
  ok "Dependencies installed"
else
  ok "node_modules present"
fi

# ── 4. Clear stale build cache ─────────────────────────────────
if [ -d "$ROOT/.next" ]; then
  warn "Clearing .next cache for clean start..."
  rm -rf "$ROOT/.next"
  ok ".next cache cleared"
fi

# ── 5. Launch ─────────────────────────────────────────────────
echo
sep
echo -e "  ${WHITE}${BOLD}Starting dev server...${RST}"
echo -e "  ${DIM}Local:  ${AMBER}http://localhost:3000/dashboard${RST}"
echo -e "  ${DIM}Stop:   Ctrl + C  |  First load ~30-60s${RST}"
sep
echo

# Open browser when port 3000 is ready (TCP poll)
(
  for i in $(seq 1 180); do
    sleep 1
    if nc -z 127.0.0.1 3000 2>/dev/null; then
      open_url "http://localhost:3000/dashboard"
      break
    fi
  done
) &

# Start Next.js (Ctrl+C to stop)
npm run dev
