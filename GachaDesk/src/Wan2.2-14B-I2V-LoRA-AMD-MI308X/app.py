# ============================================
# Wan-2.2 14B 图生视频 - AMD ROCm环境
# 适合新手学习的详细注释版本
# ============================================

# 导入操作系统模块，用于文件路径和环境变量操作
import os
# 导入日志模块，用于记录运行日志（同时输出到控制台和界面）
import logging
# 导入系统模块，用于环境检测异常时退出程序
import sys

# ==================== 环境变量配置 ====================
# 设置模型缓存路径到 /mnt/workspace，避免默认路径空间不足
# MODELSCOPE_CACHE: ModelScope 模型下载缓存目录
os.environ["MODELSCOPE_CACHE"] = "/mnt/workspace/.cache/modelscope"
# HF_HOME: HuggingFace 模型下载缓存目录
os.environ["HF_HOME"] = "/mnt/workspace/.cache/huggingface"
# GRADIO_TEMP_DIR: Gradio 临时文件目录
os.environ["GRADIO_TEMP_DIR"] = "/mnt/workspace/.cache/gradio"

# 自动创建上述目录，如果目录已存在则不会报错
for path in [
    "/mnt/workspace/.cache/modelscope",
    "/mnt/workspace/.cache/huggingface",
    "/mnt/workspace/.cache/gradio",
    "/mnt/workspace/models"
]:
    os.makedirs(path, exist_ok=True)

# ==================== 第三方库导入 ====================
# gradio: 用于构建网页交互界面
import gradio as gr
# torch: PyTorch 深度学习框架
import torch
# random: 用于生成随机数（如随机种子）
import random
# glob: 用于文件路径匹配（查找LoRA文件）
import glob
# time: 用于计时（统计各阶段耗时）
import time
# uuid: 用于生成唯一文件名
import uuid
# numpy: 数值计算库，处理图像数组
import numpy as np
# imageio: 图像和视频读写库
import imageio
# snapshot_download: 从 ModelScope 下载模型
from modelscope import snapshot_download
# WanImageToVideoPipeline: Wan-2.2 图生视频推理管道
from diffusers import WanImageToVideoPipeline
# PIL 相关：图像处理（裁剪、绘制水印）
from PIL import Image, ImageDraw, ImageFont

# ==================== 日志配置 ====================
# 创建 logger 实例，命名为 "Wan2.2"
logger = logging.getLogger("Wan2.2")
logger.setLevel(logging.INFO)

# 控制台输出 handler（带时间戳格式）
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_console_handler)

# 全局日志缓冲区（供 Gradio 界面运行日志读取显示）
LOG_BUFFER = []

class _BufferHandler(logging.Handler):
    """自定义日志 handler，将消息追加到全局缓冲区供界面显示"""
    def emit(self, record):
        LOG_BUFFER.append(record.getMessage())

# 缓冲区 handler（不带时间戳，界面显示更简洁）
_buffer_handler = _BufferHandler()
_buffer_handler.setLevel(logging.INFO)
logger.addHandler(_buffer_handler)

# 尝试导入 imageio-ffmpeg，用于视频编码
try:
    import imageio_ffmpeg
except ImportError:
    logger.info("⚠️ 警告: imageio-ffmpeg 未安装，视频导出可能失败。请运行: pip install imageio-ffmpeg")

# ==================== 全局变量 ====================
# PIPELINE: 保存加载好的模型管道，避免重复加载
PIPELINE = None
# MODEL_LOADED: 标记模型是否已加载到显存
MODEL_LOADED = False
# FIRST_INFERENCE_DONE: 标记首次推理是否已完成（首次推理有初始化开销）
FIRST_INFERENCE_DONE = False
# CACHE_DIR: 模型缓存根目录
CACHE_DIR = "/mnt/workspace/models"

