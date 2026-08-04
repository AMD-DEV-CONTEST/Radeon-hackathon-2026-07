#!/usr/bin/env bash
# Full setup. Roughly 60-90 min, dominated by compiling pytorch3d.
#
#   ./scripts/setup.sh              everything except layer-3 DDS
#   ./scripts/setup.sh --with-dds   also build CycloneDDS and unitree_mujoco
source "$(dirname "$0")/common.sh"
HERE="$(dirname "$0")"

# Write env.sh first. It used to be written at the very end, so a failure
# partway through left no env file and no hint that one was expected.
step "Writing env.sh"
write_env
info "wrote $REPO/env.sh"

"$HERE/setup_system.sh"
"$HERE/setup_mjx.sh"
"$HERE/setup_gvhmr.sh"
"$HERE/setup_gmr.sh"
[ "${1:-}" = "--with-dds" ] && "$HERE/setup_dds.sh"

step "Done"
cat <<MSG
  source env.sh
  ./scripts/verify.sh
MSG
