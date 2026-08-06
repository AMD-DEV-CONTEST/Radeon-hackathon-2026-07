# make_sheet_export.py  —  P0 交付：拼 sticker sheet + 导出规格 PNG
# 输入: images/expr8/matte_flood_wb_{expr}.png (8张带背版成品, 1024x1024 RGBA)
# 输出:
#   images/expr8/delivery/sheet_4x2.png        (浅灰背板预览版, 4x2)
#   images/expr8/delivery/sheet_4x2_transparent.png (透明底版)
#   images/expr8/delivery/wechat/  *.png        (500x500 透明)
#   images/expr8/delivery/telegram/ *.png       (512x512 透明)
import os
from PIL import Image, ImageFilter

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
SRC = os.environ.get('EXPR8_DIR', os.path.join(_PROJECT_ROOT, 'demo_output'))
OUT = os.path.join(SRC, 'delivery')
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, 'wechat'), exist_ok=True)
os.makedirs(os.path.join(OUT, 'telegram'), exist_ok=True)

EXPRS = ['happy', 'pout', 'crying', 'angry', 'shy', 'wink', 'surprised', 'love']
COLS, ROWS = 4, 2
GAP = 60
CELL = 1120  # 单张原生尺寸（白边已加 48px 透明留白 → 1024+96）

def load(e):
    p = os.path.join(SRC, f'matte_flood_wb_{e}.png')
    im = Image.open(p).convert('RGBA')
    assert im.size == (CELL, CELL), f'{e} size {im.size} != {CELL}'
    return im

imgs = [load(e) for e in EXPRS]

# ---- 拼 sheet ----
W = COLS * CELL + (COLS + 1) * GAP
H = ROWS * CELL + (ROWS + 1) * GAP
# 浅灰背板预览版 —— 用纯白背板，避免EDT白边(255,255,255)与灰底(237,237,240)产生可见色差线
sheet_bg = Image.new('RGBA', (W, H), (255, 255, 255, 255))
# 透明底版
sheet_trans = Image.new('RGBA', (W, H), (0, 0, 0, 0))
for i, im in enumerate(imgs):
    r, c = divmod(i, COLS)
    x = GAP + c * (CELL + GAP)
    y = GAP + r * (CELL + GAP)
    sheet_bg.alpha_composite(im, (x, y))
    sheet_trans.alpha_composite(im, (x, y))

sheet_bg.save(os.path.join(OUT, 'sheet_4x2.png'))
sheet_trans.save(os.path.join(OUT, 'sheet_4x2_transparent.png'))
print(f'sheet saved: {W}x{H}, 8 stickers')

# ---- 导出规格 ----
for e, im in zip(EXPRS, imgs):
    wc = im.resize((500, 500), Image.LANCZOS)
    wc.save(os.path.join(OUT, 'wechat', f'{e}.png'))
    tg = im.resize((512, 512), Image.LANCZOS)
    tg.save(os.path.join(OUT, 'telegram', f'{e}.png'))
print('export wechat(500) + telegram(512) done for 8 stickers')

print('OUTDIR:', OUT)
