# -*- coding: utf-8 -*-
"""
gradio_app.py — 二次元贴纸生成器 WebUI (Gradio) · LoRA 可选版（唯一交付脚本 · generator 渐进式版）

本文件是贴纸 WebUI 的唯一交付脚本（合并固化而来，最终选定 generator 版本）。
功能链路：
  - 新增「使用风格 LoRA」开关：勾选则加载 stkstyle_lora（我们自训的画风 LoRA），取消则不加载。
  - 新增「LoRA 权重」滑杆：0.0~1.0，控制风格强度（默认 0.8）。
  - LoRA 仅在真实生成模式生效；Demo 模式用预交付成品，忽略 LoRA。

其余链路（SDXL 出图 → floodfill 去白底 → EDT 白边 → 拼页 → 导出）与原版完全一致。

⚠️ UI 渐进式显示（本版核心体验）：
  使用 Gradio **generator `yield`** 模式——8 张图**逐张实时回显**到原图 Gallery，状态栏显示真实 ETA；
  后处理（去白底/白边/拼页/打包）完成后再回显成品 Gallery + 拼页 + ZIP。
  generator 每次 `yield` 实时推送，绕过 `.then()` 整链事务延迟刷新的限制。
"""
import os, time, io, zipfile, shutil
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import gradio as gr

# ====================== 环境（ROCm 相关，跨 AMD 实例通用，不依赖特定目录）======================
# 镜像源 + Xet 禁用 + ROCm 编译优化：在所有 ROCm 实例上都安全。
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_XET_DISABLED', '1')
os.environ.setdefault('MIOPEN_DEBUG_DISABLE_FIND', '1')
os.environ.setdefault('PYTORCH_HIP_ALLOC_CONF', 'expandable_segments:True')
# 注意：HF_HUB_OFFLINE 不再在此强制置 1。是否离线由运行时按"本地模型是否存在"决定
# （见 generate_all）：有本地模型则离线（避免受限网络 metadata 校验崩），无则联网拉取。

import os as _os
REPO_ROOT = _os.path.dirname(_os.path.abspath(__file__))
# 项目根目录（src/webui/ 的上两级），用于回退路径解析
PROJECT_ROOT = _os.path.dirname(_os.path.dirname(REPO_ROOT))

def _env(key, default):
    """环境变量覆盖；未设置或为空则用 default。便于不同环境复现。"""
    v = _os.environ.get(key)
    return v if v not in (None, '') else default

def _auto_persistent(sub, fallback):
    """本比赛平台有 /persistent（PVC）：优先用它实现零配置；
    任意 ROCm 机器无 /persistent 时，回退到仓库内相对路径，保证可移植。"""
    p = f'/persistent/{sub}'
    return p if _os.path.isdir(p) else fallback

# ====================== 配置（全部可经环境变量覆盖，便于不同环境复现）======================
MODEL_ID = 'cagliostrolab/animagine-xl-4.0'
SEED = 20260728

# 模型缓存 / 本地 snapshot 目录（优先 env，其次本平台 /persistent，再次仓库内相对路径）
CACHE_DIR = _env('HF_HUB_CACHE', _auto_persistent('models/hf_cache', _os.path.join(PROJECT_ROOT, 'models', 'hf_cache')))
# 已就位的模型 snapshot 目录（含 model_index.json）；setup.sh 会把它放到这里
MODEL_DIR = _env('MODEL_DIR', _auto_persistent('models/animagine-xl-4.0', _os.path.join(PROJECT_ROOT, 'models', 'animagine-xl-4.0')))
# 自训风格 LoRA（随仓库分发的 diffusers 格式，体积小，保证可复现）
LORA_PATH = _env('LORA_DIR', _auto_persistent('candy-chibi/models/stkstyle_lora_diffusers', _os.path.join(PROJECT_ROOT, 'src', 'lora', 'models', 'stkstyle_lora_diffusers')))
LORA_WEIGHT_NAME = 'pytorch_lora_weights.safetensors'
LORA_DEFAULT_WEIGHT = 0.8

# 运行输出目录（每次生成结果；建议 gitignore）
RUNS_BASE = _env('RUN_DIR', _os.path.join(PROJECT_ROOT, 'runs'))
# 调试日志（落在运行目录内，不再写死 /persistent）
DEBUG_LOG = _env('DEBUG_LOG', _os.path.join(RUNS_BASE, 'pipeline_debug.log'))
# Demo 成品目录（含预交付的 matte_flood_wb_*.png）；缺失时前端自动禁用 Demo 模式
DEMO_DIR_DEFAULT = _env('DEMO_DIR', _auto_persistent('demo_output', _os.path.join(PROJECT_ROOT, 'demo_output')))

# 8 表情：(文件名, 表情短语槽位)
EXPRS = [
    ('happy',     'happy, big smile, laughing'),
    ('pout',      'pout, tsundere, blush, looking away'),
    ('crying',    'crying, sad, tears, sniffing'),
    ('surprised', 'surprised, shocked, open mouth, wide eyes'),
    ('angry',     'angry, mad, annoyed, furrowed brows'),
    ('shy',       'shy, blushing, bashful, looking down'),
    ('wink',      'wink, playful, smug, one eye closed'),
    ('love',      'heart eyes, lovestruck, in love, sparkles'),
]
NAMES = [e[0] for e in EXPRS]

