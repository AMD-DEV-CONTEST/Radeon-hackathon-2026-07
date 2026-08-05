"""Adapter for the frozen Quadrupedal-Agility Go2 BBC checkpoint."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from unilab.algos.torch.cpp_loco import (
    DEFAULT_CPP_LOCO_CONTRACT,
    unilab_action_to_canonical_target,
)


@dataclass(frozen=True)
class AgilityBbcContract:
    source_default_dof: tuple[float, ...] = (0.0, 0.9, -1.8) * 4
    source_action_scale: float = 0.25
    source_hip_scale_reduction: float = 0.3
    clip_observations: float = 100.0
    clip_actions: float = 100.0


DEFAULT_AGILITY_BBC_CONTRACT = AgilityBbcContract()
SOURCE_AGILITY_BBC_CONTRACT = AgilityBbcContract(source_hip_scale_reduction=0.5)
SOURCE_TSC_COMMAND_LOW = (
    (0.5, -0.3, -1.57, 0.45, 0.25),
    (0.8, -0.5, -0.5, 0.45, 0.25),
    (0.8, -0.3, -0.5, 0.45, 0.25),
)
SOURCE_TSC_COMMAND_HIGH = (
    (1.5, 0.3, 1.57, 0.58, 0.34),
    (2.5, 0.5, 0.5, 0.58, 0.34),
    (2.0, 0.3, 0.5, 0.58, 0.34),
)


def _batch(value: np.ndarray, width: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != width:
        raise ValueError(f"{name} must have shape (N, {width}), got {array.shape}")
    return array


def _roll_pitch(base_quat_wxyz: np.ndarray) -> np.ndarray:
    quat = _batch(base_quat_wxyz, 4, "base_quat_wxyz")
    w, x, y, z = quat.T
    roll = np.arctan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2.0 * (w * y - z * x), -1.0, 1.0))
    return np.stack((roll, pitch), axis=1).astype(np.float32)


def _yaw(base_quat_wxyz: np.ndarray) -> np.ndarray:
    quat = _batch(base_quat_wxyz, 4, "base_quat_wxyz")
    w, x, y, z = quat.T
    yaw = np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return yaw.reshape(-1, 1).astype(np.float32)


def build_agility_proprio(
    base_quat_wxyz: np.ndarray,
    base_ang_vel: np.ndarray,
    dof_pos: np.ndarray,
    dof_vel: np.ndarray,
    previous_action: np.ndarray,
    foot_contact: np.ndarray,
    contract: AgilityBbcContract = DEFAULT_AGILITY_BBC_CONTRACT,
) -> np.ndarray:
    """Build the source deployment 57-D proprioception in FL/FR/RL/RR order."""
    quat = _batch(base_quat_wxyz, 4, "base_quat_wxyz")
    gyro = _batch(base_ang_vel, 3, "base_ang_vel")
    position = _batch(dof_pos, 12, "dof_pos")
    velocity = _batch(dof_vel, 12, "dof_vel")
    previous = _batch(previous_action, 12, "previous_action")
    contact = _batch(foot_contact, 4, "foot_contact")
    batch_size = quat.shape[0]
    if any(value.shape[0] != batch_size for value in (gyro, position, velocity, previous, contact)):
        raise ValueError("proprioception batch sizes differ")

    proprio = np.concatenate(
        (
            _roll_pitch(quat),
            gyro * 0.25,
            position - np.asarray(contract.source_default_dof, dtype=np.float32),
            velocity * 0.05,
            previous,
            (contact > 0.5).astype(np.float32) - 0.5,
            np.zeros((batch_size, 12), dtype=np.float32),
        ),
        axis=1,
    )
    return np.clip(
        proprio,
        -float(contract.clip_observations),
        float(contract.clip_observations),
    )


def agility_action_to_unilab(
    source_action: np.ndarray,
    contract: AgilityBbcContract = DEFAULT_AGILITY_BBC_CONTRACT,
) -> np.ndarray:
    """Preserve the source PD joint target in the UniLab actuator contract."""
    action = np.clip(
        _batch(source_action, 12, "source_action"),
        -float(contract.clip_actions),
        float(contract.clip_actions),
    )
    scale = np.full(12, float(contract.source_action_scale), dtype=np.float32)
    scale[[0, 3, 6, 9]] *= float(contract.source_hip_scale_reduction)
    target_dof = np.asarray(contract.source_default_dof, dtype=np.float32) + action * scale

    unilab = DEFAULT_CPP_LOCO_CONTRACT
    actuator_to_dof = np.asarray(unilab.actuator_to_dof, dtype=np.int64)
    target_actuator = target_dof[:, actuator_to_dof]
    default_actuator = np.asarray(unilab.unilab_default_dof, dtype=np.float32)[actuator_to_dof]
    action_scale = np.asarray(unilab.unilab_action_scale_actuator, dtype=np.float32)
    return (target_actuator - default_actuator) / action_scale


def resolve_student_actor_inputs(
    predicted_yaw: torch.Tensor,
    obstacle_probabilities: torch.Tensor,
    delta_yaw: np.ndarray | None,
    obstacle_type: int | None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Choose the actor-visible yaw/one-hot slots for the depth student.

    Defaults reproduce the released deployment (depth predictions); explicit
    values override the corresponding slot without touching the depth encoder
    input contract or the scan latent.
    """
    if delta_yaw is None:
        actor_yaw = predicted_yaw
    else:
        actor_yaw = torch.as_tensor(
            _batch(delta_yaw, 2, "delta_yaw"),
            device=predicted_yaw.device,
            dtype=predicted_yaw.dtype,
        )
    if obstacle_type is None:
        actor_one_hot = torch.nn.functional.one_hot(
            torch.argmax(obstacle_probabilities, dim=-1), num_classes=6
        ).to(predicted_yaw.dtype)
    else:
        if not 0 <= int(obstacle_type) < 6:
            raise ValueError("obstacle_type must be in [0, 5]")
        actor_one_hot = torch.eye(
            6, device=predicted_yaw.device, dtype=predicted_yaw.dtype
        )[[int(obstacle_type)]]
    return actor_yaw, actor_one_hot


