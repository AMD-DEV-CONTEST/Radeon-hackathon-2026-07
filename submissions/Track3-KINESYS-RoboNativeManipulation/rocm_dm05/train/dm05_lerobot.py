"""OpenDM DM0.5 LoRA training entry point for local LeRobot Dataset v3 data.

The model, transforms, collator and trainer come from the pinned OpenDM
checkout. This module only supplies a local LeRobot v3 loader and the verified
DishwasherUnloadCutleryLong defaults used by ``scripts/train_cutlery_amd.sh``.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Literal

import tyro
from loguru import logger
from torch.utils.data import DataLoader
from tqdm import tqdm

# Make the repository-local LeRobot loader importable from this entry point.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from lerobot_dataset import LerobotDataset  # noqa: E402

import opendm.data.normalize as normalize  # noqa: E402
from opendm.constants.robot import ActionMode, RobotStateDesc  # noqa: E402
from opendm.data.augmentations import NoAugmentationPipeline  # noqa: E402
from opendm.data.collator import NormStatsCollator, TrainingCollator  # noqa: E402
from opendm.data.transforms import (  # noqa: E402
    ChatTokenization,
    Normalize,
    PadAction,
    Pipeline,
    PixelTransform,
)
from opendm.exp.dm05_exp import (  # noqa: E402
    DM05DataConfig as _DM05DataConfig,
)
from opendm.exp.dm05_exp import (  # noqa: E402
    DM05Exp as _DM05Exp,
)
from opendm.exp.dm05_exp import (  # noqa: E402
    DM05InferenceConfig as _DM05InferenceConfig,
)
from opendm.exp.dm05_exp import (  # noqa: E402
    DM05ModelConfig as _DM05ModelConfig,
)
from opendm.exp.dm05_exp import (  # noqa: E402
    DM05OptimizerConfig as _DM05OptimizerConfig,
)
from opendm.exp.dm05_exp import (  # noqa: E402
    DM05TrainerConfig as _DM05TrainerConfig,
)


def _default_state_desc(action_dim: int) -> list:
    """Match OpenDM BiGym semantics: two grippers after the joint dimensions.

    Absolute-action training does not consume ``state_desc``, but storing it in
    metadata keeps the loader compatible with relative-action transforms.
    """
    n_gripper = 2
    n_joint = max(0, action_dim - n_gripper)
    return [RobotStateDesc.JOINT] * n_joint + [RobotStateDesc.GRIPPER] * n_gripper


@dataclass
class DM05DataConfig(_DM05DataConfig):
    lerobot_path: str = field(
        default="/path/to/lerobot-dataset"
    )
    dataset_name: str = field(default="bigym_plus_put_cups")
    image_keys: list[str] = field(
        default_factory=lambda: ["images_1", "images_2", "images_3"]
    )
    action_dim: int = field(default=16)
    action_mode: ActionMode = field(default=ActionMode.ABSOLUTE)
    add_state: bool = field(default=True)

    def build_dataset(
        self,
        processor,
        action_horizon: int,
        tokenizer_max_length: int = 1024,
    ) -> tuple:
        image_keys = self.image_keys
        pipeline = Pipeline(
            [
                self._action_transform(action_horizon),
                # LeRobot already returns PIL images; no URL loader is needed.
                PixelTransform(
                    transform_pipeline=NoAugmentationPipeline(),
                    image_keys=image_keys,
                ),
                Normalize(
                    norm_stats_path=str(self.norm_stats_path(action_horizon)),
                    norm_keys=["state", "action"],
                    use_quantiles=True,
                ),
                ChatTokenization(
                    processor=processor,
                    n_bins=self.n_bins,
                    max_length=tokenizer_max_length,
                    image_keys=image_keys,
                    add_state=self.add_state,
                ),
                PadAction(32),
            ]
        )
        dataset = LerobotDataset(
            lerobot_path=self.lerobot_path,
            image_keys=image_keys,
            state_desc=_default_state_desc(self.action_dim),
            transforms=pipeline,
            dataset_name=self.dataset_name,
            decode_video=True,
        )
        collator = TrainingCollator(
            pad_token_id=processor.tokenizer.pad_token_id,
            max_length=tokenizer_max_length,
        )
        return dataset, collator

    def compute_norm_stats(
        self,
        action_horizon: int,
        batch_size: int = 128,
        num_workers: int = 32,
    ) -> None:
        """Compute normalization statistics without decoding video frames.

        This mirrors OpenDM's base implementation while replacing JsonlDataset
        with the local LeRobot loader. The statistics path reads state and action
        columns from Parquet only.
        """
        norm_keys = ["state", "action"]
        dataset = LerobotDataset(
            lerobot_path=self.lerobot_path,
            image_keys=self.image_keys,
            state_desc=_default_state_desc(self.action_dim),
            transforms=Pipeline([self._action_transform(action_horizon)]),
            dataset_name=self.dataset_name,
            decode_video=False,
        )
        dataloader = DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=True,
            num_workers=num_workers,
            collate_fn=NormStatsCollator(),
            persistent_workers=True,
            prefetch_factor=4,
        )
        stats = {key: normalize.RunningStats() for key in norm_keys}
        max_batches = self.compute_norm_stats_max_batches or len(dataloader)
        total = min(len(dataloader), max_batches)
        for batch_idx, batch in tqdm(
            enumerate(dataloader),
            total=total,
            desc=f"Computing norm stats [{self.dataset_name}]",
        ):
            if batch_idx >= max_batches:
                break
            for key in norm_keys:
                values = batch[key]
                stats[key].update(values.reshape(-1, values.shape[-1]))

        norm_stats = {}
        for key, stat in stats.items():
            stat = stat.get_statistics()
            norm_stats[key] = {
                name: getattr(stat, name).tolist()
                for name in ("mean", "std", "q01", "q99")
            }

        output_path = self.norm_stats_path(action_horizon)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"norm_stats": norm_stats}, indent=2))
        logger.info(f"Saved norm stats for {self.dataset_name} to {output_path}")


@dataclass
class DM05ModelConfig(_DM05ModelConfig):
    model_name_or_path: str | None = field(
        default="Dexmal/DM05"
    )
    chunk_size: int = field(default=16)
    llm_attn_implementation: Literal["auto", "eager", "sdpa", "flex_attention"] = field(
        default="eager"
    )
    vision_attn_implementation: Literal[
        "auto", "eager", "sdpa", "flash_attention_2"
    ] = field(default="sdpa")
    action_attn_implementation: Literal["auto", "eager", "sdpa", "flex_attention"] = (
        field(default="sdpa")
    )
    vlm_gradient_checkpointing: bool = field(default=True)
    ae_gradient_checkpointing: bool = field(default=True)


@dataclass
class DM05OptimizerConfig(_DM05OptimizerConfig):
    base_lr: float = field(default=5e-4)
    warmup_steps: int = field(default=500)


@dataclass
class DM05TrainerConfig(_DM05TrainerConfig):
    fsdp1: bool | None = field(default=False)
    per_device_train_batch_size: int = field(default=4)
    gradient_accumulation_steps: int = field(default=6)
    save_steps: int = field(default=1000)
    num_train_steps: int = field(default=2000)
    save_only_model: bool = field(default=False)
    output_dir: str = field(default="user_checkpoints/dm05_lerobot_bigym_plus")


@dataclass
class DM05InferenceConfig(_DM05InferenceConfig):
    output_action_dim: int = field(default=16)
    image_keys: list[str] = field(
        default_factory=lambda: ["images_1", "images_2", "images_3"]
    )


@dataclass
class DM05Exp(_DM05Exp):
    use_lora: bool | None = field(default=True)
    model_config: DM05ModelConfig = field(default_factory=DM05ModelConfig)
    optimizer_config: DM05OptimizerConfig = field(default_factory=DM05OptimizerConfig)
    trainer_config: DM05TrainerConfig = field(default_factory=DM05TrainerConfig)
    data_config: DM05DataConfig = field(default_factory=DM05DataConfig)
    inference_config: DM05InferenceConfig = field(default_factory=DM05InferenceConfig)


if __name__ == "__main__":
    exp = tyro.cli(DM05Exp)
    if exp.task == "train":
        exp.train()
    elif exp.task == "inference":
        exp.inference()
    else:
        raise ValueError(f"Invalid task: {exp.task}")
