# Reproduction guide

Two paths. **Path A needs only a ROCm host** — no robot — and reproduces the trained policies
and their measured success rates. **Path B** adds the physical SO-101 and reproduces the 85%
real-robot result.

**Where each stage actually ran.** This is the honest split, and Path A follows it rather than
pretending otherwise:

| Stage | Machine used for the submitted results | Verified on the Radeon host? |
|---|---|---|
| Demonstration collection (Genesis physics) | macOS / Apple silicon (`gs.metal`) | Partly — see the note |
| ACT training (all 5 runs) | **ROCm / Radeon GPU** | **Yes** |
| Closed-loop simulated evaluation | macOS | **Yes** — physics on `gs.amdgpu`, cameras via EGL, policy on ROCm |
| Real-robot evaluation | macOS + SO-101 | Needs the hardware (Path B) |

`run_pipeline.sh --quick` runs the third row end to end on the Radeon host in about 3 minutes,
so simulation stepping, camera rasterisation, training and policy inference are all confirmed
working on the GPU.

The one step that has not fully transferred is the **many-episode collection loop**. Genesis'
contact solver behaves differently on the ROCm backend: the scripted expert's rake grasp
flicks the cube instead of sweeping it in and the cube slides off the 0.5 m table (`substeps=4`
stabilised this on metal — 9/9 grasps — but is not enough there). A single episode is fine —
`src/grasp_demo_so101.py` succeeds on ROCm with 0.3 mm placement error — so the scene and the
5-DOF IK are sound; it is the repeated contact-rich rollouts that need tuning. Rather than
tune that blind under a deadline, **the three datasets are published on Hugging Face** and
Path A downloads them, reproducing everything downstream on the GPU.

Verified on the hackathon Radeon Cloud host: AMD EPYC 9334 + Radeon GPU,
`torch 2.9.1+rocm7.2.1.gitff65f5bc`, Genesis 1.2.3, headless (no display attached).

---

## 0. Get the project

Verified on a Radeon Cloud instance launched from the
**`amd-oneclick-base:rocm7.2.1-py3.12-v20260416`** container image (ROCm 7.2.1, Python 3.12).

That image keeps its ROCm build of torch in a virtualenv at **`/opt/venv`**, which the
template has active on login. If you have left it (or you are on a different host), activate
it before anything else — `/usr/bin/python` has no torch:

```bash
source /opt/venv/bin/activate
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# observed on that image: 2.9.1+gitff65f5b True
# the version string varies between image builds; what matters is that it prints True
```

Any ROCm host with torch already installed works. This project never installs torch itself,
because the PyPI wheel is the CUDA build and cannot see a Radeon GPU.

```bash
git clone -b track3-so101-cheap-sim2real \
  https://github.com/omiya0555/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/track3_omiya_SO101_CheapSim2Real/submission
```

Everything below runs from this `submission/` directory. The SO-101 URDF and meshes are
bundled in `assets/`, so no further downloads are needed to build the scene.

<details>
<summary>If <code>git clone</code> fails with <code>server certificate verification failed. CAfile: none</code></summary>

Some ROCm images ship a stale CA bundle and no `http.sslCAInfo`, so git cannot validate
GitHub's certificate. The TLS handshake itself succeeds — this is a certificate-validation
failure, not a connectivity problem. Normally this fixes it:

```bash
apt-get install -y --reinstall ca-certificates
git config --global http.sslCAInfo /etc/ssl/certs/ca-certificates.crt
```

If it does not, clone once with verification disabled **for that command only** (`-c` does not
persist, unlike `git config --global http.sslVerify false`), then verify the content by its
commit hash — git is content-addressed, so a matching SHA proves nothing was altered in
transit:

```bash
git -c http.sslVerify=false clone -b track3-so101-cheap-sim2real \
  https://github.com/omiya0555/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07 && git rev-parse HEAD
# expect: 3f3ccd776a8ec8a27c52cf285b28d96056628ce6
```

</details>

## 1. Environment

Two ways. **Either** use the template's Python directly, which is the shortest path on a
Radeon Cloud instance:

```bash
bash setup.sh
```

