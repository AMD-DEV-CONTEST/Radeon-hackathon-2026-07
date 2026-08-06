# ============================================================
# sticker_pipeline.py  —  W1 完整流水线 v8（前景层叠构图版）
#
# 核心原则：以 sticker_original.py（62-token 黄金 prompt）为唯一基准，
#           只换 crossed arms,pout → 各表情词，其余一字不改。
#           白边由模型原生生成（white border + thick outline + sticker），
#           后处理仅做去背+透明化（保留模型自带的模切效果）。
#
# v8 修正: "breaking out of frame" 效果太弱 → 改用
#          "foreground, overlapping border"
#          让角色身体/手臂作为前景层叠在背景边框之上
#          （匹配黄金参照图的 die-cut 贴纸构图）
#
# 配方(不变): Animagine XL 4.0 / Euler a / 28步 / CFG 5.5 / 1024 / seed族
# 存盘: /persistent output (PVC) → scp 拉回本地
# ============================================================
import os, time
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['HF_XET_DISABLED'] = '1'

import torch
import numpy as np
from PIL import Image, ImageFilter
from diffusers import StableDiffusionXLPipeline, EulerAncestralDiscreteScheduler

# ---- 加载模型 ----
print('Loading model...')
t0 = time.time()
pipe = StableDiffusionXLPipeline.from_pretrained(
    'cagliostrolab/animagine-xl-4.0', torch_dtype=torch.float16, use_safetensors=True
).to('cuda')
pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
print(f'Model loaded in {time.time()-t0:.1f}s')

# ================================================================
# 严格基线 prompt（来自 sticker_original.py，62-token 黄金配方）
#   原始: 1girl, solo, chibi, cat girl, cat ears, fang, pink hair,
#          crossed arms, pout,
#          blush stickers, sticker, thick outline, white border,
#          flat color, vivid colors, pastel green background, simple background,
#          upper body, masterpiece, high score, great score, absurdres
#
#   策略: 只把 "crossed arms, pout" 这个位置替换为各表情词，
#         其余 52 个 token 一个字不动 → 风格/元素/白边严格对齐黄金参照图
# ================================================================

BASE_HEAD = '1girl, solo, chibi, cat girl, cat ears, fang, pink hair, '
BASE_TAIL = (', blush stickers, sticker, thick outline, white border, '
             'flat color, vivid colors, pastel green background, simple background, '
             'foreground, overlapping border, upper body, distant view, masterpiece, high score, great score, absurdres')

NEG = ('lowres, bad anatomy, bad hands, extra digits, fewer digits, cropped, '
       'worst quality, low quality, low score, bad score, average score, '
       'signature, watermark, jpeg artifacts, blurry, 3d, realistic, gradient background, '
       'close up, face closeup, filling frame')

# ---- §7 核心8表情（短词，替换 crossed arms,pout 位置）----
EXPRS = [
    ('happy',    'happy, big smile, laughing'),
    ('shy',      'shy, blushing, looking away'),
    ('angry',    'angry, annoyed, puffed cheeks'),
    ('cry',      'crying, tears, sad face'),
    ('shock',    'surprised, shocked, wide eyes'),
    ('love',     'love, heart hands, wink'),
    ('confused', 'confused, sweating, question mark'),
    ('sleep',    'sleeping, peaceful, zzz'),
]

N_CANDIDATES = 1
BASE_SEED = 20260728

# ---- 单表情快速验证（设环境变量 EXPR_FILTER=happy 则只跑该表情）----
EXPR_FILTER = os.environ.get('EXPR_FILTER', '')  # 留空=跑全部
if EXPR_FILTER:
    EXPRS = [(n, w) for n, w in EXPRS if n == EXPR_FILTER]
    if not EXPRS:
        print(f'ERROR: expression "{EXPR_FILTER}" not found!')
        import sys; sys.exit(1)
    print(f'=== FILTER MODE: only running "{EXPR_FILTER}" ===')

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
_pvc_out = '/persistent/output'
OUT = _pvc_out if os.path.isdir(_pvc_out) else os.path.join(_PROJECT_ROOT, 'output')
os.makedirs(OUT, exist_ok=True)