# ==================== ROCm 环境检测函数 ====================
def print_rocm_info():
    """打印 AMD ROCm 环境信息，辅助调试"""
    logger.info("-" * 60)
    logger.info("🖥️  AMD MI308X ROCm 环境检测:")

    try:
        if torch.cuda.is_available():
            # 原始探测输出（与 python -c 命令一致）
            logger.info(f"   原始探测: is_available={torch.cuda.is_available()}, hip={torch.version.hip}, device={torch.cuda.get_device_name(0)}")
            gpu_count = torch.cuda.device_count()
            if gpu_count > 0:
                gpu_details = []
                for i in range(gpu_count):
                    gpu_name = torch.cuda.get_device_name(i)
                    # GPU名称为空时使用默认描述
                    if not gpu_name or gpu_name.strip() == "":
                        gpu_name = "AMD GPU (名称不可用)"
                    gpu_mem = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)
                    gpu_details.append(f"GPU {i}: {gpu_name} ({gpu_mem:.2f} GB)")
                gpu_info = f"{gpu_count} 个 GPU\n" + "\n".join(gpu_details)
            else:
                gpu_info = "CUDA 可用但未检测到 GPU 设备"
            logger.info(f"   {gpu_info}")
        else:
            logger.info("   ❌ 错误：未检测到 AMD GPU！")
            logger.info("   请确认已正确安装 ROCm 驱动及 PyTorch ROCm 版本。")
            logger.info("   如使用 conda 环境，请运行: conda install pytorch 等等")
            sys.exit(1)
    except Exception as e:
        logger.info(f"   ❌ 错误：环境检测异常: {e}")
        sys.exit(f"❌ 环境检测异常: {e}\n请检查 PyTorch 及 ROCm 环境是否正确安装。")

    logger.info("-" * 60)

# ==================== 模型预下载函数 ====================
def preload_all_models():
    """
    预下载并检查模型缓存
    首次运行会下载约40GB模型文件，后续运行直接使用缓存
    """
    logger.info("=" * 60)
    logger.info("🔥 开始检查模型缓存 (保存至 /mnt/workspace)...")

    # 主模型 ID（来自 ModelScope）
    base_model_id = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"
    # 拼接本地缓存路径
    base_model_path = os.path.join(CACHE_DIR, f"models--{base_model_id.replace('/', '--')}")
    
    # 检查主模型是否已下载
    if os.path.exists(base_model_path) and os.listdir(base_model_path):
        logger.info("✅ 主模型已存在，跳过下载。")
    else:
        logger.info(f"📥 下载主模型: {base_model_id}")
        snapshot_download(base_model_id, cache_dir=CACHE_DIR)

    # LoRA 模型 ID（加速推理用）
    lora_repo = "lightx2v/Wan2.2-Distill-Loras"
    lora_path = os.path.join(CACHE_DIR, f"models--{lora_repo.replace('/', '--')}")
    
    # 检查 LoRA 是否已下载
    if os.path.exists(lora_path) and os.listdir(lora_path):
        logger.info("✅ LoRA 模型已存在，跳过下载。")
    else:
        logger.info(f"📥 下载 LoRA: {lora_repo}")
        snapshot_download(lora_repo, cache_dir=CACHE_DIR)

    logger.info("✅ 所有模型已就绪！")
    logger.info("=" * 60)

