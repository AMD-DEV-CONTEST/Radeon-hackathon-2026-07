// 画布坐标数学 —— 纯函数，不碰 DOM，便于单测（FRONTEND_PLAN.md §10）。
// 这里是整个画布视图正确性的核心：一旦往返有偏差，取色、笔触、选区全会错位。

export const ZOOM_LEVELS = [1, 2, 4, 8, 16, 32];

/** 设备像素 → 素材像素。落在素材外时返回的坐标也会越界，由调用方判断。 */
export function screenToImage(deviceX, deviceY, view) {
  return {
    x: Math.floor((deviceX - view.originX) / view.zoom),
    y: Math.floor((deviceY - view.originY) / view.zoom),
  };
}

/** 素材像素 → 该像素左上角的设备像素坐标。 */
export function imageToScreen(imgX, imgY, view) {
  return { x: view.originX + imgX * view.zoom, y: view.originY + imgY * view.zoom };
}

export function inBounds(p, width, height) {
  return p.x >= 0 && p.y >= 0 && p.x < width && p.y < height;
}

/**
 * 以锚点缩放：锚点下的素材像素在缩放前后停留在同一屏幕位置。
 * 原点必须取整，否则 150% DPI 下会累积出半像素漂移。
 */
export function zoomAt(view, deviceX, deviceY, delta) {
  const nextIndex = Math.max(0, Math.min(ZOOM_LEVELS.length - 1, view.zoomIndex + delta));
  if (nextIndex === view.zoomIndex) return view;

  const before = screenToImage(deviceX, deviceY, view);
  const zoom = ZOOM_LEVELS[nextIndex];
  return {
    zoomIndex: nextIndex,
    zoom,
    originX: Math.round(deviceX - before.x * zoom),
    originY: Math.round(deviceY - before.y * zoom),
  };
}

/** 选一个能整体放下的最大档位。放不下时退到 1x。 */
export function fitZoomIndex(imgW, imgH, viewportW, viewportH, margin = 0) {
  let best = 0;
  for (let i = 0; i < ZOOM_LEVELS.length; i += 1) {
    const z = ZOOM_LEVELS[i];
    if (imgW * z <= viewportW - margin && imgH * z <= viewportH - margin) best = i;
  }
  return best;
}

export function centerOrigin(imgW, imgH, zoom, viewportW, viewportH) {
  return {
    originX: Math.round((viewportW - imgW * zoom) / 2),
    originY: Math.round((viewportH - imgH * zoom) / 2),
  };
}