def make_sticker_rgba(img):
    """
    绿背键控去背 → RGBA（保留模型自带的 white border 效果）。
    不加额外白边 —— 黄金参照图的白边就是模型自己画的。
    """
    arr = np.array(img.convert('RGB')).astype(np.float32)
    h, w = arr.shape[:2]

    # 取四角+四边边缘像素均值作为背景色
    edge_px = np.concatenate([
        arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]
    ], axis=0)
    bg_color = edge_px.mean(axis=0)

    # 颜色距离 > 阈值 = 前景
    dist = np.sqrt(((arr - bg_color) ** 2).sum(axis=2))
    alpha_raw = (dist > 40).astype(np.uint8) * 255

    # 轻柔模糊去锯齿
    alpha_smooth = np.array(
        Image.fromarray(alpha_raw, mode='L').filter(ImageFilter.GaussianBlur(radius=1.5))
    )
    alpha_bin = (alpha_smooth > 128).astype(np.uint8) * 255

    # 组合 RGBA
    rgba = np.dstack([arr.astype(np.uint8), alpha_bin])
    return Image.fromarray(rgba, mode='RGBA')


# ============================================================
# token 校验 + 主循环
# ============================================================
_sample_prompt = BASE_HEAD + EXPRS[0][1] + BASE_TAIL
_n = len(pipe.tokenizer(_sample_prompt).input_ids)
print(f'prompt tokens: {_n} (must be <=77, baseline=62)')
if _n > 77:
    print('WARNING: token count exceeds 77! Truncation will occur.')

results = []
TOTAL_IMAGES = len(EXPRS) * N_CANDIDATES
DONE_COUNT = 0

for expr_idx, (name, expr_word) in enumerate(EXPRS):
    # 严格拼接：基线头 + 表情词 + 基线尾
    prompt = BASE_HEAD + expr_word + BASE_TAIL

    candidates = []
    for ci in range(N_CANDIDATES):
        seed = BASE_SEED + expr_idx * 100 + ci * 7
        g = torch.Generator('cuda').manual_seed(seed)
        t_gen_start = time.time()

        img = pipe(prompt=prompt, negative_prompt=NEG,
                   num_inference_steps=28, guidance_scale=5.5,
                   width=1024, height=1024, generator=g).images[0]
        t_gen = time.time() - t_gen_start
        DONE_COUNT += 1

        raw_path = f'{OUT}/expr_{name}_c{ci}_s{seed}.png'
        img.save(raw_path)

        # 去背透明化（保留模型自带白边）
        rgba = make_sticker_rgba(img)
        stk_path = f'{OUT}/expr_{name}_c{ci}_s{seed}_sticker.png'
        rgba.save(stk_path)

        candidates.append((rgba, seed, t_gen))
        print(f'  [{DONE_COUNT}/{TOTAL_IMAGES}] {name} c{ci} s={seed} gen={t_gen:.1f}s')

    # 默认取 c0（seed 最接近基线）作为 winner
    best_rgba, best_seed, _ = candidates[0]
    print(f'  >> {name} WINNER: seed={best_seed}')
    best_rgba.save(f'{OUT}/expr_{name}_winner_sticker.png')
    results.append((name, best_rgba, best_seed))

    done = expr_idx + 1
    print(f'=== [{done}/8] {name} DONE ({time.strftime("%H:%M:%S")}) ===\n')


# ---- 拼 2×4 sticker sheet（透明底） ----
cols, rows, cell = 4, 2, 1024
sheet = Image.new('RGBA', (cols * cell, rows * cell), (255, 255, 255, 0))
for idx, (name, rgba, seed) in enumerate(results):
    r, c = divmod(idx, cols)
    sheet.paste(rgba, (c * cell, r * cell))
sheet_path = f'{OUT}/sticker_sheet_8expr_v8.png'
sheet.save(sheet_path)

# ---- 最终报告 ----
print('\n' + '=' * 50)
print(f'FINAL REPORT — sticker_pipeline v6 (baseline-strict)')
print('=' * 50)
for name, _, seed in results:
    print(f'  {name}: seed={seed}')
print(f'\nSHEET -> {sheet_path}')
print(f'TOTAL images generated: {TOTAL_IMAGES}')
print('PIPELINE_DONE')
