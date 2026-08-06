"""
独立游戏资产工作室自定义节点（P3）
- W3: PBRFromDepth   深度图 → normal / height / roughness / metalness
- W4: MusicGenNode   文本 → 背景音乐（transformers MusicGen）
- W5: ProceduralSFX  类型 → 环境音效（程序化合成）
"""
import os
from pathlib import Path

import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MUSICGEN_DIR = Path(
    os.environ.get("MUSICGEN_MODEL_DIR", PROJECT_ROOT / "ComfyUI" / "models" / "musicgen" / "musicgen-small")
)

SR = 44100


# ---------------------------------------------------------------- W3
class PBRFromDepth:
    """由灰度深度图生成 PBR 贴图组：法线 / 高度 / 粗糙度 / 金属度"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "depth_image": ("IMAGE",),
                "strength": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 10.0, "step": 0.1}),
                "roughness_scale": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 4.0, "step": 0.1}),
                "metalness": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("normal", "height", "roughness", "metalness")
    FUNCTION = "run"
    CATEGORY = "indie-studio"

    @staticmethod
    def _to_img(arr: np.ndarray) -> torch.Tensor:
        if arr.ndim == 2:
            arr = np.repeat(arr[..., None], 3, axis=-1)
        return torch.from_numpy(arr.astype(np.float32)).unsqueeze(0).clamp(0.0, 1.0)

    def run(self, depth_image, strength, roughness_scale, metalness):
        depth = depth_image[0, :, :, 0].float().cpu().numpy()
        gy, gx = np.gradient(depth, edge_order=1)
        gx, gy = gx * strength, gy * strength
        normal = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
        normal = normal / np.maximum(np.linalg.norm(normal, axis=-1, keepdims=True), 1e-6)
        normal = (normal * 0.5 + 0.5).clip(0, 1)
        height = depth
        edge = np.sqrt(gx ** 2 + gy ** 2)
        roughness = (edge / max(float(edge.max()), 1e-6) * roughness_scale).clip(0, 1)
        metal = np.full_like(depth, metalness)
        return (
            self._to_img(normal),
            self._to_img(height),
            self._to_img(roughness),
            self._to_img(metal),
        )


# ---------------------------------------------------------------- W4
class MusicGenNode:
    """文本提示 → 背景音乐（transformers MusicGen small）"""

    _model = None
    _processor = None

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "dark ambient electronic music, industrial, heavy metal clanking percussion, ominous, slow tempo, underground bar atmosphere",
                    },
                ),
                "duration": ("FLOAT", {"default": 8.0, "min": 2.0, "max": 30.0, "step": 0.5}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2 ** 31 - 1}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "run"
    CATEGORY = "indie-studio"

    @classmethod
    def _load(cls):
        if cls._model is None:
            from transformers import AutoProcessor, MusicgenForConditionalGeneration

            if not (MUSICGEN_DIR / "pytorch_model.bin").exists():
                raise FileNotFoundError(
                    f"MusicGen 模型未找到: {MUSICGEN_DIR}\n"
                    "请执行: bash scripts/download_musicgen.sh（或从 hf-mirror 下载 facebook/musicgen-small）"
                )
            cls._processor = AutoProcessor.from_pretrained(str(MUSICGEN_DIR))
            cls._model = MusicgenForConditionalGeneration.from_pretrained(str(MUSICGEN_DIR))
            device = "cuda" if torch.cuda.is_available() else "cpu"
            cls._model.to(device)
            cls._model.eval()
        return cls._processor, cls._model

    def run(self, prompt, duration, seed):
        processor, model = self._load()
        inputs = processor(text=[prompt], padding=True, return_tensors="pt")
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        max_new_tokens = max(64, int(duration * 50))  # MusicGen v1 帧率约 50 tokens/s
        torch.manual_seed(seed)
        with torch.no_grad():
            audio = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=1.0)
        waveform = audio.cpu()  # (batch, channels, samples)
        sample_rate = int(model.config.audio_encoder.sampling_rate)
        return ({"waveform": waveform, "sample_rate": sample_rate},)


# ---------------------------------------------------------------- W5
class ProceduralSFX:
    """程序化环境音效：玻璃杯碰撞 / 含糊交谈 / 酒吧环境底噪"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "kind": (["glass_clink", "murmur", "ambient_bar"], {"default": "glass_clink"}),
                "duration": ("FLOAT", {"default": 4.0, "min": 0.5, "max": 60.0, "step": 0.5}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2 ** 31 - 1}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "run"
    CATEGORY = "indie-studio"

    @staticmethod
    def _lowpass(x: np.ndarray, cutoff: float, sr: int = SR) -> np.ndarray:
        from scipy.signal import butter, lfilter

        b, a = butter(2, cutoff / (sr / 2), btype="low")
        return lfilter(b, a, x)

    @staticmethod
    def _bandpass(x: np.ndarray, lo: float, hi: float, sr: int = SR) -> np.ndarray:
        from scipy.signal import butter, lfilter

        b, a = butter(2, [lo / (sr / 2), hi / (sr / 2)], btype="band")
        return lfilter(b, a, x)

    def _glass_clink(self, rng: np.random.Generator, duration: float) -> np.ndarray:
        n = int(duration * SR)
        t = np.arange(n) / SR
        out = np.zeros(n)
        for _ in range(int(rng.integers(3, 9))):
            start = float(rng.uniform(0.0, max(duration - 1.0, 0.1)))
            length = int(rng.uniform(0.25, 0.9) * SR)
            i0, i1 = int(start * SR), min(int(start * SR) + length, n)
            seg = t[i0:i1] - start
            freqs = rng.uniform(2200, 8200, size=10)
            wave = sum(np.sin(2 * np.pi * f * seg + rng.uniform(0, 6.28)) for f in freqs) / 10
            env = np.exp(-seg * rng.uniform(12, 38))
            out[i0:i1] += float(rng.uniform(0.25, 1.0)) * wave * env
        return np.tanh(out * 1.4)

    def _murmur(self, rng: np.random.Generator, duration: float) -> np.ndarray:
        n = int(duration * SR)
        t = np.arange(n) / SR
        noise = self._bandpass(rng.standard_normal(n), 220, 1400)
        # 拟音节包络
        syllable = np.zeros(n)
        pos = 0
        while pos < n:
            on = int(rng.uniform(0.08, 0.35) * SR)
            off = int(rng.uniform(0.05, 0.3) * SR)
            seg = np.minimum(np.arange(on) / max(on, 1), 1.0)
            syllable[pos:min(pos + on, n)] += seg[: max(n - pos, 0)]
            pos += on + off
        out = noise * syllable
        out = self._lowpass(out, 900)
        return np.tanh(out * 1.2)

    def _ambient_bar(self, rng: np.random.Generator, duration: float) -> np.ndarray:
        n = int(duration * SR)
        rumble = self._lowpass(rng.standard_normal(n) * 0.7, 120)
        murmur = self._murmur(rng, duration) * 0.25
        clinks = self._glass_clink(rng, duration) * 0.5
        return np.tanh(rumble + murmur + clinks)

    def run(self, kind, duration, seed):
        rng = np.random.default_rng(seed)
        if kind == "glass_clink":
            mono = self._glass_clink(rng, duration)
        elif kind == "murmur":
            mono = self._murmur(rng, duration)
        else:
            mono = self._ambient_bar(rng, duration)
        waveform = torch.from_numpy(mono[None, None, :]).float()
        return ({"waveform": waveform, "sample_rate": SR},)