That script installs the system libraries and Python dependencies, verifies the template's
torch actually sees the GPU (and aborts with an explanation if not — the PyPI torch wheel is
the CUDA build and will not work), persists `PYOPENGL_PLATFORM=egl`, and finishes by running
the smoke test.

**Or** build the container, if you prefer an isolated environment:

```bash
cd ..                       # the Dockerfile sits one level up, next to docs/
docker build -t so101-sim2real .
docker run --rm -it \
  --device=/dev/kfd --device=/dev/dri --group-add video \
  --shm-size 16G \
  -v "$PWD/outputs:/workspace/outputs" \
  so101-sim2real
```

Either way, confirm the machine can run everything before spending GPU hours:

```bash
python src/smoke_test_rocm.py
```

Expected tail:

```
[OK ] PYOPENGL_PLATFORM — egl
[OK ] torch + ROCm — 2.9.1+rocm7.2.1.gitff65f5bc / AMD Radeon ...
[OK ] Genesis scene build — SO-101 + table + cube
[OK ] offscreen render (both cameras) — {'world': (480, 640, 3), 'wrist': (480, 640, 3)}
SMOKE_OK — data collection, training and sim evaluation are all runnable here
```

Two environment details are **not optional**; `setup.sh` and the Dockerfile both handle them,
but they matter if you install by hand:

| Variable | Why |
|---|---|
| `PYOPENGL_PLATFORM=egl` | Genesis rasterises the cameras through pyrender, whose default pyglet path needs a display and fails headless with `IndexError: list index out of range`. Use `osmesa` if your EGL stack is unavailable (software, slower). |
| `--dataset.video_backend=pyav` (passed per command) | LeRobot defaults to `torchcodec`, whose compiled extension is ABI-incompatible with AMD's custom torch build and fails at import. |

`default_backend()` in `src/build_scene_so101.py` requests **`gs.gpu`** and lets Genesis
resolve the device; on the Radeon Cloud host that becomes **`gs.amdgpu`**, so simulation
physics, camera rasterisation and policy inference all run on the Radeon GPU.

Do not name `gs.cuda` yourself: ROCm reuses torch's CUDA API, so `torch.cuda.is_available()`
returns True, but Genesis computes through Taichi, which has no HIP path, and rejects it with
"Torch device 'cuda' not available". Policy inference is the opposite case — there `cuda` is
correct on ROCm, which is why the two are resolved separately.

Override with `SO101_GENESIS_BACKEND=gpu|amdgpu|cuda|cpu|metal`, or pass `--cpu` to any script.

`requirements.txt` deliberately omits **torch** (PyPI's wheel is the CUDA build and will not
see the Radeon GPU — use the template's or AMD's ROCm wheel) and **torchcodec** (see above).

---

## 2. The whole pipeline in one command

For a first end-to-end run — fetch the dataset, train on the Radeon GPU, evaluate — use the
driver script:

```bash
bash run_pipeline.sh --quick     # ~5 min: 100 steps, one 10-second eval episode
bash run_pipeline.sh --full      # ~11 h:  100k steps, 20 full eval episodes
```

Both download `omiya239532/so101_cube_dr` (50 episodes, full DR) rather than collecting, for
the reason given above, then train on the Radeon GPU and evaluate in closed loop. Both print
`PIPELINE_OK` and the measured success rate.

**`--quick` is a plumbing check and will report 0%. That is the intended outcome**, not a
failure of the method: 100 training steps cannot learn a manipulation task. Its job is to
prove dataset → ROCm training → closed-loop evaluation works end to end, in a few minutes,
before anyone commits GPU hours. For the actual numbers use `--full`; on this task success is
25% at 20k steps and peaks at **60% at 60k**, then declines as the 50-episode dataset's
information ceiling is reached (§5.1).

To collect your own demonstrations instead, see A2 — it works on Apple silicon and is worth
running there if you have it, since it is the step that replaces hours of teleoperation.

Path A below is the same pipeline as individual commands, which is what you want when
reproducing a specific experiment (the checkpoint curve, the colour sweep) rather than the
whole flow.

---

## Path A — simulation only (no robot needed)

### A1. Look at the scripted expert

