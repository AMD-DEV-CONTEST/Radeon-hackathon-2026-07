import json
import math
import os
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import (
    RTDetrImageProcessor,
    RTDetrV2ForObjectDetection,
)


def required_env(primary, legacy):
    value = os.environ.get(primary) or os.environ.get(legacy)
    if not value:
        raise RuntimeError(
            f"Set {primary} (preferred) or legacy {legacy} before training"
        )
    return value


data_root = Path(required_env("VISION_DATA_ROOT", "SH17_DERIVED"))
base_root = Path(required_env("VISION_BASE_MODEL_ROOT", "RTDETR_BASE_ROOT"))
train_root = Path(required_env("VISION_TRAIN_ROOT", "PPE_TRAIN_ROOT"))
report_path = Path(required_env("VISION_TRAIN_REPORT", "PPE_TRAIN_REPORT"))

epochs = int(required_env("VISION_EPOCHS", "PPE_EPOCHS"))
batch_size = int(required_env("VISION_BATCH_SIZE", "PPE_BATCH_SIZE"))
learning_rate = float(required_env("VISION_LEARNING_RATE", "PPE_LEARNING_RATE"))
backbone_lr = float(
    required_env("VISION_BACKBONE_LEARNING_RATE", "PPE_BACKBONE_LEARNING_RATE")
)
weight_decay = float(required_env("VISION_WEIGHT_DECAY", "PPE_WEIGHT_DECAY"))
seed = int(required_env("VISION_SEED", "PPE_SEED"))

checkpoint_root = train_root / "checkpoint-last"
best_root = train_root / "best-model"
history_path = train_root / "training-history.json"
state_path = checkpoint_root / "training-state.pt"

train_root.mkdir(parents=True, exist_ok=True)

random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed_all(seed)

torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True

train_annotations_path = data_root / "annotations" / "instances_train.json"
train_annotations = json.loads(train_annotations_path.read_text(encoding="utf-8"))
source_categories = {
    int(item["id"]): str(item["name"])
    for item in train_annotations.get("categories", [])
}
configured_mapping = os.environ.get("VISION_CLASS_MAPPING_JSON")
if configured_mapping:
    source_categories = {
        int(key): str(value)
        for key, value in json.loads(configured_mapping).items()
    }
if not source_categories:
    raise RuntimeError("COCO training annotations must define at least one category")
annotation_category_ids = {
    int(item["category_id"])
    for item in train_annotations.get("annotations", [])
}
unknown_category_ids = annotation_category_ids - set(source_categories)
if unknown_category_ids:
    raise RuntimeError(
        f"Training annotations use unmapped category IDs: {sorted(unknown_category_ids)}"
    )
source_to_model = {
    source_id: model_id
    for model_id, source_id in enumerate(sorted(source_categories))
}
id2label = {
    source_to_model[source_id]: source_categories[source_id]
    for source_id in sorted(source_categories)
}
label2id = {
    name: identifier
    for identifier, name in id2label.items()
}

processor = RTDetrImageProcessor.from_pretrained(
    base_root,
    local_files_only=True,
)


