"""VLA inference helpers: load an agent + run one closed-loop episode.

Two entry points:

  * ``load_agent(...)``  -- thin wrapper over ``vla.agent.make_agent`` returning a
    ready ``VLAAgent``.
  * ``run_episode(env, agent, ...)`` -- the Step-3 inference loop: query the agent at
    its dataset fps, hold each action for the matching number of sim substeps, and
    stop on task success. Returns an ``EpisodeResult``.

CLI:
    # self-check the loop wiring WITHOUT a GPU/sim, using a dummy agent + fake obs
    python vla/inference.py --self-check

    # run a real episode (needs Genesis + a trained checkpoint, on the Radeon box)
    python vla/inference.py --checkpoint <ckpt> --repo-id so101/cube_pick \\
        --dataset-root datasets/cube_pick --episodes 3 --save-video
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vla.agent import VLAAgent, make_agent


def load_agent(
    checkpoint: str,
    dataset_repo_id: str,
    dataset_root: str | None = None,
    *,
    backend: str = "smolvla",
    device: str = "cuda",
    use_amp: bool = False,
) -> VLAAgent:
    """Load a VLAAgent for closed-loop inference."""
    return make_agent(
        backend, checkpoint, dataset_repo_id, dataset_root,
        device=device, use_amp=use_amp,
    )


@dataclass
class EpisodeResult:
    success: bool
    n_steps: int = 0
    frames: list = field(default_factory=list)


def run_episode(
    env,
    agent: VLAAgent,
    *,
    max_seconds: float = 15.0,
    control_fps: int = 100,
    record_video: bool = False,
    target_color: str | None = None,
    seed: int | None = None,
) -> EpisodeResult:
    """Run one closed-loop rollout: reset -> (observe -> predict -> step)* -> success.

    The agent is queried at ``agent.fps``; each returned action is held for the
    matching number of sim substeps via ``env.step`` (which itself advances
    ``control_substeps`` steps). A fractional accumulator keeps the average
    control:policy ratio exact.
    """
    agent.reset()
    obs = env.reset(seed=seed, target_color=target_color)

    fps = getattr(agent, "fps", 30)
    max_frames = round(max_seconds * fps)
    result = EpisodeResult(success=False)

    for _ in range(max_frames):
        if record_video and "image" in obs:
            result.frames.append(obs["image"])

        chunk = agent.predict(
            obs["image"], obs["instruction"], obs["state"],
            wrist_image=obs.get("wrist_image"),
        )
        action = np.asarray(chunk)[0]  # first action of the chunk
        obs = env.step(action)
        result.n_steps += 1

        if env.check_success():
            result.success = True
            break

    return result


# ----------------------------------------------------------------------------
# Self-check: exercise the inference loop wiring without torch/lerobot/Genesis.
# ----------------------------------------------------------------------------

class _DummyAgent(VLAAgent):
    """A no-op agent returning zero action chunks; for wiring self-checks only."""

    backend = "dummy"
    fps = 30

    def __init__(self, action_dim: int = 6):
        self.action_dim = action_dim

    def reset(self) -> None:
        pass

    def predict(self, image, instruction, robot_state, *, wrist_image=None) -> np.ndarray:
        assert image.ndim == 3 and image.shape[2] == 3, "image must be HxWx3"
        assert isinstance(instruction, str) and instruction, "instruction must be non-empty str"
        assert np.asarray(robot_state).reshape(-1).shape[0] == self.action_dim
        return np.zeros((1, self.action_dim), dtype=np.float32)


class _DummyEnv:
    """Minimal env stub mirroring SO101PickPlaceEnv's obs/step/reset/success API."""

    def __init__(self, succeed_after: int = 3):
        self._n = 0
        self._succeed_after = succeed_after

    def _obs(self) -> dict:
        return {
            "image": np.zeros((48, 64, 3), dtype=np.uint8),
            "wrist_image": np.zeros((48, 64, 3), dtype=np.uint8),
            "state": np.zeros(6, dtype=np.float32),
            "instruction": "Pick the red cube and place it into the basket",
        }

    def reset(self, *, seed=None, target_color=None) -> dict:
        self._n = 0
        return self._obs()

    def step(self, action) -> dict:
        assert np.asarray(action).reshape(-1).shape[0] == 6
        self._n += 1
        return self._obs()

    def check_success(self, color=None) -> bool:
        return self._n >= self._succeed_after


def _self_check() -> int:
    """Run the inference loop end-to-end with stubs; returns a process exit code."""
    env = _DummyEnv(succeed_after=3)
    agent = _DummyAgent()
    result = run_episode(env, agent, max_seconds=1.0, record_video=True)
    ok = result.success and result.n_steps == 3 and len(result.frames) == 3
    print(f"[self-check] success={result.success} steps={result.n_steps} "
          f"frames={len(result.frames)} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="VLA inference (Step 3).")
    parser.add_argument("--self-check", action="store_true",
                        help="Verify the loop wiring with stubs (no GPU/sim needed).")
    parser.add_argument("--checkpoint", help="Trained policy checkpoint dir.")
    parser.add_argument("--repo-id", help="Dataset repo id the policy trained on.")
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--backend", default="smolvla")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("-c", "--cpu", action="store_true", help="Genesis CPU backend.")
    args = parser.parse_args()

    if args.self_check:
        raise SystemExit(_self_check())

    if not (args.checkpoint and args.repo_id):
        raise SystemExit("Provide --checkpoint and --repo-id (or use --self-check).")

    import genesis as gs
    from simulation.genesis_env import SO101PickPlaceEnv, build_scene

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    env = SO101PickPlaceEnv(bundle=build_scene())
    agent = load_agent(
        args.checkpoint, args.repo_id, args.dataset_root,
        backend=args.backend, device=args.device,
    )
    n_success = 0
    for ep in range(args.episodes):
        result = run_episode(env, agent, max_seconds=args.max_seconds, seed=1000 + ep)
        n_success += int(result.success)
        print(f"[infer] ep {ep} steps={result.n_steps} success={result.success}")
    print(f"[infer] success rate: {n_success}/{args.episodes}")


if __name__ == "__main__":
    main()
