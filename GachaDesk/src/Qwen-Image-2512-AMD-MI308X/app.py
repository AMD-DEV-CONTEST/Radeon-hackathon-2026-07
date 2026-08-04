# 导入操作系统模块，用于文件路径和环境变量操作
import os

# ==================== 路径配置 ====================
# 设置模型缓存路径到 /mnt/workspace，避免默认路径空间不足
# HF_HOME: HuggingFace 模型下载缓存目录
os.environ["HF_HOME"] = "/mnt/workspace/.cache/huggingface"
# MODELSCOPE_CACHE: ModelScope 模型下载缓存目录
os.environ["MODELSCOPE_CACHE"] = "/mnt/workspace/.cache/modelscope"
# GRADIO_TEMP_DIR: Gradio 临时文件目录
os.environ["GRADIO_TEMP_DIR"] = "/mnt/workspace/.cache/gradio"

# 自动创建上述目录，如果目录已存在则不会报错
for path in [
    "/mnt/workspace/.cache/huggingface",
    "/mnt/workspace/.cache/modelscope",
    "/mnt/workspace/.cache/gradio",
    "/mnt/workspace/outputs"
]:
    os.makedirs(path, exist_ok=True)

# ==================== 第三方库导入 ====================
# gradio: 用于构建网页交互界面
import gradio as gr
# torch: PyTorch 深度学习框架
import torch
# random: 用于生成随机数（如随机种子）
import random
# time: 用于计时（统计各阶段耗时）
import time
# uuid: 用于生成唯一文件名
import uuid
# sys: 用于 stdout 重定向捕获 print 输出
import sys
# io: 用于 StringIO 内存流
from io import StringIO
# DiffusionPipeline: ModelScope 扩散模型推理管道
from modelscope import DiffusionPipeline


# ==================== Print 捕获工具 ====================
class PrintCapture:
    """捕获 print 输出到字符串，同时保持终端显示"""
    def __enter__(self):
        self._buf = StringIO()
        self._old = sys.stdout
        sys.stdout = self._buf
        return self

    def __exit__(self, *args):
        sys.stdout = self._old

    def get(self):
        """获取已捕获的文本并清空缓冲区"""
        val = self._buf.getvalue()
        # 同时输出到终端，保持终端日志完整
        self._old.write(val)
        self._old.flush()
        self._buf = StringIO()  # 重置缓冲区
        return val.rstrip()

    def flush(self):
        """清空缓冲区"""
        self._buf = StringIO()

# ==================== 全局变量 ====================
# PIPELINE: 保存加载好的模型管道，避免重复加载
PIPELINE = None
# MODEL_LOADED: 标记模型是否已加载到显存
MODEL_LOADED = False
# MODEL_ID: Qwen-Image 模型标识，全局统一使用
MODEL_ID = "Qwen/Qwen-Image-2512"

# Qwen-Image 官方推荐分辨率比例
ASPECT_RATIOS = {
    "1:1 正方形 (1328×1328)": (1328, 1328),
    "16:9 横屏 (1664×928)": (1664, 928),
    "9:16 竖屏 (928×1664)": (928, 1664),
    "4:3 横屏 (1472×1140)": (1472, 1140),
    "3:4 竖屏 (1140×1472)": (1140, 1472),
    "3:2 横屏 (1584×1056)": (1584, 1056),
    "2:3 竖屏 (1056×1584)": (1056, 1584),
}

# 正向质量后缀（根据提示词语言自动追加）
POSITIVE_MAGIC = {
    "en": ", Ultra HD, 4K, cinematic composition.",
    "zh": ", 超清，4K，电影级构图.",
}

