import os
import sys
import gc
import time
import shutil
import logging
import threading
import traceback
from collections import deque

# ==================== 1. 核心持久化与 AMD 优化环境变量 ====================
# 必须在 import torch 之前设置！
WORKSPACE_DIR = "/mnt/workspace"

# 强制将 Triton 和 PyTorch 的编译缓存转移到持久化目录，解决重启重编问题
os.environ["TRITON_CACHE_DIR"] = os.path.join(WORKSPACE_DIR, ".triton_cache")
os.environ["TORCH_EXTENSIONS_DIR"] = os.path.join(WORKSPACE_DIR, ".torch_extensions")
os.environ["XDG_CACHE_HOME"] = os.path.join(WORKSPACE_DIR, ".cache")

# AMD MI308X 性能与编译环境变量
os.environ["TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL"] = "1"
os.environ["FLASH_ATTENTION_TRITON_AMD_ENABLE"] = "TRUE"
os.environ["PYTORCH_TUNABLEOP_ENABLED"] = "0"
os.environ["HIP_FORCE_DEV_KERNARG"] = "1"
os.environ["PYTORCH_HIP_ALLOC_CONF"] = "garbage_collection_threshold:0.8,max_split_size_mb:512"

# 创建必要的持久化目录
MODELS_DIR = os.path.join(WORKSPACE_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(os.path.join(WORKSPACE_DIR, "hf_cache"), exist_ok=True)
os.makedirs(os.path.join(WORKSPACE_DIR, "gradio_temp"), exist_ok=True)
os.makedirs(os.environ["TRITON_CACHE_DIR"], exist_ok=True)
os.makedirs(os.environ["TORCH_EXTENSIONS_DIR"], exist_ok=True)

# 设置模型下载缓存
os.environ["MODELSCOPE_CACHE"] = MODELS_DIR
os.environ["HF_HOME"] = os.path.join(WORKSPACE_DIR, "hf_cache")
os.environ["GRADIO_TEMP_DIR"] = os.path.join(WORKSPACE_DIR, "gradio_temp")
# ==============================================================================

import torch
from PIL import Image
import gradio as gr
from modelscope import snapshot_download, model_file_download
from diffusers import QwenImageEditPlusPipeline

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ==================== 运行日志同步到界面 ====================
# 全局日志缓冲区：保留最近 200 条日志
LOG_BUFFER = deque(maxlen=200)
LOG_LOCK = threading.Lock()

class GradioLogHandler(logging.Handler):
    """自定义日志处理器：把 logger 的日志同时写入界面日志框"""
    def emit(self, record):
        try:
            msg = self.format(record)
            with LOG_LOCK:
                LOG_BUFFER.append(msg)
        except Exception:
            pass

# 给 logger 挂接界面日志处理器（格式与终端一致）
_gradio_handler = GradioLogHandler()
_gradio_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s'))
logger.addHandler(_gradio_handler)

def get_log_text():
    """返回最近日志内容（供界面日志框展示）"""
    with LOG_LOCK:
        return "\n".join(list(LOG_BUFFER))

def clear_log():
    """清空日志缓冲区"""
    with LOG_LOCK:
        LOG_BUFFER.clear()
    return ""

# 2. 检测GPU并启用 Triton Flash Attention
if torch.cuda.is_available():
    logger.info("[System] 检测到 AMD GPU，启用 Triton Flash Attention...")
    # 启用 FlashAttention 加速（对 AMD MI308X 至关重要，可显著减少显存占用并提速）
    torch.backends.cuda.enable_flash_sdp(True)
    # 启用内存高效的 SDP（Scaled Dot-Product Attention）实现，作为 FlashAttention 的备用方案
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    # 禁用数学实现的 SDP（较慢），强制使用上面更优的注意力内核
    torch.backends.cuda.enable_math_sdp(False)
    try:
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        # 名称为空时提示不可显示
        gpu_display = gpu_name if gpu_name else "GPU名称未显示"
        logger.info(f"[System]GPU张数: {torch.cuda.device_count()}, GPU名称: {gpu_display}, 显存: {gpu_mem:.2f} GB")
    except Exception as e:
        logger.error(f"[System] GPU 信息获取错误: {e}")

pipe = None

# 记录已完成过推理的分辨率，用于判断是否首次（首次需编译 AMD GPU 内核，耗时较长）
INFERRED_SHAPES = set()
SHAPES_LOCK = threading.Lock()

# 3. 模型初始化
def init_model():
    global pipe
    if pipe is None:
        logger.info("[Init] 初始化模型...")
        gc.collect(); torch.cuda.empty_cache()
        model_dir = snapshot_download("Qwen/Qwen-Image-Edit-2511", cache_dir=MODELS_DIR)
        
        logger.info("[Init] 加载图像编辑管道到显卡...")
        pipe = QwenImageEditPlusPipeline.from_pretrained(model_dir, torch_dtype=torch.bfloat16).to("cuda")
        pipe.set_progress_bar_config(disable=True)

        logger.info("[Init] 加载 Lightning 加速用的蒸馏 LoRA 文件...")
        try:
            lora_path = model_file_download("lightx2v/Qwen-Image-Edit-2511-Lightning",
                                            "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
                                            cache_dir=MODELS_DIR)
        except:
            lora_dir = snapshot_download("lightx2v/Qwen-Image-Edit-2511-Lightning", cache_dir=MODELS_DIR)
            lora_path = os.path.join(lora_dir, "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors")
        pipe.load_lora_weights(lora_path, adapter_name="lightning")
        pipe.set_adapters(["lightning"], adapter_weights=[1.0])
        logger.info("✅ 模型准备完成！")


def step_callback(pipe, step_index, timestep, callback_kwargs):
    """每一步去噪后同步并记录，必须返回一个字典（可为空）

    参数说明:
        pipe:            正在执行的扩散管道对象（QwenImageEditPlusPipeline）
        step_index:      当前完成的去噪步序号（从 0 开始）
        timestep:        当前步对应的时间步值（调度器中的噪声调度刻度）
        callback_kwargs: 回调附加参数，包含启用的 tensor 输入（如 latents）
    """
    # 同步 CUDA/ROCm 流，确保 GPU 上该步的计算全部完成，避免日志时序错乱
    torch.cuda.synchronize()
    # 记录当前完成的步数（+1 转为人类可读的 1-based 序号）
    logger.info(f"   ▶ 步骤 {step_index+1} 完成 (timestep={timestep})")
    # 回调必须返回字典；返回空字典表示不做任何修改，保持原样继续
    return {}
# 5. 推理函数
def center_crop_to_size(img, target_w, target_h):
    """将图片居中裁剪到目标宽高比，再缩放到目标尺寸（不拉伸变形）

    逻辑: 按目标宽高比 (target_w/target_h) 与原图宽高比比较，
    在原图较宽的一侧裁剪掉多余部分（居中对称裁剪），保留内容主体。
    """
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        # 原图比目标更宽：按高度为基准，居中裁掉左右多余的宽度
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        # 原图比目标更高（或相等）：按宽度为基准，居中裁掉上下多余的高度
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))
    # 裁剪后缩放到目标分辨率（LANCZOS 高质量重采样）
    return img.resize((target_w, target_h), Image.Resampling.LANCZOS)

