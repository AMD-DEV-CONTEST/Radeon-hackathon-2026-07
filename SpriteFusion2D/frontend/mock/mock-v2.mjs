// V2 契约的 mock 实现：描边 / 像素化 / 生成 / 视频，外加解锁 GUI 的建项目与导入。
//
// 与 mock-sidecar.mjs 同样的定位：**只提供契约形状，不提供产品算法**。
// 但预览图是真算出来的（一个几十行的膨胀、一个几十行的降采样量化），
// 因为一个假的预览图没法验证界面——面板要显示的正是"后端算出来的样子"。
// 真后端接上后这些函数整体废弃，前端一行不用改（BACKEND_PLAN_V2.md §1）。
//
// 任务模型按 BACKEND_PLAN_V2.md §1.2：
//   长方法立刻返回 {job}，随后发 progress 通知，最后发 job.done。

const ERR = { USAGE: 2, NOT_FOUND: 3, FAILED: 4, BACKEND_UNAVAILABLE: 5, PARTIAL: 6, REFUSED: 7 };

function rpcError(code, message, details = null) {
  const err = new Error(message);
  err.rpc = { code, message, details };
  return err;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ================================================================ 像素工具
// 这些是为了让预览"看起来是真的"，不是产品算法。

/** 复制一份 {data,width,height}。 */
function cloneImage(img) {
  return { data: Uint8Array.from(img.data), width: img.width, height: img.height };
}

const NEIGH8 = [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]];
const NEIGH4 = [[0, -1], [-1, 0], [1, 0], [0, 1]];

/**
 * 外描边：alpha>0 的形状向外膨胀一圈，新增的像素染色。
 * `skipDiagonal` 时只有纯对角接触的像素不算——像素画里通常要跳过，
 * 否则 45° 边会长出锯齿（BACKEND_PLAN_V2.md §2.2）。
 */
function outlineImage(img, opts = {}) {
  const {
    thickness = 1,
    connectivity = 8,
    skipDiagonal = true,
    colorMode = 'fixed',
    color = [0, 0, 0],
    darken = 40,
  } = opts;

  let out = cloneImage(img);
  const { width: w, height: h } = img;
  let added = 0;

  for (let pass = 0; pass < Math.max(1, thickness); pass += 1) {
    const src = out;
    const dst = cloneImage(src);
    const neigh = connectivity === 4 ? NEIGH4 : NEIGH8;

    for (let y = 0; y < h; y += 1) {
      for (let x = 0; x < w; x += 1) {
        const i = (y * w + x) * 4;
        if (src.data[i + 3] > 0) continue; // 已经是实体，不描

        let orthoHit = null;
        let diagHit = null;
        for (const [dx, dy] of neigh) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
          const j = (ny * w + nx) * 4;
          if (src.data[j + 3] === 0) continue;
          if (dx === 0 || dy === 0) orthoHit = j;
          else if (diagHit === null) diagHit = j;
        }

        const hit = orthoHit ?? (skipDiagonal ? null : diagHit);
        if (hit === null) continue;

        let r; let g; let b;
        if (colorMode === 'darken-neighbor') {
          const k = 1 - darken / 100;
          r = Math.round(src.data[hit] * k);
          g = Math.round(src.data[hit + 1] * k);
          b = Math.round(src.data[hit + 2] * k);
        } else {
          [r, g, b] = color;
        }
        dst.data[i] = r;
        dst.data[i + 1] = g;
        dst.data[i + 2] = b;
        dst.data[i + 3] = 255;
        added += 1;
      }
    }
    out = dst;
  }

  return { image: out, added };
}

/** 描边像素的掩码图：供画布叠加层高亮用（与抠图面板同一套机制）。 */
function outlineMask(before, after) {
  const mask = cloneImage(after);
  for (let i = 0; i < mask.data.length; i += 4) {
    const isNew = before.data[i + 3] === 0 && after.data[i + 3] > 0;
    // 叠加层约定：alpha 低处才被染色，所以"新增"要写成 alpha=0
    mask.data[i + 3] = isNew ? 0 : 255;
  }
  return mask;
}

/**
 * 抠图：取边界众数色，擦掉容差内的像素。
 * `borderOnly` 时只擦与边界连通的部分——关掉会把角色内部的同色区域一起擦掉，
 * 这正是那个开关存在的理由，mock 也要如实复现，否则界面上验不出来。
 */
