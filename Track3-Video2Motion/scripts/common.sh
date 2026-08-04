# Shared settings for the setup scripts.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENVS="${V2M_VENVS:-$HOME/venvs}"
THIRD="${V2M_THIRD_PARTY:-$HOME/video2motion-deps}"
PY="${V2M_PYTHON:-python3.12}"
ROCM_INDEX="${V2M_ROCM_INDEX:-https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/}"

step() { printf '\n\033[1;31m▶ %s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1 (see scripts/setup_system.sh)"; }
