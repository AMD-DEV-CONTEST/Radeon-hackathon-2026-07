# -*- coding: utf-8 -*-
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# === Appendix D: HfFolder monkey-patch (keep BEFORE gradio import) ===
# huggingface_hub >= 0.26 removed HfFolder, but gradio 4.14-4.44.x still
# does `from huggingface_hub import HfFolder, whoami` inside gradio/oauth.py.
# Stub it out to unblock `import gradio` on hf_hub 0.34+ (required by
# diffusers >= 0.39 / transformers >= 4.57).   [2026-07-30]
import types as _types
try:
    import huggingface_hub as _hf_hub
    _hf_hub.HfFolder  # probe
except Exception:
    _stub = _types.ModuleType("HfFolder_stub")
    _stub.get_token = staticmethod(lambda *a, **kw: None)
    _stub.save_token = staticmethod(lambda *a, **kw: None)
    _stub.delete_token = staticmethod(lambda *a, **kw: None)
    try:
        import huggingface_hub as _hf_hub  # noqa: F811
        _hf_hub.HfFolder = _stub
        sys.modules["huggingface_hub"].HfFolder = _stub
    except Exception:
        pass

from datetime import datetime

try:
    from gradio_client import utils as _gc_utils
    _orig_json_schema_to_python = getattr(_gc_utils, "_json_schema_to_python_type", None)
    if _orig_json_schema_to_python is not None:
        def _safe_json_schema_to_python_type(schema, defs=None):
            if isinstance(schema, bool):
                return "Any"
            if not isinstance(schema, dict):
                return str(type(schema).__name__)
            if "additionalProperties" in schema:
                ap = schema["additionalProperties"]
                if isinstance(ap, bool):
                    schema = {**schema, "additionalProperties": {"type": "string"}}
            try:
                return _orig_json_schema_to_python(schema, defs)
            except Exception:
                return "Any"
        _gc_utils._json_schema_to_python_type = _safe_json_schema_to_python_type
except Exception:
    pass

import gradio as gr
import torch
from PIL import Image
from engine import (
    ROCmAIGCEngine,
    DEFAULT_SD3_MODEL,
    SD3_MEDIUM_MODEL,
    SD3_LARGE_MODEL,
    SD3_LARGE_TURBO_MODEL,
    LOCAL_SD3_MODEL_DIR,
    LOCAL_SD3_LARGE_DIR,
    LOCAL_SD3_TURBO_DIR,
    SD3_RECOMMENDED_WIDTH,
    SD3_RECOMMENDED_HEIGHT,
    DEFAULT_WAN_T2V_MODEL,
    LOCAL_WAN_T2V_DIR,
    WAN22_TI2V_5B_SIZE_GB,
)

_UTF8_HEAD = """
<meta charset="UTF-8">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
"""

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

engine = None


def get_engine():
    global engine
    if engine is None:
        engine = ROCmAIGCEngine()
    return engine


def save_result_image(image: Image.Image, prefix: str = "result") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    image.save(filepath)
    return filepath


# ================================================================
# Callbacks
# ================================================================
def predict_img2img(image, prompt, strength, steps, guidance_scale, negative_prompt):
    if image is None:
        return None, "请先上传一张图片"
    try:
        eng = get_engine()
        result_image = eng.generate_cyberpunk_art(
            init_image=image,
            prompt=prompt,
            strength=strength,
            steps=int(steps),
            guidance_scale=guidance_scale,
            negative_prompt=negative_prompt
        )
        saved_path = save_result_image(result_image, "img2img")
        _lbl = getattr(eng, "_image_model_label", "") or ""
        model_tag = f"[{_lbl}]" if _lbl else ("[SDXL]" if getattr(eng, "_sd_is_sdxl", False) else "[SD v1.5]")
        return result_image, (
            f"{model_tag} 生成成功！已保存到：{saved_path}\n"
            f"设备: {eng.device} | 步数: {int(steps)} | 强度: {strength}"
        )
    except Exception as e:
        import traceback
        return None, f"生成失败：{str(e)}\n{traceback.format_exc()}"


def predict_txt2img_sd(prompt, steps, guidance_scale, width, height, negative_prompt):
    if not prompt or not str(prompt).strip():
        return None, "请输入提示词"
    try:
        eng = get_engine()
        result_image = eng.generate_text_to_image(
            prompt=prompt,
            steps=int(steps),
            guidance_scale=guidance_scale,
            width=int(width),
            height=int(height),
            negative_prompt=negative_prompt,
        )
        saved_path = save_result_image(result_image, "txt2img_sd")
        _lbl = getattr(eng, "_image_model_label", "") or ""
        model_tag = f"[{_lbl}]" if _lbl else ("[SDXL]" if getattr(eng, "_sd_is_sdxl", False) else "[SD v1.5]")
        return result_image, (
            f"{model_tag} 生成成功！已保存到：{saved_path}\n"
            f"设备: {eng.device} | 尺寸: {int(width)}x{int(height)} | 步数: {int(steps)}"
        )
    except Exception as e:
        import traceback
        return None, f"生成失败：{str(e)}\n{traceback.format_exc()}"