function removeBackground(img, opts = {}) {
  const { tolerance = 10, borderOnly = true, connectivity = 8, mode = 'lab' } = opts;
  const { width: w, height: h } = img;
  const at = (x, y) => (y * w + x) * 4;

  // 边界众数色
  const tally = new Map();
  const edge = [];
  for (let x = 0; x < w; x += 1) { edge.push([x, 0], [x, h - 1]); }
  for (let y = 1; y < h - 1; y += 1) { edge.push([0, y], [w - 1, y]); }
  for (const [x, y] of edge) {
    const i = at(x, y);
    if (img.data[i + 3] === 0) continue;
    const key = `${img.data[i]},${img.data[i + 1]},${img.data[i + 2]}`;
    tally.set(key, (tally.get(key) ?? 0) + 1);
  }
  let bestKey = null; let bestN = 0;
  for (const [k, n] of tally) if (n > bestN) { bestN = n; bestKey = k; }
  if (!bestKey) return { image: cloneImage(img), erased: 0, chosen: null, coverage: 0 };
  const [br, bg, bb] = bestKey.split(',').map(Number);

  // exact 模式容差无效；rgb/lab 都退化成距离阈值（mock 不做真正的 ΔE）
  const limit = mode === 'exact' ? 0 : tolerance * (mode === 'lab' ? 2.2 : 1.0);
  const near = (i) => {
    const dr = img.data[i] - br;
    const dg = img.data[i + 1] - bg;
    const db = img.data[i + 2] - bb;
    return Math.sqrt(dr * dr + dg * dg + db * db) <= limit;
  };

  const kill = new Uint8Array(w * h);
  if (borderOnly) {
    const stack = [];
    for (const [x, y] of edge) if (near(at(x, y))) { stack.push(x, y); kill[y * w + x] = 1; }
    const neigh = connectivity === 4 ? NEIGH4 : NEIGH8;
    while (stack.length) {
      const y = stack.pop();
      const x = stack.pop();
      for (const [dx, dy] of neigh) {
        const nx = x + dx;
        const ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
        if (kill[ny * w + nx]) continue;
        if (!near(at(nx, ny))) continue;
        kill[ny * w + nx] = 1;
        stack.push(nx, ny);
      }
    }
  } else {
    for (let p = 0; p < w * h; p += 1) if (near(p * 4)) kill[p] = 1;
  }

  const out = cloneImage(img);
  let erased = 0;
  for (let p = 0; p < w * h; p += 1) {
    if (!kill[p]) continue;
    const i = p * 4;
    out.data[i] = 0; out.data[i + 1] = 0; out.data[i + 2] = 0; out.data[i + 3] = 0;
    erased += 1;
  }
  const hex = `#${[br, bg, bb].map((c) => c.toString(16).padStart(2, '0')).join('')}`;
  return { image: out, erased, chosen: hex, coverage: bestN / edge.length };
}

const PALETTES = {
  auto: null,
  gameboy: [[15, 56, 15], [48, 98, 48], [139, 172, 15], [155, 188, 15]],
  pico8: [
    [0, 0, 0], [29, 43, 83], [126, 37, 83], [0, 135, 81],
    [171, 82, 54], [95, 87, 79], [194, 195, 199], [255, 241, 232],
    [255, 0, 77], [255, 163, 0], [255, 236, 39], [0, 228, 54],
    [41, 173, 255], [131, 118, 156], [255, 119, 168], [255, 204, 170],
  ],
  nes: [
    [124, 124, 124], [0, 0, 252], [0, 0, 188], [68, 40, 188],
    [148, 0, 132], [168, 0, 32], [168, 16, 0], [136, 20, 0],
    [80, 48, 0], [0, 120, 0], [0, 104, 0], [0, 88, 0],
    [0, 64, 88], [0, 0, 0], [188, 188, 188], [248, 248, 248],
  ],
};

/** sRGB -> 线性，区域平均要在线性光里做（BACKEND_PLAN_V2.md §4.2）。 */
const toLinear = (c) => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const toSrgb = (l) => {
  const s = l <= 0.0031308 ? l * 12.92 : 1.055 * l ** (1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(s * 255)));
};