# 打印 ROCm 环境信息
def print_rocm_info():
    """打印 AMD ROCm 环境信息，辅助调试"""
    print("-" * 60)
    print("🖥️  AMD MI308X ROCm 环境检测:")

    try:
        import torch
        if torch.cuda.is_available():
            # 原始探测输出（与 python -c 命令一致）
            print(f"   原始探测: is_available={torch.cuda.is_available()}, hip={torch.version.hip}, device={torch.cuda.get_device_name(0)}")
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
            print(f"   {gpu_info}")
        else:
            print("   ❌ 错误：未检测到 AMD GPU！")
            print("   请确认已正确安装 ROCm 驱动及 PyTorch ROCm 版本。")
            print("   如使用 conda 环境，请运行: conda install pytorch 等等")
            sys.exit(1)
    except Exception as e:
        print(f"   ❌ 错误：环境检测异常: {e}")
        sys.exit(f"❌ 环境检测异常: {e}\n请检查 PyTorch 及 ROCm 环境是否正确安装。")

    print("-" * 60)


def preload_all_models():
    """
    预下载模型到本地目录
    通过 modelscope download 下载到 ./models/Qwen-Image
    """
    # 先打印 ROCm 环境信息
    print_rocm_info()

    print("=" * 60)
    print("🔥 开始检查模型缓存...")

    model_id = MODEL_ID
    ms_cache = os.environ.get("MODELSCOPE_CACHE", "/mnt/workspace/.cache/modelscope")
    local_dir = os.path.join(ms_cache, f"models--{model_id.replace('/', '--')}")

    print(f"📦 模型名称: {model_id}")
    print(f"📂 缓存路径: {local_dir}")

    if os.path.exists(local_dir) and os.listdir(local_dir):
        print(f"✅ 模型已存在，跳过下载。")
        for root, dirs, files in os.walk(local_dir):
            level = root.replace(local_dir, "").count(os.sep)
            indent = "   " * level
            sub = "📁 " if level > 0 else "└── "
            print(f"{indent}{sub}{os.path.basename(root)}/")
            if level < 2:
                for f in files[:5]:
                    print(f"{indent}   📄 {f}")
            break
    else:
        print(f"📥 下载模型: {model_id}")
        import subprocess
        subprocess.run([
            "modelscope", "download",
            "--model", model_id,
            "--local_dir", local_dir
        ], check=True)
        print(f"✅ 下载完成，保存至: {local_dir}")

    print("✅ 所有模型已就绪！")
    print("=" * 60)

    # 再次打印 ROCm 环境信息
    print_rocm_info()