def predict_txt2img_sd3(prompt, steps, guidance_scale, width, height, seed):
    if not prompt or not str(prompt).strip():
        return None, "请输入提示词"
    eng = get_engine()
    try:
        # SD3 已加载 → 用 SD3.5-Medium 出图（最高画质）
        if eng._sd3_loaded and eng.sd3_pipeline is not None:
            seed_val = int(seed) if seed is not None and str(seed).strip() != "" else None
            result_image = eng.sd3_generate_text_to_image(
                prompt=prompt,
                steps=int(steps),
                guidance_scale=float(guidance_scale),
                width=int(width),
                height=int(height),
                seed=seed_val,
            )
            saved_path = save_result_image(result_image, "txt2img_sd3")
            used_seed = seed_val if seed_val is not None else "random"
            _sd3_label = getattr(eng, "_image_model_label", "") or "SD3.5-Medium"
            return result_image, (
                f"[{_sd3_label}] 生成成功！已保存到：{saved_path}\n"
                f"设备: {eng.device} | 尺寸: {result_image.size[0]}x{result_image.size[1]} | "
                f"步数: {int(steps)} | Guidance: {float(guidance_scale):.1f} | Seed: {used_seed}"
            )
        # SD3 未加载（如磁盘放不下 10G）→ 自动回退到开源 SD 模型（SDXL / SD v1.5），保证本 Tab 始终可用
        print("  [Tab1] SD3 未加载，自动回退到 SD 模型生成文生图")
        result_image = eng.generate_text_to_image(
            prompt=prompt,
            steps=int(steps),
            guidance_scale=guidance_scale,
            width=int(width),
            height=int(height),
        )
        saved_path = save_result_image(result_image, "txt2img_sd")
        _lbl = getattr(eng, "_image_model_label", "") or ""
        model_tag = f"[{_lbl}]" if _lbl else ("[SDXL]" if getattr(eng, "_sd_is_sdxl", False) else "[SD v1.5]")
        return result_image, (
            f"{model_tag} 生成成功（SD3 未加载，已自动回退到 SD）！已保存到：{saved_path}\n"
            f"设备: {eng.device} | 尺寸: {int(width)}x{int(height)} | 步数: {int(steps)}"
        )
    except Exception as e:
        import traceback
        return None, f"生成失败：{str(e)}\n{traceback.format_exc()}"


def reload_sd3_engine(sd3_model_path):
    import os as _os
    try:
        eng = get_engine()
        target = sd3_model_path.strip() if sd3_model_path and str(sd3_model_path).strip() else None
        if not target:
            target = getattr(eng, "sd3_model_id", None) or LOCAL_SD3_MODEL_DIR

        is_default_local_cache = (
            _os.path.abspath(target.rstrip("/\\"))
            == _os.path.abspath(LOCAL_SD3_MODEL_DIR.rstrip("/\\"))
        )
        looks_like_hf_repo = (
            "/" in target
            and not _os.path.isdir(target)
            and not target.startswith(".")
            and not _os.path.isabs(target)
        )

        # ---- 诊断 1：本地目录模式？（默认缓存目录即使不存在也允许，会自动从 HF 下载）----
        if is_default_local_cache:
            idx = _os.path.join(target, "model_index.json")
            if _os.path.isfile(idx):
                pass
            else:
                if not looks_like_hf_repo:
                    target = DEFAULT_SD3_MODEL
        elif ("/" not in target or _os.path.isdir(target)) and not looks_like_hf_repo:
            if not _os.path.isdir(target):
                return (
                    f"SD3 重载失败：本地目录不存在\n"
                    f"路径: {target}\n"
                    f"请填写已存在的目录（包含 model_index.json、text_encoder、vae、transformer、scheduler 等子目录/文件），\n"
                    f"或清空输入框使用默认本地缓存目录（会自动从 HuggingFace 下载到 {LOCAL_SD3_MODEL_DIR}）。"
                )
            idx = _os.path.join(target, "model_index.json")
            if not _os.path.isfile(idx):
                return (
                    f"SD3 重载失败：目录 {target} 下找不到 model_index.json\n"
                    f"请确认已把完整 diffusers 格式的 SD3 模型放到该目录，而不是只放单个 .safetensors 文件。\n"
                    f"参考结构：\n"
                    f"  {target.rstrip('/')}/\n"
                    f"    ├── model_index.json\n"
                    f"    ├── text_encoder/ + text_encoder_2/ + text_encoder_3/\n"
                    f"    ├── tokenizer/ + tokenizer_2/ + tokenizer_3/\n"
                    f"    ├── vae/\n"
                    f"    ├── transformer/\n"
                    f"    └── scheduler/"
                )

        # ---- 诊断 2：在线模式，检查 HF 登录 & 授权 ----
        def _hf_help(repo: str) -> str:
            return (
                f"下载该 SD3 模型失败，请按以下排查：\n"
                f"  ① 默认模型 SD3.5-Medium 是 Community License，可直接下载；\n"
                f"  ② 若你手动指定了其他 model_id，请确认该仓库为公开可访问；\n"
                f"  ③ 网络/磁盘：确认能访问 HuggingFace 镜像，且磁盘剩余 ≥ 24GB（首次下载 SD3 约 10-16GB）。\n"
                f"  如需离线使用，可将已下载的模型目录填到「SD3 模型管理」下方路径后重载。"
            )

        try:
            eng.reload_sd3(model_id=target)
        except Exception as _e:
            _msg = str(_e)
            _trace = __import__("traceback").format_exc()
            if "403" in _msg or "gated repo" in _msg.lower() or "not in the authorized list" in _msg.lower():
                repo_for_help = DEFAULT_SD3_MODEL if is_default_local_cache else target.replace('"', "").strip()
                return (
                    f"SD3 重载失败：HuggingFace 返回 403 无授权访问。\n"
                    f"当前 model_id = {target}\n\n"
                    + _hf_help(repo_for_help)
                    + f"\n\n底层错误：{_msg[:400]}"
                )
            if "Memory" in _msg or "OutOfMemoryError" in _msg or "CUDA out of memory" in _msg or "HIP out of memory" in _msg:
                return (
                    f"SD3 重载失败：显存不足。\n"
                    f"SD3.5-Medium 需要约 10GB 参数 + 推理激活。48GB 机器应轻松；若共享占用多请先关闭其他进程释放显存后重试。\n"
                    f"底层错误：{_msg[:400]}\n{_trace[:1200]}"
                )
            return f"SD3 重载失败：{_msg[:600]}\n{_trace[:1600]}"

        return (
            f"SD3 重新加载成功！\n"
            f"当前模型路径: {eng.sd3_model_id}\n"
            f"SD3 可用: {eng._sd3_loaded}\n"
            f"{'（首次下载后已缓存到本地，后续无需重复下载）' if is_default_local_cache else ''}"
        )
    except Exception as e:
        import traceback
        return f"SD3 重载未捕获异常：{str(e)}\n{traceback.format_exc()}"