/** 区域平均降采样 + 调色板量化。仍然不是产品算法，但足以让预览可信。 */
function pixelifyImage(img, opts = {}) {
  const { targetWidth = 64, palette = 'auto', colors = 16, dither = 'none' } = opts;
  const scale = img.width / targetWidth;
  const outW = Math.max(1, Math.round(targetWidth));
  const outH = Math.max(1, Math.round(img.height / scale));
  const out = { data: new Uint8Array(outW * outH * 4), width: outW, height: outH };

  for (let y = 0; y < outH; y += 1) {
    for (let x = 0; x < outW; x += 1) {
      const x0 = Math.floor(x * scale);
      const x1 = Math.min(img.width, Math.ceil((x + 1) * scale));
      const y0 = Math.floor(y * scale);
      const y1 = Math.min(img.height, Math.ceil((y + 1) * scale));
      let lr = 0; let lg = 0; let lb = 0; let la = 0; let n = 0;
      for (let sy = y0; sy < y1; sy += 1) {
        for (let sx = x0; sx < x1; sx += 1) {
          const i = (sy * img.width + sx) * 4;
          lr += toLinear(img.data[i]);
          lg += toLinear(img.data[i + 1]);
          lb += toLinear(img.data[i + 2]);
          la += img.data[i + 3];
          n += 1;
        }
      }
      if (n === 0) n = 1;
      const o = (y * outW + x) * 4;
      out.data[o] = toSrgb(lr / n);
      out.data[o + 1] = toSrgb(lg / n);
      out.data[o + 2] = toSrgb(lb / n);
      out.data[o + 3] = Math.round(la / n) > 127 ? 255 : 0;
    }
  }

  const pal = PALETTES[palette] ?? null;
  const used = new Set();
  if (pal) {
    // 固定调色板：最近邻。dither 只影响是否加一点有序扰动。
    const bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
    for (let y = 0; y < outH; y += 1) {
      for (let x = 0; x < outW; x += 1) {
        const i = (y * outW + x) * 4;
        if (out.data[i + 3] === 0) continue;
        const bias = dither === 'bayer4' ? (bayer[y % 4][x % 4] / 16 - 0.5) * 32 : 0;
        let best = 0; let bestD = Infinity;
        for (let p = 0; p < pal.length; p += 1) {
          const dr = out.data[i] + bias - pal[p][0];
          const dg = out.data[i + 1] + bias - pal[p][1];
          const db = out.data[i + 2] + bias - pal[p][2];
          const d = dr * dr + dg * dg + db * db;
          if (d < bestD) { bestD = d; best = p; }
        }
        out.data[i] = pal[best][0];
        out.data[i + 1] = pal[best][1];
        out.data[i + 2] = pal[best][2];
        used.add(best);
      }
    }
  } else {
    // auto：粗暴地按位深截断当作"学出来的调色板"，只为得到一个颜色数
    const levels = Math.max(2, Math.round(Math.cbrt(colors)));
    const step = 255 / (levels - 1);
    for (let i = 0; i < out.data.length; i += 4) {
      if (out.data[i + 3] === 0) continue;
      for (let c = 0; c < 3; c += 1) {
        out.data[i + c] = Math.round(Math.round(out.data[i + c] / step) * step);
      }
      used.add(`${out.data[i]},${out.data[i + 1]},${out.data[i + 2]}`);
    }
  }

  return { image: out, colorsUsed: used.size };
}

// ================================================================ 装配

/**
 * @param deps.writePng   (key, image) => 绝对路径
 * @param deps.send       (obj) => void        直接往 stdout 发一行 JSON
 * @param deps.state      mock-sidecar 的共享状态
 * @param deps.assets     ASSETS 表（可写，生成/导入会往里加）
 * @param deps.framesOf   (assetId) => frames[]
 * @param deps.build      demo-assets 的构图函数
 */