class CocoDataset(Dataset):
    def __init__(self, split):
        self.split = split
        aliases = ("validation", "val") if split == "validation" else (split,)
        self.disk_split = next(
            (
                alias
                for alias in aliases
                if (data_root / "annotations" / f"instances_{alias}.json").is_file()
                and (data_root / "images" / alias).is_dir()
            ),
            None,
        )
        if self.disk_split is None:
            raise FileNotFoundError(
                f"Missing COCO images/annotations for split {split}: {data_root}"
            )

        path = (
            data_root
            / "annotations"
            / f"instances_{self.disk_split}.json"
        )

        payload = json.loads(
            path.read_text(encoding="utf-8")
        )

        self.images = payload["images"]
        self.by_image = defaultdict(list)

        for annotation in payload["annotations"]:
            source_category_id = int(annotation["category_id"])
            if source_category_id not in source_to_model:
                raise RuntimeError(
                    f"{split} annotation uses unmapped category {source_category_id}"
                )
            self.by_image[int(annotation["image_id"])].append(
                {
                    **annotation,
                    "category_id": source_to_model[source_category_id],
                }
            )

    def __len__(self):
        return len(self.images)

    def __getitem__(self, index):
        record = self.images[index]

        image_path = (
            data_root
            / "images"
            / self.disk_split
            / record["file_name"]
        )

        with Image.open(image_path) as source:
            image = source.convert("RGB")

        encoded = processor(
            images=image,
            annotations={
                "image_id": int(record["id"]),
                "annotations": self.by_image[
                    int(record["id"])
                ],
            },
            return_tensors="pt",
        )

        return {
            "pixel_values": encoded[
                "pixel_values"
            ][0],
            "pixel_mask": (
                encoded["pixel_mask"][0]
                if "pixel_mask" in encoded
                else None
            ),
            "labels": encoded["labels"][0],
        }


def collate(items):
    batch = {
        "pixel_values": torch.stack([
            item["pixel_values"]
            for item in items
        ]),
        "labels": [
            item["labels"]
            for item in items
        ],
    }

    masks = [item["pixel_mask"] for item in items]

    if all(mask is not None for mask in masks):
        batch["pixel_mask"] = torch.stack(masks)

    return batch


def move_labels(labels, device):
    return [
        {
            key: (
                value.to(device)
                if isinstance(value, torch.Tensor)
                else value
            )
            for key, value in item.items()
        }
        for item in labels
    ]


def run_batch(model, batch, device):
    pixel_values = batch["pixel_values"].to(device)
    pixel_mask = batch.get("pixel_mask")

    if pixel_mask is not None:
        pixel_mask = pixel_mask.to(device)

    return model(
        pixel_values=pixel_values,
        pixel_mask=pixel_mask,
        labels=move_labels(
            batch["labels"],
            device,
        ),
    )


train_dataset = CocoDataset("train")
validation_dataset = CocoDataset("validation")

device = torch.device("cuda")
start_epoch = 1
history = []

if state_path.is_file():
    model = RTDetrV2ForObjectDetection.from_pretrained(
        checkpoint_root,
        local_files_only=True,
    )
else:
    model = RTDetrV2ForObjectDetection.from_pretrained(
        base_root,
        local_files_only=True,
        num_labels=len(id2label),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    )

model.to(device)

backbone_parameters = []
other_parameters = []

for name, parameter in model.named_parameters():
    if not parameter.requires_grad:
        continue

    if "backbone" in name:
        backbone_parameters.append(parameter)
    else:
        other_parameters.append(parameter)

optimizer = torch.optim.AdamW(
    [
        {
            "params": backbone_parameters,
            "lr": backbone_lr,
        },
        {
            "params": other_parameters,
            "lr": learning_rate,
        },
    ],
    weight_decay=weight_decay,
)

steps_per_epoch = math.ceil(
    len(train_dataset) / batch_size
)
total_steps = steps_per_epoch * epochs

scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
    optimizer,
    T_max=max(1, total_steps),
)

best_validation_loss = float("inf")
global_step = 0

if state_path.is_file():
    state = torch.load(
        state_path,
        map_location="cpu",
        weights_only=False,
    )

    optimizer.load_state_dict(state["optimizer"])
    scheduler.load_state_dict(state["scheduler"])

    start_epoch = int(state["epoch"]) + 1
    global_step = int(state["global_step"])
    best_validation_loss = float(
        state["best_validation_loss"]
    )
    history = state.get("history", [])

    print(
        f"RESUME epoch={start_epoch} "
        f"global_step={global_step}",
        flush=True,
    )

torch.cuda.reset_peak_memory_stats()
training_started = time.perf_counter()