```bash
python src/grasp_demo_so101.py            # add --vis on a machine with a display
```

One scripted pick-and-place. This is the data generator: 5-DOF position-priority IK with
wrist iteration, vertical descent, rake grasp, constant-height polar transport, measured
set-down, and grasp verification with one retry.

### A2. Collect 50 demonstrations (~2 h, fully automatic)

```bash
python src/record_dataset_so101.py --episodes 50 --dr-appearance --dr-runtime \
  --repo-id <your-hf-user>/so101_cube_dr --root datasets/so101_cube_dr
```

No human in the loop. Expert success is 94-98%; only successful episodes are stored, and
~14% contain a retry. The three datasets the report compares differ only in these flags:

```bash
--episodes 50                              # baseline: placement randomisation only (dataset ①)
--episodes 50 --dr-cube-color              # cube colour only (dataset ②)
--episodes 50 --dr-appearance --dr-runtime # full DR (dataset ③)
```

`--dr-appearance` is shorthand for `--dr-cube-color --dr-table-color --dr-lighting`
(re-sampled per domain); `--dr-runtime` re-samples friction, mass and world-camera extrinsics
every episode. Note the output directory flag here is `--root`, while the evaluation scripts
use `--dataset-root`.

All three share the same seed series, so **placements are identical across datasets** and DR
is the only variable. That is what makes §5.2/§5.3 of the report controlled comparisons.

**To skip collection**, pull the published datasets instead:

```bash
huggingface-cli download omiya239532/so101_cube_dr --repo-type dataset \
  --local-dir datasets/so101_cube_dr
```

### A3. Train ACT on the Radeon GPU

```bash
lerobot-train \
  --dataset.repo_id=<your-hf-user>/so101_cube_dr \
  --dataset.root=datasets/so101_cube_dr \
  --dataset.image_transforms.enable=true \
  --dataset.video_backend=pyav \
  --policy.type=act \
  --output_dir=outputs/act_dr \
  --steps=100000 --batch_size=8 --save_freq=20000 \
  --policy.device=cuda --policy.push_to_hub=false \
  --wandb.enable=false
```

Reference figures on the verified host: **2.55 step/s, 3.9 GB VRAM, ~11 h for 100k steps**,
with `data_s ≈ 0.002 s` against `updt_s ≈ 0.388 s` (the GPU, not the loader, is the
bottleneck). Watch utilisation in another shell with `rocm-smi`.

For the 20k-step fine-tunes, start from a checkpoint instead of `--policy.type`:

```bash
  --policy.path=outputs/act_dr/checkpoints/060000/pretrained_model \
  --steps=20000 --save_freq=5000
```

### A4. Evaluate in simulation (fixed seeds)

```bash
python src/eval_policy_so101.py \
  --policy-path outputs/act_dr/checkpoints/060000/pretrained_model \
  --repo-id <your-hf-user>/so101_cube_dr --dataset-root datasets/so101_cube_dr \
  --episodes 20 --save-video \
  --results-out outputs/eval_results/act_dr_060000.json
```

Seeds are fixed (`--seed` default 1000, one per episode), so **checkpoints and policies are
compared on identical placements**. Expected for the 60k checkpoint of the red-only dataset:
`success rate: 12/20 = 60.0%`.

To reproduce the **checkpoint curve** (§5.1 — success peaks at 60k and declines while loss
still falls), run the above for `020000 … 100000`.

To reproduce the **colour-generalisation result** (§5.2 — success tracks object-background
RGB distance, not hue), hold the policy fixed and change only the cube colour:

```bash
for c in "0.90,0.70,0.05" "0.12,0.18,0.85" "0.05,0.05,0.05" "0.65,0.50,0.35" "0.20,0.62,0.40"; do
  python src/eval_policy_so101.py --policy-path outputs/act_red/checkpoints/060000/pretrained_model \
    --repo-id <you>/so101_cube_red --dataset-root datasets/so101_cube_red \
    --episodes 10 --cube-color "$c" \
    --results-out "outputs/eval_results/red60k_$c.json"
done
```

The last colour is the table's own colour — expect the collapse to ~10%.

---

## Path B — the physical SO-101

