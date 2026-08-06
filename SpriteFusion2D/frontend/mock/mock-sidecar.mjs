#!/usr/bin/env node
// Mock sidecar：用 Node 实现 FRONTEND_PLAN.md §3.3 的 JSON-RPC 契约。
//
// 存在的唯一理由是让阶段 A 的前端在真实后端写出来之前可以被开发和验收。
// 它必须严格遵守契约的形状（信封、错误码、进度通知、cache/ 传图），
// 但不实现任何真实算法——将来换成 `python -m sprite_workshop.daemon --stdio`
// 时，前端一行都不用改。
//
// 协议：stdout 每行一个 JSON 对象；日志一律走 stderr。

import { createInterface } from 'node:readline';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import { encodePng } from './png.mjs';
import {
  DEMO,
  buildEffectFrame,
  buildHeroFrame,
  buildHeroSheet,
  buildHeroSheetClean,
  buildWeaponFrame,
} from './demo-assets.mjs';
import { createV2 } from './mock-v2.mjs';

const SCHEMA_VERSION = 1;

// 与后端计划 §9.5 的退出码一一对应。
const ERR = {
  USAGE: 2,
  NOT_FOUND: 3,
  FAILED: 4,
  BACKEND_UNAVAILABLE: 5,
  PARTIAL: 6,
  REFUSED: 7,
};

function log(...args) {
  process.stderr.write(`[mock-sidecar] ${args.join(' ')}\n`);
}

// ---------------------------------------------------------------- 演示项目

const state = {
  projectPath: null,
  cacheDir: null,
  revision: 12,
  opened: false,
};

const FRAME_TAGS = [
  ['walk', 'south'],
  ['walk', 'south'],
  ['walk', 'south'],
  ['walk', 'south'],
  ['walk', 'north'],
  ['walk', 'north'],
  ['walk', 'north'],
  ['walk', 'north'],
];

const ASSETS = {
  hero_source: {
    kind: 'source',
    label: '蝶子 原图',
    note: 'AI 生成，绿底 4x2 行走表',
    frames: 1,
    build: () => [{ id: 'hero_source', image: buildHeroSheet() }],
  },
  hero_recovered: {
    kind: 'asset',
    label: '蝶子 已恢复',
    note: 'optimized · 1x',
    frames: 1,
    build: () => [{ id: 'hero_recovered', image: buildHeroSheet() }],
  },
  hero_clean: {
    kind: 'asset',
    label: '蝶子 已抠图',
    note: 'lab · 容差 10 · 硬 alpha',
    frames: 1,
    build: () => [{ id: 'hero_clean', image: buildHeroSheetClean() }],
  },
  hero_walk: {
    kind: 'frameset',
    label: '蝶子 行走',
    note: 'grid 4x2 拆帧',
    frames: 8,
    build: () =>
      Array.from({ length: 8 }, (_, i) => ({
        id: `walk_${FRAME_TAGS[i][1] === 'south' ? 's' : 'n'}_${String(i % 4).padStart(2, '0')}`,
        image: buildHeroFrame(i),
        tags: FRAME_TAGS[i],
      })),
  },
  rifle: {
    kind: 'frameset',
    label: '长枪',
    note: '合成用图层',
    frames: 4,
    build: () =>
      Array.from({ length: 4 }, (_, i) => ({
        id: `rifle_${String(i).padStart(2, '0')}`,
        image: buildWeaponFrame(i),
        tags: ['weapon'],
      })),
  },
  spark_fx: {
    kind: 'frameset',
    label: '闪光特效',
    note: '含半透明像素',
    frames: 4,
    build: () =>
      Array.from({ length: 4 }, (_, i) => ({
        id: `spark_${String(i).padStart(2, '0')}`,
        image: buildEffectFrame(i),
        tags: ['fx'],
      })),
  },
};

const CLIPS = [
  { id: 'walk_south', label: '行走·南', loop: 'loop', frames: 4, durationMs: 120 },
  { id: 'walk_north', label: '行走·北', loop: 'loop', frames: 4, durationMs: 120 },
];

const HISTORY = [
  { revision: 12, operation: 'split', frames: 8, warnings: 0, at: '2026-08-03 14:22' },
  { revision: 11, operation: 'background.remove', frames: 1, warnings: 1, at: '2026-08-03 14:19' },
  { revision: 10, operation: 'recover', frames: 1, warnings: 0, at: '2026-08-03 14:15' },
  { revision: 9, operation: 'import', frames: 1, warnings: 0, at: '2026-08-03 14:12' },
];

// 缓存已写出的 PNG，避免重复编码。key -> 绝对路径
const written = new Map();

