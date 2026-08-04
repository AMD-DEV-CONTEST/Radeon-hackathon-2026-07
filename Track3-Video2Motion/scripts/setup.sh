#!/usr/bin/env bash
# Full setup. Roughly 60-90 min, dominated by compiling pytorch3d.
#
#   ./scripts/setup.sh              everything except layer-3 DDS
#   ./scripts/setup.sh --with-dds   also build CycloneDDS and unitree_mujoco
source "$(dirname "$0")/common.sh"
HERE="$(dirname "$0")"

"$HERE/setup_system.sh"
"$HERE/setup_mjx.sh"
"$HERE/setup_gvhmr.sh"
"$HERE/setup_gmr.sh"
[ "${1:-}" = "--with-dds" ] && "$HERE/setup_dds.sh"

step "Writing env file"
cat > "$REPO/env.sh" <<ENVEOF
# source this before running anything
export V2M_WORKDIR=$REPO/workdir
export V2M_GVHMR=$THIRD/GVHMR
export V2M_GMR=$THIRD/GMR
export V2M_UNITREE_MUJOCO=$THIRD/unitree_mujoco
export V2M_PY_MJX=$VENVS/mjx/bin/python
export V2M_PY_GVHMR=$VENVS/gvhmr/bin/python
export V2M_PY_GMR=$VENVS/gmr/bin/python
export CYCLONEDDS_HOME=$THIRD/cyclonedds_install
export LD_LIBRARY_PATH=\$CYCLONEDDS_HOME/lib:\${LD_LIBRARY_PATH:-}
export CYCLONEDDS_URI=file://$THIRD/cyclonedds_lo.xml
export MUJOCO_GL=egl
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export MPLBACKEND=Agg
ENVEOF
info "wrote $REPO/env.sh"

step "Done"
cat <<MSG
  source env.sh
  ./scripts/verify.sh
MSG