# ==================== 模型加载函数 ====================
def load_qwen_pipeline():
    """
    加载 Qwen-Image 文生图模型
    优先 HuggingFace，ModelScope 作为国内网络备用通道

    返回:
        pipe: 加载好的推理管道对象
    """
    # 使用全局变量，确保多次调用共享同一个模型实例
    global PIPELINE, MODEL_LOADED
    # gc: 垃圾回收模块，用于释放内存
    import gc

    # 如果模型已经加载过，直接返回，避免重复加载
    if MODEL_LOADED and PIPELINE is not None:
        print("✅ 管道已在内存中，跳过加载")
        return PIPELINE

    model_id = MODEL_ID
    ms_cache = os.environ.get("MODELSCOPE_CACHE", "/mnt/workspace/.cache/modelscope")
    local_dir = os.path.join(ms_cache, f"models--{model_id.replace('/', '--')}")
    print(f"🔄 加载模型: {model_id}")
    print(f"   📂 缓存路径: {local_dir}")
    # 强制垃圾回收，释放无用内存
    gc.collect()
    # 清空显存缓存（如果有 GPU）
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # ---------- PyTorch 后端优化配置 ----------
    if torch.cuda.is_available():
        rocm_available = hasattr(torch.version, "hip") and torch.version.hip is not None
        if rocm_available:
            # ROCm 优化：TF32 矩阵乘法加速（MI300+ 受益显著）
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.set_float32_matmul_precision("high")
            # ROCm Flash Attention 后端选择（优先 AOTriton）
            if hasattr(torch.backends.cuda, "preferred_rocm_fa_library"):
                try:
                    torch.backends.cuda.preferred_rocm_fa_library("aotriton")
                    print("⚡ ROCm Flash Attention 后端已设为: aotriton")
                except Exception:
                    print("ℹ️ AOTriton 不可用，使用默认 Flash Attention 后端")
   

    # 注意力实现选项:
    #   - "flash_attention_2": 显存高效且速度极快，ROCm 环境完美支持 (可选)
    #   - "sdpa":              PyTorch 原生优化注意力，兼容性极佳，可作为备选 (可选)
    #   - "eager":             传统手写注意力机制，速度最慢且显存占用高，仅用于调试 (可选)
    #   - "flash_attention_3": (不可选)
    attn_impl = "flash_attention_2"

    # ---------- 设备检测 ----------
    if torch.cuda.is_available():
        torch_dtype = torch.bfloat16    # 精度选项: torch.float16（更快/省显存）或 torch.bfloat16（更稳/ROCm 原生支持）
        device = "cuda"
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        backend = "ROCm" if rocm_available else "CUDA"
        print(f"⚡ GPU: {gpu_name} | 显存: {vram_gb:.1f}GB | 精度: bfloat16 | 后端: {backend}")
        if rocm_available:
            print(f"⚡ 注意力实现: {attn_impl} | 内存模式: 全量 GPU ({vram_gb:.0f}GB显存)")
        else:
            print(f"⚡ 注意力实现: {attn_impl} | 内存模式: 全量 GPU ({vram_gb:.0f}GB)")
    else:
        torch_dtype = torch.float32
        device = "cpu"
        print("⚠️ 未检测到 GPU，使用 CPU 推理（速度极慢）")

    # ---------- 加载模型（本地路径）----------
    print(f"   → 从本地加载 ...")
    
    pipe = DiffusionPipeline.from_pretrained(
        local_dir,
        torch_dtype=torch_dtype,
        attn_implementation=attn_impl,
        trust_remote_code=True,
    )
    pipe = pipe.to(device)
    print("✅ 模型加载成功！")

    # 更新全局变量，标记模型已加载
    PIPELINE = pipe
    MODEL_LOADED = True
    return pipe