# ==================== 模型加载函数 ====================
def load_wan_pipeline(base_model_id, use_lora):
    """
    加载 Wan-2.2 图生视频模型到 GPU 显存
    
    参数:
        base_model_id: 主模型 ID（字符串）
        use_lora: 是否使用 LoRA（"无 (None)" 或 "LightX2V..."）
    
    返回:
        pipe: 加载好的推理管道对象
    """
    # 使用全局变量，确保多次调用共享同一个模型实例
    global PIPELINE, MODEL_LOADED
    # gc: 垃圾回收模块，用于释放内存
    import gc

    # 如果模型已经加载过，直接返回，避免重复加载
    if MODEL_LOADED and PIPELINE is not None:
        logger.info("✅ 管道已在显存中，跳过加载")
        return PIPELINE

    logger.info(f"🔄 加载模型: {base_model_id}")
    # 强制垃圾回收，释放无用内存
    gc.collect()
    # 如果有 CUDA（GPU），清空显存缓存
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # 下载（或从缓存加载）模型文件
    model_dir = snapshot_download(base_model_id, cache_dir=CACHE_DIR)
    logger.info("⚡ 加载中（FP16 精度，针对 AMD 平台适配）...")

    try:
        # 尝试使用 xformers 加速（提升 AMD GPU 上的注意力计算效率）
        pipe = WanImageToVideoPipeline.from_pretrained(
            model_dir,                    # 模型本地路径
            torch_dtype=torch.float16,    # 使用 FP16 精度（节省显存）
            low_cpu_mem_usage=True,       # 低 CPU 内存使用模式
            device_map="cuda",            # 使用 GPU（AMD ROCm 环境）
            attn_implementation="xformers"  # 使用 xformers 优化注意力
        )
        # 确保所有模型组件都使用 FP16 精度
        pipe.transformer = pipe.transformer.to(dtype=torch.float16)
        pipe.vae = pipe.vae.to(dtype=torch.float16)
        pipe.unet = pipe.unet.to(dtype=torch.float16)
        pipe.text_encoder = pipe.text_encoder.to(dtype=torch.float16)
        logger.info("✅ 模型加载成功！")
    except Exception as e:
        # 如果 xformers 不可用，回退到默认配置
        logger.info(f"⚠️ xformers 加载失败，使用默认配置: {e}")
        pipe = WanImageToVideoPipeline.from_pretrained(
            model_dir,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
            device_map="cuda"
        )
        logger.info("✅ 模型加载成功（默认配置）")

    # 如果用户选择使用 LoRA，挂载 LoRA 权重
    if use_lora != "无 (None)":
        logger.info("🧩 挂载 LightX2V LoRA（极速模式）...")
        lora_dir = snapshot_download("lightx2v/Wan2.2-Distill-Loras", cache_dir=CACHE_DIR)
        # 查找 high_noise 和 low_noise 的 LoRA 文件
        high_noise_files = glob.glob(os.path.join(lora_dir, "*high_noise_lora*.safetensors"))
        low_noise_files = glob.glob(os.path.join(lora_dir, "*low_noise_lora*.safetensors"))
        
        if high_noise_files and low_noise_files:
            try:
                # 加载两个 LoRA 适配器
                pipe.load_lora_weights(high_noise_files[0], adapter_name="high")
                pipe.load_lora_weights(low_noise_files[0], adapter_name="low", load_into_transformer_2=True)
                # 设置适配器权重，两个适配器各占 50%
                pipe.set_adapters(["high", "low"], adapter_weights=[1.0, 1.0])
                logger.info("✅ LoRA 挂载成功")
            except Exception as e:
                logger.info(f"⚠️ LoRA 挂载失败: {e}")

    # 更新全局变量，标记模型已加载
    PIPELINE = pipe
    MODEL_LOADED = True
    return pipe

# ==================== 图片处理函数 ====================
def center_crop_resize(img, target_w, target_h):
    """
    以图片中心为基准，缩放并裁剪到目标尺寸（类似 CSS 的 cover 模式）
    
    参数:
        img: PIL Image 对象（输入图片）
        target_w: 目标宽度（像素）
        target_h: 目标高度（像素）
    
    返回:
        img_cropped: 裁剪后的 PIL Image 对象
    """
    # 获取原始图片尺寸
    orig_w, orig_h = img.size
    # 计算缩放比例（取宽高缩放中的较大值，确保覆盖目标尺寸）
    scale = max(target_w / orig_w, target_h / orig_h)
    # 计算缩放后的尺寸
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    # 使用 LANCZOS 算法高质量缩放（抗锯齿）
    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
    
    # 计算裁剪位置（中心裁剪）
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    # 执行裁剪
    img_cropped = img_resized.crop((left, top, left + target_w, top + target_h))
    return img_cropped

