#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"
run_python "$RADEONNAV_ROOT/setup/verify_environment.py"