def run_inference(pil_image, prompt, negative_prompt, res_str, steps, cfg_scale, seed):
    """执行图片编辑推理，返回生成图片的保存路径

    参数说明:
        pil_image:       用户上传的 PIL 图像（Gradio Image 组件 type="pil"）
        prompt:          正向提示词，描述期望的编辑效果
        negative_prompt: 负向提示词，描述要避免出现的内容
        res_str:         分辨率字符串，形如 "1664x928"，从中解析宽高
        steps:           去噪步数（num_inference_steps）
        cfg_scale:       真实 CFG 引导强度（true_cfg_scale）
        seed:            随机种子，-1 表示随机
    返回:
        str: 生成图片在服务器上的保存路径
    """
    # 记录推理开始时间，用于统计总耗时
    start_time = time.time()
    # 2. 空图拦截防御：防止引发 NoneType 错误
    if pil_image is None:
        raise gr.Error("未检测到图片！请先上传一张需要编辑的图片。")
        
    # 确保模型已加载（首次调用会触发模型下载与初始化）
    init_model()
    
    # 3. 解析下拉框固定的分辨率 "宽x高" → (width, height)
    width, height = map(int, res_str.split('x'))
    
    # 释放 Python 侧无用对象并清空 GPU 缓存，为推理腾出显存
    gc.collect(); torch.cuda.empty_cache()
    # 统一转 RGB 后，按目标比例居中裁剪再缩放（不拉伸变形，保留主体）
    img = center_crop_to_size(pil_image.convert("RGB"), width, height)
    
    # 支持 -1 表示随机种子（每次生成结果不同）
    seed_val = int(seed)
    if seed_val < 0:
        # 从 GPU 生成器取一个随机种子，并记录到日志便于复现
        seed_val = torch.Generator(device="cuda").seed()
        logger.info(f"[模型推理] 使用随机种子: {seed_val}")
    # 用固定种子创建 GPU 上的随机数生成器，保证同参数可复现
    generator = torch.Generator(device="cuda").manual_seed(seed_val)

    logger.info(f"[模型推理] 正向提示词: {prompt}")
    logger.info(f"[模型推理] 调用管道进行推理 {width}x{height}...")
    
    # 判断是否为该分辨率首次推理：首次需要编译 AMD GPU 内核（约20分钟），复次秒出
    with SHAPES_LOCK:
        first_time = (width, height) not in INFERRED_SHAPES
        if first_time:
            INFERRED_SHAPES.add((width, height))
    if first_time:
        logger.info(f"[模型推理] ⚠️ {width}x{height} 为首次推理，需要编译 AMD GPU 内核（约20分钟），请耐心等待...")
    
    
    # inference_mode 下不保存梯度，节省显存并加速推理
    with torch.inference_mode():
        output = pipe(
            image=[img],                          # 输入图像（列表形式传入）
            prompt=prompt,                        # 正向提示词
            negative_prompt=negative_prompt if negative_prompt else " ",  # 负向提示词（空则用空格占位）
            height=height, width=width,           # 输出尺寸
            num_inference_steps=steps,            # 去噪步数
            generator=generator,                  # 随机数生成器（控制随机性/可复现）
            true_cfg_scale=float(cfg_scale),      # 真实引导强度，控制提示词遵循程度
            guidance_scale=1.0,                   # 普通引导尺度固定为 1.0（由 true_cfg_scale 主导）
            num_images_per_prompt=1,              # 每次生成 1 张图
            callback_on_step_end=step_callback,   # 每步结束后回调，用于进度日志
            callback_on_step_end_tensor_inputs=["latents"],  # 回调时额外传入 latents 张量
        )
    logger.info("[模型推理] 完成。")
    logger.info(f"[模型推理] 用时{time.time()-start_time:.2f}秒。")
    
    # 保存结果到持久化目录，文件名含实际种子与时间戳避免冲突
    save_path = os.path.join(WORKSPACE_DIR, f"out_{seed_val}_{int(time.time())}.png")
    output.images[0].save(save_path)
    return save_path