// 缓存必须落在**项目目录内**，和真 daemon 的 _cache_dir 一致。
// 否则主进程的路径白名单（只认项目根）会把预览图 403 掉——
// 契约的形状要一致，不只是 JSON 字段一致。
function ensureCache() {
  if (state.cacheDir) return state.cacheDir;
  const base = state.projectPath
    ? join(state.projectPath, 'cache', 'prev')
    : join(tmpdir(), 'sprite-workshop-mock', 'cache', 'prev');
  mkdirSync(base, { recursive: true });
  state.cacheDir = base;
  return base;
}

/** 打开/新建项目后缓存根会变，已写出的路径要作废重来。 */
function resetCache() {
  state.cacheDir = null;
  written.clear();
}

function writePng(key, image) {
  if (written.has(key)) return written.get(key);
  const dir = ensureCache();
  const file = join(dir, `${key}.png`);
  writeFileSync(file, encodePng(image.data, image.width, image.height));
  written.set(key, file);
  return file;
}

function framesOf(assetId) {
  const asset = ASSETS[assetId];
  if (!asset) return null;
  return asset.build().map((frame, index) => {
    const image = frame.image;
    return {
      id: frame.id,
      index,
      width: image.width,
      height: image.height,
      tags: frame.tags ?? [],
      durationMs: 120,
      // 契约：只回项目相对/绝对路径，像素不进 JSON
      path: writePng(`${assetId}__${frame.id}`, image),
    };
  });
}

// ---------------------------------------------------------------- 方法实现

const methods = {
  'app.hello': () => ({
    schema_version: SCHEMA_VERSION,
    backend: 'mock-sidecar (Node)',
    real_backend: false,
    note: 'sprite_workshop 尚未实现；本进程仅提供契约形状与演示数据',
  }),

  doctor: () => ({
    checks: [
      { name: 'Python', status: 'skip', detail: '未接入真实后端' },
      { name: 'Pillow', status: 'skip', detail: '未接入真实后端' },
      { name: 'Torch', status: 'skip', detail: '未接入真实后端' },
      { name: '可见设备', status: 'skip', detail: '未接入真实后端' },
      { name: 'atlas 后端 (rectpack)', status: 'skip', detail: '可选依赖' },
      { name: 'rembg 后端', status: 'skip', detail: '可选依赖' },
      { name: 'RPC 契约', status: 'ok', detail: `schema v${SCHEMA_VERSION} · stdio` },
      { name: '缓存目录', status: 'ok', detail: ensureCache() },
    ],
  }),

  'project.open': ({ path } = {}) => {
    if (!path) throw rpcError(ERR.USAGE, '缺少项目路径');
    state.projectPath = path;
    state.opened = true;
    resetCache();
    return {
      project_id: 'chouko',
      name: '蝶子',
      path,
      schema_version: SCHEMA_VERSION,
      head_revision: state.revision,
      defaults: { device: 'auto', algorithm: 'optimized', alpha_mode: 'hard' },
    };
  },

  'project.tree': () => {
    requireOpen();
    return {
      groups: [
        {
          id: 'sources',
          label: 'sources',
          items: listOf('source'),
        },
        { id: 'assets', label: 'assets', items: listOf('asset') },
        { id: 'framesets', label: 'frame sets', items: listOf('frameset') },
        {
          id: 'clips',
          label: 'clips',
          items: CLIPS.map((c) => ({
            id: c.id,
            label: c.label,
            note: `${c.frames} 帧 · ${c.loop}`,
            kind: 'clip',
            frames: c.frames,
          })),
        },
      ],
    };
  },

  'asset.frames': ({ asset } = {}) => {
    requireOpen();
    const frames = framesOf(asset);
    if (!frames) throw rpcError(ERR.NOT_FOUND, `资产不存在：${asset}`);
    return { asset, frames };
  },

  'history.list': () => {
    requireOpen();
    return { head_revision: state.revision, entries: HISTORY };
  },

  // 故意保留一个慢操作，用来验证进度通知与取消。
  'demo.slow': async ({ steps = 8 } = {}, ctx) => {
    for (let i = 1; i <= steps; i += 1) {
      if (ctx.cancelled) throw rpcError(ERR.PARTIAL, `已取消，完成 ${i - 1}/${steps}`);
      await sleep(120);
      ctx.progress(i, steps);
    }
    return { done: steps };
  },
};

function listOf(kind) {
  return Object.entries(ASSETS)
    .filter(([, a]) => a.kind === kind)
    .map(([id, a]) => ({ id, label: a.label, note: a.note, kind: a.kind, frames: a.frames }));
}

function requireOpen() {
  if (!state.opened) throw rpcError(ERR.NOT_FOUND, '尚未打开项目');
}

