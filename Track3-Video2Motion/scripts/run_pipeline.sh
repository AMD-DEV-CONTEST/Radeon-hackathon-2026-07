#!/usr/bin/env bash
# End-to-end: a video in, a validated policy out.
#
#   ./scripts/run_pipeline.sh <video.mp4> <name> [hours]
#
# `hours` defaults to 6, which is what the reported results used. The motion is
# fully performed from about 2 h; the rest buys smoothness.
source "$(dirname "$0")/common.sh"

VIDEO="${1:?usage: run_pipeline.sh <video.mp4> <name> [hours]}"
NAME="${2:?usage: run_pipeline.sh <video.mp4> <name> [hours]}"
HOURS="${3:-6}"
STEPS=$(python3 -c "print(int($HOURS*3600*17000))")

PY_MJX="${V2M_PY_MJX:-$VENVS/mjx/bin/python}"
PY_GVHMR="${V2M_PY_GVHMR:-$VENVS/gvhmr/bin/python}"
PY_GMR="${V2M_PY_GMR:-$VENVS/gmr/bin/python}"
GVHMR="${V2M_GVHMR:-$THIRD/GVHMR}"
GMR="${V2M_GMR:-$THIRD/GMR}"
WORK="${V2M_WORKDIR:-$REPO/workdir}"
mkdir -p "$WORK"/{uploads,motions,motions_mjx,motions_bm,train,render,deploy}

step "1/5  Video → SMPL-X   (GVHMR, AMD GPU)"
# GVHMR keys its output directory on the file name and silently reuses a stale
# cache when the name repeats; the only tell is "Time elapsed: 0.03s".
rm -rf "$GVHMR/outputs/demo/$NAME"
# Pointing at a video already sitting in uploads/ is a natural thing to do —
# on a re-run, say. `cp` calls that an error and aborts the whole pipeline.
[ "$(readlink -f "$VIDEO")" = "$(readlink -f "$WORK/uploads/$NAME.mp4")" ] \
    || cp "$VIDEO" "$WORK/uploads/$NAME.mp4"
( cd "$GVHMR" && MPLBACKEND=Agg "$PY_GVHMR" tools/demo/demo.py \
    --video "$WORK/uploads/$NAME.mp4" --static_cam )

step "2/5  SMPL-X → G1 joints   (GMR, CPU/IK)"
( cd "$GMR" && xvfb-run -a -s "-screen 0 1280x720x24" "$PY_GMR" \
    scripts/gvhmr_to_robot.py \
    --gvhmr_pred_file "$GVHMR/outputs/demo/$NAME/hmr4d_results.pt" \
    --robot unitree_g1 --save_path "$WORK/motions/$NAME.pkl" )

step "3/5  Convert and derive body poses/velocities"
# Two different scene files, and they are not interchangeable:
#   * playground's scene references its assets by a relative path that only
#     resolves through base.get_assets() + from_xml_string (used by
#     eval_track.py and layer2_numpy.py)
#   * gmr_to_mjx.py and replay_check.py use from_xml_path, which needs a scene
#     whose assets sit next to it — that is menagerie's own scene_mjx.xml
SCENE=$("$PY_MJX" -c "from mujoco_playground._src import mjx_env; \
    print(mjx_env.MENAGERIE_PATH / 'unitree_g1' / 'scene_mjx.xml')")
MUJOCO_GL=osmesa "$PY_MJX" "$REPO/src/gmr_to_mjx.py" \
    --gmr_pkl "$WORK/motions/$NAME.pkl" --mjx_xml "$SCENE" \
    --out "$WORK/motions_mjx/$NAME.npz"
"$PY_MJX" "$REPO/src/motion_prep.py" \
    --inp "$WORK/motions_mjx/$NAME.npz" --out "$WORK/motions_bm/$NAME.npz"
MUJOCO_GL=egl "$PY_MJX" "$REPO/src/replay_check.py" --xml "$SCENE" \
    --motion "$WORK/motions_mjx/$NAME.npz" --out "$WORK/render/${NAME}_retargeted.mp4"

info "check $WORK/render/${NAME}_retargeted.mp4 before spending hours on training"

step "4/5  Train   (~$HOURS h, $STEPS steps)"
"$PY_MJX" "$REPO/src/train_track.py" --motion "$WORK/motions_bm/$NAME.npz" \
    --run_name "$NAME" --num_envs 4096 --num_timesteps "$STEPS" \
    --num_evals $(( STEPS / 5000000 > 4 ? STEPS / 5000000 : 4 )) --keep_checkpoints

step "5/5  Validate (layers 1 and 2)"
MUJOCO_GL=egl "$PY_MJX" "$REPO/src/eval_track.py" \
    --params "$WORK/train/$NAME/params_best" --motion "$WORK/motions_bm/$NAME.npz" \
    --video "$WORK/render/${NAME}_layer1.mp4"
MUJOCO_GL=egl "$PY_MJX" "$REPO/src/layer2_numpy.py" \
    --params "$WORK/train/$NAME/params_best" --motion "$WORK/motions_bm/$NAME.npz" \
    --out "$WORK/render/${NAME}_layer2.mp4"

step "Done"
cat <<MSG
  policy   $WORK/deploy/track_$NAME.npz
  videos   $WORK/render/${NAME}_layer{1,2}.mp4

  For layer 3 (unitree_mujoco over DDS):
    ./scripts/run_layer3.sh $NAME
MSG