# 5. 默认正向提示词
default_prompt = "把这张图片换个背景，换个表情，换个服装"
# 6. 默认负向提示词
default_neg = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感，构图混乱，文字模糊，扭曲，水印，模糊，变形，多余肢体，缺失手指，裁剪，伪影，签名，用户名，错误"

# 推荐分辨率（下拉框全部显示，但仅 1664x928 可用）
# 每项为 (显示标签, 实际值)，实际值保持 "宽x高" 格式便于解析
RES_OPTIONS = [
    ("1:1 正方形 (1328x1328)", "1328x1328"),
    ("16:9 横屏 (1664x928)", "1664x928"),
    ("9:16 竖屏 (928x1664)", "928x1664"),
    ("4:3 横屏 (1472x1140)", "1472x1140"),
    ("3:4 竖屏 (1140x1472)", "1140x1472"),
    ("3:2 横屏 (1584x1056)", "1584x1056"),
    ("2:3 竖屏 (1056x1584)", "1056x1584"),
]
# 当前唯一支持的分辨率（其他分辨率会触发 AMD 内核重新编译，耗时过长）
LOCKED_RES = "1664x928"

def lock_resolution(choice):
    """锁定分辨率：只允许 1664x928，选择其他选项时提示并自动弹回"""
    if choice != LOCKED_RES:
        gr.Info(f"⚠️ 当前仅支持 {LOCKED_RES}，已自动锁定该分辨率！")
    return LOCKED_RES

# 7. 查看 WORKSPACE_DIR 目录的总空间和剩余空间
def check_disk_space():
    """查看 WORKSPACE_DIR 的总空间和剩余空间"""
    try:
        usage = shutil.disk_usage(WORKSPACE_DIR)
        total_gb = usage.total / 1024**3
        used_gb = usage.used / 1024**3
        free_gb = usage.free / 1024**3
        return (f"📁 工作目录: {WORKSPACE_DIR}\n"
                f"总空间: {total_gb:.2f} GB\n"
                f"已使用: {used_gb:.2f} GB ({used_gb/total_gb*100:.1f}%)\n"
                f"剩余: {free_gb:.2f} GB ({free_gb/total_gb*100:.1f}%)")
    except Exception as e:
        return f"❌ 磁盘空间查询失败: {e}"

