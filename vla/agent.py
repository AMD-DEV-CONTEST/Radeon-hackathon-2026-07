"""Unified Vision-Language-Action agent interface.

``VLAAgent`` is the single interface the rest of the system programs against::

    agent = SmolVLAAgent(checkpoint, dataset_repo_id, dataset_root, device="cuda")
    action_chunk = agent.predict(image, instruction, robot_state)

``predict`` takes an RGB image (HxWx3 uint8), a natural-language instruction, and
the current robot state (6-D joint positions), and returns an action chunk
(one or more 6-D joint-target vectors). Concrete backends implement ``_select``;
the base class handles the numpy<->policy plumbing shared by all of them.

Backends:
  * ``SmolVLAAgent``  -- LeRobot SmolVLA (implemented; the project default).
  * ``ACTAgent``      -- alias that reuses the same generic LeRobot loader.
  * ``OpenVLAAgent``  -- stub (raises NotImplementedError with guidance).

The SmolVLA/ACT path reuses LeRobot's generic ``PreTrainedConfig`` +
``make_policy`` + ``make_pre_post_processors`` + ``predict_action`` API, matching
the (verified) approach in the sibling ``franka_fruit_pick/eval_policy.py``.

NOTE: Requires ``lerobot`` + ``torch`` and a trained checkpoint; run on the
Radeon (ROCm) machine. On ROCm the device string is still ``"cuda"`` (the ROCm
torch build maps CUDA APIs onto HIP).
"""

from __future__ import annotations

import abc
from typing import ClassVar

import numpy as np

# Observation feature keys (must match the dataset the policy trained on;
# see dataset/lerobot_loader.py and scripts/record_dataset.py).
STATE_KEY = "observation.state"
WORLD_IMAGE_KEY = "observation.images.world"
WRIST_IMAGE_KEY = "observation.images.wrist"


