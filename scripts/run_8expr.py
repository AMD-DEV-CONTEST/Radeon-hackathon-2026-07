# ============================================================
# run_8expr.py  —  8 表情批量（定稿 step1 提示词，2026-07-29 续作）
#
# 正向: 严格原版 62-token 结构 + 只换表情词（表情词作为 {EXPR} 槽位）
# 负向: 原版 NEG + step1 禁悬浮词（floating, gap below, space under, floating character）
# 配方: Animagine XL 4.0 / Euler a / 28步 / CFG 5.5 / 1024 / seed 20260728（统一）
#
# 8 个表情: happy / pout / crying / surprised / angry / shy / wink / love
# 同 seed 保证角色基础结构一致、"像一家人"
# 严禁加任何额外正向词（破框类/形状类都会翻车，已验证 step2/step3）
# ============================================================
import os, time
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['HF_XET_DISABLED'] = '1'

import torch
import numpy as np
from PIL import Image, ImageFilter
from diffusers import StableDiffusionXLPipeline, EulerAncestralDiscreteScheduler

print('Loading model...')
t0 = time.time()
pipe = StableDiffusionXLPipeline.from_pretrained(
    'cagliostrolab/animagine-xl-4.0', torch_dtype=torch.float16, use_safetensors=True
).to('cuda')
pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
print(f'Model loaded in {time.time()-t0:.1f}s')

# ---- 定稿 step1 提示词（一字不动，只换 {EXPR}）----
BASE_HEAD = '1girl, solo, chibi, cat girl, cat ears, fang, pink hair, '
BASE_TAIL = ('blush stickers, sticker, thick outline, white border, '
             'flat color, vivid colors, pastel green background, simple background, upper body, '
             'masterpiece, high score, great score, absurdres')
NEG_BASE = ('lowres, bad anatomy, bad hands, extra digits, fewer digits, cropped, '
            'worst quality, low quality, low score, bad score, average score, '
            'signature, watermark, jpeg artifacts, blurry, 3d, realistic, gradient background')
NEG_STEP1 = 'floating, gap below character, space under character, floating character'

# 8 个表情： (名字, 表情短语)
EXPRS = [
    ('happy',    'happy, big smile, laughing'),
    ('pout',     'pout, tsundere, blush, looking away'),
    ('crying',   'crying, sad, tears, sniffing'),
    ('surprised','surprised, shocked, open mouth, wide eyes'),
    ('angry',    'angry, mad, annoyed, furrowed brows'),
    ('shy',      'shy, blushing, bashful, looking down'),
    ('wink',     'wink, playful, smug, one eye closed'),
    ('love',     'heart eyes, lovestruck, in love, sparkles'),
]

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_pvc_out = '/persistent/output/expr8'
OUT = _pvc_out if os.path.isdir(os.path.dirname(_pvc_out)) else os.path.join(_PROJECT_ROOT, 'output', 'expr8')
os.makedirs(OUT, exist_ok=True)
seed = int(os.environ.get('SEED', '20260728'))

for name, expr in EXPRS:
    prompt = BASE_HEAD + expr + ', ' + BASE_TAIL
    neg = NEG_BASE + ', ' + NEG_STEP1
    nt = len(pipe.tokenizer(prompt).input_ids)
    nn = len(pipe.tokenizer(neg).input_ids)
    print(f'[{name}] prompt tokens: {nt} | neg tokens: {nn} | seed={seed}')
    if nt > 77:
        print(f'  !! WARNING: {name} prompt > 77, truncation!')

    g = torch.Generator('cuda').manual_seed(seed)
    t_gen = time.time()
    img = pipe(prompt=prompt, negative_prompt=neg,
               num_inference_steps=28, guidance_scale=5.5,
               width=1024, height=1024, generator=g).images[0]
    dt = time.time() - t_gen
    print(f'[{name}] generated in {dt:.1f}s')

    raw_path = f'{OUT}/expr8_{name}_{seed}.png'
    img.save(raw_path)
    print(f'  RAW -> {raw_path}')

    # 去背透明（保留模型自带白边；色键不完美，仅作参考版）
    arr = np.array(img.convert('RGB')).astype(np.float32)
    edge_px = np.concatenate([arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]], axis=0)
    bg_color = edge_px.mean(axis=0)
    dist = np.sqrt(((arr - bg_color) ** 2).sum(axis=2))
    alpha_raw = (dist > 40).astype(np.uint8) * 255
    alpha_sm = np.array(Image.fromarray(alpha_raw, mode='L').filter(ImageFilter.GaussianBlur(radius=1.5)))
    alpha_bin = (alpha_sm > 128).astype(np.uint8) * 255
    rgba = np.dstack([arr.astype(np.uint8), alpha_bin])
    stk_path = f'{OUT}/expr8_{name}_{seed}_sticker.png'
    Image.fromarray(rgba, mode='RGBA').save(stk_path)
    print(f'  STICKER -> {stk_path}')

print('ALL_8_DONE')
