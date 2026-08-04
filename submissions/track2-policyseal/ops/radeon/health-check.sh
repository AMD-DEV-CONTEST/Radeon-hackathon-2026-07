#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_root"
source ops/radeon/policyseal-env.sh

.venv/bin/python ops/radeon/validate-runtime.py --quick --require-services
printf 'PolicySeal Radeon services are healthy and loopback-only.\n'