Needs the arm, a leader arm for teleoperation, and two USB cameras. Run this part on the
machine the robot is plugged into (the policy runs there; see the report's latency note).

### B1. Calibrate and verify conventions

```bash
lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/tty.usbmodemXXXX \
  --robot.id=so101_real

python src/eval_policy_so101_real.py --port /dev/tty.usbmodemXXXX --probe
```

`--probe` releases torque and prints each joint in **both** conventions (real degrees and
simulator radians) so they can be checked against the simulator's home pose. Then confirm the
arm actually reaches that pose:

```bash
python src/eval_policy_so101_real.py --port /dev/tty.usbmodemXXXX --home-only
```

### B2. Align the cameras to the digital twin

```bash
python src/align_cameras_so101.py
```

Renders the simulated overhead view so the real camera and the white target sheet can be
moved to match it. Visual transfer depends on this.

### B3. Check the cameras are actually live — do not skip this

```bash
python src/smoke_test_cameras.py     # or: python src/validate_camera_liveness.py --live
```

A UVC camera can return `ok=True` with a **frozen buffer**: frames keep arriving, pixels
never change. Ten teleoperation episodes and one whole evaluation were recorded that way
during this project; shape, units, fps and playability were all valid and **the training loss
was identical to a clean run**. Only pixel-change-over-time detects it.

The recorder and the real-robot runner now open cameras with **no resolution request** (asking
this rig's wrist camera for 320×240 selects a 120 fps mode that stalls every ~9 s; its native
1920×1080@30 mode soaked 150 s clean) and crop/resize in software, with a liveness guard that
refuses to start on a static stream and reopens the device after 2 s of no change.

### B4. Record 10 teleoperation episodes (~35 min)

```bash
python src/record_so101_launcher.py \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodemXXXX --robot.id=so101_real \
  --robot.cameras='{"world": {"type": "opencv", "index_or_path": 0, "width": 320, "height": 240, "fps": 30},
                    "wrist": {"type": "opencv", "index_or_path": 1, "width": 320, "height": 240, "fps": 30}}' \
  --teleop.type=so101_leader --teleop.port=/dev/tty.usbmodemYYYY --teleop.id=so101_leader \
  --dataset.repo_id=<you>/so101_real_teleop --dataset.root=datasets/so101_real_teleop \
  --dataset.fps=30 --dataset.num_episodes=10 \
  --dataset.episode_time_s=40 --dataset.reset_time_s=10 \
  --dataset.single_task="pick the cube and place it on the white target sheet" \
  --dataset.push_to_hub=false
```

This is LeRobot's own `lerobot-record` — the teleop loop, episode timing, keyboard controls
and dataset writing are untouched. Only the camera transport is swapped, for the reasons in
B3. Confirm `(LIVE)` appears for both cameras before you start driving. Vary the cube's
starting position across the 10 episodes; coverage matters more than count.

Then validate before spending GPU time on it:

```bash
python src/validate_camera_liveness.py     # expects VALIDATION_PASS
```

Per episode this checks camera liveness, joint ranges and units, that the gripper actually
closed and reopened, and that measured state tracks commanded action.

### B5. Convert units and merge with the simulated data

```bash
python src/merge_real_sim_so101.py \
  --real datasets/so101_real_teleop --sim datasets/so101_cube_dr \
  --out datasets/so101_mixed --repeat 3
```

Real episodes are converted to simulator units (radians; round-trip error 5e-8) and
oversampled ×3 so they are **33% of the mixture** rather than 14%. Result: 80 episodes /
66,317 frames.

### B6. Fine-tune, then evaluate on hardware

```bash
lerobot-train \
  --dataset.repo_id=<you>/so101_mixed --dataset.root=datasets/so101_mixed \
  --dataset.image_transforms.enable=true --dataset.video_backend=pyav \
  --policy.path=outputs/act_dr/checkpoints/060000/pretrained_model \
  --output_dir=outputs/act_cotrain \
  --steps=20000 --batch_size=8 --save_freq=5000 \
  --policy.device=cuda --policy.push_to_hub=false --wandb.enable=false
```

```bash
python src/eval_policy_so101_real.py \
  --port /dev/tty.usbmodemXXXX --cam-world 0 --cam-wrist 1 \
  --policy-path outputs/act_cotrain/checkpoints/020000/pretrained_model \
  --repo-id <you>/so101_mixed --dataset-root datasets/so101_mixed \
  --episodes 10 --save-video --video-episodes 0 \
  --video-dir outputs/real_videos/cotrain
```

Each episode eases to home, waits for you to place the cube and press Enter, then rolls out
for up to 45 s. Torque is always released **after** easing home, on every exit path.

Finally, audit the rollouts — this is how the report's evaluations were certified:

```bash
python src/audit_rollout_videos.py
```

Prints per-video camera staleness (`CLEAN` / `CONFOUNDED`) and where the cube ended up
relative to the target sheet.

Camera indices change between sessions; re-enumerate before every run.
`--ep-offset N` resumes a run that died partway without overwriting existing episodes.

---

## Expected results

| What | Command | Expected |
|---|---|---|
| Sim, red-only 60k | A4 | 12/20 = 60% |
| Sim, checkpoint curve | A4 ×5 | 25 / 40 / **60** / 55 / 50 % at 20-100k |
| Sim, colour sweep | A4 with `--cube-color` | tracks ‖Δc‖, collapses to 10% at table colour |
| Real, co-trained | B6 | **85%** (17/20), 1-2 cm placement error |
| Real, 10 episodes only | B6 with `--policy.type=act` | 25% (5/20) |

Simulated numbers are seed-fixed and should reproduce closely. Real-robot numbers depend on
your rig's calibration, lighting and camera placement; treat 85% as the result obtained on
this rig, not a guarantee. The 85%-vs-25% gap is over 20 episodes per arm on identical
placements (Fisher exact p = 0.00033) — see the report §5.5.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `git clone` → `server certificate verification failed. CAfile: none` | The image's CA bundle is stale and git has no `sslCAInfo`. Fix: `apt-get install -y --reinstall ca-certificates && git config --global http.sslCAInfo /etc/ssl/certs/ca-certificates.crt`. See §0 if that does not help. |
| `numpy.dtype size changed ... Expected 96, got 88`, or `Numba needs NumPy 2.2 or less` | numpy and scikit-image must move together — scikit-image's wheels are compiled against one numpy C API, so changing numpy alone swaps one error for the other. `pip install --force-reinstall "numpy>=2.2,<2.3" "scikit-image>=0.25,<0.26"`. `setup.sh` does this when `import genesis` fails. |
| `huggingface-hub>=0.34.0,<1.0 is required ... but found huggingface-hub==1.x` during `import lerobot.datasets` | The image ships transformers 4.x, which pins huggingface-hub below 1.0, while lerobot needs 1.0+. Upgrade transformers, do not downgrade the hub: `pip install -U "transformers>=5.5"`. `setup.sh` does this automatically. |
| `RepositoryNotFoundError: 401` for a `local/...` repo id during training | The local dataset is incomplete, so LeRobot fell back to looking it up on the Hub. Check `meta/info.json` and `meta/tasks.parquet` exist under the dataset root; if not, re-collect (`--overwrite`). It is the missing metadata, not authentication, that causes this. |
| `IndexError: list index out of range` in pyglet/pyrender | No display. `export PYOPENGL_PLATFORM=egl` (or `osmesa`). |
| `ImportError` from torchcodec | ABI mismatch with AMD's torch. Pass `--dataset.video_backend=pyav`; do not install torchcodec. |
| Grasping never succeeds in sim | Collision meshes were convexified. `convexify=False` is mandatory — it destroys the gripper's concave shape. |
| Intermittent grasp failures in sim | `substeps=2` gives contact chaos; use 4. |
| Camera opens but the image never changes | See B3. Do not request a resolution; capture native and resize. |
| Servo drops off the bus ("no status packet") | STS3215 overload. Power-cycle; avoid sustained full-grip holds and long folded-pose holds. |
| `FileNotFoundError` writing a dataset from a script | LeRobot's writer uses a spawn `ProcessPoolExecutor`; the script needs an `if __name__ == "__main__":` guard. |
