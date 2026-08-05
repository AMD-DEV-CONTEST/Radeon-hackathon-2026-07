"""Run a policy in the loop, and score it the same way the teacher is scored.

    uv run evaluate                                   # score the last checkpoint
    uv run evaluate --video out/eval.mp4              # ...and film one env
    uv run evaluate --regression                      # replay; needs no lerobot

This is the other half of `record.py`. That module defines what an action MEANS;
this one is the only place that has to interpret it, and it has to interpret it
identically or the numbers a policy emits mean something other than what they
meant in training. Two contracts, both inherited:

  RATE   one action per `record_every` control steps -- 25 Hz. Not "about
         25 Hz": the delta was measured over exactly that window.
  DELTA  command `q_measured + action`, never `action` alone. The recorded
         value is a command offset and it carries the standing error the
         position controller needs just to hold the arm up against gravity.
         Commanding the delta alone drops that, and the arm sags a little
         further every tick.

REPLAY IS THE REGRESSION. Feeding the teacher's own recorded actions back
through this loop has to reproduce the demonstration. If it does not, the
recorded actions do not mean what this loop thinks they mean, and no amount of
training will fix it -- the dataset and the deployment would be different
control problems. It needs no checkpoint and no lerobot, so it is the cheapest
test in the project and the one that catches the most.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import genesis as gs

from . import teacher
from .config import CHECKPOINT, EnvConfig
from .randomize import EpisodeSetup, sample_episode
from .record import Recorder, state_vector
from .render_episode import write
from .robot import N_DOFS
from .scene import SceneBundle, build_scene
from .task_state import EpisodeResult, Monitor, cabinet_shift


def run_policy(b: SceneBundle, setup: EpisodeSetup, policy, ticks: int, *,
               on_tick=None) -> EpisodeResult:
    """One episode under policy control. `b.reset(setup)` must precede.

    Returns the teacher's own verdict type, judged by the same latch, so the
    two are directly comparable. The monitor ticks every CONTROL step rather
    than every action, because `hold_steps` counts control steps.
    """
    monitor = Monitor(b)
    for _ in range(ticks):
        q = b.qpos()
        action = policy(b.render_obs(), state_vector(q), b.tactile_feature(),
                        setup.prompts)
        q_cmd = q[:, :N_DOFS] + np.asarray(action, dtype=np.float64)

        # Issue once, then hold for the tick. This is the training-time
        # contract, not an approximation of it.
        for _ in range(b.cfg.record_every):
            b.franka.control_dofs_position(q_cmd)
            b.step()
            monitor.update()
        if on_tick is not None:
            on_tick()
    return monitor.result()


class ReplayPolicy:
    """Emits the teacher's recorded actions, in order."""

    def __init__(self, rec: Recorder):
        self.actions = list(rec.action)   # per tick, each (N, 9)
        self.t = 0

    def reset(self) -> None:
        self.t = 0

    def __call__(self, images, state, tactile, prompts) -> np.ndarray:
        # Past the end, repeat the last action rather than emitting zeros: a
        # zero delta commands the arm to wherever it has already sagged to,
        # and from there it sags again.
        a = self.actions[min(self.t, len(self.actions) - 1)]
        self.t += 1
        return a


