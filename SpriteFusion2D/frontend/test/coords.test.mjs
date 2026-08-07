// 画布坐标单测 —— FRONTEND_PLAN.md §10
// 坐标往返一旦有偏差，取色、笔触、选区会全线错位，所以这里覆盖到边界与各 DPI。

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const C = await import(
  pathToFileURL(path.join(here, '..', 'renderer', 'js', 'coords.js')).href
);

const view = (zoomIndex, originX, originY) => ({
  zoomIndex,
  zoom: C.ZOOM_LEVELS[zoomIndex],
  originX,
  originY,
});

test('缩放档位只有 1/2/4/8/16/32，没有连续缩放', () => {
  assert.deepEqual(C.ZOOM_LEVELS, [1, 2, 4, 8, 16, 32]);
});

test('素材→屏幕→素材 往返在所有档位和偏移下精确', () => {
  for (let zi = 0; zi < C.ZOOM_LEVELS.length; zi += 1) {
    for (const [ox, oy] of [[0, 0], [7, 13], [-31, -64], [1000, -3]]) {
      const v = view(zi, ox, oy);
      for (const [x, y] of [[0, 0], [1, 1], [31, 39], [15, 22]]) {
        const s = C.imageToScreen(x, y, v);
        const back = C.screenToImage(s.x, s.y, v);
        assert.deepEqual(back, { x, y }, `zoom=${v.zoom} origin=${ox},${oy} p=${x},${y}`);
      }
    }
  }
});

test('像素格内任意位置都映射回同一个素材像素', () => {
  const v = view(3, 10, 20); // 8x
  const s = C.imageToScreen(5, 6, v);
  for (let dy = 0; dy < v.zoom; dy += 1) {
    for (let dx = 0; dx < v.zoom; dx += 1) {
      assert.deepEqual(C.screenToImage(s.x + dx, s.y + dy, v), { x: 5, y: 6 });
    }
  }
});

test('原点左上方的坐标得到负数而不是被截断为 0', () => {
  const v = view(2, 100, 100); // 4x
  assert.deepEqual(C.screenToImage(99, 99, v), { x: -1, y: -1 });
  assert.deepEqual(C.screenToImage(96, 96, v), { x: -1, y: -1 });
  assert.deepEqual(C.screenToImage(95, 95, v), { x: -2, y: -2 });
});

test('inBounds 使用半开区间，右下边界不含', () => {
  assert.equal(C.inBounds({ x: 0, y: 0 }, 32, 40), true);
  assert.equal(C.inBounds({ x: 31, y: 39 }, 32, 40), true);
  assert.equal(C.inBounds({ x: 32, y: 39 }, 32, 40), false);
  assert.equal(C.inBounds({ x: 31, y: 40 }, 32, 40), false);
  assert.equal(C.inBounds({ x: -1, y: 0 }, 32, 40), false);
});

test('锚点缩放后，锚点下的素材像素仍在锚点下', () => {
  let v = view(1, 5, 9); // 2x
  const anchor = { x: 137, y: 211 };
  const before = C.screenToImage(anchor.x, anchor.y, v);

  for (const delta of [1, 1, 1, -1, 1, -1, -1]) {
    const next = C.zoomAt(v, anchor.x, anchor.y, delta);
    v = { ...next };
    const after = C.screenToImage(anchor.x, anchor.y, v);
    assert.deepEqual(after, before, `zoom=${v.zoom} 后锚点漂移`);
  }
});

test('缩放到端点时返回原对象，不越界', () => {
  const top = view(C.ZOOM_LEVELS.length - 1, 0, 0);
  assert.equal(C.zoomAt(top, 50, 50, 1), top);
  const bottom = view(0, 0, 0);
  assert.equal(C.zoomAt(bottom, 50, 50, -1), bottom);
});

test('缩放后的原点始终是整数（防 DPI 半像素漂移）', () => {
  let v = view(0, 0, 0);
  for (const anchor of [[333, 177], [12, 999], [1, 1]]) {
    for (const delta of [1, 1, 1, 1, 1, -1, -1]) {
      v = { ...C.zoomAt(v, anchor[0], anchor[1], delta) };
      assert.equal(Number.isInteger(v.originX), true, `originX=${v.originX}`);
      assert.equal(Number.isInteger(v.originY), true, `originY=${v.originY}`);
    }
  }
});

test('fit 选出能整体放下的最大档位', () => {
  // 32x40 素材放进 960x660，留 24 边距：16x 需要 512x640，纵向 640 > 636，故退到 8x
  assert.equal(C.ZOOM_LEVELS[C.fitZoomIndex(32, 40, 960, 660, 24)], 8);
  // 视口变高后 16x 放得下
  assert.equal(C.ZOOM_LEVELS[C.fitZoomIndex(32, 40, 960, 700, 24)], 16);
  // 超大素材退到 1x 而不是负档位
  assert.equal(C.ZOOM_LEVELS[C.fitZoomIndex(4096, 4096, 800, 600, 0)], 1);
});

test('居中原点为整数且左右留白差不超过 1', () => {
  for (const [w, h, vw, vh, zi] of [
    [32, 40, 961, 661, 3],
    [128, 80, 800, 600, 2],
    [7, 7, 101, 101, 0],
  ]) {
    const zoom = C.ZOOM_LEVELS[zi];
    const o = C.centerOrigin(w, h, zoom, vw, vh);
    assert.equal(Number.isInteger(o.originX), true);
    assert.equal(Number.isInteger(o.originY), true);
    const leftGap = o.originX;
    const rightGap = vw - (o.originX + w * zoom);
    assert.ok(Math.abs(leftGap - rightGap) <= 1, `左右留白差 ${leftGap} vs ${rightGap}`);
  }
});