def hf_login_ui(token_text):
    """通过 WebUI 粘贴 HF Token 一键登录（huggingface_hub >= 0.34）。"""
    if not token_text or not str(token_text).strip():
        return "请先粘贴 HuggingFace Token（hf_... 开头，在 https://huggingface.co/settings/tokens 创建 Read 权限的 token 即可）。"
    tok = str(token_text).strip()
    try:
        from huggingface_hub import login
        login(token=tok, add_to_git_credential=False)
        # 验证能访问 gated repo（不下载权重，仅 HEAD metadata）
        from huggingface_hub import HfApi
        api = HfApi()
        try:
            info = api.model_info(DEFAULT_SD3_MODEL)
            gated = getattr(info, "gated", False) or getattr(info, "private_gated", False)
            g_ok = "模型可公开访问（无需 gated 授权）" if not gated else "模型为 gated repo：若仍 403，请先在网页端 Request access 并通过审核"
        except Exception as _e:
            g_ok = f"元数据查询失败：{str(_e)[:160]}"
        return (
            f"HuggingFace 登录成功！\n"
            f"当前 Token 前 10 位：{tok[:10]}...\n"
            f"{DEFAULT_SD3_MODEL} 访问状态：{g_ok}\n"
            f"→ 现在可以点「重新加载 SD3 模型」开始下载 ~10GB 权重（首次约 3-10 分钟取决于网络）。"
        )
    except Exception as e:
        import traceback
        return f"HF 登录失败：{str(e)}\n{traceback.format_exc()}"


def predict_text_to_video(
    prompt, steps, guidance_scale, num_frames,
    width, height, fps, negative_prompt, export_gif, seed
):
    if not prompt or not str(prompt).strip():
        return None, None, "请输入视频提示词"
    try:
        eng = get_engine()
        seed_val = int(seed) if seed is not None and str(seed).strip() != "" else None
        mp4_path, gif_path, frame_count = eng.generate_text_to_video(
            prompt=prompt,
            steps=int(steps),
            guidance_scale=float(guidance_scale),
            num_frames=int(num_frames),
            width=int(width),
            height=int(height),
            fps=int(fps),
            negative_prompt=negative_prompt,
            export_gif=bool(export_gif),
            seed=seed_val,
        )
        # 实际使用的引擎（来自三级回退链 Wan → LTX → Legacy）
        _backend = getattr(eng, "_t2v_last_backend", None)
        if _backend == "wan":
            engine_type = f"Wan2.2-TI2V-5B ({DEFAULT_WAN_T2V_MODEL})"
        elif _backend == "ltx":
            engine_type = "LTX-Video (Lightricks/LTX-Video · 回退)"
        elif _backend == "legacy":
            engine_type = "SD T2V (旧版 damo-vilab · 兜底)"
        else:
            engine_type = "未知"
        total_sec = int(frame_count) / max(1, int(fps))
        used_seed = seed_val if seed_val is not None else "random"
        msg = (
            f"视频生成成功！引擎 = {engine_type}\n"
            f"  MP4 保存路径: {mp4_path}\n"
            f"  帧数: {frame_count} / FPS: {int(fps)} / 时长: {total_sec:.2f}s\n"
            f"  尺寸: {int(width)}x{int(height)} / 步数: {int(steps)} / Guidance: {float(guidance_scale):.1f}\n"
            f"  Seed: {used_seed} | 设备: {eng.device}"
        )
        if gif_path:
            msg += f"\n  GIF 保存路径: {gif_path}"
        return mp4_path, gif_path, msg
    except Exception as e:
        return None, None, f"视频生成失败：{str(e)}"


def reload_t2v_engine(t2v_model_path):
    import os as _os
    try:
        eng = get_engine()
        target = t2v_model_path.strip() if t2v_model_path and str(t2v_model_path).strip() else None
        if not target:
            target = DEFAULT_WAN_T2V_MODEL

        try:
            eng.reload_t2v(model_id=target)
        except Exception as _e:
            _msg = str(_e)
            _trace = __import__("traceback").format_exc()
            if "pipeline" in _msg.lower() or "diffusers" in _msg.lower() or "wan" in _msg.lower() or "ltx" in _msg.lower():
                return (
                    f"T2V 主模型重载失败：diffusers 版本过低或未安装 WanPipeline / LTXPipeline。\n"
                    f"请执行：pip install -U diffusers（需 >=0.33）\n"
                    f"然后重启 WebUI 后重试。\n\n"
                    f"底层错误：{_msg[:600]}\n{_trace[:1600]}"
                )
            if "Memory" in _msg or "OutOfMemoryError" in _msg or "CUDA out of memory" in _msg or "HIP out of memory" in _msg:
                return (
                    f"T2V 主模型重载失败：显存不足。\n"
                    f"建议：\n"
                    f"  ① 减少帧数或降低分辨率；\n"
                    f"  ② 关闭其他占用显存的进程后重试。\n\n"
                    f"底层错误：{_msg[:400]}\n{_trace[:1200]}"
                )
            return f"T2V 主模型重载失败：{_msg[:600]}\n{_trace[:1600]}"

        _loaded = (
            "Wan2.2-TI2V-5B 已加载"
            if getattr(eng, "_wan_t2v_loaded", False)
            else ("LTX-Video 已加载（回退）" if getattr(eng, "_ltx_loaded", False) else "未加载")
        )
        return (
            f"T2V 主模型重新加载成功！\n"
            f"当前模型: {eng.t2v_model_id}\n"
            f"已加载后端: {_loaded}\n"
            f"{'（首次下载后已缓存到本地，后续无需重复下载）' if target == DEFAULT_WAN_T2V_MODEL else ''}"
        )
    except Exception as e:
        import traceback
        return f"T2V 主模型重载未捕获异常：{str(e)}\n{traceback.format_exc()}"