def expand_source_tsc_command(command: torch.Tensor) -> torch.Tensor:
    """Map selected trot/canter/jump one-hot commands into source five-mode slots."""
    if command.ndim != 2 or command.shape[1] != 9:
        raise ValueError(f"command must have shape (N, 9), got {tuple(command.shape)}")
    return torch.cat(
        (command[:, :6], command.new_zeros((command.shape[0], 2)), command[:, 6:]),
        dim=1,
    )


class AgilityBbcPolicyAdapter:
    """Run the source three-mode BBC in one UniLab Go2 environment."""

    def __init__(
        self,
        source_root: str | Path,
        checkpoint: str | Path,
        *,
        device: str | torch.device = "cuda",
        contract: AgilityBbcContract = DEFAULT_AGILITY_BBC_CONTRACT,
        mode_count: int = 3,
        use_half: bool = False,
    ) -> None:
        root = Path(source_root).resolve()
        for path in (root / "tsc", root):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))

        from go2_deploy.scripts.common import (
            build_low_level_model,
            validate_low_level_checkpoint,
        )

        self.device = torch.device(device)
        self.dtype = torch.float16 if use_half else torch.float32
        self.contract = contract
        self.mode_count = mode_count
        self.model, self.estimator = build_low_level_model(mode_count, str(self.device), use_half)
        payload = torch.load(Path(checkpoint), map_location=self.device, weights_only=False)
        validate_low_level_checkpoint(payload, mode_count)
        self.model.load_state_dict(payload["actor_critic"])
        self.estimator.load_state_dict(payload["estimator"])
        self.model.eval()
        self.estimator.eval()
        self.previous_action = np.zeros((1, 12), dtype=np.float32)
        self.history = np.zeros((1, 570), dtype=np.float32)

    def reset(self) -> None:
        self.previous_action.fill(0.0)
        self.history.fill(0.0)

    def act(
        self,
        *,
        base_quat_wxyz: np.ndarray,
        base_ang_vel: np.ndarray,
        dof_pos: np.ndarray,
        dof_vel: np.ndarray,
        foot_contact: np.ndarray,
        command: np.ndarray,
        explicit: np.ndarray | None = None,
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        proprio = build_agility_proprio(
            base_quat_wxyz,
            base_ang_vel,
            dof_pos,
            dof_vel,
            self.previous_action,
            foot_contact,
            self.contract,
        )
        if proprio.shape[0] != 1:
            raise ValueError("Agility BBC adapter currently supports one environment")
        command_array = _batch(command, 6 + self.mode_count, "command")
        if command_array.shape[0] != 1:
            raise ValueError("Agility BBC adapter currently supports one environment")

        proprio_tensor = torch.as_tensor(proprio, device=self.device, dtype=self.dtype)
        history_tensor = torch.as_tensor(self.history.copy(), device=self.device, dtype=self.dtype)
        command_tensor = torch.as_tensor(command_array, device=self.device, dtype=self.dtype)
        with torch.inference_mode():
            explicit_tensor = (
                self.estimator(proprio_tensor)
                if explicit is None
                else torch.as_tensor(
                    _batch(explicit, 4, "explicit"),
                    device=self.device,
                    dtype=self.dtype,
                )
            )
            low_input = torch.cat(
                (
                    proprio_tensor,
                    explicit_tensor,
                    torch.zeros((1, 29), device=self.device, dtype=self.dtype),
                    history_tensor,
                    command_tensor,
                ),
                dim=1,
            )
            source_action_tensor = self.model.act_inference(low_input, hist_encoding=True)

        source_action = source_action_tensor.cpu().numpy().astype(np.float32)
        explicit_array = explicit_tensor.cpu().numpy().astype(np.float32)
        low_input_array = low_input.cpu().numpy().astype(np.float32)
        if not all(
            np.isfinite(value).all()
            for value in (
                proprio,
                explicit_array,
                low_input_array,
                source_action,
            )
        ):
            raise FloatingPointError("Agility BBC produced NaN or Inf")

        self.previous_action[:] = source_action
        self.history[:, :-57] = self.history[:, 57:]
        self.history[:, -57:] = proprio
        unilab_action = agility_action_to_unilab(source_action, self.contract)
        return unilab_action, {
            "proprio": proprio,
            "explicit": explicit_array,
            "history": history_tensor.cpu().numpy().astype(np.float32),
            "low_input": low_input_array,
            "source_action": source_action,
            "canonical_target": unilab_action_to_canonical_target(unilab_action),
        }


class AgilityTscPolicyAdapter:
    """Run the frozen TSC teacher or depth student through the BBC adapter."""

    def __init__(
        self,
        source_root: str | Path,
        high_checkpoint: str | Path,
        low_checkpoint: str | Path,
        *,
        device: str | torch.device = "cuda",
        low_contract: AgilityBbcContract = DEFAULT_AGILITY_BBC_CONTRACT,
        low_mode_count: int = 3,
        command_profile: str = "deployment",
        high_branch: str = "teacher",
        use_half: bool = False,
    ) -> None:
        root = Path(source_root).resolve()
        for path in (root / "tsc", root):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))

        from go2_deploy.config.go2_parkour_config import (
            Go2ParkourCfg,
            Go2ParkourCfgPPO,
        )
        from go2_deploy.module.depth_backbone import (
            DepthOnlyFCBackbone58x87,
            RecurrentDepthBackbone,
        )
        from go2_deploy.module.estimator import Estimator
        from go2_deploy.module.net_high import Actor, get_activation
        from go2_deploy.utils.command_builder import CommandBuilder

        self.device = torch.device(device)
        if self.device.type != "cuda":
            raise RuntimeError("Agility TSC source model requires a CUDA/ROCm device")
        if high_branch not in {"teacher", "student"}:
            raise ValueError("high_branch must be 'teacher' or 'student'")
        self.high_branch = high_branch
        self.dtype = torch.float16 if use_half else torch.float32
        env_cfg = Go2ParkourCfg
        policy_cfg = Go2ParkourCfgPPO
        self.high_model = Actor(
            num_prop=env_cfg.env.n_proprio,
            num_auxiliary=env_cfg.env.n_auxiliary,
            num_scan=env_cfg.env.n_scan,
            num_priv_latent=env_cfg.env.n_priv_latent,
            num_priv_explicit=env_cfg.env.n_priv,
            num_hist=env_cfg.env.history_len,
            num_actions_d=env_cfg.env.num_actions_d,
            num_actions_c=env_cfg.env.num_actions_c,
            scan_encoder_dims=policy_cfg.policy.scan_encoder_dims,
            actor_hidden_dims=policy_cfg.policy.actor_hidden_dims,
            priv_encoder_dims=policy_cfg.policy.priv_encoder_dims,
            init_with_orthogonal=policy_cfg.policy.init_with_orthogonal,
            tanh_encoder_output=policy_cfg.policy.tanh_encoder_output,
            activation=get_activation(policy_cfg.policy.activation),
        ).to(self.device)
        payload = torch.load(Path(high_checkpoint), map_location=self.device, weights_only=False)
        if high_branch == "teacher":
            teacher_actor = {
                key.removeprefix("actor."): value
                for key, value in payload["model_state_dict"].items()
                if key.startswith("actor.")
            }
            self.high_model.load_state_dict(teacher_actor)
            self.high_estimator = Estimator(
                input_dim=env_cfg.env.n_proprio - env_cfg.env.n_auxiliary,
                output_dim=env_cfg.env.n_priv,
                hidden_dims=policy_cfg.estimator.hidden_dims,
            ).to(self.device)
            self.high_estimator.load_state_dict(payload["estimator_state_dict"])
            self.depth_encoder = None
        else:
            self.high_model.load_state_dict(payload["depth_actor_state_dict"])
            depth_backbone = DepthOnlyFCBackbone58x87(
                env_cfg.env.n_proprio,
                policy_cfg.policy.scan_encoder_dims[-1],
                policy_cfg.depth_encoder.hidden_dims,
            )
            self.depth_encoder = RecurrentDepthBackbone(
                depth_backbone,
                policy_cfg.policy.scan_encoder_dims[-1],
                env_cfg,
            ).to(self.device)
            self.depth_encoder.load_state_dict(
                {
                    key: value
                    for key, value in payload["depth_encoder_state_dict"].items()
                    if "byol" not in key
                }
            )
            self.high_estimator = None
        if use_half:
            self.high_model.half()
            if self.high_estimator is not None:
                self.high_estimator.half()
            if self.depth_encoder is not None:
                self.depth_encoder.half()
        self.high_model.eval()
        if self.high_estimator is not None:
            self.high_estimator.eval()
        if self.depth_encoder is not None:
            self.depth_encoder.eval()
        self.commander = CommandBuilder(
            env_cfg.env.num_actions_d,
            env_cfg,
            device=self.device,
            use_half=use_half,
        )
        if command_profile == "source":
            if low_mode_count != 5:
                raise ValueError("source command profile requires low_mode_count=5")
            low = torch.tensor(SOURCE_TSC_COMMAND_LOW, device=self.device, dtype=self.dtype)
            high = torch.tensor(SOURCE_TSC_COMMAND_HIGH, device=self.device, dtype=self.dtype)
            self.commander.command_offset_mat = low
            self.commander.command_range_mat = high - low
        elif command_profile != "deployment":
            raise ValueError("command_profile must be 'deployment' or 'source'")
        self.command_profile = command_profile
        self.low_mode_count = low_mode_count
        self.bbc = AgilityBbcPolicyAdapter(
            root,
            low_checkpoint,
            device=self.device,
            contract=low_contract,
            mode_count=low_mode_count,
            use_half=use_half,
        )
        self._history_fill_steps = 0
        self._initial_yaw: torch.Tensor | None = None

    def reset(self) -> None:
        self.bbc.reset()
        self._history_fill_steps = 0
        self._initial_yaw = None
        if self.depth_encoder is not None:
            self.depth_encoder.delete_memory()

    def preview_command(
        self,
        *,
        base_quat_wxyz: np.ndarray,
        base_ang_vel: np.ndarray,
        dof_pos: np.ndarray,
        dof_vel: np.ndarray,
        foot_contact: np.ndarray,
        height_scan: np.ndarray | None = None,
        delta_yaw: np.ndarray | None = None,
        obstacle_type: int | None = None,
        depth_image: np.ndarray | None = None,
        low_explicit: np.ndarray | None = None,
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        if low_explicit is not None:
            _batch(low_explicit, 4, "low_explicit")
        proprio = build_agility_proprio(
            base_quat_wxyz,
            base_ang_vel,
            dof_pos,
            dof_vel,
            self.bbc.previous_action,
            foot_contact,
        )
        proprio_tensor = torch.as_tensor(proprio, device=self.device, dtype=self.dtype)
        history_tensor = torch.as_tensor(
            self.bbc.history.copy(), device=self.device, dtype=self.dtype
        )
        with torch.inference_mode():
            if self.high_branch == "teacher":
                if height_scan is None or delta_yaw is None or obstacle_type is None:
                    raise ValueError(
                        "teacher branch requires height_scan, delta_yaw, and obstacle_type"
                    )
                scan = _batch(height_scan, 132, "height_scan")
                yaw = _batch(delta_yaw, 2, "delta_yaw")
                if scan.shape[0] != 1 or yaw.shape[0] != 1:
                    raise ValueError("Agility TSC adapter currently supports one environment")
                if not 0 <= obstacle_type < 6:
                    raise ValueError("obstacle_type must be in [0, 5]")
                obstacle_one_hot = np.eye(6, dtype=np.float32)[[obstacle_type]]
                high_proprio = np.concatenate((proprio, yaw, obstacle_one_hot), axis=1)
                scan_tensor = torch.as_tensor(scan, device=self.device, dtype=self.dtype)
                explicit = self.high_estimator(proprio_tensor)
                scan_latent = None
                student_diagnostics: dict[str, np.ndarray] = {}
            else:
                if depth_image is None:
                    raise ValueError("student branch requires depth_image")
                depth = np.asarray(depth_image, dtype=np.float32)
                if depth.shape != (1, 58, 87):
                    raise ValueError(f"depth_image must have shape (1, 58, 87), got {depth.shape}")
                if not np.isfinite(depth).all():
                    raise ValueError("depth_image contains NaN or Inf")
                high_proprio_tensor = torch.cat(
                    (
                        proprio_tensor,
                        torch.zeros((1, 8), device=self.device, dtype=self.dtype),
                    ),
                    dim=1,
                )
                observed_yaw = torch.as_tensor(
                    _yaw(base_quat_wxyz), device=self.device, dtype=self.dtype
                )
                if self._initial_yaw is None:
                    self._initial_yaw = observed_yaw.clone()
                absolute_yaw = (observed_yaw - self._initial_yaw + torch.pi / 2) % (
                    2 * torch.pi
                ) - torch.pi / 2
                high_proprio_tensor[:, 57] = absolute_yaw[:, 0]
                depth_latent = self.depth_encoder(
                    torch.as_tensor(depth, device=self.device, dtype=self.dtype),
                    high_proprio_tensor,
                )
                predicted_yaw = 1.5 * depth_latent[:, 32:34]
                obstacle_probabilities = depth_latent[:, 34:]
                obstacle_index = torch.argmax(obstacle_probabilities, dim=-1)
                actor_yaw, actor_one_hot = resolve_student_actor_inputs(
                    predicted_yaw,
                    obstacle_probabilities,
                    delta_yaw,
                    obstacle_type,
                )
                high_proprio_tensor[:, 57:59] = actor_yaw
                high_proprio_tensor[:, 59:65] = actor_one_hot
                high_proprio = high_proprio_tensor.cpu().numpy().astype(np.float32)
                scan = np.zeros((1, 132), dtype=np.float32)
                scan_tensor = torch.zeros((1, 132), device=self.device, dtype=self.dtype)
                explicit = self.bbc.estimator(proprio_tensor)
                scan_latent = depth_latent[:, :32]
                student_diagnostics = {
                    "depth_image": depth,
                    "depth_latent": depth_latent.cpu().numpy().astype(np.float32),
                    "predicted_delta_yaw": predicted_yaw.cpu().numpy().astype(np.float32),
                    "predicted_obstacle": obstacle_index.cpu().numpy().astype(np.int64),
                    "obstacle_probabilities": obstacle_probabilities.cpu()
                    .numpy()
                    .astype(np.float32),
                    "absolute_yaw": absolute_yaw.cpu().numpy().astype(np.float32),
                    "actor_delta_yaw": actor_yaw.cpu().numpy().astype(np.float32),
                    "actor_obstacle_one_hot": actor_one_hot.cpu()
                    .numpy()
                    .astype(np.float32),
                }
            high_input = torch.cat(
                (
                    torch.as_tensor(high_proprio, device=self.device, dtype=self.dtype),
                    scan_tensor,
                    explicit,
                    history_tensor,
                ),
                dim=1,
            )
            embedding = self.high_model(high_input, hist_encoding=True, scandots_latent=scan_latent)
            logits = self.high_model.actor_d(embedding)
            skill = torch.argmax(torch.softmax(logits, dim=-1), dim=-1)
            continuous = self.high_model.actor_c(embedding)
            high_action = torch.cat((skill.unsqueeze(-1), continuous), dim=-1)
            command = self.commander.set_commands(high_action)
            if self.low_mode_count == 5:
                command = expand_source_tsc_command(command)

        diagnostics = {
            "high_proprio": high_proprio,
            "height_scan": scan,
            "high_input": high_input.cpu().numpy().astype(np.float32),
            "high_explicit": explicit.cpu().numpy().astype(np.float32),
            "high_embedding": embedding.cpu().numpy().astype(np.float32),
            "skill_logits": logits.cpu().numpy().astype(np.float32),
            "skill": skill.cpu().numpy().astype(np.int64),
            "high_continuous": continuous.cpu().numpy().astype(np.float32),
            "command": command.cpu().numpy().astype(np.float32),
            **student_diagnostics,
        }
        if not all(np.isfinite(value).all() for value in diagnostics.values()):
            raise FloatingPointError("Agility TSC produced NaN or Inf")
        return diagnostics["command"], diagnostics

    def act(self, **observations: np.ndarray | int) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        command, high = self.preview_command(**observations)
        low_keys = (
            "base_quat_wxyz",
            "base_ang_vel",
            "dof_pos",
            "dof_vel",
            "foot_contact",
        )
        action, low = self.bbc.act(
            **{key: observations[key] for key in low_keys},
            command=command,
            explicit=observations.get("low_explicit"),
        )
        if self.high_branch == "student":
            # Match go2_deploy HistoryWrapper.step(), which returns zero history.
            self.bbc.history.fill(0.0)
        elif self._history_fill_steps < 1:
            self.bbc.history[:] = np.tile(low["proprio"], (1, 10))
            self._history_fill_steps += 1
        return action, {**high, **low}


__all__ = [
    "AgilityBbcContract",
    "AgilityBbcPolicyAdapter",
    "AgilityTscPolicyAdapter",
    "DEFAULT_AGILITY_BBC_CONTRACT",
    "SOURCE_AGILITY_BBC_CONTRACT",
    "SOURCE_TSC_COMMAND_HIGH",
    "SOURCE_TSC_COMMAND_LOW",
    "agility_action_to_unilab",
    "build_agility_proprio",
    "expand_source_tsc_command",
    "resolve_student_actor_inputs",
]