# ==================== 水印添加函数 ====================
def add_watermark(frame, watermark_text="AI ART XIHUYISHENG AMD RADEON"):
    """
    在视频帧右下角添加半透明水印
    
    参数:
        frame: 视频帧（numpy 数组或 PIL Image）
        watermark_text: 水印文字内容
    
    返回:
        frame: 添加水印后的帧（numpy 数组）
    """
    # 将 numpy 数组转换为 PIL Image（如果输入是数组的话）
    if isinstance(frame, np.ndarray):
        img = Image.fromarray(frame)
    else:
        img = frame
    
    # 根据视频尺寸自适应字体大小（最小12号，最大为画面尺寸的1/30）
    font_size = max(12, min(img.width, img.height) // 30)
    
    # 尝试加载系统字体（按优先级尝试，优先加载中文字体）
    font_paths = [
        # 中文字体路径（Ubuntu 常见）
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-SC-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/truetype/arphic/ukai.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/freefont/NotoSansCJK-Regular.ttc",
        # 英文字体（备选）
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    font = None
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                continue
    # 如果没有找到合适的字体，使用默认字体
    if font is None:
        font = ImageFont.load_default()
    
    # 计算文字占据的宽度和高度
    text_bbox = ImageDraw.Draw(img).textbbox((0, 0), watermark_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # 设置边距，将水印放在右下角
    padding = 10
    x = img.width - text_width - padding
    y = img.height - text_height - padding
    
    # 将图片转换为 RGBA 模式（支持透明度）
    img_rgba = img.convert("RGBA")
    draw = ImageDraw.Draw(img_rgba)
    
    # 绘制阴影（黑色，半透明），使文字更清晰
    shadow_color = (0, 0, 0, 100)
    draw.text((x + 2, y + 2), watermark_text, font=font, fill=shadow_color)
    
    # 绘制主文字（白色，半透明）
    watermark_color = (255, 255, 255, 150)
    draw.text((x, y), watermark_text, font=font, fill=watermark_color)
    
    # 转换回 RGB 模式（视频帧不需要透明度通道）
    img_rgb = img_rgba.convert("RGB")
    return np.array(img_rgb)

# ==================== 视频生成主函数 ====================
def generate_video(
    img_path, pos_prompt, neg_prompt, base_model, lora_choice,
    resolution, frames, seed, watermark_text="AI ART XIHUYISHENG AMD RADEON"
):
    """
    生成视频的主函数，使用 yield 返回中间状态（流式输出）
    
    参数:
        img_path: 输入图片路径
        pos_prompt: 正向提示词（描述想要生成的内容）
        neg_prompt: 负向提示词（描述不想要的内容）
        base_model: 主模型 ID
        lora_choice: LoRA 选择
        resolution: 分辨率（如 "1280x720", "832x480", "768x432"）
        frames: 总帧数（81或121）
        seed: 随机种子（-1 表示随机）
        watermark_text: 水印文字（留空则不添加）
    
    返回:
        使用 yield 生成元组 (视频路径, 状态文本)
    """
    # 记录总开始时间
    total_start_time = time.time()
    # 声明全局变量（首次推理标记）
    global FIRST_INFERENCE_DONE
    # 清空日志缓冲区，开始记录本次生成的日志
    LOG_BUFFER.clear()

    # 检查是否上传了图片
    if not img_path:
        return None, "❌ 错误：请先上传一张参考图片！"

    logger.info(f"✅ 模型参数: {base_model} | {lora_choice}")
    yield None, "\n".join(LOG_BUFFER)  # 立即输出到界面运行日志

    # 如果 seed 为 -1，生成一个随机种子
    if seed == -1:
        seed = random.randint(0, 2**32 - 1)
    # 创建随机数生成器（用于控制生成结果的可重复性）
    generator = torch.Generator(device="cpu").manual_seed(int(seed))
    logger.info(f"✅ 随机种子: {seed}")
    yield None, "\n".join(LOG_BUFFER)  # 立即输出到界面运行日志

    # 解析分辨率
    width, height = map(int, resolution.split("x"))
    # 固定参数：帧率 16，推理步数 4，引导系数 1
    fps_val = 16
    steps = 4
    cfg = 1
    
    logger.info(f"✅ 分辨率参数: {width}x{height} | {frames}帧 | {steps}步 | CFG={cfg}")
    logger.info(f"✅ 水印文字: {watermark_text}")
    logger.info(f"✅ 正向提示词: {pos_prompt}")
    yield None, "\n".join(LOG_BUFFER)  # 立即输出到界面运行日志

    #提示首次加载需要5分钟等
    logger.info(f"🔄 模型加载中...")
    yield None, "\n".join(LOG_BUFFER)

    try:
        # 阶段1：加载模型
        model_start = time.time()
        pipe = load_wan_pipeline(base_model, lora_choice)
        model_time = time.time() - model_start
        logger.info(f"✅ 模型加载完成，耗时: {model_time:.2f}秒")
        logger.info(f"🎥 准备参数: {width}x{height} | {frames}帧 | {steps}步 | CFG={cfg}")
        yield None, "\n".join(LOG_BUFFER)

        # 阶段2：处理输入图片（打开并转换为 RGB，然后居中裁剪适配目标分辨率）
        input_image = Image.open(img_path).convert("RGB")
        input_image = center_crop_resize(input_image, width, height)
        logger.info(f"✅ 输入图片处理完成，分辨率: {width}x{height}")
        yield None, "\n".join(LOG_BUFFER)


        logger.info(f"✅ GPU 推理中...")
        yield None, "\n".join(LOG_BUFFER)

        # 首次推理需初始化 CUDA 内核等，耗时较长（约5分钟），提醒用户耐心等待
        if not FIRST_INFERENCE_DONE:
            logger.info("⏳ 首次推理正在初始化管道，请耐心等待约5分钟...")
            yield None, "\n".join(LOG_BUFFER)

        # 阶段3：GPU 推理生成视频帧
        infer_start = time.time()
        output = pipe(
            image=input_image,           # 输入图片
            prompt=pos_prompt,           # 正向提示词
            negative_prompt=neg_prompt,  # 负向提示词
            height=height,               # 视频高度
            width=width,                 # 视频宽度
            num_frames=int(frames),      # 总帧数
            guidance_scale=float(cfg),   # 引导系数（值越高，提示词约束力越强）
            num_inference_steps=int(steps),  # 推理步数（步数越多，效果越好但越慢）
            generator=generator          # 随机数生成器
        ).frames[0]  # 获取生成的视频帧列表
        infer_time = time.time() - infer_start
        # 标记首次推理已完成，后续推理不再需要初始化等待
        FIRST_INFERENCE_DONE = True
        logger.info(f"✅ GPU 推理完成，耗时: {infer_time:.2f}秒")
        logger.info("📤 正在导出视频...")
        yield None, "\n".join(LOG_BUFFER)

        # 阶段4：导出视频文件
        # 生成唯一文件名（时间戳 + 随机字符串）
        timestamp = int(time.time())
        unique_id = uuid.uuid4().hex[:8]
        out_path = f"/mnt/workspace/output_{timestamp}_{unique_id}.mp4"

        writer_start = time.time()
        # 使用 imageio 创建视频写入器
        writer = imageio.get_writer(
            out_path,
            fps=int(fps_val),            # 帧率
            format='FFMPEG',             # 使用 FFmpeg 编码
            mode='I',                    # 帧模式
            codec='libx264',             # H.264 编码（兼容性好）
            output_params=['-preset', 'fast', '-crf', '23']  # 编码参数：快速预设，质量适中
        )

        # 遍历每一帧，处理后写入视频
        for frame in output:
            # 如果是 PIL Image，转换为 numpy 数组
            if isinstance(frame, Image.Image):
                frame = np.array(frame)
            # 确保像素值在 0-255 范围内（uint8 格式）
            if frame.max() <= 1.0:
                frame = (frame * 255).astype(np.uint8)
            else:
                frame = frame.astype(np.uint8)
            # 如果水印文字不为空，添加水印
            if watermark_text.strip():
                frame = add_watermark(frame, watermark_text)
            # 写入帧
            writer.append_data(frame)

        # 关闭写入器（完成视频导出）
        writer.close()
        writer_time = time.time() - writer_start

        # 清理显存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # 计算总耗时并输出结果
        total_time = time.time() - total_start_time
        logger.info(f"✅ 视频生成完毕！文件: {out_path} | 总耗时: {total_time:.2f}秒")
        logger.info(f"⏱️ 模型加载: {model_time:.2f}秒 | GPU推理: {infer_time:.2f}秒 | 视频导出: {writer_time:.2f}秒")
        yield out_path, "\n".join(LOG_BUFFER)

    # 异常处理：捕获并报告错误
    except Exception as e:
        total_time = time.time() - total_start_time
        logger.info(f"❌ 运行报错：{str(e)} | 已耗时: {total_time:.2f}秒")
        yield None, "\n".join(LOG_BUFFER)

# ==================== 显卡状态监视函数 ====================
def get_gpu_status():
    """
    获取显卡实时状态（显存占用、利用率、温度）
    以 torch.cuda 为主获取显存和利用率，rocm-smi 补充温度/频率
    每 2 秒由 Gradio 自动调用刷新
    """
    import subprocess, json

    if not torch.cuda.is_available():
        return "⚠️ 未检测到 GPU"

    lines = []
    for i in range(torch.cuda.device_count()):
        name = torch.cuda.get_device_name(i)
        if not name or name.strip() == "":
            name = "AMD GPU"
        lines.append(f"🎮 GPU {i}: {name}")

        # ---- 显存：使用 mem_get_info 获取系统级真实占用 ----
        try:
            free, total = torch.cuda.mem_get_info(i)
            used = total - free
            used_gb = used / (1024 ** 3)
            total_gb = total / (1024 ** 3)
            percent = (used / total * 100) if total > 0 else 0
            # 构建文字进度条
            bar_len = 20
            filled = int(percent / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"💾 显存: {used_gb:.1f}GB / {total_gb:.1f}GB ({percent:.1f}%) [{bar}]")
        except Exception:
            lines.append("💾 显存: 不可用")

        # ---- 利用率：torch.cuda.utilization 在 ROCm 下可能不可用 ----
        try:
            util = torch.cuda.utilization(i)
            lines.append(f"📊 利用率: {util:.1f}%")
        except Exception:
            lines.append("📊 利用率: 不可用")

        # ---- 温度/频率：尝试 rocm-smi 补充 ----
        try:
            result = subprocess.run(
                ["rocm-smi", "--showtemp", "--showclocks", "--json"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                card_key = f"card{i}" if f"card{i}" in data else "card0"
                if card_key in data and isinstance(data[card_key], dict):
                    card = data[card_key]
                    temp = card.get("Temperature (Sensor edge) (C)", "N/A")
                    sclk = card.get("GPU SCLK clock speed:", "N/A")
                    mclk = card.get("GPU MCLK clock speed:", "N/A")
                    lines.append(f"🌡️ 温度: {temp}°C  |  ⚡ 核心: {sclk}  |  显存: {mclk}")
        except Exception:
            pass

        lines.append("")  # 空行分隔多卡

    return "\n".join(lines).strip()

# ==================== Gradio UI 界面 ====================
# 创建 Gradio 界面（Gradio 6 中 theme 已移至 launch()，使用 Soft 主题，indigo 为主色调）
with gr.Blocks() as demo:
    # 页面标题和说明（渐变色标题 + 彩色特性标签）
    gr.HTML("""
    <div style="text-align: center; padding: 16px 0 6px;">
        <h1 style="margin: 0; font-size: 2rem; font-weight: 800;
             background: linear-gradient(90deg, #6366f1, #a855f7, #ec4899);
             -webkit-background-clip: text; background-clip: text; color: transparent;">
            🎬 Wan2.2-14B-I2V 图生视频
        </h1>
        <div style="margin-top: 6px; font-size: 1.05rem; color: #64748b; font-weight: 600;">
            AMD MI308X · 192G 显存 · 单卡专用
        </div>
        <div style="margin-top: 12px; display: flex; gap: 8px; justify-content: center; flex-wrap: wrap;">
            <span style="background:#ecfdf5;color:#059669;border:1px solid #a7f3d0;border-radius:999px;padding:3px 12px;font-size:0.85rem;font-weight:600;">⚡ ROCm 7.2 加速</span>
            <span style="background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;border-radius:999px;padding:3px 12px;font-size:0.85rem;font-weight:600;">🔢 float16 精度</span>
            <span style="background:#fff7ed;color:#ea580c;border:1px solid #fed7aa;border-radius:999px;padding:3px 12px;font-size:0.85rem;font-weight:600;">🚀 xFormers 注意力优化</span>
            <span style="background:#fdf2f8;color:#db2777;border:1px solid #fbcfe8;border-radius:999px;padding:3px 12px;font-size:0.85rem;font-weight:600;">⚡ LoRA 4 步极速推理</span>
            <span style="background:#f5f3ff;color:#7c3aed;border:1px solid #ddd6fe;border-radius:999px;padding:3px 12px;font-size:0.85rem;font-weight:600;">🖥️ 本地单卡全量 GPU 推理</span>
        </div>
    </div>
    """)

    # ⚠️ 免责声明（醒目位置）
    gr.Markdown("""
    **⚠️ 免责声明**：本工具仅供学习研究使用。用户需遵守法律法规及平台规范，严禁生成违法违规、有害信息、价值观导向不正、虚假信息或侵权内容。用户对生成内容负全部责任，开发者不对用户生成内容承担法律责任。
    """)
    
    # 1. 参考图片（共享）
    with gr.Row():
        input_image = gr.Image(type="filepath", label="🖼️ 上传参考图片")
        with gr.Column():
            load_example_btn1 = gr.Button("📷 使用示例图片1", variant="secondary", size="sm")
            load_example_btn2 = gr.Button("📷 使用示例图片2", variant="secondary", size="sm")
            load_example_btn3 = gr.Button("📷 使用示例图片3", variant="secondary", size="sm")
    
    def load_example_image(img_name):
        example_path = os.path.join(os.path.dirname(__file__), "images", img_name)
        if os.path.exists(example_path):
            return example_path
        return None
    
    load_example_btn1.click(fn=lambda: load_example_image("t1.jpg"), outputs=[input_image])
    load_example_btn2.click(fn=lambda: load_example_image("t2.jpg"), outputs=[input_image])
    load_example_btn3.click(fn=lambda: load_example_image("t3.jpg"), outputs=[input_image])
    
    # 2. 反向提示词（共享）
    neg_prompt = gr.Textbox(
        label="负向提示词",
        value="暴力，变形，扭曲，崩坏，模糊，水印，鬼影, 扭曲的脸,多余肢体, 多余角色",
        lines=2
    )
    
    # 3. 运行日志（共享）
    status_text = gr.Textbox(label="💻 运行日志", interactive=False, lines=10)
    
    # 4. 视频生成区域（单视频模式）
    prompt_input = gr.Textbox(
        label="正向提示词",
        value="门后走来一只中华田园犬，又转身原路返回，在门后消失。",
        lines=3
    )
    with gr.Row():
        generate_btn = gr.Button("🎬 生成视频", variant="primary", size="lg")
    output_video = gr.Video(label="✨ 生成视频")
    
    # 7. 其它设置（折叠面板，默认收起）
    with gr.Accordion("⚙️ 高级设置", open=False):
        # 水印文字输入框
        watermark_text = gr.Textbox(
            label="🏷️ 水印文字",
            value="AI ART XIHUYISHENG AMD RADEON",
            lines=1,
            placeholder="输入水印文字，留空则不添加水印"
        )
        
        # 核心模型与 LoRA 设置
        with gr.Row():
            base_model = gr.Dropdown(
                choices=["Wan-AI/Wan2.2-I2V-A14B-Diffusers"],
                value="Wan-AI/Wan2.2-I2V-A14B-Diffusers",
                label="🌟 主模型"
            )
            lora_model = gr.Dropdown(
                choices=["无 (None)", "LightX2V (4步极速生成 LoRA)"],
                value="LightX2V (4步极速生成 LoRA)",
                label="🧩 选择附加 LoRA"
            )
        
        # 生成参数设置
        with gr.Row():
            resolution = gr.Dropdown(
                choices=["1280x720", "832x480", "768x432"],
                value="768x432",
                label="📐 分辨率"
            )
            frames = gr.Dropdown(
                choices=["81", "121"],
                value="81",
                label="🎞️ 总帧数"
            )
            seed = gr.Number(value=-1, label="🎲 随机数种子 (-1为随机)", precision=0)
    
    # 底部说明
    gr.Markdown("""
    **⚡ 配置**：LightX2V 蒸馏 LoRA + xformers 加速，4步推理即可输出高质量视频（可选分辨率 1280x720/832x480/768x432，可选81/121帧，固定16FPS）。  
    **🏷️ 水印设置**：水印文字留空则不添加水印。
    """)

    # 显卡状态监视（底部，每 2 秒自动刷新）
    gpu_monitor = gr.Textbox(
        label="🖥️ 显卡状态监视（实时）",
        interactive=False,
        lines=3
    )

    # 绑定生成按钮的点击事件
    generate_btn.click(
        fn=generate_video,
        inputs=[input_image, prompt_input, neg_prompt, base_model, lora_model, resolution, frames, seed, watermark_text],
        outputs=[output_video, status_text]
    )

    # 显卡监视自动刷新（每 2 秒，Gradio 6 移除了 every 参数，改用 gr.Timer）
    gpu_timer = gr.Timer(2)
    gpu_timer.tick(fn=get_gpu_status, outputs=[gpu_monitor])


# ==================== 程序入口 ====================
if __name__ == "__main__":
    # 打印 ROCm 环境信息（启动时检测 GPU 是否可用）
    print_rocm_info()
    # 预下载模型（程序启动时执行）
    preload_all_models()
    # 启动 Gradio 服务（Gradio 6 默认开启 MCP 服务，端点: /gradio_api/mcp/sse）
    demo.queue().launch(
        theme=gr.themes.Soft(primary_hue="indigo"),  # Gradio 6 中主题需在 launch() 传入
        server_name="0.0.0.0",        # 允许外部访问
        server_port=7860,              # 端口号
        share=False,                   # 不生成公网链接
        allowed_paths=["/mnt/workspace"]  # 允许访问的目录
    )