def get_system_info():
    eng = get_engine()
    lines = [
        f"PyTorch 版本: **{torch.__version__}**",
        f"ROCm build: **{getattr(torch.version, 'hip', 'N/A')}**",
        f"CUDA/ROCm 可用: **{torch.cuda.is_available()}**",
    ]
    if torch.cuda.is_available():
        lines += [
            f"GPU 设备: **{torch.cuda.get_device_name(0)}**",
            f"GPU 数量: {torch.cuda.device_count()}",
            f"GPU 显存: **{torch.cuda.get_device_properties(0).total_memory / (1024**3):.2f} GB**",
        ]
    lines += [
        f"SD 基础模型: `{eng.model_id}`",
        f"SD3.5 模型: `{eng.sd3_model_id}`",
        f"SD3.5 已加载: **{eng._sd3_loaded}**",
        f"视频主模型 (Wan2.2-TI2V-5B): `{eng.t2v_model_id}`",
        f"Wan 已加载: **{getattr(eng, '_wan_t2v_loaded', False)}**",
        f"LTX 回退已加载: **{eng._ltx_loaded}**",
        f"输出目录: `{OUTPUT_DIR}`",
    ]
    return "\n\n".join(lines)


# ================================================================
# Prompt presets (中文友好 + 赛博朋克强化)
# ================================================================
cyberpunk_prompts = [
    "未来感赛博都市夜景，霓虹招牌，湿漉漉的雨后街道，空中飞行的汽车，电影级构图",
    "赛博朋克武士，发光的武士刀，霓虹东京背景，全息投影，烟雾缭绕",
    "机器人仿生人肖像，清晰可见的电路，霓虹色长发，电影级打光",
    "赛博朋克街市，全息商贩，霓虹灯小吃摊，人潮涌动",
    "未来摩托车，霓虹流光，赛博朋克高速公路，运动模糊",
]

sd3_premium_prompts = [
    "A cyberpunk megacity at twilight: layered vertical architecture, colossal holographic koi fish drifting between skyscrapers, neon magenta and cyan signage reflected on rain-slick streets, a lone biker with a glowing visor waits at an intersection, volumetric god rays through smog, ultra detailed cinematic wide shot, depth of field",
    "A female cyberpunk netrunner jacked into a terminal: chrome cables plugged into her temple, floating holographic data cubes orbiting her head, dim room lit by monitor glow, intricate circuit patterns on her neck, rain streaked window behind her showing the cityscape, dramatic chiaroscuro lighting, hyperrealistic portrait",
    "A ramen stall hidden in a dark Tokyo alleyway in 2099: neon kanji lanterns hanging above, steam curling from a pork bone broth bowl, a robotic chef with brass gears serving, a cyborg customer with a glowing cybernetic eye slurping noodles, moody atmosphere, rich wet textures, cinematic shallow depth of field",
    "A cybernetic samurai standing on a rooftop overlooking neo-Tokyo: intricate chrome armor with glowing blue under-light, katana drawn crackling with plasma energy, cherry blossoms falling mixed with rain particles, massive corporate holograms in the background skyline, epic wide angle composition, dramatic silhouette, 8k ultra detail",
    "A bioluminescent cyber-whale soaring over a neon cyberpunk skyline: translucent body with visible glowing data streams, holographic advertisements projected on its skin, swirling colorful data clouds, smaller flying drones escorting it, citizens in the streets looking up in awe, epic surreal fantasy atmosphere, cinematic scale",
]

t2v_video_prompts = [
    "清晨阳光穿透森林，薄雾在树间流动，镜头缓缓向前推进，丁达尔效应，自然光，电影级运镜",
    "一只金毛犬在海边奔跑，浪花轻拍沙滩，日落时分橙红色天空，慢动作跟拍，温馨治愈",
    "繁忙的东京涩谷十字路口，行人穿梭，霓虹广告牌闪烁，高空俯拍逐渐拉远，都市节奏感",
    "一杯热咖啡放在木质桌面上，蒸汽缓缓上升，窗外雪花飘落，浅景深特写，温暖氛围",
    "未来太空站内，宇航员漂浮穿过圆形舱门，地球透过舷窗可见，零重力慢动作，科幻写实",
]

t2v_video_presets = [
    # Wan2.2-TI2V-5B：宽高需被 16 整除，≤720P 时画质/速度最佳。
    ("480P (832×480) · 5B 推荐画质", 832, 480),
    ("576P (1024×576) · 平衡画质速度", 1024, 576),
    ("720P (1280×720) · 高分辨率", 1280, 720),
    ("720P 竖屏 (720×1280) · 竖屏演示", 720, 1280),
]

t2v_frame_presets = [
    # 帧数需满足 (num_frames-1) % 4 == 0；默认 24fps 运动更自然。
    ("3秒 (81帧 @ 24fps) · 答辩推荐", 81, 24),
    ("2秒 (49帧 @ 24fps) · 流畅", 49, 24),
    ("3秒 (73帧 @ 24fps)", 73, 24),
    ("4秒 (97帧 @ 24fps)", 97, 24),
    ("5秒 (121帧 @ 24fps) · 长镜头", 121, 24),
]

video_prompts = t2v_video_prompts

sd3_resolution_presets = [
    ("1024 × 1024 (方形·推荐)", 1024, 1024),
    ("832 × 1216 (竖版肖像)", 832, 1216),
    ("1216 × 832 (横版风景)", 1216, 832),
    ("768 × 1024 (标准竖版)", 768, 1024),
    ("1024 × 768 (标准横版)", 1024, 768),
    ("1344 × 768 (超宽屏)", 1344, 768),
]