NODE_CLASS_MAPPINGS = {
    "PBRFromDepth": PBRFromDepth,
    "MusicGenNode": MusicGenNode,
    "ProceduralSFX": ProceduralSFX,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PBRFromDepth": "PBR From Depth (IndieStudio)",
    "MusicGenNode": "MusicGen (IndieStudio)",
    "ProceduralSFX": "Procedural SFX (IndieStudio)",
}


# ---------------------------------------------------------------- W6
class ActionPose:
    """按动作指令生成 OpenPose 风格骨架帧序列（跑步/攻击）"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (["run", "attack"], {"default": "run"}),
                "frames": ("INT", {"default": 8, "min": 4, "max": 16, "step": 1}),
                "width": ("INT", {"default": 512, "min": 256, "max": 1024, "step": 64}),
                "height": ("INT", {"default": 512, "min": 256, "max": 1024, "step": 64}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("poses",)
    FUNCTION = "run"
    CATEGORY = "indie-studio"

    # OpenPose 18 点：0鼻 1颈 2右肩 3右肘 4右腕 5左肩 6左肘 7左腕
    #              8右髋 9右膝 10右踝 11左髋 12左膝 13左踝 14右眼 15左眼 16右耳 17左耳
    LIMBS = [(0, 1), (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
             (1, 8), (1, 11), (8, 9), (9, 10), (11, 12), (12, 13),
             (8, 11), (0, 14), (0, 15), (14, 16), (15, 17)]

    def _run_keypoints(self, i, frames, w, h):
        import math

        ph = 2 * math.pi * i / frames
        cx, hip_y = 0.55 * w, 0.62 * h
        sh_x = cx - 0.05 * w
        sh_y = 0.40 * h
        neck = (sh_x - 0.005 * w, sh_y - 0.012 * h)
        nose = (sh_x - 0.01 * w, 0.285 * h)
        sh_r = (sh_x + 0.02 * w, sh_y + 0.015 * h)
        sh_l = (sh_x - 0.02 * w, sh_y + 0.015 * h)
        hip_r = (cx + 0.02 * w, hip_y)
        hip_l = (cx - 0.02 * w, hip_y)
        eye_r = (nose[0] + 0.015 * w, nose[1] - 0.012 * h)
        eye_l = (nose[0] - 0.015 * w, nose[1] - 0.012 * h)
        ear_r = (eye_r[0] + 0.012 * w, eye_r[1] + 0.004 * h)
        ear_l = (eye_l[0] - 0.012 * w, eye_l[1] + 0.004 * h)

        def leg(hx, phase):
            foot = (hx + 0.20 * w * math.sin(phase), hip_y + 0.30 * h - 0.07 * h * math.cos(phase))
            knee = (hx + 0.10 * w * math.sin(phase + 1.0), hip_y + 0.15 * h + 0.03 * h * math.cos(phase))
            return knee, foot

        def arm(sx, sy, phase):
            elb = (sx + 0.09 * w * math.sin(phase + 0.8), sy + 0.10 * h + 0.02 * h * math.cos(phase))
            wri = (sx + 0.13 * w * math.sin(phase), elb[1] + 0.06 * h)
            return elb, wri

        knee_r, foot_r = leg(hip_r[0], ph)
        knee_l, foot_l = leg(hip_l[0], ph + math.pi)
        elb_r, wri_r = arm(sh_r[0], sh_r[1], ph)
        elb_l, wri_l = arm(sh_l[0], sh_l[1], ph + math.pi)
        return [nose, neck, sh_r, elb_r, wri_r, sh_l, elb_l, wri_l,
                hip_r, knee_r, foot_r, hip_l, knee_l, foot_l,
                eye_r, eye_l, ear_r, ear_l]

    def _attack_keypoints(self, i, frames, w, h):
        import math

        t = i / max(frames - 1, 1)
        cx = 0.45 * w + 0.28 * w * t
        hip_y = 0.64 * h - 0.04 * h * math.sin(math.pi * t)
        neck = (cx + 0.01 * w, hip_y - 0.25 * h)
        nose = (neck[0] + 0.015 * w, neck[1] - 0.105 * h)
        sh_r = (cx + 0.025 * w, hip_y - 0.225 * h)
        sh_l = (cx - 0.015 * w, hip_y - 0.22 * h)
        hip_r = (cx + 0.02 * w, hip_y)
        hip_l = (cx - 0.02 * w, hip_y)
        eye_r = (nose[0] + 0.015 * w, nose[1] - 0.012 * h)
        eye_l = (nose[0] - 0.015 * w, nose[1] - 0.012 * h)
        ear_r = (eye_r[0] + 0.012 * w, eye_r[1] + 0.004 * h)
        ear_l = (eye_l[0] - 0.012 * w, eye_l[1] + 0.004 * h)
        # 前腿（右）弓步
        knee_r = (cx + 0.12 * w + 0.05 * w * t, hip_y + 0.13 * h)
        foot_r = (cx + 0.18 * w + 0.07 * w * t, hip_y + 0.30 * h)
        # 后腿（左）蹬直
        knee_l = (cx - 0.10 * w, hip_y + 0.14 * h)
        foot_l = (cx - 0.20 * w, hip_y + 0.30 * h)
        # 挥剑臂（右）：向前上方劈出后回落
        sweep = math.sin(math.pi * t)
        wri_r = (neck[0] + 0.10 * w + 0.32 * w * t, 0.42 * h + 0.16 * h * sweep)
        elb_r = ((sh_r[0] + wri_r[0]) / 2, (sh_r[1] + wri_r[1]) / 2 + 0.02 * h)
        # 后收臂（左）
        elb_l = (sh_l[0] - 0.08 * w, sh_l[1] + 0.10 * h)
        wri_l = (sh_l[0] - 0.16 * w, sh_l[1] + 0.14 * h)
        return [nose, neck, sh_r, elb_r, wri_r, sh_l, elb_l, wri_l,
                hip_r, knee_r, foot_r, hip_l, knee_l, foot_l,
                eye_r, eye_l, ear_r, ear_l]

    def _draw(self, kps, w, h):
        import cv2

        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        line_w = max(3, w // 96)
        dot_r = max(3, w // 128)
        for a, b in self.LIMBS:
            p1 = (int(kps[a][0]), int(kps[a][1]))
            p2 = (int(kps[b][0]), int(kps[b][1]))
            cv2.line(canvas, p1, p2, (200, 200, 200), line_w)
        right = {2, 3, 4, 8, 9, 10}
        for j, (x, y) in enumerate(kps):
            color = (60, 60, 255) if j in right else (255, 120, 60) if j in {5, 6, 7, 11, 12, 13} else (210, 210, 210)
            cv2.circle(canvas, (int(x), int(y)), dot_r, color, -1)
        return canvas.astype(np.float32) / 255.0

    def run(self, action, frames, width, height):
        poses = []
        for i in range(frames):
            kps = self._run_keypoints(i, frames, width, height) if action == "run" else self._attack_keypoints(i, frames, width, height)
            poses.append(self._draw(kps, width, height))
        batch = np.stack(poses)
        return (torch.from_numpy(batch).float(),)


NODE_CLASS_MAPPINGS["ActionPose"] = ActionPose
NODE_DISPLAY_NAME_MAPPINGS["ActionPose"] = "Action Pose (IndieStudio)"


# ---------------------------------------------------------------- W7
class SaveMeshGLB:
    """把 TripoSR 等节点输出的 MESH 保存为 GLB/OBJ（W7：2D 角色图 → 3D 模型）"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mesh": ("MESH",),
                "filename_prefix": ("STRING", {"default": "W7_model"}),
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = "indie-studio"

    def save(self, mesh, filename_prefix):
        from folder_paths import get_save_image_path, get_output_directory

        full_folder, filename, counter, subfolder, _ = get_save_image_path(
            filename_prefix, get_output_directory()
        )
        full_folder = Path(full_folder)
        saved = []
        for batch_number, single_mesh in enumerate(mesh):
            # 与 Flowty 预览一致：TripoSR 坐标系 → 直立 Y-up
            single_mesh.apply_transform(np.array(
                [[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]]
            ))
            base = filename.replace("%batch_num%", str(batch_number))
            base = f"{base}_{counter:05}_"
            single_mesh.export(str(full_folder / f"{base}model.glb"))
            single_mesh.export(str(full_folder / f"{base}model.obj"))
            for f in sorted(full_folder.glob(f"{base}*")):
                saved.append({"filename": f.name, "type": "output", "subfolder": subfolder})
        return {"ui": {"mesh": saved}}


NODE_CLASS_MAPPINGS["SaveMeshGLB"] = SaveMeshGLB
NODE_DISPLAY_NAME_MAPPINGS["SaveMeshGLB"] = "Save Mesh GLB (IndieStudio)"