export function createV2(deps) {
  const { writePng, send, state, resetCache, assets, framesOf, build } = deps;

  // ------------------------------------------------------------ 任务注册表
  let jobSeq = 0;
  const jobs = new Map();

  function newJob(label) {
    jobSeq += 1;
    const id = `job-${jobSeq}`;
    const job = { id, label, cancelled: false, done: false };
    jobs.set(id, job);
    return job;
  }

  function jobProgress(job, stage, done, total) {
    if (job.cancelled) return;
    send({ method: 'progress', params: { job: job.id, stage, done, total } });
  }

  function jobDone(job, result) {
    job.done = true;
    jobs.delete(job.id);
    send({ method: 'job.done', params: { job: job.id, ok: true, result } });
  }

  function jobFailed(job, code, message) {
    job.done = true;
    jobs.delete(job.id);
    send({ method: 'job.done', params: { job: job.id, ok: false, error: { code, message, details: null } } });
  }

  /** 跑一段带阶段的假工作，每个阶段之间检查取消。 */
  async function runStages(job, stages, finish) {
    try {
      for (const [stage, steps, perStep] of stages) {
        for (let i = 1; i <= steps; i += 1) {
          if (job.cancelled) {
            jobFailed(job, ERR.PARTIAL, `已取消（${stage}）`);
            return;
          }
          await sleep(perStep);
          jobProgress(job, stage, i, steps);
        }
      }
      if (job.cancelled) {
        jobFailed(job, ERR.PARTIAL, '已取消');
        return;
      }
      jobDone(job, await finish());
    } catch (error) {
      jobFailed(job, error.rpc?.code ?? ERR.FAILED, error.rpc?.message ?? String(error.message));
    }
  }

  function requireOpen() {
    if (!state.opened) throw rpcError(ERR.NOT_FOUND, '尚未打开项目');
  }

  function firstImageOf(assetId) {
    const asset = assets[assetId];
    if (!asset) throw rpcError(ERR.NOT_FOUND, `资产不存在：${assetId}`);
    return asset.build()[0].image;
  }

  let previewSeq = 0;

  // ------------------------------------------------------------ 方法表
  const methods = {
    // ---------------------------------------------------- 建项目 / 导入
    'project.create': ({ path, id, name } = {}) => {
      if (!path) throw rpcError(ERR.USAGE, '缺少项目路径');
      state.projectPath = path;
      state.opened = true;
      state.revision = 1;
      resetCache?.();
      return {
        project_id: id || 'untitled',
        name: name || '未命名项目',
        path,
        schema_version: 1,
        head_revision: 1,
        defaults: { device: 'auto', algorithm: 'optimized', alpha_mode: 'hard' },
      };
    },

    'asset.import': ({ path, as } = {}) => {
      requireOpen();
      if (!path) throw rpcError(ERR.USAGE, '缺少文件路径');
      const id = as || `imported_${Object.keys(assets).length}`;
      assets[id] = {
        kind: 'source',
        label: as || '导入的图片',
        note: String(path).split(/[\\/]/).pop(),
        frames: 1,
        build: () => [{ id, image: build.heroSheet() }],
      };
      state.revision += 1;
      return { asset: id, kind: 'source', revision: state.revision };
    },

    // 前端据此决定走 recover 还是 pixelify（BACKEND_PLAN_V2.md §3）
    'source.classify': ({ source } = {}) => {
      requireOpen();
      const looksPixel = /source|pixel|sheet/i.test(String(source ?? ''));
      return {
        kind: looksPixel ? 'pixel-art' : 'photo',
        confidence: looksPixel ? 0.92 : 0.31,
        detected_step: looksPixel ? 8 : null,
      };
    },

    // ---------------------------------------------------- 抠图
    // 原 mock 没有这两个方法（当时抠图只有真 daemon 有）。
    // 抠图现在是操作栈的一步，缺了整条栈就断。
    'background.analyze': (params = {}) => {
      requireOpen();
      const started = Date.now();
      const asset = params.asset;
      const src = firstImageOf(asset);
      const { image, erased, chosen, coverage } = removeBackground(src, params);
      previewSeq += 1;
      const key = `bg_${asset}_${previewSeq}`;
      // 遮罩语义：alpha 是「保留的形状」，低 alpha 处才被叠加层染色
      const mask = cloneImage(image);
      for (let i = 0; i < mask.data.length; i += 4) mask.data[i + 3] = image.data[i + 3] > 0 ? 255 : 0;
      const total = src.width * src.height;
      return {
        analysis: {
          chosen: chosen ? { color: chosen, border_coverage: coverage } : null,
          erased_pixels: erased,
          total_pixels: total,
          erased_ratio: total ? erased / total : 0,
          elapsed_ms: Date.now() - started,
        },
        frames: [{ id: asset, path: writePng(key, image), maskPath: writePng(`${key}_m`, mask) }],
        warnings: params.borderOnly === false
          ? [{ code: 'bg.internal', message: '关掉「只擦外围」会连主体内部的同色区域一起擦掉' }]
          : [],
      };
    },

    'background.apply': (params = {}) => {
      requireOpen();
      const asset = params.asset;
      const src = firstImageOf(asset);
      const { image } = removeBackground(src, params);
      const id = params.as || `${asset}_clean`;
      assets[id] = {
        kind: 'asset',
        label: `${assets[asset]?.label ?? asset} 已抠图`,
        note: `${params.mode ?? 'lab'} · 容差 ${params.tolerance ?? 10}`,
        frames: 1,
        build: () => [{ id, image }],
      };
      state.revision += 1;
      return { revision: state.revision, outputs: [id], warnings: [] };
    },

    // ---------------------------------------------------- 描边
    'outline.analyze': (params = {}) => {
      requireOpen();
      const started = Date.now();
      const asset = params.asset;
      const src = firstImageOf(asset);
      const { image, added } = outlineImage(src, params);
      previewSeq += 1;
      const key = `outline_${asset}_${previewSeq}`;
      return {
        analysis: {
          outline_pixels: added,
          total_pixels: src.width * src.height,
          elapsed_ms: Date.now() - started,
        },
        frames: [{
          id: asset,
          path: writePng(key, image),
          maskPath: writePng(`${key}_mask`, outlineMask(src, image)),
        }],
        warnings: params.thickness > 2
          ? [{ code: 'outline.thick', message: '粗描边会吃掉细结构' }]
          : [],
      };
    },

    'outline.apply': (params = {}) => {
      requireOpen();
      const asset = params.asset;
      const src = firstImageOf(asset);
      const { image } = outlineImage(src, params);
      const id = params.as || `${asset}_outlined`;
      assets[id] = {
        kind: 'asset',
        label: `${assets[asset]?.label ?? asset} 描边`,
        note: `${params.preset ?? 'custom'} · ${params.thickness ?? 1}px`,
        frames: 1,
        build: () => [{ id, image }],
      };
      state.revision += 1;
      return { revision: state.revision, outputs: [id], warnings: [] };
    },

    // ---------------------------------------------------- 像素化
    'pixelify.analyze': (params = {}) => {
      requireOpen();
      const started = Date.now();
      const asset = params.asset ?? params.source;
      const src = firstImageOf(asset);
      const { image, colorsUsed } = pixelifyImage(src, params);
      previewSeq += 1;
      const warnings = [];
      if (params.dither === 'floyd-steinberg') {
        warnings.push({ code: 'dither.fs', message: '误差扩散会打散色块，精灵图不推荐' });
      }
      return {
        analysis: {
          out_width: image.width,
          out_height: image.height,
          colors_used: colorsUsed,
          source_width: src.width,
          source_height: src.height,
          elapsed_ms: Date.now() - started,
        },
        frames: [{ id: asset, path: writePng(`pixelify_${asset}_${previewSeq}`, image) }],
        warnings,
      };
    },

    'pixelify.apply': (params = {}) => {
      requireOpen();
      const asset = params.asset ?? params.source;
      const src = firstImageOf(asset);
      const { image } = pixelifyImage(src, params);
      const id = params.as || `${asset}_px`;
      assets[id] = {
        kind: 'asset',
        label: `${assets[asset]?.label ?? asset} 像素化`,
        note: `${params.targetWidth ?? 64}px · ${params.palette ?? 'auto'}`,
        frames: 1,
        build: () => [{ id, image }],
      };
      state.revision += 1;
      return { revision: state.revision, outputs: [id], warnings: [] };
    },

    // ---------------------------------------------------- 生成
    'generate.providers': () => ({
      available: true,
      provider: 'mock',
      note: '真实实现走 ComfyUI HTTP API（BACKEND_PLAN_V2.md §6）',
      models: [
        { id: 'default', label: '默认' },
        { id: 'pixel_v3', label: '像素画 v3' },
        { id: 'anime_xl', label: '动漫 XL' },
      ],
      styles: [
        { id: 'pixel', label: '像素画' },
        { id: 'flat', label: '平涂插画' },
        { id: 'render3d', label: '3D 渲染感' },
      ],
    }),

    'generate.submit': (params = {}) => {
      requireOpen();
      const count = Math.max(1, Math.min(8, Number(params.count) || 4));
      const job = newJob('生成');
      runStages(job, [['排队中', 1, 300], ['采样', count * 4, 180], ['解码', count, 120]], async () => {
        const candidates = Array.from({ length: count }, (_, i) => {
          const image = build.heroFrame(i % 8);
          return {
            id: `cand_${job.id}_${i}`,
            seed: 100000 + i,
            path: writePng(`gen_${job.id}_${i}`, image),
          };
        });
        return { candidates, prompt: params.prompt ?? '', model: params.model ?? 'default' };
      });
      return { job: job.id, label: '生成' };
    },

    // 候选收入项目：真实实现会在这里自动接 recover（§6.4）
    'generate.commit': (params = {}) => {
      requireOpen();
      const picked = [].concat(params.candidates ?? []);
      if (picked.length === 0) throw rpcError(ERR.USAGE, '没有选中任何候选');
      const outputs = picked.map((_, i) => {
        const id = params.as ? (picked.length > 1 ? `${params.as}_${i}` : params.as) : `generated_${state.revision}_${i}`;
        assets[id] = {
          kind: 'asset',
          label: `生成 ${id}`,
          note: '已接 recover',
          frames: 1,
          build: () => [{ id, image: build.heroFrame(i % 8) }],
        };
        return id;
      });
      state.revision += 1;
      return { revision: state.revision, outputs, warnings: [], recovered: true };
    },

    // ---------------------------------------------------- 视频
    'video.probe': ({ path } = {}) => {
      if (!path) throw rpcError(ERR.USAGE, '缺少视频路径');
      return {
        path,
        duration: 4.0,
        fps: 30,
        width: 768,
        height: 512,
        thumbnails: Array.from({ length: 8 }, (_, i) => ({
          t: Number((i * 0.5).toFixed(2)),
          path: writePng(`vthumb_${i}`, build.heroFrame(i % 8)),
        })),
      };
    },

    'video.import': (params = {}) => {
      requireOpen();
      const from = Number(params.from ?? 0);
      const to = Number(params.to ?? 4);
      const fps = Number(params.fps ?? 8);
      const planned = Math.max(1, Math.round((to - from) * fps));
      const job = newJob('视频转动帧');
      // 阶段名按 FRONTEND_PLAN_V2.md §2.2：用户看到"学调色板"至少知道机器没死
      runStages(job, [
        ['解码', Math.min(planned, 12), 90],
        ['选帧', 3, 120],
        ['学调色板', 4, 200],
        ['量化', Math.min(planned, 12), 90],
        ['去重', 2, 150],
        ['写入', 2, 120],
      ], async () => {
        const kept = Math.max(1, Math.round(planned * 0.72));
        const id = params.as || `video_${state.revision}`;
        assets[id] = {
          kind: 'frameset',
          label: params.as || '视频动帧',
          note: `${kept} 帧 · ${fps}fps`,
          frames: kept,
          build: () => Array.from({ length: kept }, (_, i) => ({
            id: `${id}_${String(i).padStart(2, '0')}`,
            image: build.heroFrame(i % 8),
            tags: ['video'],
          })),
        };
        state.revision += 1;
        return {
          revision: state.revision,
          asset: id,
          clip: { id: `${id}_clip`, durationMs: Math.round(1000 / fps) },
          frames_decoded: planned,
          frames_kept: kept,
          colors_used: 24,
          grid_step: 6,
          palette_stats: params.paletteStats ?? 'diff',
        };
      });
      return { job: job.id, label: '视频转动帧' };
    },

    // ---------------------------------------------------- 任务控制
    'job.cancel': ({ job: id } = {}) => {
      const job = jobs.get(id);
      if (!job) throw rpcError(ERR.NOT_FOUND, `任务不存在：${id}`);
      job.cancelled = true;
      return { job: id, cancelled: true };
    },

    'job.list': () => ({
      jobs: [...jobs.values()].map((j) => ({ job: j.id, label: j.label })),
    }),
  };

  return { methods, outlineImage, pixelifyImage, PALETTES };
}