# ==================== 图像生成主函数 ====================
def generate_image(
    prompt, neg_prompt, resolution, steps, cfg_scale, seed
):
    """
    生成图像的主函数，使用 yield 返回中间状态（流式输出）
    所有 print 日志均同时显示在 Gradio 状态栏

    参数:
        prompt: 正向提示词（描述想要生成的内容）
        neg_prompt: 负向提示词（描述不想要的内容）
        resolution: 分辨率预设键名（如 "1:1 正方形 (1328×1328)"）
        steps: 推理步数
        cfg_scale: 引导系数（true_cfg_scale）
        seed: 随机种子（-1 表示随机）

    返回:
        使用 yield 生成元组 (图像路径或 None, 状态文本)
    """
    # 记录总开始时间
    total_start_time = time.time()
    # 用于累积完整日志
    full_log = ""

    # 检查是否输入了提示词
    if not prompt or not prompt.strip():
        return None, "❌ 错误：请输入正向提示词！"

    # 解析分辨率
    width, height = ASPECT_RATIOS[resolution]

    # 如果 seed 为 -1，生成一个随机种子
    if seed == -1 or seed is None:
        seed = random.randint(0, 2**32 - 1)
    seed = int(seed)

    # 输出准备状态
    msg = f"📐 分辨率: {width}×{height} ({resolution})\n🎲 Seed: {seed}\n⚙️ 步数: {steps} | CFG: {cfg_scale}\n🔄 准备生成(准备约1分钟)..."
    print(f"   {msg}")
    full_log += msg + "\n"
    yield None, msg

    try:
        # ---------- 阶段1：加载模型（捕获 print）----------
        with PrintCapture() as cap:
            model_start = time.time()
            pipe = load_qwen_pipeline()
            model_time = time.time() - model_start

        # 模型加载日志
        load_log = cap.get()
        if load_log:
            full_log += load_log + "\n"
            yield None, full_log

        msg = f"✅ 模型加载完成，耗时: {model_time:.2f}秒"
        print(f"   {msg}")

        full_log += msg + "\n"
        yield None, full_log

        # ---------- 阶段2：GPU 推理 ----------
        # 自动检测提示词语言，追加质量后缀
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in prompt)
        quality_suffix = POSITIVE_MAGIC["zh"] if has_chinese else POSITIVE_MAGIC["en"]
        enhanced_prompt = prompt + quality_suffix
        print(f"   {enhanced_prompt}")
        
        # 创建随机数生成器（GPU 上更快）
        gen_device = "cuda" if torch.cuda.is_available() else "cpu"
        generator = torch.Generator(device=gen_device).manual_seed(seed)
        print(f"   {generator}")

        infer_start = time.time()
        print(f"   {infer_start}")
        
        # ---------- 阶段3：推理 ----------
        # 构建生成参数
        gen_kwargs = {
            "prompt": enhanced_prompt,
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "true_cfg_scale": cfg_scale,
            "generator": generator,
        }
        # 如果负向提示词不为空，加入到生成参数
        if neg_prompt and neg_prompt.strip():
            gen_kwargs["negative_prompt"] = neg_prompt

        msg = f"🎨  {width}×{height} | {steps}步 | CFG={cfg_scale}"
        msg+=f"\n推理约{steps*6/60:.2f}分钟。减步数→缩短时间 | 增步数→更贴近提示词。当前{steps}步"
        msg+=f"\n📐Qwen-Image 推理中..."

        full_log += msg + "\n"
        yield None, full_log
        print(f"   {msg}")

        output = pipe(**gen_kwargs)
        # ROCm 上需要显式同步，确保 GPU 操作完成
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        print(f"   pipe() 返回，开始 VAE 解码 ...")

        # VAE 解码（.images[0] 触发 latent→pixel），ROCm 上 float16 可能挂起
        try:
            image = output.images[0]
        except Exception:
            print(f"   ⚠️ VAE float16 解码失败，回退 float32 重试 ...")
            # 回退方案：手动以 float32 跑 VAE 解码
            pipe.vae.to(dtype=torch.float32)
            latent = output.images if hasattr(output, "images") else None
            if latent is not None and hasattr(latent, "shape"):
                image = pipe.vae.decode(latent.to(dtype=torch.float32)).sample
            else:
                raise

        infer_time = time.time() - infer_start
        msg = f"✅ 推理完成，耗时: {infer_time:.2f}秒\n📤 正在导出图像..."
        print(f"   {msg}")

        full_log += msg + "\n"
        yield None, full_log

        # ---------- 阶段3：保存图像文件 ----------
        timestamp = int(time.time())
        unique_id = uuid.uuid4().hex[:8]
        out_filename = f"qwen_image_{timestamp}_{unique_id}.png"
        out_path = os.path.join("/mnt/workspace/outputs", out_filename)

        # 同步后再保存，避免 ROCm 异步错误
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        image.save(out_path)
        print(f"   ✅ 已保存: {out_path}")

        # 计算总耗时
        total_time = time.time() - total_start_time

        print(f"✅ 图像生成完成！文件: {out_path} | 总耗时: {total_time:.2f}秒")
        msg = (
            f"✅ 图像生成完毕！\n"
            f"📁 文件名: {out_filename}\n"
            f"📐 分辨率: {width}×{height}\n"
            f"🎲 Seed: {seed}\n"
            f"⏱️ 模型加载: {model_time:.2f}秒\n"
            f"⏱️ GPU推理: {infer_time:.2f}秒\n"
            f"⏱️ **总耗时: {total_time:.2f}秒**"
        )
        full_log += msg
        yield out_path, full_log

    except Exception as e:
        import traceback
        total_time = time.time() - total_start_time
        error_detail = traceback.format_exc()
        print(f"❌ 生成报错:\n{error_detail}")
        err_msg = f"❌ 运行报错：{str(e)}\n⏱️ 已耗时: {total_time:.2f}秒"
        full_log += err_msg
        yield None, full_log