for epoch in range(start_epoch, epochs + 1):
    epoch_started = time.perf_counter()

    generator = torch.Generator()
    generator.manual_seed(seed + epoch)

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=generator,
        num_workers=0,
        collate_fn=collate,
        pin_memory=False,
    )

    validation_loader = DataLoader(
        validation_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
        collate_fn=collate,
        pin_memory=False,
    )

    model.train()
    train_losses = []

    for step, batch in enumerate(train_loader, 1):
        optimizer.zero_grad(set_to_none=True)

        output = run_batch(model, batch, device)
        loss = output.loss

        if not torch.isfinite(loss):
            raise RuntimeError(
                f"Non-finite loss epoch={epoch} "
                f"step={step}: {loss.item()}"
            )

        loss.backward()

        torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            max_norm=1.0,
        )

        optimizer.step()
        scheduler.step()

        global_step += 1
        loss_value = float(loss.detach().cpu())
        train_losses.append(loss_value)

        if step == 1 or step % 50 == 0:
            print(
                f"epoch={epoch}/{epochs} "
                f"train={step}/{len(train_loader)} "
                f"loss={loss_value:.6f} "
                f"lr={scheduler.get_last_lr()[-1]:.8f}",
                flush=True,
            )

    model.eval()
    validation_losses = []

    with torch.no_grad():
        for step, batch in enumerate(
            validation_loader,
            1,
        ):
            output = run_batch(model, batch, device)
            loss = output.loss

            if not torch.isfinite(loss):
                raise RuntimeError(
                    f"Non-finite validation loss "
                    f"epoch={epoch} step={step}"
                )

            validation_losses.append(
                float(loss.detach().cpu())
            )

            if step % 50 == 0:
                print(
                    f"epoch={epoch}/{epochs} "
                    f"validation="
                    f"{step}/{len(validation_loader)}",
                    flush=True,
                )

    mean_train_loss = (
        sum(train_losses) / len(train_losses)
    )
    mean_validation_loss = (
        sum(validation_losses)
        / len(validation_losses)
    )

    epoch_record = {
        "epoch": epoch,
        "train_loss": mean_train_loss,
        "validation_loss": mean_validation_loss,
        "train_steps": len(train_losses),
        "validation_steps": len(validation_losses),
        "duration_seconds": (
            time.perf_counter() - epoch_started
        ),
        "global_step": global_step,
    }

    history.append(epoch_record)

    checkpoint_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    model.save_pretrained(
        checkpoint_root,
        safe_serialization=True,
    )
    processor.save_pretrained(checkpoint_root)

    is_best = (
        mean_validation_loss
        < best_validation_loss
    )

    if is_best:
        best_validation_loss = mean_validation_loss

        best_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        model.save_pretrained(
            best_root,
            safe_serialization=True,
        )
        processor.save_pretrained(best_root)

    history_path.write_text(
        json.dumps(history, indent=2) + "\n",
        encoding="utf-8",
    )

    torch.save(
        {
            "epoch": epoch,
            "global_step": global_step,
            "best_validation_loss": (
                best_validation_loss
            ),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "history": history,
        },
        state_path,
    )

    print(
        f"EPOCH COMPLETE epoch={epoch} "
        f"train_loss={mean_train_loss:.6f} "
        f"validation_loss="
        f"{mean_validation_loss:.6f} "
        f"best={is_best}",
        flush=True,
    )

report = {
    "status": "PASS",
    "epochs": epochs,
    "completed_epochs": len(history),
    "global_step": global_step,
    "batch_size": batch_size,
    "dataset_root": str(data_root),
    "base_model_root": str(base_root),
    "id2label": id2label,
    "source_category_mapping": source_categories,
    "best_validation_loss": best_validation_loss,
    "duration_seconds": (
        time.perf_counter() - training_started
    ),
    "peak_gpu_memory_bytes": (
        torch.cuda.max_memory_allocated()
    ),
    "checkpoint": str(checkpoint_root),
    "best_model": str(best_root),
    "history": history,
}

report_path.write_text(
    json.dumps(report, indent=2) + "\n",
    encoding="utf-8",
)

print(json.dumps(report, indent=2), flush=True)
print("RT-DETR FULL TRAINING PASS", flush=True)
