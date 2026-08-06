# -*- coding: utf-8 -*-
# matte_floodfill_batch.py — 全量 8 表情 flood-fill 抠图
import os
from PIL import Image, ImageDraw

_SENTINEL = (2, 2, 2)
WHITE_TOL = 22

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
BASE = os.environ.get('EXPR8_DIR', os.path.join(_PROJECT_ROOT, 'demo_output'))
OUT_DIR = BASE
NAMES = ['happy','pout','crying','surprised','angry','shy','wink','love']

def matte(in_path):
    im = Image.open(in_path).convert('RGB')
    W,H = im.size; fimg=im.copy(); dr=ImageDraw.Draw(fimg,'RGB')
    seeds=[(0,0),(W-1,0),(0,H-1),(W-1,H-1),(W//2,0),(W//2,H-1),(0,H//2),(W-1,H//2)]
    for (x,y) in seeds:
        r,g,b=fimg.getpixel((x,y))
        if max(abs(r-255),abs(g-255),abs(b-255))<=WHITE_TOL:
            try: ImageDraw.floodfill(fimg,(x,y),_SENTINEL,thresh=WHITE_TOL)
            except: pass
    px=fimg.load(); out=im.copy().convert('RGBA'); opx=out.load(); bg=0
    for y in range(H):
        for x in range(W):
            if px[x,y]==_SENTINEL:
                opx[x,y]=(opx[x,y][0],opx[x,y][1],opx[x,y][2],0); bg+=1
    return out, f'{100*bg/(W*H):.1f}%'

for n in NAMES:
    inp=os.path.join(BASE,f'expr8_{n}_20260728.png')
    outp=os.path.join(OUT_DIR,f'matte_flood_{n}.png')
    if not os.path.exists(inp):
        print(f'⚠️ SKIP {n}: input not found'); continue
    img,pct=matte(inp)
    img.save(outp)
    print(f'✅ {n}: transparent={pct} -> {os.path.basename(outp)}')

# 合成到洋红底供检查
MAGENTA=(255,0,255)
for n in NAMES:
    mp=os.path.join(OUT_DIR,f'matte_flood_{n}.png')
    cp=os.path.join(OUT_DIR,f'CHECK_flood_{n}_magenta.png')
    if not os.path.exists(mp): continue
    m=Image.open(mp).convert('RGBA')
    c=Image.new('RGBA',m.size,MAGENTA); c.alpha_composite(m); c.convert('RGB').save(cp)
print('\nAll done. CHECK_flood_*_magenta.png ready.')
