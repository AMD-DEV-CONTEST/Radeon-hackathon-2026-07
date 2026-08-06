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

step "Demo policy"
# The web UI's Simulate tab needs a trained policy to have something to show.
# Without this a fresh clone lands on an empty dropdown and the only way to see
# the pipeline work is to train for hours first. Copy the shipped salute policy
# into the working directory, where every reader — the UI, verify.sh, the run
# list — already looks for it.
WORK="${V2M_WORKDIR:-$REPO/workdir}"
mkdir -p "$WORK/motions_bm" "$WORK/train/bm_salute_upright"
if [ -e "$WORK/train/bm_salute_upright/params_best" ]; then
  info "demo policy already installed"
else
  cp "$REPO/assets/demo_salute/motion.npz" "$WORK/motions_bm/salute_upright.npz"
  cp -r "$REPO/assets/demo_salute/params_best" "$WORK/train/bm_salute_upright/"
  info "installed the salute demo policy into $WORK"
fi

step "Done"
cat <<MSG
  source env.sh
  ./scripts/verify.sh
MSG
