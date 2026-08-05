"""Backend for the Video2Motion web app.

Wraps three mutually incompatible Python environments behind one interface:

    gvhmr_env   PyTorch-ROCm + pytorch3d   (no jax)
    GMR/gmr     retargeting deps
    mjx         JAX-ROCm + MuJoCo          (no torch)

They cannot coexist in one interpreter, so every stage runs as a subprocess
and the stages exchange data through files on disk.
"""

from __future__ import annotations

import os
import re
import sys
import shutil
import signal
import subprocess
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C  # noqa: E402

BASE = C.SRC
GVHMR = C.GVHMR
GMR = C.GMR
PY_GVHMR = C.PY_GVHMR
PY_GMR = C.PY_GMR
PY_MJX = C.PY_MJX
# The retarget and replay stages shell out to plain MuJoCo, which resolves
# meshes relative to the XML — so they need menagerie's standalone scene, not
# Playground's. The two are not interchangeable; see config.py.
SCENE_STANDALONE = C.scene_xml_standalone()

# ------------------------------------------------------------- tensorboard
TB_PORT = 6006
_tb_proc = None


def tensorboard_url() -> str:
    """Start TensorBoard over the training directory once, return its URL.

    Served on its own port rather than embedded: the training curves are worth
    looking at with real axes and run comparison, which a static PNG cannot do.
    """
    global _tb_proc
    if _tb_proc is None or _tb_proc.poll() is not None:
        C.TRAIN_OUT.mkdir(parents=True, exist_ok=True)
        try:
            _tb_proc = subprocess.Popen(
                [PY_MJX, "-m", "tensorboard.main",
                 "--logdir", str(C.TRAIN_OUT), "--port", str(TB_PORT),
                 "--bind_all", "--reload_interval", "10"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:                                    # noqa: BLE001
            return ""
    return f"http://localhost:{TB_PORT}/"


WORK = C.UPLOADS
DL = C.DOWNLOADS
C.ensure_dirs()

# Env-steps/s on a single W7900, measured on an otherwise idle GPU. Anything
# else training at the same time roughly halves it, so the budget estimate is
# an upper bound, not a promise — watch throughput/env_steps_per_s in
# TensorBoard for what a run is actually getting.
THROUGHPUT = 16_500


# --------------------------------------------------------------------- job
@dataclass
class Job:
    name: str
    lines: list[str] = field(default_factory=list)
    done: bool = False
    ok: bool = False
    stopped: bool = False
    result: dict = field(default_factory=dict)
    proc: subprocess.Popen | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, s: str):
        with self._lock:
            self.lines.append(s.rstrip())

    def tail(self, n: int = 500) -> str:
        with self._lock:
            return "\n".join(self.lines[-n:])

    def stop(self):
        """Ask the running subprocess to exit; checkpoints on disk survive."""
        self.stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                p.terminate()
            self.log("\n[stopped by user] terminating training; "
                     "checkpoints written so far are kept.")


def _run(job: Job, cmd, cwd=None, env=None, on_line=None) -> int:
    e = dict(os.environ)
    if env:
        e.update(env)
    job.log(f"$ {' '.join(str(c) for c in cmd)}")
    p = subprocess.Popen(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=e,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, start_new_session=True)
    job.proc = p
    for line in p.stdout:
        job.log(line)
        if on_line:
            on_line(line)
    p.wait()
    job.proc = None
    return p.returncode


def safe_name(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-z_\-]", "_", (s or "").strip())
    return s.strip("_") or "motion"


def _zip(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        if src.is_dir():
            for f in src.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(src.parent))
        else:
            z.write(src, src.name)
    return str(dest)


# ---------------------------------------------------------------- browsing
def list_smpl() -> list[str]:
    root = GVHMR / "outputs" / "demo"
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir()
                  if (d / "hmr4d_results.pt").exists())


def list_motions() -> list[str]:
    return sorted(p.stem for p in C.MOTIONS_BM.glob("*.npz"))


def list_runs() -> list[str]:
    root = C.TRAIN_OUT
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir()
                  if (d / "params_best").exists())


def bundle_smplx(name: str) -> str | None:
    """Step 1's output: GVHMR's result file and its preview renders."""
    if not name:
        return None
    d = GVHMR / "outputs" / "demo" / name
    return _zip(d, DL / f"{name}_smplx.zip") if d.is_dir() else None