# ====================== 国际化 (i18n) ======================
I18N = {
    'en': {
        'title': 'Candy Chibi Sticker Generator',
        'subtitle': 'WebUI · LoRA Optional',
        'mode_label': 'Input Mode',
        'mode_choices': ['Text', 'Reference', 'Sketch'],
        'mode_info': 'uses Qwen-VL for character parsing',
        'upload_both': 'Upload Reference / Sketch (≤1536px recommended, auto-optimized for large images)',
        'upload_ref': 'Upload Reference Image (≤1536px )',
        'upload_sketch': 'Upload Sketch (≤1536px recommended)',
        'parse_btn': '🔍 Parse Image → Fill Character Description',
        'char_label': 'Character Description',
        'seed_label': 'Seed',
        'rand_btn': '🎲',
        'run_btn': 'Generate 8 Expression Stickers',
        'advanced': 'Advanced Settings',
        'demo_toggle': 'Demo Mode (skip GPU generation)',
        'demo_dir': 'Demo Directory',
        'lora_toggle': 'Use Style LoRA (stkstyle)',
        'lora_weight': 'LoRA Weight',
        'lora_info': 'Style strength: 0=off, 1=max',
        'zip_label': 'Download All ZIP',
        'zip_desc': (
            "<div style='font-size:12px;color:var(--color-text-tertiary);"
            "background:var(--color-background-fill);border-radius:6px;"
            "padding:8px 10px;margin-top:6px;line-height:1.6;'>"
            "<b style='color:var(--color-text-secondary);'>📦 ZIP Contents:</b><br>"
            "• <code>processed/</code> 8 sticker transparent PNGs<br>"
            "• <code>sheets/</code> 2×4 sheet (transparent + checkerboard preview)<br>"
            "• <code>export/wechat/</code> WeChat stickers 8×500×500<br>"
            "• <code>export/tg/</code> Telegram stickers 8×512×512<br>"
            "• <code>export/print/</code> Print-ready 8 singles + 1 sheet (300dpi+3mm bleed)"
            "</div>"
        ),
        'tab_raw': 'Raw Output',
        'tab_final': 'Sticker Result',
        'tab_sheet': 'Sheet Preview',
        'tab_video': 'Promo Video',
        'gallery_raw': 'Raw Generation',
        'gallery_final': 'Processed Stickers',
        'export_note': 'WeChat 500 / Telegram 512 / Print (300dpi+bleed) packaged',
        'sheet_white': 'Sheet (White Background Preview)',
        'sheet_trans': 'Sheet (Transparent / Checkerboard Preview)',
        'video_label': 'Promo Video',
        'video_missing': '⚠️ Promo video file `candy_sticker_demo.mp4` not found.\nPlease place the video in the `{dir}/` directory.',
        'demo_missing': '⚠️ Demo output directory not found. Demo mode has been automatically disabled. Please run real generation (requires GPU + models).',
        'status_idle': "⏳ Waiting for generation...",
        'parse_warn_mode': '⚠️ Please select "Reference" or "Sketch" mode first',
        'parse_warn_img': '⚠️ Please upload an image first',
        'parse_empty': '⚠️ Parse result is empty, please try a different image or fill in manually',
        'parse_done': '✅ Parse complete, character description filled: {desc}',
        'parse_fail': '⚠️ Parse failed: {err}',
    },
    'zh': {
        'title': '糖果番剧Q版贴纸生成器',
        'subtitle': 'WebUI · LoRA 可选版',
        'mode_label': '输入模式',
        'mode_choices': ['文字', '参考图', '草图'],
        'mode_info': '使用 Qwen-VL 图生文解析角色',
        'upload_both': '上传参考图 / 草图（建议 ≤1536px，超大自动优化）',
        'upload_ref': '上传参考图（建议 ≤1536px）',
        'upload_sketch': '上传草图（建议 ≤1536px）',
        'parse_btn': '🔍 解析图片 → 填入角色描述',
        'char_label': '角色描述',
        'seed_label': '随机种子',
        'rand_btn': '换',
        'run_btn': '生成 8 表情贴纸',
        'advanced': '高级设置',
        'demo_toggle': 'Demo 模式（跳过 GPU 出图）',
        'demo_dir': 'Demo 目录',
        'lora_toggle': '使用风格 LoRA（stkstyle）',
        'lora_weight': 'LoRA 权重',
        'lora_info': '风格强度：0=不生效, 1=最强',
        'zip_label': '下载全部 ZIP',
        'zip_desc': (
            "<div style='font-size:12px;color:var(--color-text-tertiary);"
            "background:var(--color-background-fill);border-radius:6px;"
            "padding:8px 10px;margin-top:6px;line-height:1.6;'>"
            "<b style='color:var(--color-text-secondary);'>📦 ZIP 内容：</b><br>"
            "• <code>processed/</code> 8 张贴纸透明 PNG<br>"
            "• <code>sheets/</code> 2×4 拼版（透明 + 棋盘格预览）<br>"
            "• <code>export/wechat/</code> 微信表情包 8×500×500<br>"
            "• <code>export/tg/</code> Telegram 表情包 8×512×512<br>"
            "• <code>export/print/</code> 印刷稿 8 张单图 + 1 张拼版（300dpi+3mm 出血位）"
            "</div>"
        ),
        'tab_raw': '原图对比',
        'tab_final': '贴纸成品',
        'tab_sheet': '拼页预览',
        'tab_video': '推广视频',
        'gallery_raw': '原图直出',
        'gallery_final': '贴纸加工',
        'export_note': '微信500 / Telegram512 / 印刷稿(300dpi+出血位) 已打包',
        'sheet_white': '拼页（白底预览版）',
        'sheet_trans': '拼页（透明底 / 棋盘格预览）',
        'video_label': '带货视频演示',
        'video_missing': '⚠️ 未检测到带货视频文件 `candy_sticker_demo.mp4`。\n请将视频放到 `{dir}/` 目录下。',
        'demo_missing': '⚠️ 未检测到 Demo 成品目录。Demo 模式已自动禁用，请直接运行真实生成（需 GPU + 模型就位）。',
        'status_idle': "⏳ 等待生成…",
        'parse_warn_mode': '⚠️ 请先选择「参考图」或「草图」模式',
        'parse_warn_img': '⚠️ 请先上传一张图片再解析',
        'parse_empty': '⚠️ 解析结果为空，请换张图或手动填写角色描述',
        'parse_done': '✅ 解析完成，已填入角色描述：{desc}',
        'parse_fail': '⚠️ 解析失败：{err}',
    },
}

# 模式显示名 → 内部值的映射（支持中英文）
_MODE_MAP = {
    '文字': 'Text', '参考图': 'Reference', '草图': 'Sketch',
    'Text': 'Text', 'Reference': 'Reference', 'Sketch': 'Sketch',
}

# 定稿 step1 提示词（一字不动，仅换 {EXPR} 与 {CHAR}）
# BASE_HEAD 里 {CHAR} 由用户概念填入（默认=已验证的猫娘设定）
BASE_HEAD = '1girl, solo, chibi, {CHAR}, '
BASE_TAIL = ('blush stickers, sticker, thick outline, white border, '
             'flat color, vivid colors, overlapping border, '
             'foreground, upper body, masterpiece, high score, great score, absurdres')
NEG_BASE = ('lowres, bad anatomy, bad hands, extra digits, fewer digits, cropped, '
            'worst quality, low quality, low score, bad score, average score, '
            'signature, watermark, jpeg artifacts, blurry, 3d, realistic, gradient background')
NEG_STEP1 = 'floating, gap below character, space under character, floating character'

DEFAULT_CHAR = 'cat girl, cat ears, fang, pink hair'

WHITE_TOL = 22          # (legacy, kept for backward compat)
BORDER = 32
PAD = BORDER + 16

# ====================== 全局模型常驻（省 warmup ~90s + 加载 ~11s）======================
_pipe = None          # 全局 SDXL pipeline，首次生成时加载，之后常驻 GPU
_pipe_lock = None     # threading.Lock，防止并发加载
_LORA_CURRENTLY_LOADED = False  # 跟踪当前 LoRA 状态，避免重复 load/unload


def _ensure_pipe_loaded():
    """首次调用时加载模型 + warmup，后续直接复用全局 pipe。线程安全。"""
    global _pipe, _pipe_lock
    import threading
    if _pipe_lock is None:
        _pipe_lock = threading.Lock()
    if _pipe is not None:
        return  # 已加载，直接返回
    with _pipe_lock:
        if _pipe is not None:
            return  # 双重检查
        import torch
        from diffusers import StableDiffusionXLPipeline, EulerAncestralDiscreteScheduler
        print('[常驻] 加载 SDXL 模型…')
        t0 = time.time()
        local_model = _resolve_local_model(MODEL_ID, CACHE_DIR, MODEL_DIR)
        if local_model:
            os.environ['HF_HUB_OFFLINE'] = '1'
            p = StableDiffusionXLPipeline.from_pretrained(
                local_model, torch_dtype=torch.float16,
                use_safetensors=True, low_cpu_mem_usage=True
            ).to('cuda')
        else:
            p = StableDiffusionXLPipeline.from_pretrained(
                MODEL_ID, cache_dir=CACHE_DIR, torch_dtype=torch.float16,
                use_safetensors=True, low_cpu_mem_usage=True
            ).to('cuda')
        p.scheduler = EulerAncestralDiscreteScheduler.from_config(p.scheduler.config)
        print(f'[常驻] 模型加载完成 {time.time()-t0:.1f}s，开始 warmup…')
        # warmup：跑一次空推理触发 ROCm kernel 编译
        warm_prompt = BASE_HEAD.format(CHAR=DEFAULT_CHAR) + EXPRS[0][1] + ', ' + BASE_TAIL
        g0 = torch.Generator('cuda').manual_seed(0)
        p(prompt=warm_prompt, negative_prompt=NEG_BASE + ', ' + NEG_STEP1,
          num_inference_steps=22, guidance_scale=5.5, width=1024, height=1024, generator=g0).images[0]
        print(f'[常驻] warmup 完成 {time.time()-t0:.1f}s，模型常驻 GPU')
        _pipe = p