class Pi05Policy:
    """A fine-tuned checkpoint, driven at the recorded rate.

    `select_action` serves from an internal queue and only runs a forward pass
    when it empties, so the chunking comes out of the checkpoint's own config
    for free. A forward pass therefore has `n_action_steps` ticks to complete;
    if it takes longer the arm still steps at 25 Hz, it just waits between
    chunks, so the symptom shows up in wall time rather than silently in the
    trajectory.

    The batch below must match what the DATASET yields, not what the simulator
    renders. LeRobotDataset serves images as (N, 3, H, W) float in [0, 1];
    `render_obs` returns (N, H, W, 3) uint8. Handing the latter straight to the
    policy reaches the vision tower as a 224-channel image.
    """

    def __init__(self, checkpoint: str, *, device: str = "cuda"):
        import torch
        from lerobot.policies.factory import make_pre_post_processors

        from .policy_tactile import OBS_TACTILE, TactilePI05Policy, register

        register()
        self.torch = torch
        self.device = device
        self.key_tactile = OBS_TACTILE
        self.policy = TactilePI05Policy.from_pretrained(checkpoint).to(device).eval()
        self.pre, self.post = make_pre_post_processors(self.policy.config, checkpoint)

        # Only the ticks that empty the queue actually run the model. reset()
        # clears it, so a forward pass is exactly every n_action_steps-th tick
        # -- which beats reading the queue's private length to find out.
        self.n_action_steps = self.policy.config.n_action_steps
        self.chunk_ms: list[float] = []
        self.tick = 0

    def reset(self) -> None:
        self.policy.reset()
        self.tick = 0

    def __call__(self, images, state, tactile, prompts) -> np.ndarray:
        torch = self.torch
        # Timed around the whole call on purpose: the forward is async, and the
        # .cpu() at the end is what forces it to finish. Timing the model call
        # alone would measure kernel launches.
        forward = self.tick % self.n_action_steps == 0
        self.tick += 1
        t0 = time.perf_counter()

        batch = {f"observation.images.{k}":
                 torch.from_numpy(v).to(self.device)
                      .permute(0, 3, 1, 2).float().div_(255.0)
                 for k, v in images.items()}
        batch["observation.state"] = torch.from_numpy(state).to(self.device).float()
        batch[self.key_tactile] = torch.from_numpy(tactile).to(self.device).float()
        batch["task"] = list(prompts)

        with torch.no_grad():
            action = self.policy.select_action(self.pre(batch))
        out = self.post(action).cpu().numpy()

        if forward:
            self.chunk_ms.append(1e3 * (time.perf_counter() - t0))
        return out