def bundle_motion(name: str) -> str | None:
    """Step 2's output: the retargeted G1 trajectory in all three forms."""
    if not name:
        return None
    # Same basename in three directories, so the archive names have to say
    # which is which rather than landing on top of each other.
    items = [(C.MOTIONS_RAW / f"{name}.pkl", "gmr.pkl"),
             (C.MOTIONS_MJX / f"{name}.npz", "mjx.npz"),
             (C.MOTIONS_BM / f"{name}.npz", "training_reference.npz"),
             (C.RENDER_OUT / f"replay_{name}.mp4", "replay.mp4"),
             (C.RENDER_OUT / f"{name}_retarget.mp4", "retarget.mp4")]
    items = [(f, a) for f, a in items if f.exists()]
    if not items:
        return None
    dest = DL / f"{name}_g1_motion.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f, arc in items:
            z.write(f, f"{name}/{arc}")
    return str(dest)


def bundle_checkpoint(run: str, ck: str | None) -> str | None:
    """Step 3's output: one checkpoint, not the whole run.

    A finished run holds ~70 checkpoints and several hundred megabytes of
    shard files; zipping all of it to hand over the one that was selected is
    not a download anybody wants.
    """
    if not run:
        return None
    d = C.TRAIN_OUT / run / (ck or "params_best")
    if not d.exists():
        return None
    return _zip(d, DL / f"{run}_{d.name}.zip")


def policy_choices() -> list[str]:
    """Every run that has a usable checkpoint, shipped example included.

    Step 4 used to ask whether you wanted the example or your own run before it
    would show you either. They are the same kind of thing — a trained policy —
    so they belong in one list.
    """
    return list_runs()


def resolve_policy(run: str, ck: str | None):
    """(params, motion, motion_name) for a selected run, or None.

    Run directories are named after the motion with a prefix recording where
    they came from: bm_ for the shipped example, web_ for a run started here.
    """
    if not run:
        return None
    params = C.TRAIN_OUT / run / (ck or "params_best")
    if not params.exists():
        return None
    mname = run.removeprefix("web_").removeprefix("bm_")
    return str(params), motion_bm(mname), mname


def list_checkpoints(run: str) -> list[str]:
    d = C.TRAIN_OUT / run
    if not d.exists():
        return []
    out = [p.name for p in d.iterdir()
           if p.is_dir() and p.name.startswith(("params", "ckpt"))]
    return sorted(out)


def smpl_pt(name: str) -> str:
    return str(GVHMR / "outputs" / "demo" / name / "hmr4d_results.pt")


def motion_bm(name: str) -> str:
    return str(C.MOTIONS_BM / f"{name}.npz")


# ------------------------------------------------------------------ step 1
def step1(video_path: str, name: str, job: Job):
    """GVHMR: monocular video -> SMPL-X body motion."""
    name = safe_name(name or Path(video_path).stem)
    job.log("STEP 1  Video -> SMPL-X body motion   (GVHMR, AMD GPU)")
    job.log(f"        project name : {name}")
    job.log(f"        input video  : {video_path}")

    # GVHMR keys its output directory on the file name and silently reuses a
    # stale cache when the name repeats. The only tell is "Time elapsed: 0.03s".
    out_dir = GVHMR / "outputs" / "demo" / name
    if out_dir.exists():
        job.log(f"        clearing stale cache {out_dir}")
        shutil.rmtree(out_dir, ignore_errors=True)

    staged = WORK / f"{name}.mp4"
    shutil.copy(video_path, staged)

    rc = _run(job, [PY_GVHMR, "tools/demo/demo.py", "--video", str(staged),
                    "--static_cam"], cwd=GVHMR, env={"MPLBACKEND": "Agg"})
    pt = out_dir / "hmr4d_results.pt"
    if rc != 0 or not pt.exists():
        job.log(f"FAILED  GVHMR exited with {rc}")
        job.done = True
        return

    preview = None
    for pat in ("*_global.mp4", "*_incam.mp4", "*.mp4"):
        hits = sorted(out_dir.glob(pat))
        if hits:
            preview = str(hits[0])
            break

    job.result = {"name": name, "pt": str(pt), "preview": preview,
                  "download": _zip(pt, DL / f"{name}_smplx.zip")}
    job.log(f"OK      SMPL-X result at {pt}")
    job.done = job.ok = True