# 8. 监测 GPU 状态（显存占用、利用率）
def check_gpu():
    """监测 GPU 状态（显存占用、利用率）"""
    lines = []
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            name = torch.cuda.get_device_name(i)
            free, total = torch.cuda.mem_get_info(i)
            used = total - free
            lines.append(f"🎮 GPU {i}: {name}")
            lines.append(f"显存: 已用 {used/1024**3:.2f} GB / 总 {total/1024**3:.2f} GB ({used/total*100:.1f}%)")
            # ROCm 下 torch.cuda.utilization 可能不可用，兼容处理
            try:
                util = torch.cuda.utilization(i)
                lines.append(f"利用率: {util:.1f}%")
            except Exception:
                lines.append("利用率: 不可用")
            lines.append("")
    else:
        lines.append("⚠️ 未检测到 GPU")
    return "\n".join(lines) if lines else "⚠️ 未检测到 GPU"

# 9. 综合状态：磁盘 + GPU 一起显示
def check_system_status():
    """查看磁盘空间 + GPU 状态"""
    return check_disk_space() + "\n\n" + check_gpu()

with gr.Blocks(title="Qwen-Image-Edit") as demo:
    gr.Markdown("# Qwen-Image-Edit-2511 AMD MI308X 192GB显存专用")
    gr.Markdown("""### 运行环境
<span style="display:inline-block;background:#6f42c1;color:#fff;border-radius:10px;padding:2px 10px;margin:2px;">🖥️ AMD MI308X 专用</span>
<span style="display:inline-block;background:#0d6efd;color:#fff;border-radius:10px;padding:2px 10px;margin:2px;">🎯 bfloat16 精度</span>
<span style="display:inline-block;background:#198754;color:#fff;border-radius:10px;padding:2px 10px;margin:2px;">⚡ FlashAttention 加速</span>
<span style="display:inline-block;background:#fd7e14;color:#fff;border-radius:10px;padding:2px 10px;margin:2px;">🚀 Lightning 4步蒸馏 LoRA 加速</span>""")
    
    with gr.Row():
        with gr.Column():
            img_in = gr.Image(type="pil", label="上传图片 (仅支持16:9横屏，居中按尺寸裁剪)")
            prompt_in = gr.Textbox(label="提示词", value=default_prompt)
            neg_in = gr.Textbox(label="负提示词", value=default_neg)
            
            btn = gr.Button("生成", variant="primary")
            
            # 10. 系统状态监测按钮（磁盘空间 + GPU）
            gr.Markdown("### 系统监测")
            with gr.Row():
                disk_btn = gr.Button("查看磁盘空间", variant="secondary")
                gpu_btn = gr.Button("监测GPU", variant="secondary")
                status_btn = gr.Button("全部状态", variant="secondary")
            sys_info = gr.Textbox(label="系统信息", interactive=False, lines=8)
            
            
            
        with gr.Column():
            # 11. 生成结果图片
            img_out = gr.Image(type="filepath", label="生成结果")           
            
            # 12. 运行日志框：同步显示 logger 信息
            gr.Markdown("### 运行日志")
            log_out = gr.Textbox(label="运行日志", interactive=False, lines=10)
            with gr.Row():
                refresh_log_btn = gr.Button("刷新日志", variant="secondary")
                clear_log_btn = gr.Button("清空日志", variant="secondary")

            # 13. 参数设置
            with gr.Accordion("参数设置", open=False):
                # 4. 官方推荐分辨率全部显示，但仅锁定 1664x928 可选（避免重复编译内核）
                res_dropdown = gr.Dropdown(
                    choices=RES_OPTIONS, 
                    value="1664x928", 
                    label="分辨率 (当前仅支持16:9 横屏1664x928)"
                )
                steps = gr.Slider(1, 20, 4, step=1, label="Steps")
                cfg = gr.Slider(1.0, 5.0, 1.5, label="CFG")
                seed = gr.Number(-1, label="Seed (-1 为随机)")
    
            
    btn.click(run_inference, [img_in, prompt_in, neg_in, res_dropdown, steps, cfg, seed], [img_out])
    # 锁定分辨率：选择非 1664x928 时自动弹回
    res_dropdown.change(lock_resolution, inputs=res_dropdown, outputs=res_dropdown)
    disk_btn.click(check_disk_space, outputs=sys_info)
    gpu_btn.click(check_gpu, outputs=sys_info)
    status_btn.click(check_system_status, outputs=sys_info)
    refresh_log_btn.click(get_log_text, outputs=log_out)
    clear_log_btn.click(clear_log, outputs=log_out)
    
    # 定时器每 2 秒自动刷新日志框
    timer = gr.Timer(2)
    timer.tick(get_log_text, outputs=log_out)

if __name__ == "__main__":
    logger.info("开始运行 Gradio...")
    demo.launch(server_name="0.0.0.0", server_port=7860, allowed_paths=[WORKSPACE_DIR])