function rpcError(code, message, details = null) {
  const err = new Error(message);
  err.rpc = { code, message, details };
  return err;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- 传输层

const inflight = new Map();

function send(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

// V2 契约（描边 / 像素化 / 生成 / 视频 / 建项目导入）挂进同一张方法表。
// 必须在 send 定义之后装配：任务模型要主动往 stdout 发进度与完成通知。
const v2 = createV2({
  writePng,
  send,
  state,
  resetCache,
  assets: ASSETS,
  framesOf,
  build: {
    heroSheet: buildHeroSheet,
    heroFrame: buildHeroFrame,
    weaponFrame: buildWeaponFrame,
    effectFrame: buildEffectFrame,
  },
});
Object.assign(methods, v2.methods);

async function handle(msg) {
  const { id, method, params } = msg;

  if (method === '$cancel') {
    const ctx = inflight.get(params?.request);
    if (ctx) ctx.cancelled = true;
    return;
  }

  const impl = methods[method];
  if (!impl) {
    send({
      id,
      ok: false,
      command: method,
      error: { code: ERR.USAGE, message: `未知方法：${method}`, details: null },
    });
    return;
  }

  const started = Date.now();
  const ctx = {
    cancelled: false,
    progress: (done, total) => send({ method: 'progress', params: { request: id, done, total } }),
  };
  inflight.set(id, ctx);

  try {
    const result = await impl(params ?? {}, ctx);
    send({
      id,
      ok: true,
      command: method,
      project: state.projectPath,
      revision: state.opened ? state.revision : null,
      outputs: [],
      warnings: [],
      metrics: { elapsed_ms: Date.now() - started },
      result,
    });
  } catch (error) {
    const rpc = error.rpc ?? { code: ERR.FAILED, message: String(error.message), details: null };
    log('error', method, rpc.code, rpc.message);
    send({ id, ok: false, command: method, error: rpc });
  } finally {
    inflight.delete(id);
  }
}

function main() {
  if (process.argv.includes('--selftest')) return selftest();

  log(`started pid=${process.pid} node=${process.version}`);
  const rl = createInterface({ input: process.stdin });
  rl.on('line', (line) => {
    const text = line.trim();
    if (!text) return;
    let msg;
    try {
      msg = JSON.parse(text);
    } catch {
      log('malformed line dropped');
      return;
    }
    handle(msg);
  });
  rl.on('close', () => {
    log('stdin closed, exiting');
    process.exit(0);
  });
  return undefined;
}

function selftest() {
  const results = [];
  const check = (name, fn) => {
    try {
      fn();
      results.push(`  ok   ${name}`);
    } catch (e) {
      results.push(`  FAIL ${name}: ${e.message}`);
      process.exitCode = 1;
    }
  };

  check('app.hello 返回 schema 版本', () => {
    if (methods['app.hello']().schema_version !== 1) throw new Error('版本不符');
  });
  check('未打开项目时 project.tree 报 3', () => {
    try {
      methods['project.tree']();
    } catch (e) {
      if (e.rpc.code !== ERR.NOT_FOUND) throw new Error(`码不对 ${e.rpc.code}`);
      return;
    }
    throw new Error('本应抛错');
  });
  check('project.open 后可列树', () => {
    methods['project.open']({ path: join(tmpdir(), `sprite-workshop-selftest-${process.pid}`) });
    const tree = methods['project.tree']();
    if (tree.groups.length !== 4) throw new Error('分组数不对');
  });
  check('hero_walk 出 8 帧且都写出 PNG', () => {
    const { frames } = methods['asset.frames']({ asset: 'hero_walk' });
    if (frames.length !== 8) throw new Error(`帧数 ${frames.length}`);
    for (const f of frames) if (!f.path.endsWith('.png')) throw new Error('路径不是 png');
  });
  check('帧尺寸符合演示契约 32x40', () => {
    const { frames } = methods['asset.frames']({ asset: 'hero_walk' });
    if (frames[0].width !== DEMO.W || frames[0].height !== DEMO.H) throw new Error('尺寸不符');
  });
  check('不存在的资产报 3', () => {
    try {
      methods['asset.frames']({ asset: 'nope' });
    } catch (e) {
      if (e.rpc.code !== ERR.NOT_FOUND) throw new Error(`码不对 ${e.rpc.code}`);
      return;
    }
    throw new Error('本应抛错');
  });
  check('抠图版本透明像素 RGB 已归零', () => {
    const { data } = buildHeroSheetClean();
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] === 0 && (data[i] || data[i + 1] || data[i + 2])) {
        throw new Error('存在隐藏色');
      }
    }
  });

  process.stderr.write(`mock-sidecar selftest\n${results.join('\n')}\n`);
  return undefined;
}

main();