# ==================== Gradio UI 界面 ====================
# Gradio 6.0 起 theme 参数需传入 launch()，不传入 Blocks()
with gr.Blocks() as demo:
    # 页面标题和说明
    gr.Markdown(f"""
    # Qwen-Image 文生图 | AMD MI308X 专用
    **{MODEL_ID} | MMDiT | ROCm 加速 | bfloat16精度 | Flash Attention 2 加速 | 单卡本地GPU全量加载**
    """)

    # ⚠️ 免责声明
    gr.Markdown("""
    **⚠️ 免责声明**：本工具仅供学习研究使用。用户需遵守法律法规及平台规范，严禁生成违法违规、有害信息、价值观导向不正、虚假信息或侵权内容。用户对生成内容负全部责任，开发者不对用户生成内容承担法律责任。
    """)

    # 主布局：输入 | 输出
    with gr.Row():
        # 左侧：输入面板
        with gr.Column(scale=1):
            # 正向提示词
            prompt = gr.Textbox(
                label="📝 正向提示词（描述你想生成的图像）",
                placeholder="例如：一只可爱的橘猫坐在窗台上，阳光洒在它的毛发上，照片级真实感...",
                lines=5,
                value=""
            )

            # ⭐ 快速示例
            gr.Markdown("**⭐ 快速示例（点击自动填充提示词）**")
            with gr.Row():
                btn_example1 = gr.Button("黎明·山间云海", size="sm", min_width=140)
                btn_example2 = gr.Button("高速·赛车飞驰", size="sm", min_width=140)
                btn_example3 = gr.Button("风景·雷峰夕照", size="sm", min_width=140)
                btn_example4 = gr.Button("街景·人物肖像", size="sm", min_width=140)
                btn_example5 = gr.Button("美食·甜品特写", size="sm", min_width=140)
                btn_example6 = gr.Button("科幻·星球大战", size="sm", min_width=140)
                btn_example7 = gr.Button("古风·仙侠意境", size="sm", min_width=140)
                btn_example8 = gr.Button("萌宠·橘猫日常", size="sm", min_width=140)

            # 负向提示词
            neg_prompt = gr.Textbox(
                label="🚫 负向提示词（描述你不想要的效果）",
                value="低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。",
                lines=3
            )

            # 生成按钮
            generate_btn = gr.Button("🎨 生成图像", variant="primary", size="lg")

            # 运行日志
            status_text = gr.Textbox(label="💻 运行日志", interactive=False, lines=8)

        # 右侧：输出面板
        with gr.Column(scale=1):
            output_image = gr.Image(label="✨ 生成结果", type="filepath")

            # 高级设置（折叠面板）
            with gr.Accordion("⚙️ 高级设置", open=False):
                resolution = gr.Dropdown(
                    choices=list(ASPECT_RATIOS.keys()),
                    value="16:9 横屏 (1664×928)",
                    label="📐 分辨率"
                )
                with gr.Row():
                    steps = gr.Slider(
                        minimum=10, maximum=100, value=25, step=1,
                        label="🔄 推理步数",
                        info="步数越多，质量越高但越慢（推荐 50 步）"
                    )
                    cfg_scale = gr.Slider(
                        minimum=1.0, maximum=10.0, value=4.0, step=0.5,
                        label="🎯 CFG 引导系数",
                        info="值越高越贴合提示词（推荐 4.0）"
                    )
                seed = gr.Number(
                    value=-1,
                    label="🎲 随机种子 (-1为随机)",
                    precision=0,
                    info="设置具体数值可复现相同结果"
                )

    # 底部说明
    gr.Markdown("""
    **⚡ 运行环境**：单卡 AMD MI308X 192GB显存 (ROCm) 本地推理，模型缓存至本地，无需调用远程 API。
    bfloat16 精度 | Flash Attention 2 加速 | 全量 GPU 显存推理。
    """)

    # 绑定生成按钮
    generate_btn.click(
        fn=generate_image,
        inputs=[prompt, neg_prompt, resolution, steps, cfg_scale, seed],
        outputs=[output_image, status_text]
    )

    # 绑定快速示例按钮（点击填充提示词）
    btn_example1.click(
        fn=lambda: "黎明时分，群山之巅云雾翻涌，第一缕阳光穿透云层洒向大地，天空呈现出由深蓝到橙红的渐变，远处山峦层叠如黛，近处松柏挂满晨露，宁静壮美，超写实摄影风格。",
        outputs=prompt
    )
    btn_example2.click(
        fn=lambda: "一辆红色法拉利跑车在傍晚的高速公路上疾驰，车轮扬起尘土，尾灯拖出两道流光，远处城市天际线剪影，动态模糊，速度感强，电影级光影。",
        outputs=prompt
    )
    btn_example3.click(
        fn=lambda: "杭州西湖畔，雷峰塔在夕阳余晖中巍然矗立，天空被染成绚丽的橙红色，湖面波光粼粼，倒映着塔影和晚霞，远处山峦叠翠，近处垂柳依依，中国风唯美风景，照片级画质。",
        outputs=prompt
    )
    btn_example4.click(
        fn=lambda: "亚州中国浙江的小镇雨后街头，一位撑着透明雨伞的女子回眸微笑，湿漉漉的石板路映着橱窗暖光，背景是古老的钟楼，浅景深人像，电影感调色，氛围感十足。",
        outputs=prompt
    )
    btn_example5.click(
        fn=lambda: "精致法式草莓慕斯蛋糕摆在复古木桌上，顶部点缀新鲜草莓与薄荷叶，表面淋有镜面果胶反光细腻，旁边放着一杯拉花拿铁，窗外柔和自然光斜射，背景虚化，美食摄影风格，色彩诱人，照片级真实感。",
        outputs=prompt
    )
    btn_example6.click(
        fn=lambda: "星球大战史诗级太空战场，一艘巨型歼星舰在深空中缓慢前行，舰体金属质感冷峻，舰桥灯光闪烁，远处数架X翼战机编队穿梭，红色与绿色激光弹交织划过黑暗太空，背景是一颗带光环的巨大行星与遥远星云，电影级光影，科幻巨制质感，超高清细节。",
        outputs=prompt
    )
    btn_example7.click(
        fn=lambda: "中国古风仙侠场景，一位白衣剑客立于悬崖之巅，长发随风飞扬，手持长剑指向苍穹，身后是飘渺云海与巍峨山峰，仙鹤盘旋飞舞，桃花瓣纷纷飘落，水墨渲染与写实光影结合，意境悠远，唯美大气。",
        outputs=prompt
    )
    btn_example8.click(
        fn=lambda: "一只胖乎乎的橘猫慵懒地趴在木质窗台上，午后的金色阳光斜照在它的毛发上泛起柔和光泽，它眯着眼睛享受阳光，窗外是模糊的绿色植物，浅景深，温馨治愈氛围，照片级真实感，毛发细节清晰。",
        outputs=prompt
    )


# ==================== 程序入口 ====================
if __name__ == "__main__":
    # 预下载模型（程序启动时执行）
    preload_all_models()
    # 启动 Gradio 服务
    # mcp_server=True: 同时作为 MCP 服务器，每个 API 端点对应一个 MCP 工具
    demo.queue().launch(
        server_name="0.0.0.0",      # 允许外部访问
        server_port=7860,            # 端口号
        share=False,                 # 不生成公网链接
        theme=gr.themes.Soft(primary_hue="indigo"),  # Gradio 6.0 起 theme 移到此位置
        allowed_paths=["/mnt/workspace"],  # 允许访问的目录
        mcp_server=True              # 启用 MCP 服务器模式
    )
