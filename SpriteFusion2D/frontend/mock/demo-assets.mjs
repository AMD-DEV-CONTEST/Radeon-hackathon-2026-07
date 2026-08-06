// 程序化生成演示素材。这是 mock 数据，不代表任何真实算法。
// 目的：让阶段 A 的界面有真实像素可看——带纯色背景的 sprite sheet、
// 已抠好的帧、以及可叠加的图层素材（身体/服装/武器）。

const W = 32;
const H = 40;
const COLS = 4;
const ROWS = 2;

// 固定调色板，模拟 recover 之后的量化结果。
const PAL = {
  bg: [0x27, 0x9a, 0x3f, 255], // 纯绿背景，便于演示抠图
  skin: [0xff, 0xe3, 0xcb, 255],
  skinShade: [0xd9, 0xa8, 0x8c, 255],
  hair: [0x3a, 0x2c, 0x3f, 255],
  hairHi: [0x5d, 0x46, 0x63, 255],
  robe: [0x9a, 0x30, 0x4a, 255],
  robeHi: [0xc4, 0x52, 0x6d, 255],
  white: [0xf2, 0xf0, 0xe6, 255],
  steel: [0xa8, 0xb4, 0xc0, 255],
  steelDark: [0x5a, 0x66, 0x74, 255],
  wood: [0x7a, 0x54, 0x32, 255],
  glow: [0xff, 0xd8, 0x66, 255],
  none: [0, 0, 0, 0],
};

function makeBuffer(w, h, fill = PAL.none) {
  const buf = new Uint8Array(w * h * 4);
  for (let i = 0; i < w * h; i += 1) {
    buf[i * 4] = fill[0];
    buf[i * 4 + 1] = fill[1];
    buf[i * 4 + 2] = fill[2];
    buf[i * 4 + 3] = fill[3];
  }
  return buf;
}

function px(buf, w, x, y, color) {
  if (x < 0 || y < 0 || x >= w) return;
  const i = (y * w + x) * 4;
  if (i < 0 || i + 3 >= buf.length) return;
  buf[i] = color[0];
  buf[i + 1] = color[1];
  buf[i + 2] = color[2];
  buf[i + 3] = color[3];
}

function rect(buf, w, x, y, rw, rh, color) {
  for (let dy = 0; dy < rh; dy += 1) {
    for (let dx = 0; dx < rw; dx += 1) px(buf, w, x + dx, y + dy, color);
  }
}

// 画一个 32x40 的角色帧。bob 控制上下浮动，step 控制腿部姿势。
function drawCharacter(buf, w, ox, oy, { bob = 0, step = 0, robe = PAL.robe, robeHi = PAL.robeHi }) {
  const cx = ox + 16;
  const top = oy + 4 + bob;

  // 头发外轮廓
  rect(buf, w, cx - 6, top, 12, 4, PAL.hair);
  rect(buf, w, cx - 7, top + 2, 14, 8, PAL.hair);
  // 脸
  rect(buf, w, cx - 5, top + 4, 10, 7, PAL.skin);
  rect(buf, w, cx - 5, top + 10, 10, 1, PAL.skinShade);
  // 刘海
  rect(buf, w, cx - 6, top + 3, 12, 2, PAL.hair);
  px(buf, w, cx - 4, top + 5, PAL.hairHi);
  // 眼睛
  px(buf, w, cx - 3, top + 7, PAL.hair);
  px(buf, w, cx + 2, top + 7, PAL.hair);
  // 侧发
  rect(buf, w, cx - 7, top + 4, 2, 9, PAL.hair);
  rect(buf, w, cx + 5, top + 4, 2, 9, PAL.hair);

  // 身体 / 巫女服
  const by = top + 12;
  rect(buf, w, cx - 6, by, 12, 12, robe);
  rect(buf, w, cx - 6, by, 12, 2, PAL.white);
  rect(buf, w, cx - 2, by + 2, 4, 10, PAL.white);
  rect(buf, w, cx - 6, by + 9, 12, 3, robeHi);
  // 手臂
  rect(buf, w, cx - 8, by + 2, 2, 7, robe);
  rect(buf, w, cx + 6, by + 2, 2, 7, robe);
  rect(buf, w, cx - 8, by + 8, 2, 2, PAL.skin);
  rect(buf, w, cx + 6, by + 8, 2, 2, PAL.skin);

  // 腿，step 制造行走姿势
  const ly = by + 12;
  rect(buf, w, cx - 4 - step, ly, 3, 4, PAL.skin);
  rect(buf, w, cx + 1 + step, ly, 3, 4, PAL.skin);
  // 脚底始终落在同一基线，方便演示 feet 对齐
  rect(buf, w, cx - 5 - step, ly + 4, 4, 2, PAL.hair);
  rect(buf, w, cx + 1 + step, ly + 4, 4, 2, PAL.hair);
}

