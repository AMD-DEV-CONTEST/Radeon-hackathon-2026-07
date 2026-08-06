#!/usr/bin/env bash
# Install Node.js >=22.13 on the Radeon Notebook when the image only ships Node 20.
# Safe to re-run. Prefer nvm when available; otherwise NodeSource apt package.
set -euo pipefail

need_install=1
if command -v node >/dev/null 2>&1; then
  ver="$(node --version)"
  major="${ver#v}"
  major="${major%%.*}"
  minor="${ver#v}"
  minor="${minor#*.}"
  minor="${minor%%.*}"
  if (( major > 22 || (major == 22 && minor >= 13) )); then
    echo "Node.js already OK: ${ver}"
    need_install=0
  else
    echo "Node.js ${ver} is too old; installing >=22.13..."
  fi
fi

if (( need_install == 1 )); then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [[ ! -s "${NVM_DIR}/nvm.sh" ]]; then
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  fi
  # shellcheck disable=SC1091
  . "${NVM_DIR}/nvm.sh"
  nvm install 22.14.0
  nvm alias default 22.14.0
  nvm use 22.14.0
fi

# Node may already be OK via /opt/node22 without ever setting NVM_DIR.
# Keep set -u safe when nvm is present but NVM_DIR was never exported.
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
# shellcheck disable=SC1091
if [[ -s "${NVM_DIR}/nvm.sh" ]]; then
  . "${NVM_DIR}/nvm.sh"
  nvm use default >/dev/null 2>&1 || true
fi

echo "node=$(command -v node) $(node --version)"
echo "npm=$(command -v npm) $(npm --version)"
node -e 'const [maj,min]=process.versions.node.split(".").map(Number); if(maj<22||(maj===22&&min<13)) process.exit(2)'
echo "Node preflight PASS"