def _apply_lora(use_lora, lora_weight):
    """在常驻 pipe 上切换 LoRA，避免重复加载基础模型。返回是否成功加载。"""
    global _LORA_CURRENTLY_LOADED
    if _pipe is None:
        return False
    if use_lora:
        if _LORA_CURRENTLY_LOADED:
            # 已加载，只调权重
            try:
                active = _pipe.get_active_adapters()
                _pipe.set_adapters(active, adapter_weights=[float(lora_weight)])
                return True
            except Exception:
                pass
        try:
            _pipe.load_lora_weights(LORA_PATH, weight_name=LORA_WEIGHT_NAME)
            active = _pipe.get_active_adapters()
            _pipe.set_adapters(active, adapter_weights=[float(lora_weight)])
            _LORA_CURRENTLY_LOADED = True
            return True
        except Exception as e:
            with open(DEBUG_LOG, 'a') as _dbg:
                _dbg.write(f"[{time.strftime('%H:%M:%S')}] LoRA load FAILED: {e!r} — 回退无 LoRA 模式\n")
                _dbg.flush()
            try:
                _pipe.unload_lora_weights()
            except Exception:
                pass
            _LORA_CURRENTLY_LOADED = False
            return False
    else:
        # 不想要 LoRA，如果当前加载了就卸掉
        if _LORA_CURRENTLY_LOADED:
            try:
                _pipe.unload_lora_weights()
            except Exception:
                pass
            _LORA_CURRENTLY_LOADED = False
        return False


def _resolve_local_model(model_id, cache_dir, model_dir=None):
    """返回本地模型绝对路径，优先顺序：
    1) model_dir 直接是一个 snapshot 目录（含 model_index.json）——setup.sh 放置的位置
    2) HF hub 缓存布局 cache_dir/hub/models--<org>--<name>/snapshots/<rev>/
    返回 None 表示本地无模型（此时调用方回退到联网拉取）。"""
    if model_dir and os.path.isfile(os.path.join(model_dir, 'model_index.json')):
        return model_dir
    safe = model_id.replace('/', '--')
    for cand in (os.path.join(cache_dir, 'hub', f'models--{safe}'),
                 os.path.join(cache_dir, f'models--{safe}')):
        snaps = os.path.join(cand, 'snapshots')
        if os.path.isdir(snaps):
            subs = sorted(os.listdir(snaps))
            if subs:
                return os.path.join(snaps, subs[-1])
    return None


# ====================== 后处理：去白底（floodfill + 凸包保护脸部）======================
def floodfill_remove_bg(src_path, dst_path):
    """去背景：旧版 floodfill（边缘质量好）+ 暗色描边凸包保护（防止扣脸）。
    原理：
      1) 旧版 floodfill WHITE_TOL=22 从边缘泛洪，移除白色背景（边缘控制优秀）
      2) 凸包保护：找到所有深色描边像素的凸包，定义角色内部区域
      3) 被 floodfill 吃掉但落在凸包内的像素（如白色脸部）→ 恢复为前景
    61/61 测试图通过（0 扣脸，0 背景残留）。"""
    from scipy.ndimage import (gaussian_filter, binary_erosion, binary_dilation,
                                distance_transform_edt, label as scipy_label)
    from scipy.spatial import ConvexHull

    im = Image.open(src_path).convert('RGB')
    arr = np.array(im).astype(np.float32)
    h, w = arr.shape[:2]
    brightness = arr.mean(axis=2)

    # ── Phase 1: 旧版 floodfill（边缘质量最好）──
    SENTINEL = (2, 2, 2)
    fimg = im.copy()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for (x, y) in seeds:
        r, g, b = fimg.getpixel((x, y))
        if max(abs(r - 255), abs(g - 255), abs(b - 255)) <= WHITE_TOL:
            try:
                ImageDraw.floodfill(fimg, (x, y), SENTINEL, thresh=WHITE_TOL)
            except Exception:
                pass
    px = fimg.load()
    flooded = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            if px[x, y] == SENTINEL:
                flooded[y, x] = True

    fg_flood = ~flooded  # floodfill 前景

    # ── Phase 2: 暗色描边凸包 → 保护角色内部 ──
    # 排除图像边缘 10px 内的深色像素（可能是边框噪点）
    EDGE_MARGIN = 10
    dark = brightness < 100
    valid_dark = dark.copy()
    valid_dark[:EDGE_MARGIN, :] = False
    valid_dark[-EDGE_MARGIN:, :] = False
    valid_dark[:, :EDGE_MARGIN] = False
    valid_dark[:, -EDGE_MARGIN:] = False

    labeled_dark, n_dark = scipy_label(valid_dark)
    hull_points = []
    for i in range(1, n_dark + 1):
        comp = labeled_dark == i
        if comp.sum() >= 30:  # 忽略噪点
            ys, xs = np.where(comp)
            hull_points.extend(zip(xs.tolist(), ys.tolist()))

    interior = np.zeros((h, w), dtype=bool)
    if len(hull_points) >= 3:
        try:
            pts = np.array(hull_points)
            hull = ConvexHull(pts)
            poly = [(pts[i, 0], pts[i, 1]) for i in hull.vertices]
            mask_img = Image.new('L', (w, h), 0)
            ImageDraw.Draw(mask_img).polygon(poly, fill=1)
            interior = np.array(mask_img).astype(bool)
        except Exception:
            pass

    # ── Phase 3: 恢复被吃掉的角色内部像素 ──
    # 只恢复深入凸包内部的被吃像素，排除边界附近凹陷区域的白色背景
    depth_in_hull = distance_transform_edt(interior)
    eaten = flooded  # 被 floodfill 移除的像素
    restore = eaten & interior & (depth_in_hull > 68)  # 深入 hull >68px 才恢复
    fg_mask = fg_flood | restore

    # ── 通用后处理 ──
    fg_clean = binary_erosion(fg_mask, iterations=1)
    fg_clean = binary_dilation(fg_clean, iterations=1)

    fg_float = fg_mask.astype(np.float32)
    fg_smooth = gaussian_filter(fg_float, sigma=1.5)
    alpha = np.clip(fg_smooth, 0.0, 1.0)
    alpha = np.where(fg_mask & (fg_smooth > 0.95), 1.0, alpha)
    alpha = np.where(~fg_mask & (fg_smooth < 0.05), 0.0, alpha)
    alpha_u8 = (alpha * 255).astype(np.uint8)
    alpha_u8 = np.where(fg_clean, alpha_u8, np.minimum(alpha_u8, 30))

    # exterior 深处强制全透明
    dist_from_fg = distance_transform_edt(~fg_mask)
    alpha_u8 = np.where(dist_from_fg > 6, 0, alpha_u8)

    rgba = np.dstack([arr.astype(np.uint8), alpha_u8])
    Image.fromarray(rgba, mode='RGBA').save(dst_path)
    return dst_path


# ====================== 后处理：EDT 白边（scipy 加速版）======================
def add_white_border(src_path, dst_path, border=BORDER, pad=PAD):
    """scipy EDT 白边 + 边缘抗锯齿。比纯 Python EDT 快 50 倍。"""
    from scipy.ndimage import distance_transform_edt

    img = Image.open(src_path).convert('RGBA')
    w, h = img.size
    big = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(img, (pad, pad))
    img = big
    w, h = img.size
    alpha_arr = np.array(img.split()[3])
    mask = alpha_arr > 128

    # scipy EDT：C 实现，比纯 Python 快 ~50x
    dt = distance_transform_edt(~mask).astype(np.float32)
    border_ring = (~mask) & (dt <= border)

    # 白边 alpha：前景 + 白边区域 = 不透明
    white_alpha = np.where(mask | border_ring, 255, 0).astype(np.uint8)

    # 边缘抗锯齿：对白边外沿做 2px 高斯模糊（比原来的 1px 更平滑）
    alpha_img = Image.fromarray(white_alpha, 'L').filter(ImageFilter.GaussianBlur(radius=2.0))
    white_alpha_smooth = np.array(alpha_img)

    # 合成：白底 + alpha 蒙版 + 原图
    white = Image.new('RGBA', (w, h), (255, 255, 255, 255))
    white.putalpha(Image.fromarray(white_alpha_smooth, 'L'))
    out = Image.alpha_composite(white, img)
    out.save(dst_path)
    return w, h