# ------------------------------------------------------------------ step 2
def step2(name: str, pt_path: str, job: Job):
    """GMR: SMPL-X -> Unitree G1 29-DoF joint trajectory."""
    job.log("STEP 2  SMPL-X -> Unitree G1 joints   (GMR, CPU / IK)")

    pkl = C.MOTIONS_RAW / f"{name}.pkl"
    rc = _run(job, ["xvfb-run", "-a", "-s", "-screen 0 1280x720x24",
                    PY_GMR, "scripts/gvhmr_to_robot.py",
                    "--gvhmr_pred_file", pt_path,
                    "--robot", "unitree_g1", "--save_path", str(pkl)], cwd=GMR)
    if rc != 0 or not pkl.exists():
        job.log(f"FAILED  GMR exited with {rc}")
        job.done = True
        return

    job.log("        converting to MJX format "
            "(joint reorder / quaternion order / resample / ground align)")
    npz = C.MOTIONS_MJX / f"{name}.npz"
    rc = _run(job, [PY_MJX, str(BASE / "gmr_to_mjx.py"), "--gmr_pkl", str(pkl),
                    "--mjx_xml", SCENE_STANDALONE, "--out", str(npz)],
              env={"MUJOCO_GL": "osmesa"})
    if rc != 0 or not npz.exists():
        job.log(f"FAILED  conversion exited with {rc}")
        job.done = True
        return

    job.log("        deriving body poses and velocities "
            "(the tracking reward is computed in 3-D space)")
    bm = C.MOTIONS_BM / f"{name}.npz"
    rc = _run(job, [PY_MJX, str(BASE / "motion_prep.py"),
                    "--inp", str(npz), "--out", str(bm)])
    if rc != 0 or not bm.exists():
        job.log(f"FAILED  motion prep exited with {rc}")
        job.done = True
        return

    job.log("        kinematic replay self-check (no physics)")
    replay = C.RENDER_OUT / f"replay_{name}.mp4"
    _run(job, [PY_MJX, str(BASE / "replay_check.py"), "--xml", SCENE_STANDALONE,
               "--motion", str(npz), "--out", str(replay)],
         env={"MUJOCO_GL": "egl"})

    job.result = {"bm": str(bm), "npz": str(npz),
                  "replay": str(replay) if replay.exists() else None,
                  "download": _zip(bm, DL / f"{name}_g1_motion.zip")}
    job.log(f"OK      G1 trajectory at {bm}")
    job.done = job.ok = True


# ------------------------------------------------------------------ step 3
CURVE_RE = re.compile(
    r"step=\s*([\d,]+)\s+reward=\s*([-\d.]+)\s+ep_len=\s*([\d.]+)"
    r"\s+body_pos=([\d.nan]+)m\s+body_ori=([\d.nan]+)rad")


def step3_train(bm_path: str, name: str, hours: float, ckpt_every_m: float,
                job: Job):
    """Train the tracking policy. Streams curves; can be stopped mid-run."""
    steps = max(2_000_000, int(hours * 3600 * THROUGHPUT))
    n_ck = max(4, min(200, int(round(steps / (ckpt_every_m * 1e6)))))
    run_name = f"web_{name}"

    job.log("STEP 3  Reinforcement learning   (MuJoCo MJX + Brax PPO, AMD GPU)")
    job.log(f"        budget      : {hours:.2f} h  "
            f"~= {steps:,} env-steps at ~{THROUGHPUT:,} steps/s")
    job.log(f"        checkpoints : every ~{ckpt_every_m:g}M steps "
            f"({n_ck} total, kept on disk)")
    job.log( "        note        : full convergence takes ~500M steps (~8 h);"
             " shorter runs show the trend but will not converge.")

    curve: list[dict] = []
    job.result["curve"] = curve
    job.result["run"] = run_name

    def parse(line):
        m = CURVE_RE.search(line)
        if m:
            curve.append({
                "step": int(m.group(1).replace(",", "")),
                "reward": float(m.group(2)),
                "ep_len": float(m.group(3)),
                "body_pos": float(m.group(4)),
                "body_ori": float(m.group(5)),
            })

    rc = _run(job, [PY_MJX, str(BASE / "train_track.py"),
                    "--motion", bm_path, "--run_name", run_name,
                    "--num_envs", "4096", "--num_timesteps", str(steps),
                    "--num_evals", str(n_ck), "--keep_checkpoints"],
              cwd=BASE, env={"XLA_PYTHON_CLIENT_PREALLOCATE": "false"},
              on_line=parse)

    ck_dir = C.TRAIN_OUT / run_name
    best = ck_dir / "params_best"
    if not best.exists():
        job.log(f"FAILED  no checkpoint produced (rc={rc})")
        job.done = True
        return

    job.result["params"] = str(best)
    job.result["ckpt_dir"] = str(ck_dir)
    job.result["download"] = _zip(ck_dir, DL / f"{name}_policy.zip")
    if job.stopped:
        job.log("OK      stopped early; best checkpoint so far is usable.")
    else:
        job.log("OK      training finished.")

    job.done = job.ok = True


# ------------------------------------------------------------------ step 4
STAT_RE = re.compile(r"(\S+)\s+(\d+)/(\d+)\s+\(\s*([\d.]+)%\)\s+([\d.]+)")


