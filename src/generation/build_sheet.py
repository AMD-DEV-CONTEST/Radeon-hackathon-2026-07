# ============================================================
# build_sheet.py  —  把 8 表情拼成 2×4 sticker sheet（本地 PIL，不需 GPU）
#
# 输入: D:\work\hackson\images\expr8\expr8_<name>_20260728.png (raw 版)
# 输出: D:\work\hackson\images\expr8\sticker_sheet_8expr.png
# 顺序: happy pout crying surprised / angry shy wink love
# ============================================================
import os
from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
SRC_DIR = os.environ.get('EXPR8_DIR', os.path.join(_PROJECT_ROOT, 'demo_output'))
OUT = os.path.join(SRC_DIR, 'sticker_sheet_8expr.png')
SEED = '20260728'

# 顺序 (2 行 × 4 列)
ORDER = ['happy', 'pout', 'crying', 'surprised',
         'angry', 'shy',  'wink',   'love']

TILE = 1024          # 每张原始图尺寸
GAP = 36             # 格子间距
PAD = 48             # 外边距
LABEL_H = 64        # 底部标签条高度

cols, rows = 4, 2

def load(name):
    p = os.path.join(SRC_DIR, f'expr8_{name}_{SEED}.png')
    if not os.path.exists(p):
        # shy 候选回退
        for tag in ('v1', 'v2', 'v3'):
            alt = os.path.join(SRC_DIR, f'expr8_shy_{tag}_{SEED}.png')
            if os.path.exists(alt):
                return Image.open(alt).convert('RGB')
        raise FileNotFoundError(p)
    return Image.open(p).convert('RGB')

# 字体（跨平台回退）
_FONT_CANDIDATES = [
    r'C:\Windows\Fonts\msyh.ttc',          # Windows
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',  # Linux
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',  # Linux CJK
    '/System/Library/Fonts/PingFang.ttc',   # macOS
]
FONT_PATH = next((f for f in _FONT_CANDIDATES if os.path.exists(f)), None)
try:
    font = ImageFont.truetype(FONT_PATH, 40) if FONT_PATH else ImageFont.load_default()
except Exception:
    font = ImageFont.load_default()

W = PAD*2 + cols*TILE + (cols-1)*GAP
H = PAD*2 + rows*TILE + (rows-1)*GAP + LABEL_H

sheet = Image.new('RGB', (W, H), (38, 40, 48))   # 深灰底，凸显白边
draw = ImageDraw.Draw(sheet)

for i, name in enumerate(ORDER):
    r, c = divmod(i, cols)
    x = PAD + c*(TILE+GAP)
    y = PAD + r*(TILE+GAP)
    img = load(name)
    sheet.paste(img, (x, y))
    # 标签条
    ly = y + TILE + 8
    draw.rectangle([x, ly, x+TILE, ly+LABEL_H-8], fill=(58, 61, 70))
    tw = draw.textlength(name.upper(), font=font)
    draw.text((x + (TILE-tw)/2, ly + (LABEL_H-8-40)/2), name.upper(),
              fill=(235, 238, 245), font=font)

sheet.save(OUT)
print(f'SHEET -> {OUT}  ({W}x{H})')