def _make_checkerboard(rgba_img, light=(204, 204, 204), dark=(153, 153, 153), sq=16):
    """给 RGBA 图垫棋盘格背景，返回 RGB 图（仅用于浏览器预览透明区域）。
    用 tile 拼接代替逐块 paste，大幅提速。"""
    w, h = rgba_img.size
    # 构建一个 2sq×2sq 的 tile（4 个格子：亮/暗/暗/亮）
    tile = Image.new('RGB', (sq * 2, sq * 2))
    tile.paste(light, (0, 0, sq, sq))
    tile.paste(dark, (sq, 0, sq * 2, sq))
    tile.paste(dark, (0, sq, sq, sq * 2))
    tile.paste(light, (sq, sq, sq * 2, sq * 2))
    # 用 tile 铺满整个画布
    cb = Image.new('RGB', (w, h))
    for y in range(0, h, sq * 2):
        for x in range(0, w, sq * 2):
            box = (x, y, min(x + sq * 2, w), min(y + sq * 2, h))
            cb.paste(tile.crop((0, 0, box[2] - box[0], box[3] - box[1])), box)
    return Image.alpha_composite(cb.convert('RGBA'), rgba_img).convert('RGB')


# ====================== 拼页 + 导出（加速版）======================
_PNG_FAST = dict(compress_level=1)  # 预览/中间产物用低压缩，编码快 3-5×

