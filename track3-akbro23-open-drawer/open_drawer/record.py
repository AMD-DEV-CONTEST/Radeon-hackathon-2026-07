"""Capture teacher demonstrations as (observation, action) pairs at 25 Hz.

Three things define the data, and all three are contracts the eval loop has to
honour.

RATE. An action is the joint delta commanded over one recorded tick, so the
policy must run at `EnvConfig.record_every` control steps per action -- 25 Hz --
or its outputs mean something other than what they meant in training.

ACTION = COMMAND, NOT MOTION. The action is `q_cmd - q_measured`, not the
motion that resulted. A position-controlled arm holding against gravity needs a
permanent offset between the two, and much of an episode is hold-like.
Recording achieved motion would label all those frames "do nothing", and a
policy obeying that at inference releases the offset that holds the arm up, so
it sags further every step.

TACTILE IS ITS OWN FEATURE. It is never concatenated into `observation.state`.
pi0.5 does not feed state to the action expert as a vector -- it normalizes it,
digitizes it into 256 bins and pastes it into the text prompt -- so a force
signal folded in there arrives 8-bit quantized through the tokenizer, and the
quiet majority of an episode collapses into one or two bins while the contact
event saturates. Kept separate, the same numbers stay continuous and can be
encoded straight into the action expert's conditioning.

The inference loop this implies:

    see obs(t) -> policy emits delta -> command q_measured(t) + delta
               -> hold `record_every` control steps -> repeat
"""
from __future__ import annotations

import numpy as np

from .robot import N_DOFS
from .scene import SceneBundle

STATE_DIM = 9    # 7 arm joints + 2 finger positions
ACTION_DIM = 9   # one delta per joint


def state_vector(q: np.ndarray) -> np.ndarray:
    """(N, n_dofs) qpos -> the (N, 9) `observation.state` the dataset stores.

    The whole joint vector, fingers included -- with a 9-dim action space the
    gripper is just two more joints, so there is no gripper MODE riding
    alongside and nothing to reduce to a jaw width.

    Takes qpos rather than the bundle so the caller can reuse the read it
    already made, and so this stays a pure function of it. `eval` calls this
    too: an observation assembled even slightly differently at inference is a
    different input distribution than the one trained on.
    """
    return q[:, :N_DOFS].astype(np.float32)


class Recorder:
    """`on_step` hook that emits one frame every `record_every` control steps.

    Everything is kept BATCHED -- one `(N, ...)` array per tick, exactly as the
    renderer produces it -- and split per env only in `episode()`, at flush
    time. Splitting per tick would run an N-long Python loop inside the hot
    path for no benefit.

    A frame is complete the moment it is observed:

        action(t) = q_cmd(t) - q(t)

    because `robot.apply` issues one command per tick and holds it, and the
    hook runs BEFORE the step -- so the command in force over the next 40 ms is
    already known, and it is the one the arm will actually execute. That is
    what lets an episode be replayed through the eval loop and reproduce
    itself; if the target moved again inside the tick, a recorded action would
    be one point on a ramp while the policy's identical number is held flat.
    """

    def __init__(self, b: SceneBundle):
        self.b = b
        self.every = b.cfg.record_every
        self.images: list[dict[str, np.ndarray]] = []   # per tick, each (N,H,W,3)
        self.state: list[np.ndarray] = []               # per tick, each (N, 9)
        self.action: list[np.ndarray] = []              # per tick, each (N, 9)
        self.tactile: list[np.ndarray] = []             # per tick, each (N, dim)

    def __call__(self, q_cmd: np.ndarray) -> None:
        if self.b.step_count % self.every:
            return
        q = self.b.qpos()
        self.images.append(self.b.render_obs())
        self.state.append(state_vector(q))
        self.tactile.append(self.b.tactile_feature())
        self.action.append(
            (q_cmd[:, :N_DOFS] - q[:, :N_DOFS]).astype(np.float32))

    # ---------------------------------------------------------------- output
    @property
    def n_frames(self) -> int:
        return len(self.action)

    @property
    def camera_names(self) -> list[str]:
        return list(self.images[0]) if self.images else []

    def episode(self, i: int) -> dict:
        """Env `i`'s stream, as contiguous arrays. Copies one episode's worth."""
        return {
            "images": {name: np.stack([tick[name][i] for tick in self.images])
                       for name in self.camera_names},
            "state": np.stack([s[i] for s in self.state]),
            "action": np.stack([a[i] for a in self.action]),
            "tactile": np.stack([t[i] for t in self.tactile]),
        }

    def nbytes(self) -> int:
        """Raw buffered size. Video encoding shrinks this a lot on disk, but
        this is what sits in RAM while a batch is collected, and it is what
        caps the N a collection run can use."""
        if not self.images:
            return 0
        return sum(a.nbytes for a in self.images[0].values()) * len(self.images)