class VLAAgent(abc.ABC):
    """Abstract Vision-Language-Action policy."""

    #: Human-readable backend name (set by subclasses).
    backend: str = "abstract"

    @abc.abstractmethod
    def reset(self) -> None:
        """Clear any temporal state (action queue / ensembling) between episodes."""

    @abc.abstractmethod
    def predict(
        self,
        image: np.ndarray,
        instruction: str,
        robot_state: np.ndarray,
        *,
        wrist_image: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return an action chunk given a single observation.

        Args:
            image: world-camera RGB, HxWx3 uint8.
            instruction: natural-language task string.
            robot_state: 6-D joint positions (float).
            wrist_image: optional eye-in-hand RGB, HxWx3 uint8.

        Returns:
            ``(T, 6)`` float32 array of joint-target vectors (``T >= 1``). Callers
            that want a single action can take row 0.
        """


class _LeRobotAgent(VLAAgent):
    """Shared LeRobot-backed agent (SmolVLA / ACT / any lerobot policy).

    The concrete backend is fully determined by the loaded checkpoint's config, so
    this one class serves every lerobot policy. Subclasses only set ``backend`` and
    an optional default ``rename_map``.
    """

    default_rename_map: ClassVar[dict[str, str] | None] = None

    def __init__(
        self,
        checkpoint: str,
        dataset_repo_id: str,
        dataset_root: str | None = None,
        *,
        device: str = "cuda",
        use_amp: bool = False,
        rename_map: dict[str, str] | None = None,
    ):
        # Imported lazily so importing this module never requires torch/lerobot
        # (e.g. for --help or static checks on a machine without them).
        import torch  # noqa: F401
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
        from lerobot.policies.factory import make_policy, make_pre_post_processors
        from lerobot.utils.device_utils import get_safe_torch_device

        self.device = get_safe_torch_device(device, log=True)
        self.use_amp = use_amp

        ds_meta = LeRobotDatasetMetadata(dataset_repo_id, root=dataset_root)
        self.fps = ds_meta.fps

        cfg = PreTrainedConfig.from_pretrained(checkpoint)
        cfg.pretrained_path = checkpoint
        cfg.device = str(self.device)

        if rename_map is None:
            rename_map = self.default_rename_map or {}
        self.policy = make_policy(cfg=cfg, ds_meta=ds_meta, rename_map=rename_map)
        self.policy.eval()
        self.preprocessor, self.postprocessor = make_pre_post_processors(
            policy_cfg=cfg,
            pretrained_path=checkpoint,
            preprocessor_overrides={"device_processor": {"device": str(self.device)}},
        )
        self.policy_type = cfg.type

        # Which image keys the dataset (hence the policy) expects.
        self.image_keys = [k for k in ds_meta.features if k.startswith("observation.images")]
        print(f"[vla] loaded {self.policy_type} ({self.backend}) on {self.device}; "
              f"images={self.image_keys} fps={self.fps}")

    def reset(self) -> None:
        self.policy.reset()

    def predict(
        self,
        image: np.ndarray,
        instruction: str,
        robot_state: np.ndarray,
        *,
        wrist_image: np.ndarray | None = None,
    ) -> np.ndarray:
        from lerobot.common.control_utils import predict_action

        obs: dict[str, np.ndarray] = {
            STATE_KEY: np.asarray(robot_state, dtype=np.float32).reshape(-1),
        }
        # Map whatever the policy expects onto what we have.
        if WORLD_IMAGE_KEY in self.image_keys:
            obs[WORLD_IMAGE_KEY] = np.ascontiguousarray(image, dtype=np.uint8)
        if WRIST_IMAGE_KEY in self.image_keys and wrist_image is not None:
            obs[WRIST_IMAGE_KEY] = np.ascontiguousarray(wrist_image, dtype=np.uint8)

        action = predict_action(
            obs,
            self.policy,
            self.device,
            self.preprocessor,
            self.postprocessor,
            use_amp=self.use_amp,
            task=instruction,
            robot_type="so101",
        )
        action = action.detach().cpu().numpy().astype(np.float32)
        # predict_action returns one action; normalize to a (T, D) chunk.
        return action.reshape(1, -1) if action.ndim == 1 else action


class SmolVLAAgent(_LeRobotAgent):
    """SmolVLA backend (project default).

    SmolVLA's base (``lerobot/smolvla_base``) is trained with canonical camera keys
    ``observation.images.camera{1,2,3}``; our datasets use ``world``/``wrist``. The
    rename is baked into the saved preprocessor at fine-tune time, so at inference
    the same map is passed to ``make_policy`` for its feature-consistency check.
    """

    backend = "smolvla"
    default_rename_map: ClassVar[dict[str, str] | None] = {
        WORLD_IMAGE_KEY: "observation.images.camera1",
        WRIST_IMAGE_KEY: "observation.images.camera2",
    }


class ACTAgent(_LeRobotAgent):
    """ACT backend. ACT adapts its input features to the dataset, so no rename."""

    backend = "act"
    default_rename_map = None


class OpenVLAAgent(VLAAgent):
    """OpenVLA backend -- placeholder for future support.

    OpenVLA (7B) is not part of the LeRobot policy factory and needs its own
    HF ``transformers`` load + action de-tokenization. Left as a stub so the
    interface is stable; implement ``predict`` against the OpenVLA model card
    when adding it.
    """

    backend = "openvla"

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "OpenVLAAgent is not implemented yet. Use SmolVLAAgent (default) or "
            "ACTAgent. OpenVLA needs a transformers-based loader + action "
            "de-tokenizer; wire it here against the OpenVLA model card."
        )

    def reset(self) -> None:  # pragma: no cover - unreachable stub
        raise NotImplementedError

    def predict(self, *args, **kwargs) -> np.ndarray:  # pragma: no cover - stub
        raise NotImplementedError


# Registry for a friendly factory (used by vla/inference.py + scripts).
AGENTS: dict[str, type[VLAAgent]] = {
    "smolvla": SmolVLAAgent,
    "act": ACTAgent,
    "openvla": OpenVLAAgent,
}


def make_agent(backend: str, *args, **kwargs) -> VLAAgent:
    """Instantiate a VLAAgent by backend name (``smolvla`` | ``act`` | ``openvla``)."""
    key = backend.lower()
    if key not in AGENTS:
        raise ValueError(f"Unknown VLA backend {backend!r}; choose from {sorted(AGENTS)}.")
    return AGENTS[key](*args, **kwargs)