def _film(b: SceneBundle, e: int, frames: list) -> None:
    """One frame per action tick, with the same lines `render` burns in.

    The tick rate IS the video rate here -- 25 Hz -- so the mp4 plays back at
    the speed the policy actually ran at, unlike `render`, which films the
    control loop and subsamples it.
    """
    img = np.ascontiguousarray(b.render()[e])
    s = b.setup
    lines = [
        s.prompts[e],
        f"travel {b.drawer_travel()[e, s.target_idx[e]] * 1e3:6.1f}"
        f" / {s.target_travel[e] * 1e3:.1f} mm",
        f"taxel  {b.tactile_peak()[e]:6.2f}",
        f"cab    {cabinet_shift(b)[e] * 1e3:6.1f} mm",
    ]
    for i, line in enumerate(lines):
        cv2.putText(img, line, (10, 24 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2, cv2.LINE_AA)
    frames.append(img)


def replay(cfg: EnvConfig, batches: int) -> None:
    """Teacher, then its own actions fed back through the inference loop."""
    b = build_scene(cfg)
    rng = np.random.default_rng(cfg.seed)

    tea, rep = [], []
    for i in range(batches):
        setup = sample_episode(cfg, rng)

        b.reset(setup)
        rec = Recorder(b)
        r_teacher = teacher.run_episode(b, setup, rng, on_step=rec)

        # Same setup, same randomization, same arm -- only the controller
        # differs. Any divergence is the action contract, not the task.
        b.reset(setup)
        r_replay = run_policy(b, setup, ReplayPolicy(rec), rec.n_frames)

        tea.append(r_teacher)
        rep.append(r_replay)
        print(f"  batch {i + 1}/{batches}: teacher {r_teacher.success.sum()}/{r_teacher.n}"
              f"   replay {r_replay.success.sum()}/{r_replay.n}"
              f"   ({rec.n_frames} ticks)")

    t = np.concatenate([r.success for r in tea])
    p = np.concatenate([r.success for r in rep])
    dt = np.concatenate([r.travel for r in tea])
    dp = np.concatenate([r.travel for r in rep])
    print(f"\n  teacher  {t.sum()}/{len(t)}")
    print(f"  replay   {p.sum()}/{len(p)}")
    print(f"  travel   teacher mean {dt.mean() * 1e3:.1f} mm, "
          f"replay mean {dp.mean() * 1e3:.1f} mm, "
          f"max |diff| {np.abs(dt - dp).max() * 1e3:.2f} mm")
    if p.sum() < t.sum():
        print("\n  REPLAY IS BELOW TEACHER. The recorded actions do not mean what"
              "\n  this loop thinks they mean. Fix that before training anything.")


def evaluate(cfg: EnvConfig, batches: int, checkpoint: str, ticks: int, *,
             video: str | None = None, env: int = 0) -> None:
    policy = Pi05Policy(checkpoint)
    b = build_scene(cfg)
    rng = np.random.default_rng(cfg.seed)

    out, frames = [], []
    for i in range(batches):
        setup = sample_episode(cfg, rng)
        b.reset(setup)
        policy.reset()
        # Only the first batch is filmed; the rest are the same episode with a
        # different draw, and one mp4 is what a demo needs.
        hook = (lambda: _film(b, env, frames)) if video and i == 0 else None
        r = run_policy(b, setup, policy, ticks, on_tick=hook)
        out.append(r)
        print(f"  batch {i + 1}/{batches}: {r.success.sum()}/{r.n}")
        if frames and i == 0:
            print(f"  env {env}: success={bool(r.success[env])} "
                  f"travel={r.travel[env] * 1e3:.1f} mm "
                  f"latency={r.latency[env]}  '{setup.prompts[env]}'")
            write(frames, Path(video), round(1 / (cfg.dt * cfg.record_every)))

    r = EpisodeResult(**{f: np.concatenate([getattr(x, f) for x in out])
                         for f in EpisodeResult.__dataclass_fields__})
    print(f"\n  success       {r.success.sum()}/{r.n} = {100 * r.success.mean():.1f}%")
    print(f"  opened        {r.opened.sum()}/{r.n}")
    print(f"  released      {r.released.sum()}/{r.n}")
    print(f"  wrong drawer  {r.wrong_drawer.sum()}")
    print(f"  dragged       {r.dragged.sum()}")
    print(f"  shortfall     mean {r.shortfall.mean() * 1e3:.2f} mm")
    print(f"  cabinet shift mean {r.shift.mean() * 1e3:.2f} mm, "
          f"max {r.shift.max() * 1e3:.2f}")
    lat = r.latency[r.latency >= 0]
    if len(lat):
        print(f"  release latency mean {lat.mean():.0f} steps, "
              f"median {np.median(lat):.0f}")

    # The budget is how long the chunk it just produced will take to play out.
    # Over it, the arm waits between chunks; the trajectory is unaffected but
    # the loop no longer runs in real time.
    ms = np.array(policy.chunk_ms[1:])   # the first includes warm-up
    if len(ms):
        budget = 1e3 * cfg.dt * cfg.record_every * policy.n_action_steps
        print(f"  inference     median {np.median(ms):.0f} ms/chunk, "
              f"mean {ms.mean():.0f}, max {ms.max():.0f}  "
              f"(budget {budget:.0f} ms at N={cfg.n_envs})")


def main() -> None:
    ap = argparse.ArgumentParser(description="run a policy in the loop")
    ap.add_argument("--regression", action="store_true",
                    help="replay the teacher's own actions instead of scoring a "
                         "checkpoint; needs neither weights nor lerobot")
    ap.add_argument("--envs", type=int)
    ap.add_argument("--batches", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=200,
                    help="action ticks per episode under policy control; 200 is "
                         "8 s, against demonstrations averaging 6.6 s")
    ap.add_argument("--checkpoint", default=CHECKPOINT)
    ap.add_argument("--video", help="film one env of the first batch to this mp4")
    ap.add_argument("--env", type=int, default=0, help="which env to film")
    args = ap.parse_args()

    # The regression only has to reproduce the teacher, so one small batch
    # answers it; a success rate needs episodes to average over.
    envs = args.envs or (8 if args.regression else 16)
    batches = args.batches or (1 if args.regression else 4)

    gs.init(backend=gs.gpu, logging_level="warning")
    # The free camera is only built when it is going to be used: it is not an
    # observation, and rendering it costs a frame per tick.
    cfg = EnvConfig(n_envs=envs, seed=args.seed, add_wrist_cams=True,
                    add_camera=bool(args.video))

    if args.regression:
        replay(cfg, batches)
        return
    if not Path(args.checkpoint).exists():
        raise SystemExit(f"no checkpoint at {args.checkpoint}")
    evaluate(cfg, batches, args.checkpoint, args.ticks,
             video=args.video, env=args.env)


if __name__ == "__main__":
    main()