/** 带纯绿背景的 4x2 行走 sheet，模拟「AI 生成图恢复后」的状态。 */
export function buildHeroSheet() {
  const w = W * COLS;
  const h = H * ROWS;
  const buf = makeBuffer(w, h, PAL.bg);
  const bobs = [0, -1, 0, 1];
  const steps = [0, 1, 0, -1];
  for (let r = 0; r < ROWS; r += 1) {
    for (let c = 0; c < COLS; c += 1) {
      drawCharacter(buf, w, c * W, r * H, {
        bob: bobs[c],
        step: steps[c],
        robe: r === 0 ? PAL.robe : PAL.steelDark,
        robeHi: r === 0 ? PAL.robeHi : PAL.steel,
      });
    }
  }
  return { data: buf, width: w, height: h };
}

/** 同一 sheet 的已抠图版本。 */
export function buildHeroSheetClean() {
  const sheet = buildHeroSheet();
  const { data } = sheet;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] === PAL.bg[0] && data[i + 1] === PAL.bg[1] && data[i + 2] === PAL.bg[2]) {
      // 透明像素 RGB 归零——后端契约 §5.1
      data[i] = 0;
      data[i + 1] = 0;
      data[i + 2] = 0;
      data[i + 3] = 0;
    }
  }
  return sheet;
}

/** 拆出单帧（透明背景）。 */
export function buildHeroFrame(index) {
  const sheet = buildHeroSheetClean();
  const col = index % COLS;
  const row = Math.floor(index / COLS) % ROWS;
  const buf = makeBuffer(W, H);
  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) {
      const src = ((row * H + y) * sheet.width + (col * W + x)) * 4;
      const dst = (y * W + x) * 4;
      buf[dst] = sheet.data[src];
      buf[dst + 1] = sheet.data[src + 1];
      buf[dst + 2] = sheet.data[src + 2];
      buf[dst + 3] = sheet.data[src + 3];
    }
  }
  return { data: buf, width: W, height: H };
}

/** 武器图层：一柄可叠加的长枪。 */
export function buildWeaponFrame(index) {
  const buf = makeBuffer(W, H);
  const bob = [0, -1, 0, 1][index % 4];
  const y = 16 + bob;
  rect(buf, W, 22, y, 2, 18, PAL.wood);
  rect(buf, W, 21, y - 4, 4, 5, PAL.steel);
  rect(buf, W, 22, y - 6, 2, 3, PAL.steel);
  px(buf, W, 22, y - 7, PAL.glow);
  rect(buf, W, 21, y + 1, 4, 1, PAL.steelDark);
  return { data: buf, width: W, height: H };
}

/** 特效图层：一圈闪光。 */
export function buildEffectFrame(index) {
  const buf = makeBuffer(W, H);
  const phase = index % 4;
  const cx = 16;
  const cy = 22;
  const r = 6 + phase * 2;
  for (let a = 0; a < 32; a += 1) {
    const t = (a / 32) * Math.PI * 2;
    const x = Math.round(cx + Math.cos(t) * r);
    const y = Math.round(cy + Math.sin(t) * r * 0.6);
    const alpha = 255 - phase * 50;
    px(buf, W, x, y, [PAL.glow[0], PAL.glow[1], PAL.glow[2], alpha]);
  }
  return { data: buf, width: W, height: H };
}

export const DEMO = { W, H, COLS, ROWS, PAL };
