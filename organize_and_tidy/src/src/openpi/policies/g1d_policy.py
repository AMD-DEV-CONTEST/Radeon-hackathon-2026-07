"""G1-D 机器人 policy。

为 Unitree G1-D（Dex1 灵巧手，16 维关节空间）定义观测输入/动作输出转换。
"""
from typing import ClassVar

import cv2
import einops
import numpy as np

import openpi.transforms as _transforms


def _parse_image(image) -> np.ndarray:
    """将 LeRobot v2.1 格式图像转为 uint8 HWC numpy 数组。

    LeRobot 视频数据集返回 float32 (C,H,W) 格式，需要转 uint8 (H,W,C)。
    推理 Client 可通过 JPEG bytes 传输图像以减小公网带宽占用。
    """
    if isinstance(image, (bytes, bytearray, memoryview)):
        buffer = np.frombuffer(image, dtype=np.uint8)
        bgr = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Failed to decode JPEG image bytes from client")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    image = np.asarray(image)
    if np.issubdtype(image.dtype, np.floating):
        image = (255 * image).astype(np.uint8)
    if image.shape[0] == 3:
        image = einops.rearrange(image, "c h w -> h w c")
    return image


class G1DJointInputs(_transforms.DataTransformFn):
    """G1-D 输入转换：4 路摄像头 → 模型期望的 3 路键名映射。

    - cam_left_high   → base_0_rgb       （左全局视角作为模型主视图）
    - cam_left_wrist  → left_wrist_0_rgb
    - cam_right_wrist → right_wrist_0_rgb
    - cam_right_high  → 忽略（与 Aloha 丢弃 cam_low 一致）
    """

    MODEL_CAMERA_KEYS: ClassVar[tuple[str, ...]] = (
        "base_0_rgb",
        "left_wrist_0_rgb",
        "right_wrist_0_rgb",
    )

    CAMERA_MAPPING: ClassVar[dict[str, str]] = {
        "base_0_rgb": "cam_left_high",
        "left_wrist_0_rgb": "cam_left_wrist",
        "right_wrist_0_rgb": "cam_right_wrist",
    }

    def __call__(self, data: dict) -> dict:
        in_images = data["images"]

        # 转换图像格式: LeRobot float32 (C,H,W) → uint8 (H,W,C)
        in_images = {k: _parse_image(v) for k, v in in_images.items()}

        # 获取基础图像用于填充缺失摄像头
        first_source = next(iter(self.CAMERA_MAPPING.values()))
        base_image = in_images.get(first_source, next(iter(in_images.values())))

        images = {}
        image_masks = {}
        for model_key in self.MODEL_CAMERA_KEYS:
            source_key = self.CAMERA_MAPPING.get(model_key)
            if source_key and source_key in in_images:
                images[model_key] = in_images[source_key]
                image_masks[model_key] = np.True_
            else:
                images[model_key] = np.zeros_like(base_image)
                image_masks[model_key] = np.False_

        inputs = {
            "image": images,
            "image_mask": image_masks,
            "state": data["state"],
        }

        if "actions" in data:
            inputs["actions"] = data["actions"]

        if "prompt" in data:
            inputs["prompt"] = data["prompt"]

        return inputs


class G1DJointOutputs(_transforms.DataTransformFn):
    """G1-D 输出转换：裁剪零填充维度，恢复 16 维关节动作。

    模型输出 32 维（含零填充），裁剪到前 16 维有效关节角度。
    与 LiberoOutputs / DroidOutputs 裁剪填充维度的模式一致。
    """

    def __call__(self, data: dict) -> dict:
        return {"actions": np.asarray(data["actions"][..., :16])}
