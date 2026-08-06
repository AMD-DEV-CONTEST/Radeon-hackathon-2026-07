// 程序化生成 Minecraft 风材质，避免仓库里塞二进制贴图。
// 用固定种子，保证每次启动像素完全一致（视觉回归测试需要）。

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * 生成一块半透明噪点材质，返回 data URL。
 *
 * 关键是**半透明**：材质叠在 background-color 之上，底色透上来。
 * 早先这里生成的是不透明像素，于是 .px-btn--on / --accent / --danger 设的
 * background-color 被材质整块盖住，所有状态色都不显示。
 */
function noiseTile(amplitude, seed, size = 32) {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(size, size);
  const rand = mulberry32(seed);

  for (let i = 0; i < size * size; i += 1) {
    // 量化到 4 档，避免出现连续渐变的观感（§4.3 禁渐变）
    const step = Math.floor(rand() * 4) - 1.5;
    const d = (step / 1.5) * amplitude;
    const light = d >= 0;
    img.data[i * 4] = light ? 255 : 0;
    img.data[i * 4 + 1] = light ? 255 : 0;
    img.data[i * 4 + 2] = light ? 255 : 0;
    img.data[i * 4 + 3] = Math.round(Math.abs(d));
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL('image/png');
}

/** 中性棋盘格。画布视口内不许有风格，所以这里只有灰阶（§4.1）。 */
function checkerTile(a, b, cell = 8) {
  const canvas = document.createElement('canvas');
  canvas.width = cell * 2;
  canvas.height = cell * 2;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = a;
  ctx.fillRect(0, 0, cell * 2, cell * 2);
  ctx.fillStyle = b;
  ctx.fillRect(0, 0, cell, cell);
  ctx.fillRect(cell, cell, cell, cell);
  return canvas.toDataURL('image/png');
}

export function installTextures() {
  const root = document.documentElement;
  const css = getComputedStyle(root);
  const pick = (name, fallback) => (css.getPropertyValue(name) || fallback).trim();

  // 幅度即噪点的不透明度上限，越大颗粒越明显。底色一律由 background-color 提供。
  root.style.setProperty('--tex-stone', `url("${noiseTile(38, 1337)}")`);
  root.style.setProperty('--tex-face', `url("${noiseTile(20, 4242)}")`);
  root.style.setProperty('--tex-deep', `url("${noiseTile(26, 9001)}")`);
  root.style.setProperty(
    '--tex-checker',
    `url("${checkerTile(pick('--checker-a', '#4a4a4a'), pick('--checker-b', '#3a3a3a'))}")`,
  );
}