def step4_simulate(params: str, bm_path: str, name: str, job: Job):
    """Layers 2 and 3 — the two sim-to-sim transfers.

    Layer 2 swaps the engine: the same weights, re-implemented in plain NumPy,
    stepped by MuJoCo's C solver instead of MJX/JAX. Layer 3 swaps everything
    left — Unitree's own simulator, their G1 model, over DDS, with the policy
    seeing only what the real SDK reports.
    """
    job.log("STEP 4  Physics rollout and sim-to-sim transfer")
    stats: dict = {}
    # Layer 3 is driven by scripts/run_layer3.sh, which addresses everything by
    # the motion's own stem — the exported weights land in deploy/track_<stem>
    # and the video in render/<stem>_layer3. The project name can differ from
    # it whenever an earlier motion was picked, so key off the motion.
    mname = Path(bm_path).stem

    def parse(line):
        if "/" not in line or "%" not in line:
            return
        m = STAT_RE.search(line)
        if not m:
            return
        pct, err = float(m.group(4)), float(m.group(5))
        if "zero" in line.lower():
            stats["zero_pct"], stats["zero_err"] = pct, err
        else:
            stats["pct"], stats["err"] = pct, err
            stats["done"], stats["total"] = int(m.group(2)), int(m.group(3))

    # ---- Layer 1: the MJX engine the policy was trained in ----
    # The baseline the other two are measured against: same engine, same
    # observations, nothing swapped yet.
    job.log("")
    job.log("LAYER 1 MJX — the engine the policy trained in")
    l1 = C.RENDER_OUT / f"web_{name}_layer1.mp4"
    rc = _run(job, [PY_MJX, str(BASE / "eval_track.py"), "--params", params,
                    "--motion", bm_path, "--start", "0", "--video", str(l1)],
              cwd=BASE, env={"MUJOCO_GL": "egl"}, on_line=parse)
    if rc == 0 and l1.exists():
        job.result["layer1"] = str(l1)
        job.log(f"OK      layer 1 video at {l1}")
    else:
        job.log(f"FAILED  layer 1 exited with {rc}")

    # ---- Layer 2: NumPy policy, native MuJoCo C engine ----
    job.log("")
    job.log("LAYER 2 NumPy policy in MuJoCo's C engine (no JAX)")
    l2 = C.RENDER_OUT / f"web_{name}_layer2.mp4"
    rc = _run(job, [PY_MJX, str(BASE / "layer2_numpy.py"), "--params", params,
                    "--motion", bm_path, "--out", str(l2)],
              cwd=BASE, env={"MUJOCO_GL": "egl"}, on_line=parse)
    if rc == 0 and l2.exists():
        job.result["layer2"] = str(l2)
        job.log(f"OK      layer 2 video at {l2}")
    else:
        job.log(f"FAILED  layer 2 exited with {rc}")

    # ---- Layer 3: Unitree's simulator over DDS ----
    job.log("")
    job.log("LAYER 3 Unitree's simulator, their G1 model, over DDS")
    l3 = C.RENDER_OUT / f"{mname}_layer3.mp4"
    if not Path(C.UNITREE_MUJOCO).exists():
        job.log("SKIP    unitree_mujoco is not installed.")
        job.log("        Run: ./scripts/setup.sh --with-dds")
    else:
        rc = _run(job, ["bash", str(C.REPO / "scripts" / "run_layer3.sh"), mname],
                  cwd=C.REPO, on_line=parse)
        if rc == 0 and l3.exists():
            job.result["layer3"] = str(l3)
            job.log(f"OK      layer 3 video at {l3}")
        else:
            job.log(f"FAILED  layer 3 exited with {rc}")

    job.result["stats"] = stats
    job.result["download"] = job.result.get("layer3") or job.result.get("layer2")
    job.done = True
    job.ok = bool(job.result.get("layer1") or job.result.get("layer2")
                  or job.result.get("layer3"))


# ----------------------------------------------------------------- presets
# One shipped example, so the demo tab works before the user has trained
# anything. Everything else on this page is generated by the user.
PRESET_LABELS = {"salute_upright": "Salute (pre-trained example)"}


def presets() -> dict:
    out = {}
    for key, label in PRESET_LABELS.items():
        bm = C.MOTIONS_BM / f"{key}.npz"
        ck = C.TRAIN_OUT / f"bm_{key}" / "params_best"
        vid = C.RENDER_OUT / f"bm_{key}_final.mp4"
        if bm.exists() and ck.exists():
            out[label] = {"bm": str(bm), "params": str(ck), "name": key,
                          "video": str(vid) if vid.exists() else None}
    return out