# ================================================================
# UI
# ================================================================
with gr.Blocks(theme=gr.themes.Soft(), title="AetherStyle-ROCm", head=_UTF8_HEAD) as demo:
    gr.Markdown(
        """
        # AetherStyle-ROCm: AMD 全球黑客松参赛作品 张鹏 15830669825
        基于 **AMD Radeon GPU + ROCm 开放软件栈** 构建的高性能多模态赛博朋克艺术生成工具

        **新增 SD3.5 文生图引擎 + LTX-Video 文生视频**：SD3.5 采用 MMDiT 架构 + 三文本编码器，画质与文本理解力大幅跃升；LTX-Video（DiT + T5-XXL）实时级推理、提示词长度几乎不限，为答辩演示提供最佳视觉效果。
        """
    )

    with gr.Accordion("系统状态信息", open=False):
        sys_info = gr.Markdown()
        refresh_btn = gr.Button("刷新系统信息", size="sm")
        refresh_btn.click(fn=get_system_info, outputs=sys_info)
        demo.load(fn=get_system_info, outputs=sys_info)

    with gr.Tabs():
        # ============================================================
        # Tab 1: SD3.5 Txt2Img (PREMIUM QUALITY)
        # ============================================================
        with gr.TabItem("SD3.5 文生图（最高画质·推荐）"):
            gr.Markdown(
                """
                **Stable Diffusion 3.5 [Medium]** 引擎：采用 MMDiT（Multimodal Diffusion Transformer）架构，
                搭载 CLIP-L + CLIP-G + T5-XXL 三文本编码器，对复杂提示词的理解能力远超 SD v1.5，
                图片层次感、细节丰富度与构图质量均达到商用级水准，且支持负向提示词。

                > ? 推荐参数：步数 28~50，Guidance 5.0~7.0，1024×1024 起步（48GB VRAM 可流畅跑 1216×832）
                """
            )
            with gr.Row():
                with gr.Column():
                    sd3_prompt_box = gr.Textbox(
                        label="创意提示词（Prompt）",
                        value=sd3_premium_prompts[0],
                        lines=6,
                        placeholder="详细描述你要生成的画面：主体、环境、光线、氛围、风格、镜头语言..."
                    )
                    with gr.Row():
                        sd3_pre1 = gr.Button("赛博都市 · 巨型全息锦鲤", size="sm")
                        sd3_pre2 = gr.Button("网络行者 · 数据接入", size="sm")
                        sd3_pre3 = gr.Button("深夜拉面摊", size="sm")
                        sd3_pre4 = gr.Button("霓虹武士", size="sm")
                        sd3_pre5 = gr.Button("机械鲸 · 天空漫游", size="sm")

                    sd3_pre1.click(lambda: sd3_premium_prompts[0], outputs=sd3_prompt_box)
                    sd3_pre2.click(lambda: sd3_premium_prompts[1], outputs=sd3_prompt_box)
                    sd3_pre3.click(lambda: sd3_premium_prompts[2], outputs=sd3_prompt_box)
                    sd3_pre4.click(lambda: sd3_premium_prompts[3], outputs=sd3_prompt_box)
                    sd3_pre5.click(lambda: sd3_premium_prompts[4], outputs=sd3_prompt_box)

                    with gr.Row():
                        sd3_res_preset = gr.Dropdown(
                            label="分辨率快捷预设",
                            choices=[name for name, _, _ in sd3_resolution_presets],
                            value=sd3_resolution_presets[0][0],
                            allow_custom_value=False,
                        )
                        sd3_seed_box = gr.Number(
                            label="随机种子 (留空=随机)",
                            value=42,
                            precision=0,
                        )

                    with gr.Row():
                        sd3_width_slider = gr.Slider(
                            minimum=512, maximum=1536, value=SD3_RECOMMENDED_WIDTH, step=32,
                            label="宽度（需为 8 的倍数，建议 ≥ 1024）"
                        )
                        sd3_height_slider = gr.Slider(
                            minimum=512, maximum=1536, value=SD3_RECOMMENDED_HEIGHT, step=32,
                            label="高度（需为 8 的倍数，建议 ≥ 1024）"
                        )

                    def _apply_sd3_res_preset(name):
                        for n, w, h in sd3_resolution_presets:
                            if n == name:
                                return w, h
                        return SD3_RECOMMENDED_WIDTH, SD3_RECOMMENDED_HEIGHT

                    sd3_res_preset.change(
                        fn=_apply_sd3_res_preset,
                        inputs=sd3_res_preset,
                        outputs=[sd3_width_slider, sd3_height_slider],
                    )

                    sd3_steps_slider = gr.Slider(
                        minimum=10, maximum=60, value=28, step=1,
                        label="推理步数（更多 = 更细腻，推荐 28~50）"
                    )
                    sd3_guidance_slider = gr.Slider(
                        minimum=1.0, maximum=15.0, value=5.0, step=0.1,
                        label="Guidance Scale（SD3 推荐 5.0~7.0）"
                    )

                    with gr.Accordion("SD3 模型管理", open=False):
                        gr.Markdown(
                            "**模型本地缓存策略**：\n"
                            "默认使用 **Stable Diffusion 3.5-Medium**（Community License，可直接下载）。\n"
                            "首次文生图会自动从 HuggingFace 下载 ~10GB 权重并保存到本地目录，后续直接本地加载（无需重复下载）。\n\n"
                            "**首次加载指引**：\n"
                            "1. 默认模型 SD3.5-Medium 是 Community License，可直接下载；\n"
                            "2. 点下方「重新加载 SD3 模型」，开始下载（首次 3–10 分钟）；\n\n"
                            f"默认本地缓存目录：`{LOCAL_SD3_MODEL_DIR}`\n\n"
                            "若本地已有完整 SD3 模型（diffusers 格式）：\n"
                            "→直接在下面填写本地目录绝对路径（需要包含 **model_index.json** 等子目录/文件）。"
                        )
                        with gr.Row():
                            hf_token_box = gr.Textbox(
                                label="HuggingFace Token（hf_ 开头，粘贴这里登录后点按钮）",
                                placeholder="hf_xxxxxxxxxxxxxxxxxxxxxx",
                                lines=1,
                                type="password",
                            )
                            hf_login_btn = gr.Button("HF 登录", variant="secondary", size="sm")
                        hf_login_status = gr.Textbox(label="HF 登录状态", value="", lines=3)
                        hf_login_btn.click(
                            fn=hf_login_ui, inputs=hf_token_box, outputs=hf_login_status)
                        sd3_model_path_box = gr.Textbox(
                            label="SD3 模型路径（自动下载到本地目录，或填写已有本地目录）",
                            value=LOCAL_SD3_MODEL_DIR,
                            placeholder=f"默认：{LOCAL_SD3_MODEL_DIR}，或填写已有本地目录绝对路径；填写 HF Repo ID 会自动下载到默认本地目录",
                            lines=1,
                        )
                        reload_sd3_btn = gr.Button("重新加载 SD3 模型", variant="secondary", size="sm")
                        sd3_status_box = gr.Textbox(label="SD3 加载状态", value="", lines=5)
                        reload_sd3_btn.click(
                            fn=reload_sd3_engine,
                            inputs=sd3_model_path_box,
                            outputs=sd3_status_box,
                        )

                    sd3_gen_btn = gr.Button(
                        "启动 SD3.5 高清文生图（AMD ROCm 加速）",
                        variant="primary",
                    )

                with gr.Column():
                    sd3_output_img = gr.Image(
                        type="pil",
                        label="SD3.5 生成结果（48GB VRAM 推荐 1024px 以上）",
                        height=520,
                    )
                    sd3_status_t2i = gr.Textbox(label="状态信息", lines=4)

            sd3_gen_btn.click(
                fn=predict_txt2img_sd3,
                inputs=[
                    sd3_prompt_box,
                    sd3_steps_slider,
                    sd3_guidance_slider,
                    sd3_width_slider,
                    sd3_height_slider,
                    sd3_seed_box,
                ],
                outputs=[sd3_output_img, sd3_status_t2i],
            )

        # ============================================================
        # Tab 2: SD v1.5 Img2Img (kept for style transfer)
        # ============================================================
        with gr.TabItem("图转图风格迁移（Img2Img）"):
            with gr.Row():
                with gr.Column():
                    input_img = gr.Image(
                        type="pil",
                        label="上传源图片（Content Image）",
                        height=400
                    )
                    prompt_box = gr.Textbox(
                        label="创意提示词（Prompt）",
                        value="未来感赛博都市，发光的机械元素",
                        lines=3
                    )
                    with gr.Row():
                        preset_btn1 = gr.Button("赛博都市", size="sm")
                        preset_btn2 = gr.Button("赛博武士", size="sm")
                        preset_btn3 = gr.Button("机器人肖像", size="sm")
                        preset_btn4 = gr.Button("街市", size="sm")
                        preset_btn5 = gr.Button("摩托狂飙", size="sm")

                    preset_btn1.click(lambda: cyberpunk_prompts[0], outputs=prompt_box)
                    preset_btn2.click(lambda: cyberpunk_prompts[1], outputs=prompt_box)
                    preset_btn3.click(lambda: cyberpunk_prompts[2], outputs=prompt_box)
                    preset_btn4.click(lambda: cyberpunk_prompts[3], outputs=prompt_box)
                    preset_btn5.click(lambda: cyberpunk_prompts[4], outputs=prompt_box)

                    negative_prompt_box = gr.Textbox(
                        label="负向提示词（Negative Prompt）",
                        value="blurry, low quality, distorted, ugly, watermark, bad anatomy",
                        lines=2
                    )
                    strength_slider = gr.Slider(
                        minimum=0.1, maximum=1.0, value=0.75, step=0.05,
                        label="迁移强度（越高越偏离原图）"
                    )
                    steps_slider = gr.Slider(
                        minimum=10, maximum=50, value=30, step=5,
                        label="推理步数"
                    )
                    guidance_slider = gr.Slider(
                        minimum=1.0, maximum=20.0, value=7.5, step=0.5,
                        label="Guidance Scale"
                    )
                    submit_btn = gr.Button(
                        "启动 AMD GPU 加速风格重构", variant="primary"
                    )

                with gr.Column():
                    output_img_i2i = gr.Image(
                        type="pil",
                        label="AMD ROCm 加速生成结果",
                        height=400
                    )
                    status_i2i = gr.Textbox(label="状态信息", lines=3)

            submit_btn.click(
                fn=predict_img2img,
                inputs=[
                    input_img, prompt_box, strength_slider,
                    steps_slider, guidance_slider, negative_prompt_box
                ],
                outputs=[output_img_i2i, status_i2i]
            )

        # ============================================================
        # Tab 3: SD v1.5 Txt2Img (legacy / VRAM tight)
        # ============================================================
        with gr.TabItem("SD 文生图（低显存备用）"):
            gr.Markdown(
                """
                SD v1.5 文生图（低显存或快速预览用）。对画质有要求请切换到 **SD3.5 文生图** 标签页。
                """
            )
            with gr.Row():
                with gr.Column():
                    prompt_txt = gr.Textbox(
                        label="创意提示词（Prompt）",
                        value="赛博朋克城市夜景，霓虹灯，下雨",
                        lines=4
                    )
                    with gr.Row():
                        preset_t1 = gr.Button("赛博都市", size="sm")
                        preset_t2 = gr.Button("赛博武士", size="sm")
                        preset_t3 = gr.Button("机器人肖像", size="sm")
                    preset_t1.click(lambda: cyberpunk_prompts[0], outputs=prompt_txt)
                    preset_t2.click(lambda: cyberpunk_prompts[1], outputs=prompt_txt)
                    preset_t3.click(lambda: cyberpunk_prompts[2], outputs=prompt_txt)

                    with gr.Row():
                        width_slider = gr.Slider(
                            minimum=512, maximum=1536, value=1024, step=64,
                            label="宽度（SDXL 原生 1024，建议 ≥ 768）"
                        )
                        height_slider = gr.Slider(
                            minimum=512, maximum=1536, value=1024, step=64,
                            label="高度（SDXL 原生 1024，建议 ≥ 768）"
                        )
                    negative_prompt_sd = gr.Textbox(
                        label="负向提示词（Negative Prompt）",
                        value="blurry, low quality, distorted, ugly, watermark, bad anatomy, extra limbs, mutated",
                        lines=2,
                    )
                    steps_txt = gr.Slider(
                        minimum=10, maximum=50, value=30, step=5,
                        label="推理步数"
                    )
                    guidance_txt = gr.Slider(
                        minimum=1.0, maximum=20.0, value=7.5, step=0.5,
                        label="Guidance Scale"
                    )
                    gen_btn = gr.Button("生成图片（SD v1.5）", variant="primary")

                with gr.Column():
                    output_img_t2i = gr.Image(
                        type="pil",
                        label="SD v1.5 生成结果",
                        height=400
                    )
                    status_t2i = gr.Textbox(label="状态信息", lines=3)

            gen_btn.click(
                fn=predict_txt2img_sd,
                inputs=[prompt_txt, steps_txt, guidance_txt, width_slider, height_slider, negative_prompt_sd],
                outputs=[output_img_t2i, status_t2i]
            )

        # ============================================================
        # Tab 4: Text-to-Video — Wan2.2-TI2V-5B (Wan-AI, Apache-2.0)
        # ============================================================
        with gr.TabItem("文生视频（Wan2.2-TI2V-5B）"):
            gr.Markdown(
                """
                **Wan2.2-TI2V-5B** — 阿里 Wan-AI 开源文生视频模型（Apache-2.0，[Wan-AI/Wan2.2-TI2V-5B-Diffusers](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers)）。
                5B 参数 DiT + FlowMatch 调度器，原生支持 **720P @ 24fps**；文本编码器用 **umt5-xxl**（多语言，**原生中文，无需翻译**），提示词长度几乎不限。
                **中文提示词直接送入即可**，效果优于先英译；也可写英文。

                > 引擎自动回退链：**Wan2.2-TI2V-5B → LTX-Video(2B) → Legacy SD T2V**，任一加载失败会自动切换下一档，不崩溃。
                > **答辩推荐**：**480P（832×480）/ 3秒(81帧@24fps) / 50 步 / Guidance 6.0**。想要“大屏演示”再选 720P；更高分辨率/更长时长会显著增加显存与耗时。
                > 相比 LTX-2B，Wan 5B 在动态一致性、细节与中文语义对齐上更强，是 48GB 显存下的最优解。
                """
            )
            with gr.Row():
                with gr.Column():
                    video_prompt = gr.Textbox(
                        label="视频创意提示词（支持中文·umt5-xxl 原生中文，无需翻译）",
                        value="",
                        lines=5,
                        placeholder="输入你想要的画面：主体、动作、环境、镜头运动、光线氛围等。Wan2.2 使用 umt5-xxl 多语言编码器，中文提示词直接送入即可，效果优于先英译；也可直接写英文。",
                    )
                    with gr.Row():
                        vpre1 = gr.Button("森林晨光", size="sm")
                        vpre2 = gr.Button("海边金毛", size="sm")
                        vpre3 = gr.Button("涩谷路口", size="sm")
                        vpre4 = gr.Button("咖啡飘雪", size="sm")
                        vpre5 = gr.Button("太空站", size="sm")
                    vpre1.click(lambda: video_prompts[0], outputs=video_prompt)
                    vpre2.click(lambda: video_prompts[1], outputs=video_prompt)
                    vpre3.click(lambda: video_prompts[2], outputs=video_prompt)
                    vpre4.click(lambda: video_prompts[3], outputs=video_prompt)
                    vpre5.click(lambda: video_prompts[4], outputs=video_prompt)

                    with gr.Row():
                        t2v_res_preset = gr.Dropdown(
                            label="分辨率预设（Wan 建议 ≤720P）",
                            choices=[name for name, _, _ in t2v_video_presets],
                            value=t2v_video_presets[0][0],
                        )
                        t2v_frame_preset = gr.Dropdown(
                            label="时长预设",
                            choices=[name for name, _, _ in t2v_frame_presets],
                            value=t2v_frame_presets[0][0],
                        )
                        t2v_seed_box = gr.Number(
                            label="Seed（留空=随机）",
                            value=None,
                            precision=0,
                        )

                    with gr.Row():
                        vwidth_slider = gr.Slider(
                            minimum=320, maximum=1280, value=832, step=16,
                            label="视频宽度 (px)"
                        )
                        vheight_slider = gr.Slider(
                            minimum=256, maximum=1280, value=480, step=16,
                            label="视频高度 (px)"
                        )

                    with gr.Row():
                        frames_slider = gr.Slider(
                            minimum=9, maximum=161, value=81, step=1,
                            label="帧数（多=视频更长；需满足 (帧数-1) 能被 4 整除）",
                        )
                        fps_slider = gr.Slider(
                            minimum=8, maximum=24, value=24, step=1,
                            label="FPS（每秒帧数；24fps 运动更自然）",
                        )

                    vsteps_slider = gr.Slider(
                        minimum=5, maximum=60, value=50, step=1,
                        label="推理步数（推荐 40~50；步数越多细节越稳）",
                    )
                    vguidance_slider = gr.Slider(
                        minimum=1.0, maximum=15.0, value=6.0, step=0.1,
                        label="Guidance Scale（推荐 5~7；跟得不紧可提到 7~9，过高会过饱和）",
                    )
                    vneg_box = gr.Textbox(
                        label="负向提示词（Wan 原生中文·LTX/SD fallback 同样生效）",
                        value=(
                            "blurry, out of focus, low quality, distorted, ugly, "
                            "watermark, pixelated, noisy, grainy, compression artifacts, "
                            "color bleeding, oversaturated, smearing, motion blur, "
                            "duplicated frames, flickering, deformed, floating objects, "
                            "bad anatomy, bad motion, unnatural lighting"
                        ),
                        lines=2,
                    )
                    with gr.Row():
                        gif_toggle = gr.Checkbox(
                            value=False,
                            label="同时导出 GIF（文件更大，便于嵌入 PPT）"
                        )
                    with gr.Accordion("Wan2.2-TI2V-5B 模型管理", open=False):
                        gr.Markdown(
                            "**模型本地缓存策略**：\n"
                            f"首次加载会自动从 HuggingFace 下载 `{DEFAULT_WAN_T2V_MODEL}` 权重（DiT 5B ~11GB + VAE ~0.3GB + umt5-xxl ~23GB，合计约 {WAN22_TI2V_5B_SIZE_GB:.0f}GB），后续直接从本地 `{LOCAL_WAN_T2V_DIR}` 加载。\n\n"
                            f"默认模型 ID：`{DEFAULT_WAN_T2V_MODEL}`\n"
                            "默认推理精度：`bf16`（Wan 官方推荐；可用 `AETHER_T2V_DTYPE=fp32/fp16/bf16` 覆盖）。\n\n"
                            "若 Wan 加载失败：\n"
                            "→ 确认已安装 `pip install -U diffusers`（需 >=0.33）；\n"
                            "→ 引擎会自动回退到 LTX-Video(2B)，再失败回退到 Legacy SD T2V。"
                        )
                        with gr.Row():
                            t2v_model_path_box = gr.Textbox(
                                label="Wan2.2 模型 ID（默认 Wan-AI/Wan2.2-TI2V-5B-Diffusers）",
                                value=DEFAULT_WAN_T2V_MODEL,
                                placeholder=f"默认：{DEFAULT_WAN_T2V_MODEL}",
                                lines=1,
                            )
                        reload_t2v_btn = gr.Button("重新加载 Wan2.2-TI2V-5B 模型", variant="secondary", size="sm")
                        t2v_status_box = gr.Textbox(label="T2V 加载状态", value="", lines=5)
                        reload_t2v_btn.click(
                            fn=reload_t2v_engine,
                            inputs=t2v_model_path_box,
                            outputs=t2v_status_box,
                        )

                    gen_video_btn = gr.Button(
                        "生成视频（Wan2.2-TI2V-5B · AMD ROCm）", variant="primary"
                    )

                with gr.Column():
                    video_output = gr.Video(
                        label="AMD ROCm + Wan2.2-TI2V-5B 文生视频（MP4）",
                        height=480,
                        autoplay=True,
                        loop=True,
                    )
                    video_gif_output = gr.Image(
                        label="GIF 预览（可选）",
                        type="filepath",
                        height=320,
                    )
                    status_t2v = gr.Textbox(label="状态信息", lines=6)

            def _apply_t2v_res(name):
                for n, w, h in t2v_video_presets:
                    if n == name:
                        return w, h
                return 832, 480

            def _apply_t2v_frame(name):
                for n, f, fp in t2v_frame_presets:
                    if n == name:
                        return f, fp
                return 81, 24

            t2v_res_preset.change(
                fn=_apply_t2v_res,
                inputs=t2v_res_preset,
                outputs=[vwidth_slider, vheight_slider],
            )
            t2v_frame_preset.change(
                fn=_apply_t2v_frame,
                inputs=t2v_frame_preset,
                outputs=[frames_slider, fps_slider],
            )

            gen_video_btn.click(
                fn=predict_text_to_video,
                inputs=[
                    video_prompt, vsteps_slider, vguidance_slider,
                    frames_slider, vwidth_slider, vheight_slider,
                    fps_slider, vneg_box, gif_toggle, t2v_seed_box,
                ],
                outputs=[video_output, video_gif_output, status_t2v],
            )

    gr.Markdown(
        """
        ---
        **小贴士**：
        - 文生图：默认使用 **Stable Diffusion 3.5-Medium**（Community License，~10GB），画质优于 SD v1.5；另有 SDXL / SD v1.5 作为备选
        - 48GB VRAM 可流畅运行 SD3.5-Medium；视频默认使用 **Wan2.2-TI2V-5B**（5B DiT + umt5-xxl 原生中文，~34GB，720P@24fps），自动回退 LTX-Video(2B) → Legacy SD T2V
        - 如 SD3 首次加载失败：确认网络可访问 HuggingFace 且磁盘剩余 ≥ 14GB，或改用「SD 文生图（低显存备用）」Tab 的开源 SD 模型
        - 如 Wan2.2 首次加载失败：确认已安装 `pip install -U diffusers`（需 >=0.33），引擎会自动回退 LTX-Video，再失败回退 Legacy SD T2V
        """
    )


def _inject_charset_middleware(app):
    try:
        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        class CharsetMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
                resp = await call_next(request)
                ct = resp.headers.get("content-type", "") or ""
                if "text/" in ct and "charset=" not in ct.lower():
                    resp.headers["content-type"] = f"{ct}; charset=utf-8"
                elif not ct:
                    resp.headers["content-type"] = "text/html; charset=utf-8"
                return resp

        app.add_middleware(CharsetMiddleware)
    except Exception:
        pass


def _find_free_port(start=7860, end=7879):
    """在 [start, end] 范围内寻找可用端口，避免上次进程残留导致端口占用。"""
    import socket
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                return port
        except OSError:
            continue
    raise OSError(f"在 {start}-{end} 范围内未找到可用端口")


if __name__ == "__main__":
    try:
        _inject_charset_middleware(demo)
    except Exception:
        pass

    # 端口优先级：环境变量 GRADIO_SERVER_PORT > 自动扫描 7860-7879
    _port = int(os.environ.get("GRADIO_SERVER_PORT", "0")) or _find_free_port()
    print(f">>> Gradio 服务端口: {_port}")

    demo.launch(
        server_name="0.0.0.0",
        server_port=_port,
        share=True,
        show_api=False,
    )
