# -*- coding: utf-8 -*-
"""给带背景板的透明贴纸加"贴纸白边"(die-cut white border)。

做法 = 业界标准：对 alpha 做 距离变换(distance transform) 膨胀，生成外扩白轮廓，垫在原图下方。
- 用 **精确欧氏距离变换 (Exact EDT, Felzenszwalb & Huttenlocher)** 计算"每个透明像素到最近前景"的真实欧氏距离
- 距离 <= BORDER 的像素 = 等距外扩白边 → 外轮廓为完美圆形等距线 → 所有方向白边粗细一致
- 相比旧版 MaxFilter(3) 方形核迭代：消除了方形核把尖角磨圆、凹角填平、细锯齿抹平的整形副作用，
  也消除了 chamfer(3-4) 近似 EDT 的方向性偏差（八边形外轮廓 → 白边不均匀）
- 依赖 numpy（managed venv 已装）；纯 CPU、无需 GPU/u2net

历史：
  v1 MaxFilter(3) 迭代 26 次 → 方形核整形，边缘形状有出入
  v2 chamfer(3-4) 近似 EDT 26 → 形状贴合，但白边不均匀
  v3 精确 EDT 32（本版）→ 形状贴合 + 白边均匀，用户确认采用
"""
import os
import numpy as np
from PIL import Image, ImageFilter

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
BASE = os.environ.get('EXPR8_DIR', os.path.join(_PROJECT_ROOT, 'demo_output'))
NAMES = ['happy', 'pout', 'crying', 'surprised', 'angry', 'shy', 'wink', 'love']
BORDER = 32  # 白边像素宽度@1024（精确欧氏等距外扩）


# ============================================================
#  Exact Euclidean Distance Transform (Felzenszwalb & Huttenlocher)
#  对二值 mask 做 1-bit 前景到每个背景像素的真实欧氏距离。
#  分离式(separable)：先沿列做 1D squared EDT，再沿行做 1D squared EDT，
#  结果开方即为精确欧氏距离场。外轮廓 dt==BORDER 是完美圆形等距线。
# ============================================================

def _edt1d(f):
    """1D squared Euclidean distance transform (Felzenszwalb)。
    f[i] = 0 at foreground, INF at background。
    返回 d[i] = min_k ((i-k)^2 + f[k])  即到最近前景的平方距离。
    """
    n = len(f)
    d = f.copy().astype(np.float64)
    v = [0]
    z = [-1e20, 1e20]
    k = 0
    for q in range(1, n):
        fq = float(f[q]) + q * q
        while True:
            vk = v[k]
            s = (fq - (float(f[vk]) + vk * vk)) / (2.0 * q - 2.0 * vk)
            if s <= z[k]:
                k -= 1
            else:
                break
        k += 1
        v.insert(k, q)
        z.insert(k, s)
        z.insert(k + 1, 1e20)
    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        d[q] = (q - v[k]) ** 2 + float(f[v[k]])
    return d


def edt2d_exact(mask):
    """精确 2D 欧氏距离变换。mask=True 为前景。返回每个像素到最近前景的距离(像素)。"""
    h, w = mask.shape
    INF = 1e20
    f = np.where(mask, 0.0, INF)
    for x in range(w):
        f[:, x] = _edt1d(f[:, x])
    for y in range(h):
        f[y, :] = _edt1d(f[y, :])
    return np.sqrt(np.maximum(f, 0))


def add_white_border(src_path, dst_path, border=BORDER, pad=None):
    """精确欧氏距离变换白边。返回 (w, h)。

    修复：先给源图铺一圈透明留白(pad)，再算 EDT。否则当前景(青绿板+角色)
    本身顶到 1024 画布边缘时，白边环会贴死矩形边缘，单张图看起来像被白矩形
    框住、拼到透明 sheet 显出边缘线。pad = border + 余量，保证白边四周都有透明余量。
    """
    img = Image.open(src_path).convert('RGBA')
    w, h = img.size
    if pad is None:
        pad = border + 16  # 透明留白，避免白边贴死矩形边缘
    # 铺透明留白
    big = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(img, (pad, pad))
    img = big
    w, h = img.size

    alpha_arr = np.array(img.split()[3])
    mask = alpha_arr > 128

    dt = edt2d_exact(mask)
    border_ring = (~mask) & (dt <= border)

    white_alpha_raw = np.where(mask | border_ring, 255, 0).astype(np.uint8)
    # 抗锯齿：对 alpha 做轻微高斯模糊，消除 EDT 硬边产生的像素级锯齿(stair-step)
    alpha_img = Image.fromarray(white_alpha_raw, 'L').filter(ImageFilter.GaussianBlur(radius=1.0))
    white_alpha = np.array(alpha_img)

    white = Image.new('RGBA', (w, h), (255, 255, 255, 255))
    white.putalpha(Image.fromarray(white_alpha, 'L'))
    out = Image.alpha_composite(white, img)  # 白在底、原图在顶
    out.save(dst_path)
    return w, h


def checker(c, a=(200, 200, 200), b=(150, 150, 150)):
    img = Image.new('RGB', (c, c))
    px = img.load()
    for y in range(c):
        for x in range(c):
            px[x, y] = a if ((x // 16 + y // 16) % 2 == 0) else b
    return img


def make_sheet():
    cell = 512
    cols, rows = 4, 2
    sheet = Image.new('RGB', (cols * cell, rows * cell), (80, 80, 80))
    ch = checker(cell)
    for i, n in enumerate(NAMES):
        m = Image.open(os.path.join(BASE, f'matte_flood_wb_{n}.png')).convert('RGBA')
        thumb = Image.new('RGBA', (cell, cell))
        thumb.alpha_composite(ch.convert('RGBA'))
        mm = m.copy()
        mm.thumbnail((cell - 40, cell - 40))
        thumb.alpha_composite(mm)
        from PIL import ImageDraw
        d = ImageDraw.Draw(thumb)
        d.text((10, 10), n, (255, 80, 80))
        r, c = divmod(i, cols)
        sheet.paste(thumb.convert('RGB'), (c * cell, r * cell))
    p = os.path.join(BASE, 'matte_wb_contact_sheet.png')
    sheet.save(p)
    return p


if __name__ == '__main__':
    for n in NAMES:
        s = add_white_border(
            os.path.join(BASE, f'matte_flood_{n}.png'),
            os.path.join(BASE, f'matte_flood_wb_{n}.png'))
        print('white-border done:', n, s)
    sp = make_sheet()
    print('contact sheet:', sp)