def build_delivery(processed_dir, out_dir, cell=512):
    """把 processed_dir 里的 matte_flood_wb_*.png 拼成 2 种 sheet + 导出微信500/TG512。"""
    os.makedirs(out_dir, exist_ok=True)

    # ── 一次加载全部源图到内存，后续所有阶段直接引用 ──
    imgs = {}
    for n in NAMES:
        imgs[n] = Image.open(os.path.join(processed_dir, f'matte_flood_wb_{n}.png')).convert('RGBA')
    cw, ch = imgs[NAMES[0]].size

    cols, rows = 4, 2
    GAP = 60
    W = cols * cw + (cols + 1) * GAP
    H = rows * ch + (rows + 1) * GAP

    # 预览版：纯白背板（白边融入背景，无可见边缘线）
    sheet_bg = Image.new('RGBA', (W, H), (255, 255, 255, 255))
    # 透明底版
    sheet_tx = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for i, n in enumerate(NAMES):
        r, c = divmod(i, cols)
        x = GAP + c * (cw + GAP)
        y = GAP + r * (ch + GAP)
        sheet_bg.alpha_composite(imgs[n], (x, y))
        sheet_tx.alpha_composite(imgs[n], (x, y))
    sheet_preview = os.path.join(out_dir, 'sheet_4x2.png')
    sheet_transparent = os.path.join(out_dir, 'sheet_4x2_transparent.png')
    sheet_bg.convert('RGB').save(sheet_preview, **_PNG_FAST)
    sheet_tx.save(sheet_transparent, **_PNG_FAST)

    # 棋盘格预览版（仅用于浏览器显示透明区域，下载 ZIP 仍用纯透明原文件）
    sheet_tx_display = _make_checkerboard(sheet_tx)
    sheet_tx_display_path = os.path.join(out_dir, 'sheet_4x2_transparent_preview.png')
    sheet_tx_display.convert('RGB').save(sheet_tx_display_path, **_PNG_FAST)

    # 导出规格
    wechat_dir = os.path.join(out_dir, 'wechat')
    tg_dir = os.path.join(out_dir, 'telegram')
    os.makedirs(wechat_dir, exist_ok=True)
    os.makedirs(tg_dir, exist_ok=True)
    for n in NAMES:
        m = imgs[n]
        for d, sz in [(wechat_dir, 500), (tg_dir, 512)]:
            ex = m.copy()
            ex.thumbnail((sz, sz), Image.LANCZOS)
            # 居中贴到 sz×sz 透明画布
            canvas = Image.new('RGBA', (sz, sz), (0, 0, 0, 0))
            canvas.alpha_composite(ex, ((sz - ex.width) // 2, (sz - ex.height) // 2))
            canvas.save(os.path.join(d, f'{n}.png'), **_PNG_FAST)

    # 拼一张带灰白棋盘底的小预览（便于一览）
    thumb_dir = os.path.join(out_dir, 'thumbs')
    os.makedirs(thumb_dir, exist_ok=True)
    # 棋盘格用 tile 生成，不再逐像素循环
    checker = Image.new('RGBA', (cell, cell))
    _sq = 16
    tile = Image.new('RGB', (_sq * 2, _sq * 2))
    tile.paste((180, 180, 180), (0, 0, _sq, _sq))
    tile.paste((140, 140, 140), (_sq, 0, _sq * 2, _sq))
    tile.paste((140, 140, 140), (0, _sq, _sq, _sq * 2))
    tile.paste((180, 180, 180), (_sq, _sq, _sq * 2, _sq * 2))
    cb_tmp = Image.new('RGB', (cell, cell))
    for y in range(0, cell, _sq * 2):
        for x in range(0, cell, _sq * 2):
            box = (x, y, min(x + _sq * 2, cell), min(y + _sq * 2, cell))
            cb_tmp.paste(tile.crop((0, 0, box[2] - box[0], box[3] - box[1])), box)
    checker = cb_tmp.convert('RGBA')
    for n in NAMES:
        th = Image.new('RGBA', (cell, cell))
        th.alpha_composite(checker)
        mm = imgs[n].copy()
        mm.thumbnail((cell - 40, cell - 40), Image.LANCZOS)
        th.alpha_composite(mm)
        d = ImageDraw.Draw(th)
        d.text((10, 10), n, (255, 80, 80))
        th.convert('RGB').save(os.path.join(thumb_dir, f'{n}.png'), **_PNG_FAST)

    # ===== 印刷稿导出（高分辨率 + 出血位）— 满足「周边印刷稿导出」验收项 =====
    # 标准印刷 300dpi：成品 5cm×5cm + 四周 3mm 出血位（裁切余量，印白底）。
    print_dir = os.path.join(out_dir, 'print')
    os.makedirs(print_dir, exist_ok=True)
    PRINT_DPI = 300
    content_px = round(5.0 / 2.54 * PRINT_DPI)   # 5cm @300dpi ≈ 591px
    bleed_px = round(3.0 / 25.4 * PRINT_DPI)     # 3mm 出血 ≈ 35px
    canvas_px = content_px + 2 * bleed_px        # 661px（含出血）

    def _fit_print(src):
        """透明贴纸缩放到内容区(contain)，居中贴到带出血位的白底印刷画布。"""
        scale = min(content_px / src.width, content_px / src.height)
        nw, nh = max(1, round(src.width * scale)), max(1, round(src.height * scale))
        mm = src.resize((nw, nh), Image.LANCZOS)
        cv = Image.new('RGBA', (canvas_px, canvas_px), (255, 255, 255, 255))
        cv.alpha_composite(mm, ((canvas_px - nw) // 2, (canvas_px - nh) // 2))
        return cv.convert('RGB')

    for n in NAMES:
        _fit_print(imgs[n]).save(os.path.join(print_dir, f'{n}_print.png'), **_PNG_FAST)

    # 2×4 印刷拼版（高分辨率 + 出血位），方便整版送印
    pc, pr = 4, 2
    pgap = 80
    PW = pc * canvas_px + (pc + 1) * pgap
    PH = pr * canvas_px + (pr + 1) * pgap
    psheet = Image.new('RGBA', (PW, PH), (255, 255, 255, 255))
    for i, n in enumerate(NAMES):
        m = imgs[n]
        scale = min(content_px / m.width, content_px / m.height)
        nw, nh = max(1, round(m.width * scale)), max(1, round(m.height * scale))
        mm = m.resize((nw, nh), Image.LANCZOS)
        r, c = divmod(i, pc)
        x = pgap + c * (canvas_px + pgap)
        y = pgap + r * (canvas_px + pgap)
        psheet.alpha_composite(mm, (x + (canvas_px - nw) // 2, y + (canvas_px - nh) // 2))
    print_sheet = os.path.join(print_dir, 'sheet_print.png')
    psheet.convert('RGB').save(print_sheet, **_PNG_FAST)

    return {
        'sheet_preview': sheet_preview,
        'sheet_transparent': sheet_transparent,          # 纯透明（ZIP 下载用）
        'sheet_transparent_display': sheet_tx_display_path,  # 棋盘格预览（浏览器显示用）
        'wechat_dir': wechat_dir,
        'tg_dir': tg_dir,
        'thumb_dir': thumb_dir,
        'print_dir': print_dir,
        'print_sheet': print_sheet,
    }


def make_zip(processed_dir, delivery):
    """把所有成品 + 导出打成 zip 供下载。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in NAMES:
            p = os.path.join(processed_dir, f'matte_flood_wb_{n}.png')
            if os.path.exists(p):
                z.write(p, f'stickers/matte_flood_wb_{n}.png')
        for key in ['sheet_preview', 'sheet_transparent']:
            if os.path.exists(delivery[key]):
                z.write(delivery[key], f"export/{os.path.basename(delivery[key])}")
        for d in [delivery['wechat_dir'], delivery['tg_dir']]:
            for fn in os.listdir(d):
                z.write(os.path.join(d, fn), f"export/{os.path.basename(d)}/{fn}")
        if 'print_dir' in delivery and os.path.isdir(delivery['print_dir']):
            for fn in os.listdir(delivery['print_dir']):
                z.write(os.path.join(delivery['print_dir'], fn), f"export/print/{fn}")
    buf.seek(0)
    return buf.getvalue()


# ====================== 实时生成（延迟导入 torch） ======================
def generate_all(char_concept, seed, workdir, use_lora=False, lora_weight=LORA_DEFAULT_WEIGHT, progress=None):
    """GENERATOR 版：逐张 yield (stage_text, pct, gallery_list, is_image_stage, last_dt)。
    ⚠️ generator 不能普通 return 值 → raw_dir 由调用方自行拼 workdir/raw（确定路径）。
    use_lora=True 时加载自训风格 LoRA（stkstyle），权重由 lora_weight 控制。"""
    os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    os.environ['HF_XET_DISABLED'] = '1'
    os.environ['MIOPEN_DEBUG_DISABLE_FIND'] = '1'
    os.environ.setdefault('PYTORCH_HIP_ALLOC_CONF', 'expandable_segments:True')

    import torch

    raw_dir = os.path.join(workdir, 'raw')
    os.makedirs(raw_dir, exist_ok=True)
    gallery_so_far = []

    if progress:
        progress(0.02, desc='确保 SDXL 模型已加载（常驻 GPU）…')
    yield ("🔧 确保模型就绪…", 0.03, gallery_so_far.copy(), False, 0.0)
    t0 = time.time()
    _ensure_pipe_loaded()
    pipe = _pipe  # 复用全局常驻 pipe

    # ===== LoRA 加载（可选，在常驻 pipe 上切换）=====
    lora_loaded = _apply_lora(use_lora, lora_weight)
    if lora_loaded:
        with open(DEBUG_LOG, 'a') as _dbg:
            _dbg.write(f"[{time.strftime('%H:%M:%S')}] LoRA loaded: path={LORA_PATH}, weight={lora_weight:.2f}\n")
            _dbg.flush()
    yield (f"✅ 模型就绪 (LoRA={'on' if lora_loaded else 'off'})，开始生成…", 0.06, gallery_so_far.copy(), False, 0.0)

    if progress:
        progress(0.08, desc=f'模型就绪 (LoRA={"on" if lora_loaded else "off"})')

    head = BASE_HEAD.format(CHAR=char_concept.strip())
    n_total = len(EXPRS)
    for i, (name, expr) in enumerate(EXPRS):
        prompt = head + expr + ', ' + BASE_TAIL
        neg = NEG_BASE + ', ' + NEG_STEP1
        g = torch.Generator('cuda').manual_seed(seed)
        t1 = time.time()
        img = pipe(prompt=prompt, negative_prompt=neg,
                   num_inference_steps=22, guidance_scale=5.5,
                   width=1024, height=1024, generator=g).images[0]
        dt = time.time() - t1
        img.save(os.path.join(raw_dir, f'expr8_{name}_{seed}.png'))
        gallery_so_far.append(os.path.join(raw_dir, f'expr8_{name}_{seed}.png'))
        torch.cuda.empty_cache()
        if progress:
            progress(0.10 + 0.80 * (i + 1) / n_total, desc=f'[{name}] 生成 {dt:.1f}s ({i+1}/{n_total})')
        yield (f"🖼️ 第 {i+1}/{n_total} 张「{name}」完成 {dt:.1f}s",
               0.10 + 0.80 * (i + 1) / n_total, gallery_so_far.copy(), True, dt)
    # generator 自然结束（不 return 值）


def postprocess_all(raw_dir, processed_dir):
    """raw → floodfill 去白底 → EDT 白边 → matte_flood_wb_*.png"""
    import glob
    os.makedirs(processed_dir, exist_ok=True)
    for n in NAMES:
        # 匹配 generate_all 写入的 expr8_{name}_{seed}.png（任意 seed 均可，避免硬编码 SEED 不匹配）
        cands = sorted(glob.glob(os.path.join(raw_dir, f'expr8_{n}_*.png')))
        raw = cands[-1] if cands else os.path.join(raw_dir, f'expr8_{n}.png')
        if not os.path.exists(raw):
            continue
        matte = os.path.join(processed_dir, f'matte_flood_{n}.png')
        wb = os.path.join(processed_dir, f'matte_flood_wb_{n}.png')
        floodfill_remove_bg(raw, matte)
        add_white_border(matte, wb)
    return processed_dir


# ====================== 单 generator 流水线（yield 渐进 UI） ======================
# run_pipeline 是一个 generator：
#   第一次 yield → 只更新 gallery_raw（原图），其余 4 个 output 用 gr.skip() 跳过（不刷新）
#   第二次 yield → 更新 gallery_final（成品）+ 拼页 + 透明页 + ZIP
# Gradio 6 的 generator 每次 yield 是「实时推送」，不受 .then() 整链事务刷新限制。
def _prune_runs(runs_base, keep=12):
    """只保留最近 keep 次运行的 workdir，避免 PVC（/persistent，100G）无限增长。"""
    try:
        entries = [os.path.join(runs_base, d) for d in os.listdir(runs_base)]
        entries = [d for d in entries if os.path.isdir(d)]
        entries.sort(key=lambda p: os.path.getmtime(p))
        for stale in entries[:-keep]:
            shutil.rmtree(stale, ignore_errors=True)
    except FileNotFoundError:
        pass


def _status(text):
    """生成状态栏 HTML（统一样式，避免截断）"""
    return f"<div style='padding:10px 14px;background:#f9fafb;border:1px solid #e0e0e0;border-radius:8px;font-size:15px;'>{text}</div>"


def _status_progress(stage_text, pct, eta_txt):
    """带文本进度条 + 百分比 + 真实 ETA 的状态栏 HTML"""
    pct = max(0.0, min(1.0, float(pct)))
    filled = int(pct * 20)
    bar = '█' * filled + '░' * (20 - filled)
    return (f"<div style='padding:10px 14px;background:#f9fafb;border:1px solid #e0e0e0;"
            f"border-radius:8px;font-size:14px;'>"
            f"<div style='margin-bottom:6px;'>{stage_text}</div>"
            f"<div style='font-family:monospace;letter-spacing:1px;color:#1565c0;'>[{bar}] {pct*100:.0f}%</div>"
            f"<div style='margin-top:4px;color:#555;font-size:13px;'>{eta_txt}</div>"
            f"</div>")


def run_pipeline(char_concept, seed, demo, demo_dir, use_lora, lora_weight, mode='文字', ref_image=None, progress=None):
    """generator（消费 generate_all generator）：逐张回显原图 + 文本进度条 + 真实 ETA，
    后处理各阶段 yield 状态栏文字，最后 yield 成品+拼页+ZIP。
    独立 status 组件始终接收可见的阶段文字，弥补 gr.skip() 组件不显示 processing 遮罩的缺口。"""
    # 先确保运行目录存在（DEBUG_LOG 落在 RUNS_BASE 内，否则首次打开会因父目录不存在而崩）
    os.makedirs(RUNS_BASE, exist_ok=True)
    with open(DEBUG_LOG, 'a') as _dbg:
        _dbg.write(f"[{time.strftime('%H:%M:%S')}] run_pipeline: demo={demo!r}, seed={seed}, char={char_concept[:30]!r}, lora={use_lora!r}\n")
        _dbg.flush()

    # 创建运行 workdir（优先 env RUN_DIR，否则仓库内 ./runs）
    runs_base = RUNS_BASE
    os.makedirs(runs_base, exist_ok=True)
    run_id = f"{int(time.time())}_{os.urandom(3).hex()}"
    workdir = os.path.join(runs_base, run_id)
    os.makedirs(workdir, exist_ok=True)
    _prune_runs(runs_base, keep=12)
    processed_dir = f'{workdir}/processed'

    if demo:
        if progress:
            progress(0.5, desc='📋 Demo 模式：加载已交付成品…')
        os.makedirs(processed_dir, exist_ok=True)
        for n in NAMES:
            src = os.path.join(demo_dir, f'matte_flood_wb_{n}.png')
            if not os.path.exists(src):
                import glob as _glob
                matches = _glob.glob(os.path.join(demo_dir, f'*{n}*sticker*.png'))
                src = matches[0] if matches else None
            if src and os.path.exists(src):
                shutil.copy(src, os.path.join(processed_dir, f'matte_flood_wb_{n}.png'))
        gallery_images = [os.path.join(processed_dir, f'matte_flood_wb_{n}.png') for n in NAMES]
        if progress:
            progress(1.0, desc='Demo 原图就绪 ✅')
        # 第一次 yield：原图 + 状态（其余跳过）
        yield gallery_images, gr.skip(), gr.skip(), gr.skip(), gr.skip(), _status("📋 Demo 成品已载入，正在拼页打包…")
        # Demo 后处理=拼页+打包（成品已是去背白边状态）
        delivery = build_delivery(processed_dir, f'{workdir}/delivery')
        if progress:
            progress(0.8, desc='📦 打包 ZIP…')
        zip_path = os.path.join(workdir, 'stickers_export.zip')
        with open(zip_path, 'wb') as f:
            f.write(make_zip(processed_dir, delivery))
        if progress:
            progress(1.0, desc='🎉 Demo 全部完成！')
        yield gallery_images, gallery_images, delivery['sheet_preview'], delivery['sheet_transparent_display'], zip_path, _status("🎉 Demo 全部完成！")
        return

    # ===== 图生文解析已改为显式「解析图片」按钮（见 build_ui 的 parse_btn）=====
    # 解析结果回填到 char_input（角色描述框），用户可手动微调后再点「生成」；
    # 此处不再自动解析，避免覆盖用户手动修改的内容。

    # ===== 真实模式（消费 generate_all generator：逐张回显 + 真实 ETA）=====
    # raw_dir 是确定路径，不依赖 generate_all 的返回值（generator 不 return）
    raw_dir = os.path.join(workdir, 'raw')
    t_start = time.time()
    img_times = []          # 实测每张耗时（用于真实 ETA，warmup 不计入）
    raw_gallery = []
    for stage_text, pct, gallery_list, is_img, last_dt in generate_all(
            char_concept, seed, workdir, use_lora=use_lora,
            lora_weight=lora_weight, progress=progress):
        if is_img and last_dt > 0:
            img_times.append(last_dt)
        raw_gallery = gallery_list
        # 真实 ETA：用实测均速 × 剩余张数
        if img_times:
            avg = sum(img_times) / len(img_times)
            remaining = (len(NAMES) - len(img_times)) * avg
            eta_txt = f"⏱ 已出 {len(img_times)}/{len(NAMES)} 张 · 均速 {avg:.1f}s/张 · 预计剩余 {remaining:.0f}s"
        else:
            elapsed = time.time() - t_start
            eta_txt = f"⏳ 准备中… 已用 {elapsed:.0f}s（首张出后显示精确 ETA）"
        yield raw_gallery, gr.skip(), gr.skip(), gr.skip(), gr.skip(), _status_progress(stage_text, pct, eta_txt)

    # generate_all 结束后 raw_gallery 已是完整 8 张；补一次 100% 状态
    elapsed_total = time.time() - t_start
    yield raw_gallery, gr.skip(), gr.skip(), gr.skip(), gr.skip(), _status_progress(
        "✅ 8 张原图已全部生成", 1.0,
        f"🎉 出图总耗时 {elapsed_total:.0f}s → 贴纸加工中…")

    # ===== 阶段 2：后处理 + 拼页 + 打包（每步 yield 可见状态）=====
    if progress:
        progress(0.2, desc='🖌️ 去白底 + EDT 白边…')
    postprocess_all(raw_dir, processed_dir)
    # 去白底完成 → 状态更新（原图保持显示）
    yield raw_gallery, gr.skip(), gr.skip(), gr.skip(), gr.skip(), _status("📐 拼页中…")

    if progress:
        progress(0.5, desc='📐 拼页中…')
    delivery = build_delivery(processed_dir, f'{workdir}/delivery')
    # 拼页完成 → 状态更新
    yield raw_gallery, gr.skip(), gr.skip(), gr.skip(), gr.skip(), _status("📦 打包 ZIP 中…")

    if progress:
        progress(0.75, desc='📦 打包 ZIP…')
    zip_path = os.path.join(workdir, 'stickers_export.zip')
    with open(zip_path, 'wb') as f:
        f.write(make_zip(processed_dir, delivery))
    gallery = [os.path.join(processed_dir, f'matte_flood_wb_{n}.png') for n in NAMES]
    if progress:
        progress(1.0, desc='🎉 全部完成！')
    yield raw_gallery, gallery, delivery['sheet_preview'], delivery['sheet_transparent_display'], zip_path, _status("🎉 全部完成！")


# ====================== Gradio UI（左控制面板 + 右结果区）======================
def build_ui():
    # 优先取 CLI 传入的 --demo-dir（已写入 DEMO_DIR 环境变量），否则用仓库内默认
    demo_dir_default = os.environ.get('DEMO_DIR', DEMO_DIR_DEFAULT)
    demo_available = os.path.isdir(demo_dir_default)

    # ── 自定义主题 ──

    def _title_html(lang):
        t = I18N[lang]
        active = 'font-weight:700;color:#D4537E;'
        inactive = 'font-weight:400;color:#999;cursor:pointer;'
        en_style = active if lang == 'en' else inactive
        zh_style = active if lang == 'zh' else inactive
        # JS: 找到 elem_id='lang-input' wrapper 内的 textarea，写入值并触发事件
        _js = (
            "var el=document.querySelector('#lang-input textarea');"
            "if(el){{el.value='{val}';el.dispatchEvent(new Event('input',{{bubbles:true}}));"
            "el.dispatchEvent(new Event('change',{{bubbles:true}}));}}"
        )
        return (
            f'<div id="title-bar" style="display:flex;align-items:center;gap:8px;padding:6px 14px;'
            f'border-bottom:1px solid var(--color-border-tertiary);'
            f'background:var(--color-background-secondary);'
            f'margin:-10px -14px 8px -14px;'
            f'border-radius:var(--border-radius-lg) var(--border-radius-lg) 0 0;">'
            f'<span style="width:10px;height:10px;border-radius:50%;background:#F09595;display:inline-block"></span>'
            f'<span style="width:10px;height:10px;border-radius:50%;background:#FAC775;display:inline-block"></span>'
            f'<span style="width:10px;height:10px;border-radius:50%;background:#97C459;display:inline-block"></span>'
            f'<span style="font-size:15px;font-weight:600;margin-left:8px">{t["title"]}</span>'
            f'<span style="margin-left:auto;font-size:11px;border:1px solid #ddd;border-radius:4px;padding:1px 4px;user-select:none;">'
            f'<span id="lang-en" style="{en_style}padding:1px 4px;" onclick="{_js.format(val="EN")}">EN</span>'
            f'<span style="color:#ccc">|</span>'
            f'<span id="lang-zh" style="{zh_style}padding:1px 4px;" onclick="{_js.format(val="中文")}">中文</span>'
            f'</span>'
            f'<span style="font-size:11px;color:var(--color-text-tertiary);margin-left:12px">{t["subtitle"]}</span>'
            f'</div>'
        )

    # 默认语言
    _LANG = 'en'
    _t = I18N[_LANG]

    # 自定义主题（只保留有效参数，其他用 CSS 覆盖）
    custom_theme = gr.themes.Soft()

    # ========== 全局自定义 CSS（放在 Blocks 里，优先级最高）==========
    full_css = """
/* 1. 全局先覆盖左侧面板所有主题字号变量，从根源控制 */
.contain >div  {gap:8px}
#left_panel {
  min-width:240px; max-width:280px;
  --text-md: 12px !important;
  --body-text-size: 12px !important;
  --body-text-size-medium: 12px !important;
  --label-text-size: 12px !important;
  --input-text-size: 12px !important;
  --button-large-text-size: 12px !important;
  --button-small-text-size: 11px !important;
}

/* 2. 超高权重穿透所有左侧标签、文字、输入框、按钮 */
#left_panel label[data-testid*="radio-label"]>span{
    display:flex !important;
    align-items:center !important;
    line-height:1 !important;
}
#left_panel .gr-label,
#left_panel .gr-label span,
#left_panel .label-wrap,
#left_panel .label-wrap span,
#left_panel input,
#left_panel textarea,
#left_panel select,
#left_panel .gr-radio label,
#left_panel .gr-checkbox label,
#left_panel .gr-slider label,
#left_panel .gr-button,
#left_panel .gr-button button,
#left_panel .gr-accordion .gr-accordion-title,
#left_panel .gr-markdown,
label,.label-text{
    font-size: 12px !important;
}
span[data-testid] {
  font-size: 12px !important;
}

/* 单独处理随机按钮字号 */
#left_panel .rand-btn button {
    font-weight: 400 !important;
    font-size: 14px !important;
}

.run-btn button { width:100% !important; }
.zip-btn { margin-top:12px; }
#status_box { overflow: visible !important; }
.tab-nav button.selected {
    border-bottom:2px solid #D4537E !important;
    color:#993556 !important;
    font-weight:600;
}
/* 隐藏语言切换的隐藏输入框 */
#lang-input,
.lang-hidden {
  position: absolute !important;
  left: -9999px !important;
  width: 0 !important;
  height: 0 !important;
  overflow: hidden !important;
  opacity: 0 !important;
}
/* Promo 视频宽度限制 - 覆盖 Gradio 主题默认样式 */
.gradio-container .contain #promo-video,
.gradio-container #promo-video,
#promo-video {
  max-width: 750px !important;
}
"""

    with gr.Blocks(title=_t['title']) as demo:
        # ═══ 顶栏标题条（含语言切换，全部在同一行 HTML 内）═══
        title_html = gr.HTML(_title_html('en'))
        # 隐藏输入框（用 CSS 隐藏，保留 visible=True 确保 Gradio 正常渲染）
        lang_input = gr.Textbox(value='EN', elem_id='lang-input',
                                show_label=False, container=False,
                                elem_classes=['lang-hidden'])

        demo_missing_md = None
        if not demo_available:
            demo_missing_md = gr.Markdown(_t['demo_missing'])

        # ═══ 主布局：左控制面板 | 右结果区 ═══
        with gr.Row(equal_height=False):
            # ── 左侧：控制面板（固定宽度 ~240px）──
            with gr.Column(scale=0, elem_id='left_panel'):
                # 输入模式：文字 / 参考图(①图生文) / 草图(②草图细化)
                mode_select = gr.Radio(
                    choices=_t['mode_choices'],
                    value=_t['mode_choices'][0],
                    label=_t['mode_label'],
                    info=_t['mode_info'],
                )
                ref_image = gr.Image(
                    label=_t['upload_both'],
                    type='pil',
                    visible=False,
                    height=260,
                )
                parse_btn = gr.Button(
                    _t['parse_btn'],
                    visible=False,
                    variant='secondary',
                )
                char_input = gr.Textbox(
                    label=_t['char_label'],
                    value=DEFAULT_CHAR,
                    lines=2,
                    placeholder='cat girl, cat ears, fang, pink hair',
                )
                seed_input = gr.Number(label=_t['seed_label'], value=SEED, precision=0)
                rand_btn = gr.Button(_t['rand_btn'], size='sm', elem_classes=['rand-btn'])

                run_btn = gr.Button(_t['run_btn'], variant='primary', elem_classes=['run-btn'])

                # 高级设置手风琴
                with gr.Accordion(_t['advanced'], open=True):
                    demo_toggle = gr.Checkbox(
                        label=_t['demo_toggle'],
                        value=demo_available,
                        interactive=demo_available,
                    )
                    demo_dir = gr.Textbox(label=_t['demo_dir'], value=demo_dir_default, visible=False)
                    lora_toggle = gr.Checkbox(label=_t['lora_toggle'], value=True)
                    lora_weight = gr.Slider(
                        label=_t['lora_weight'], minimum=0.0, maximum=1.0,
                        value=LORA_DEFAULT_WEIGHT, step=0.05,
                        info=_t['lora_info'],
                        interactive=True,
                    )

                zip_out = gr.File(label=_t['zip_label'], elem_classes=['zip-btn'])
                zip_html = gr.HTML(_t['zip_desc'])

            # ── 右侧：结果展示区（Tabs + Gallery 网格）──
            with gr.Column(scale=1):
                with gr.Tabs(selected='tab_raw') as result_tabs:
                    with gr.TabItem(_t['tab_raw'], id='tab_raw') as tab_raw:
                        gallery_raw = gr.Gallery(
                            label=_t['gallery_raw'],
                            columns=4, rows=2, height='auto',
                            object_fit='contain', elem_id='gallery_raw',
                        )

                    with gr.TabItem(_t['tab_final'], id='tab_final') as tab_final:
                        gallery_final = gr.Gallery(
                            label=_t['gallery_final'],
                            columns=4, rows=2, height='auto',
                            object_fit='contain', elem_id='gallery_final',
                        )
                        export_note_html = gr.HTML(
                            "<div style='text-align:right;font-size:12px;color:var(--color-text-tertiary);padding-top:4px;'>"
                            f"{_t['export_note']}</div>"
                        )

                    with gr.TabItem(_t['tab_sheet'], id='tab_sheet') as tab_sheet:
                        with gr.Row():
                            sheet_preview = gr.Image(
                                label=_t['sheet_white'], type='filepath', scale=1,
                            )
                            sheet_transparent = gr.Image(
                                label=_t['sheet_trans'], type='filepath', scale=1,
                        )

                    with gr.TabItem(_t['tab_video'], id='tab_video') as tab_video:
                        _promo_video = os.path.join(DEMO_DIR_DEFAULT, 'candy_sticker_demo.mp4')
                        if os.path.isfile(_promo_video):
                            gr.Video(
                                value=_promo_video,
                                label=_t['video_label'],
                                autoplay=False,
                                loop=False,
                                elem_id='promo-video',
                            )
                        else:
                            video_missing_md = gr.Markdown(
                                _t['video_missing'].format(dir=DEMO_DIR_DEFAULT)
                            )

                # 进度条/状态栏：横跨右栏底部（generator yield 实时更新，进度条可拉长显示）
                status_box = gr.HTML(
                    value="<div style='padding:10px 14px;background:#E1F5EE;border:1px solid #bce4c9;"
                           "border-radius:8px;font-size:14px;color:#0F6E56;text-align:center;'>"
                           f"{_t['status_idle']}</div>",
                    elem_id='status_box')

        # ===== 单 generator 事件：run_pipeline 用 yield 渐进推送 =====
        run_btn.click(
            fn=run_pipeline,
            inputs=[char_input, seed_input, demo_toggle, demo_dir, lora_toggle, lora_weight, mode_select, ref_image],
            outputs=[gallery_raw, gallery_final, sheet_preview, sheet_transparent, zip_out, status_box],
            show_progress='full',
        )

        # 随机换种按钮
        def _rand_seed(current):
            import random as _r
            return int(_r.randint(10000000, 99999999))
        rand_btn.click(fn=_rand_seed, inputs=[seed_input], outputs=[seed_input])

        # 图生文解析按钮：上传图 → 解析 → 回填角色描述（用户可手动微调后再出图）
        def parse_image(mode, ref_image):
            internal_mode = _MODE_MAP.get(mode, mode)
            if internal_mode not in ('Reference', 'Sketch'):
                return gr.skip(), _status(I18N['en']['parse_warn_mode'])
            if ref_image is None:
                return gr.skip(), _status(I18N['en']['parse_warn_img'])
            try:
                import sys as _sys
                _multimodal_dir = _os.path.join(PROJECT_ROOT, 'src', 'multimodal')
                if _multimodal_dir not in _sys.path:
                    _sys.path.insert(0, _multimodal_dir)
                from img2prompt import image_to_char_desc
                v_mode = 'reference' if internal_mode == 'Reference' else 'sketch'
                # 记录图像属性用于诊断（哪些图容易触发模型退化）
                try:
                    img_info = f'{ref_image.size}, mode={ref_image.mode}'
                except Exception:
                    img_info = '?'
                print(f'[parse_image] start mode={v_mode} image={img_info}')
                # 防御：Qwen-VL-3B 对某些图偶发退化输出 '!' 字符串，最多重试 3 次拿到正常结果
                MAX_RETRY = 3
                char_desc = ''
                t_parse = time.time()
                for attempt in range(1, MAX_RETRY + 2):
                    t_attempt = time.time()
                    char_desc = image_to_char_desc(ref_image, mode=v_mode)
                    print(f'[parse_image] attempt {attempt} inference {time.time()-t_attempt:.1f}s -> {char_desc[:50]!r}')
                    is_bad = (
                        not char_desc
                        or len(char_desc) < 10
                        or all(c in '!.,;:-_~ \t\n' for c in char_desc)
                    )
                    if not is_bad:
                        break
                    print(f'[parse_image] attempt {attempt}/{MAX_RETRY+1} looks bad ({char_desc!r})')
                if not char_desc:
                    return gr.skip(), _status(I18N['en']['parse_empty'])
                print(f'[parse_image] final mode={v_mode} total={time.time()-t_parse:.1f}s -> {char_desc!r}')
                return char_desc, _status(I18N['en']['parse_done'].format(desc=char_desc[:80]))
            except Exception as e:
                import traceback; traceback.print_exc()
                return gr.skip(), _status(I18N['en']['parse_fail'].format(err=e))

        parse_btn.click(
            fn=parse_image,
            inputs=[mode_select, ref_image],
            outputs=[char_input, status_box],
        )

        # LoRA 权重滑杆：勾选 LoRA 时启用
        lora_toggle.change(
            fn=lambda checked: gr.update(interactive=bool(checked)),
            inputs=[lora_toggle],
            outputs=[lora_weight],
        )

        # 输入模式切换：参考图/草图显示上传框并锁定文字输入，文字模式反之；上传框 label 随 tab 动态切换
        def _on_mode_change(m):
            internal = _MODE_MAP.get(m, m)
            is_img = internal in ('Reference', 'Sketch')
            if is_img:
                label = I18N['en']['upload_ref'] if internal == 'Reference' else I18N['en']['upload_sketch']
                return gr.update(visible=True, label=label), gr.update(interactive=not is_img), gr.update(visible=is_img)
            return gr.update(visible=False), gr.update(interactive=True), gr.update(visible=False)
        mode_select.change(
            fn=_on_mode_change,
            inputs=[mode_select],
            outputs=[ref_image, char_input, parse_btn],
        )

        # ===== 语言切换回调 =====
        def _on_lang_change(lang_choice):
            lang = 'en' if lang_choice == 'EN' else 'zh'
            t = I18N[lang]
            return [
                gr.update(value=_title_html(lang)),                                          # title_html
                gr.update(choices=t['mode_choices'], value=t['mode_choices'][0],
                          label=t['mode_label'], info=t['mode_info']),                       # mode_select
                gr.update(label=t['upload_both']),                                            # ref_image
                gr.update(value=t['parse_btn']),                                              # parse_btn
                gr.update(label=t['char_label']),                                             # char_input
                gr.update(label=t['seed_label']),                                             # seed_input
                gr.update(value=t['rand_btn']),                                               # rand_btn
                gr.update(value=t['run_btn']),                                                # run_btn
                gr.update(label=t['demo_toggle']),                                            # demo_toggle
                gr.update(label=t['lora_toggle']),                                            # lora_toggle
                gr.update(label=t['lora_weight'], info=t['lora_info']),                       # lora_weight
                gr.update(label=t['zip_label']),                                              # zip_out
                gr.update(value=t['zip_desc']),                                               # zip_html
                gr.update(label=t['tab_raw']),                                                # tab_raw
                gr.update(label=t['gallery_raw']),                                            # gallery_raw
                gr.update(label=t['tab_final']),                                              # tab_final
                gr.update(label=t['gallery_final']),                                          # gallery_final
                gr.update(value=f"<div style='text-align:right;font-size:12px;color:var(--color-text-tertiary);padding-top:4px;'>{t['export_note']}</div>"),  # export_note_html
                gr.update(label=t['tab_sheet']),                                              # tab_sheet
                gr.update(label=t['sheet_white']),                                            # sheet_preview
                gr.update(label=t['sheet_trans']),                                            # sheet_transparent
                gr.update(label=t['tab_video']),                                              # tab_video
                gr.update(value=f"<div style='padding:10px 14px;background:#E1F5EE;border:1px solid #bce4c9;border-radius:8px;font-size:14px;color:#0F6E56;text-align:center;'>{t['status_idle']}</div>"),  # status_box
            ] + ([gr.update(value=t['demo_missing'])] if demo_missing_md is not None else [])  # demo_missing_md (optional)

        _lang_outputs = [
            title_html, mode_select, ref_image, parse_btn, char_input,
            seed_input, rand_btn, run_btn, demo_toggle, lora_toggle,
            lora_weight, zip_out, zip_html,
            tab_raw, gallery_raw, tab_final, gallery_final, export_note_html,
            tab_sheet, sheet_preview, sheet_transparent, tab_video, status_box,
        ]
        if demo_missing_md is not None:
            _lang_outputs.append(demo_missing_md)

        lang_input.change(
            fn=_on_lang_change,
            inputs=[lang_input],
            outputs=_lang_outputs,
        )

    return demo, custom_theme, full_css


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo-dir', default=DEMO_DIR_DEFAULT,
                        help='Demo 成品目录（含 matte_flood_wb_*.png）；默认仓库内 ./demo_output')
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument('--share', action='store_true')
    args = parser.parse_args()
    os.environ['DEMO_DIR'] = args.demo_dir
    ui, custom_theme, full_css = build_ui()
    # 真实模式出 8 张要数分钟；Gradio 6 的 queue 无 max_duration 概念（作业不会被超时杀），
    # 这里仅串行化（GPU 独占）避免并发抢卡。
    ui.queue(default_concurrency_limit=1)
    # 允许 Gradio 对外提供文件的目录：运行输出、demo 目录及其父目录、/tmp、仓库根
    # （不再写死 /persistent，任意 ROCm 机器均可）。
    _allowed = [RUNS_BASE, args.demo_dir, os.path.dirname(args.demo_dir), '/tmp', REPO_ROOT]
    _allowed = [p for p in _allowed if os.path.isdir(p)]
    # 后台预热模型（不阻塞 Gradio 启动，第一个用户请求时若未就绪会自动等待）
    import threading
    threading.Thread(target=_ensure_pipe_loaded, daemon=True, name='model-warmup').start()
    ui.launch(server_name='0.0.0.0', server_port=args.port, share=args.share,
              theme=custom_theme, css=full_css,
              allowed_paths=_allowed)
