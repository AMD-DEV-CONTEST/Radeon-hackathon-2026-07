#!/usr/bin/env bash
# Optional — only needed to reproduce layer 3 (unitree_mujoco over DDS).
source "$(dirname "$0")/common.sh"
need_cmd cmake; need_cmd git
mkdir -p "$THIRD"

step "CycloneDDS (C library, built from source)"
# The Python binding alone is not enough; it needs the native library.
[ -d "$THIRD/cyclonedds" ] || git clone -q --depth 1 -b releases/0.10.x \
    https://github.com/eclipse-cyclonedds/cyclonedds "$THIRD/cyclonedds"
cmake -S "$THIRD/cyclonedds" -B "$THIRD/cyclonedds/build" \
      -DCMAKE_INSTALL_PREFIX="$THIRD/cyclonedds_install" -DBUILD_EXAMPLES=OFF >/dev/null
cmake --build "$THIRD/cyclonedds/build" --target install -j"$(nproc)" >/dev/null

export CYCLONEDDS_HOME="$THIRD/cyclonedds_install"
export LD_LIBRARY_PATH="$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}"
PIP="$VENVS/mjx/bin/pip"

step "unitree_sdk2_python + unitree_mujoco"
$PIP install -q $PIP_OPTS cyclonedds==0.10.2
[ -d "$THIRD/unitree_sdk2_python" ] || git clone -q --depth 1 \
    https://github.com/unitreerobotics/unitree_sdk2_python "$THIRD/unitree_sdk2_python"
$PIP install -q $PIP_OPTS -e "$THIRD/unitree_sdk2_python" --no-deps
[ -d "$THIRD/unitree_mujoco" ] || git clone -q --depth 1 \
    https://github.com/unitreerobotics/unitree_mujoco "$THIRD/unitree_mujoco"

step "Applying our patches"
# Without these, layer 3 fails silently — see docs/TROUBLESHOOTING.md.
cp "$REPO/src/third_party_patches/"*.py "$THIRD/unitree_mujoco/simulate_python/"
cp "$REPO/docker/cyclonedds_lo.xml" "$THIRD/cyclonedds_lo.xml"
info "patched unitree_mujoco (PD moved out of the DDS callback, headless recorder)"

# unitree_mujoco ships configured for the Go2 — a 12-joint quadruped. Left
# alone, the simulator loads that model and the first write of a 29-joint G1
# pose dies with "could not broadcast input array from shape (29,) into shape
# (12,)", long before any DDS traffic, so the controller just times out waiting
# for a LowState it will never get.
CFG="$THIRD/unitree_mujoco/simulate_python/config.py"
sed -i 's/^ROBOT = .*/ROBOT = "g1"  # set by setup_dds.sh/' "$CFG"
# The headless recorder assigns this to mj_model.opt.timestep, so it silently
# overrides the 0.002 s in the scene XML. Training runs at 0.002; leaving
# upstream's 0.005 here means layer 3 validates against different physics.
sed -i 's/^SIMULATE_DT = .*/SIMULATE_DT = 0.002  # match training; set by setup_dds.sh/' "$CFG"
info "configured unitree_mujoco for the G1 at 0.002 s"
grep -E '^(ROBOT|SIMULATE_DT) =' "$CFG" | sed 's/^/    /'

cat <<MSG

  Add to your shell profile:

    export CYCLONEDDS_HOME=$THIRD/cyclonedds_install
    export LD_LIBRARY_PATH=\$CYCLONEDDS_HOME/lib:\$LD_LIBRARY_PATH
    export CYCLONEDDS_URI=file://$THIRD/cyclonedds_lo.xml
MSG
