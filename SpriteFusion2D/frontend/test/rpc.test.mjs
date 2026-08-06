// RPC 契约测试 —— FRONTEND_PLAN.md §10「用假 sidecar 回放，覆盖成功、错误码、进度、取消、崩溃重启」
// 这些测试跑在真实的 Sidecar 客户端 + mock sidecar 之间，验证的是协议而不是界面。

import test from 'node:test';
import assert from 'node:assert/strict';
import Module, { createRequire } from 'node:module';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { Sidecar } = require(path.join(here, '..', 'electron', 'sidecar.js'));

function makeSidecar() {
  return new Sidecar({
    command: process.execPath,
    args: [path.join(here, '..', 'mock', 'mock-sidecar.mjs')],
  });
}

async function withSidecar(fn) {
  const sc = makeSidecar();
  sc.start();
  try {
    return await fn(sc);
  } finally {
    sc.stop();
  }
}

test('app.hello 返回符合信封形状的成功响应', async () => {
  await withSidecar(async (sc) => {
    const env = await sc.call('app.hello');
    assert.equal(env.ok, true);
    assert.equal(env.command, 'app.hello');
    assert.equal(env.result.schema_version, 1);
    assert.ok('metrics' in env, '信封必须带 metrics');
    assert.ok('warnings' in env, '信封必须带 warnings');
  });
});

test('未打开项目时访问资产返回退出码 3', async () => {
  await withSidecar(async (sc) => {
    await assert.rejects(
      () => sc.call('project.tree'),
      (e) => e.rpc.code === 3,
    );
  });
});

test('未知方法返回退出码 2', async () => {
  await withSidecar(async (sc) => {
    await assert.rejects(
      () => sc.call('no.such.method'),
      (e) => e.rpc.code === 2,
    );
  });
});

test('打开项目后可列资产树与帧', async () => {
  await withSidecar(async (sc) => {
    await sc.call('project.open', { path: path.join(tmpdir(), `sprite-workshop-rpc-${process.pid}`) });
    const tree = await sc.call('project.tree');
    assert.equal(tree.result.groups.length, 4);

    const frames = await sc.call('asset.frames', { asset: 'hero_walk' });
    assert.equal(frames.result.frames.length, 8);
    for (const f of frames.result.frames) {
      assert.ok(f.path.endsWith('.png'), '像素必须以文件路径交付，不进 JSON');
      assert.ok(typeof f.width === 'number' && typeof f.height === 'number');
    }
  });
});

test('慢操作会推送进度通知', async () => {
  await withSidecar(async (sc) => {
    const seen = [];
    sc.on('notification', (msg) => {
      if (msg.method === 'progress') seen.push(msg.params);
    });
    await sc.call('demo.slow', { steps: 4 });
    assert.ok(seen.length >= 4, `期望至少 4 条进度，实际 ${seen.length}`);
    assert.equal(seen.at(-1).done, 4);
    assert.equal(seen.at(-1).total, 4);
  });
});

test('取消慢操作返回部分成功码 6', async () => {
  await withSidecar(async (sc) => {
    const promise = sc.call('demo.slow', { steps: 20 });
    // 客户端 id 从 1 开始递增；这里唯一在飞的请求就是 1
    setTimeout(() => sc.cancel(1), 250);
    await assert.rejects(
      () => promise,
      (e) => e.rpc.code === 6,
    );
  });
});

test('后端进程被杀后，在飞请求以码 5 失败并自动重启', async () => {
  const sc = makeSidecar();
  const statuses = [];
  sc.on('status', (s) => statuses.push(s.status));
  sc.start();

  try {
    const promise = sc.call('demo.slow', { steps: 20 });
    setTimeout(() => sc.child?.kill(), 200);
    await assert.rejects(
      () => promise,
      (e) => e.rpc.code === 5,
    );
    assert.ok(statuses.includes('down'), '应当广播 down 状态');

    // 退避重启后应恢复可用
    await new Promise((r) => setTimeout(r, 1200));
    const env = await sc.call('app.hello');
    assert.equal(env.ok, true, '重启后应恢复服务');
  } finally {
    sc.stop();
  }
});

// spawn 成功 ≠ 后端可用：Python 侧 import 失败时进程照样起得来。
// 早先 start() 直接报 ready，界面会一直显示健康直到第一个请求 30s 超时。
test('ready 要等握手，spawn 成功不算就绪', async () => {
  const sc = makeSidecar();
  const statuses = [];
  sc.on('status', (s) => statuses.push(s.status));
  sc.start();

  try {
    assert.equal(sc.status, 'starting', 'spawn 之后不应立刻是 ready');
    await sc.call('app.hello');
    await new Promise((r) => setTimeout(r, 100)); // 让握手的回调落地
    assert.equal(sc.status, 'ready', '握手成功后才是 ready');
    assert.deepEqual(statuses.slice(0, 2), ['starting', 'ready']);
  } finally {
    sc.stop();
  }
});

test('握手不占用调用方的 id 序列', async () => {
  await withSidecar(async (sc) => {
    // 按 id 取消的调用方依赖这个：第一个用户请求必须拿到 1。
    assert.equal(sc.nextId, 1, '握手不应推进外部可见的 id');
    await sc.call('app.hello');
    assert.equal(sc.nextId, 2, '用户请求才推进 id');
  });
});

test('stop() 让在飞请求立刻以码 5 失败，而不是挂到超时', async () => {
  const sc = makeSidecar();
  sc.start();
  const started = Date.now();
  const promise = sc.call('demo.slow', { steps: 20 });
  setTimeout(() => sc.stop(), 200);
  await assert.rejects(
    () => promise,
    (e) => e.rpc.code === 5,
  );
  assert.ok(Date.now() - started < 5000, '不应等到 30s 超时');
});

test('stdout 出现非 JSON 时不崩溃', async () => {
  await withSidecar(async (sc) => {
    const logs = [];
    sc.on('log', (l) => logs.push(l));
    sc._onLine('这不是 JSON');
    const env = await sc.call('app.hello');
    assert.equal(env.ok, true, '协议违约后仍能继续服务');
    assert.ok(logs.some((l) => l.includes('协议违约')));
  });
});

// ------------------------------------------------------------- E01：安全文件对话框接口
//
// `electron` 不在这个开发环境的依赖里装（devDependency 但没跑过 npm install），
// main.js/preload.js 顶层都无条件 `require('electron')`，直接 require 会
// MODULE_NOT_FOUND。这里用 Module._resolveFilename 把 'electron' 这个请求
// 重定向到一个手写的假模块，只提供 main.js/preload.js 实际用到的那几个成员，
// 然后把真实源码原样加载进 Node，测的是真代码而不是重新实现一遍逻辑。
//
// app.whenReady() 故意返回一个永不 resolve 的 Promise：main.js 把
// startSidecar()/createWindow() 放在它的 .then() 里，测试不需要也不应该真的
// 起子进程或建窗口，只需要模块顶层的 ipcMain.handle(...) 注册跑完。

function setupElectronMocks() {
  const handlers = new Map();
  const dialogCalls = [];
  let dialogResult = { canceled: true, filePaths: [] };

  const rendererApi = {};
  const invokeCalls = [];

  const electronStub = {
    app: {
      whenReady: () => new Promise(() => {}), // 故意永不 resolve
      on: () => {},
      quit: () => {},
    },
    BrowserWindow: class FakeBrowserWindow {
      static getAllWindows() {
        return [];
      }
    },
    ipcMain: {
      handle: (channel, fn) => handlers.set(channel, fn),
    },
    dialog: {
      showOpenDialog: async (parentWin, options) => {
        dialogCalls.push({ parentWin, options });
        return dialogResult;
      },
    },
    protocol: {
      registerSchemesAsPrivileged: () => {},
      handle: () => {},
    },
    net: { fetch: () => {} },
    contextBridge: {
      exposeInMainWorld: (name, api) => {
        rendererApi[name] = api;
      },
    },
    ipcRenderer: {
      invoke: (channel, ...args) => {
        invokeCalls.push([channel, ...args]);
        return Promise.resolve(null);
      },
      on: () => {},
    },
  };

  const FAKE_ELECTRON_ID = '\0test-electron-stub';
  const originalResolveFilename = Module._resolveFilename;
  Module._resolveFilename = function (request, ...rest) {
    if (request === 'electron') return FAKE_ELECTRON_ID;
    return originalResolveFilename.call(this, request, ...rest);
  };
  Module._cache[FAKE_ELECTRON_ID] = {
    id: FAKE_ELECTRON_ID,
    filename: FAKE_ELECTRON_ID,
    loaded: true,
    exports: electronStub,
  };

  const mainPath = path.join(here, '..', 'electron', 'main.js');
  const preloadPath = path.join(here, '..', 'electron', 'preload.js');
  const mainExports = require(mainPath);
  require(preloadPath);

  // 两个真实文件已经用真实路径缓存进 require.cache 了，假的 'electron' 解析
  // 不再需要，立刻还原，不留全局副作用给同进程里其它测试文件。
  Module._resolveFilename = originalResolveFilename;
  delete Module._cache[FAKE_ELECTRON_ID];

  return {
    handlers,
    mainExports,
    rendererApi,
    invokeCalls,
    dialogCalls,
    setDialogResult: (result) => {
      dialogResult = result;
    },
    mainPath,
    preloadPath,
  };
}

const {
  handlers: ipcHandlers,
  mainExports,
  rendererApi,
  invokeCalls,
  dialogCalls,
  setDialogResult,
  preloadPath,
} = setupElectronMocks();

test('三个新对话框接口都已注册在 main.js 的 ipcMain 上', () => {
  for (const channel of ['dialog:newProjectDir', 'dialog:importImage', 'dialog:exportDir']) {
    assert.ok(ipcHandlers.has(channel), `缺少 ${channel} 的 ipcMain.handle`);
  }
});

test('newProjectDirDialog 取消时稳定返回 null', async () => {
  setDialogResult({ canceled: true, filePaths: [] });
  const result = await ipcHandlers.get('dialog:newProjectDir')({});
  assert.equal(result, null);
});

test('newProjectDirDialog 选中目录时原样返回路径，且不预先加白名单', async () => {
  const chosen = path.join(tmpdir(), 'sprite-workshop-new-project');
  dialogCalls.length = 0;
  setDialogResult({ canceled: false, filePaths: [chosen] });
  const result = await ipcHandlers.get('dialog:newProjectDir')({});
  assert.equal(result, chosen);
  assert.equal(dialogCalls.length, 1);
  assert.ok(
    dialogCalls[0].options.properties.includes('openDirectory'),
    '必须是目录选择对话框',
  );
  assert.equal(
    mainExports.isReadable(path.join(chosen, 'meta.json')),
    false,
    '项目还没真的 open，选目录这一步不应该扩大 px:// 白名单',
  );
});

test('importImageDialog 用图片扩展名过滤，取消时返回 null', async () => {
  dialogCalls.length = 0;
  setDialogResult({ canceled: true, filePaths: [] });
  const result = await ipcHandlers.get('dialog:importImage')({});
  assert.equal(result, null);
  assert.equal(dialogCalls.length, 1);
  const { options } = dialogCalls[0];
  assert.deepEqual(options.properties, ['openFile']);
  assert.equal(options.filters.length, 1);
  assert.deepEqual(options.filters[0].extensions, mainExports.IMPORT_IMAGE_EXTENSIONS);
  assert.ok(
    mainExports.IMPORT_IMAGE_EXTENSIONS.includes('png') &&
      mainExports.IMPORT_IMAGE_EXTENSIONS.includes('jpg'),
    '至少要覆盖 png/jpg 这类常见位图后缀',
  );
});

test('importImageDialog 选中文件时原样返回路径（含中文/空格），且不预先加白名单', async () => {
  const chosen = path.join(tmpdir(), '素材 图片.png');
  setDialogResult({ canceled: false, filePaths: [chosen] });
  const result = await ipcHandlers.get('dialog:importImage')({});
  assert.equal(result, chosen);
  assert.equal(
    mainExports.isReadable(chosen),
    false,
    '导入源文件在真正落盘到项目前不应该进 px:// 白名单',
  );
});

test('exportDirDialog 取消返回 null，选中目录时原样返回路径且不加白名单', async () => {
  setDialogResult({ canceled: true, filePaths: [] });
  assert.equal(await ipcHandlers.get('dialog:exportDir')({}), null);

  const chosen = path.join(tmpdir(), 'sprite-workshop-export dest 中文');
  dialogCalls.length = 0;
  setDialogResult({ canceled: false, filePaths: [chosen] });
  const result = await ipcHandlers.get('dialog:exportDir')({});
  assert.equal(result, chosen);
  assert.ok(dialogCalls[0].options.properties.includes('openDirectory'));
  assert.equal(
    mainExports.isReadable(chosen),
    false,
    '导出目录只写文件，不该出现在读白名单里',
  );
});

test('allowRoot 仍是唯一合法扩大白名单的入口，新对话框都没有绕开它', () => {
  const dir = path.join(tmpdir(), 'sprite-workshop-allow-check');
  assert.equal(mainExports.isReadable(path.join(dir, 'a.png')), false);
  mainExports.allowRoot(dir);
  assert.equal(
    mainExports.isReadable(path.join(dir, 'a.png')),
    true,
    '既有规则本身必须还工作：project.open 成功后 allowRoot 应该生效',
  );
});

test('preload 暴露给渲染进程的 workshop API 是最小接口面，新方法把调用原样转发到对应 IPC 频道', async () => {
  const api = rendererApi.workshop;
  assert.ok(api, 'preload 必须挂 window.workshop');

  const expectedKeys = [
    'call',
    'cancel',
    'restartSidecar',
    'openProjectDialog',
    'openFileDialog',
    'newProjectDirDialog',
    'importImageDialog',
    'exportDirDialog',
    'defaultProject',
    'on',
  ].sort();
  assert.deepEqual(
    Object.keys(api).sort(),
    expectedKeys,
    '渲染进程只应该看到这些接口，不多不少',
  );
  for (const key of expectedKeys) {
    assert.equal(typeof api[key], 'function', `${key} 必须是函数`);
  }

  invokeCalls.length = 0;
  await api.newProjectDirDialog();
  await api.importImageDialog();
  await api.exportDirDialog();
  assert.deepEqual(
    invokeCalls.map((c) => c[0]),
    ['dialog:newProjectDir', 'dialog:importImage', 'dialog:exportDir'],
    '三个新方法必须分别调用各自的 IPC 频道，不共用、不错位',
  );
  assert.ok(
    invokeCalls.every((c) => c.length === 1),
    '这三个接口不接受也不需要额外参数——参数注入面越小越安全',
  );
});

test('preload.js 源码不引入 fs/path/child_process：渲染进程零文件系统权限', () => {
  const source = readFileSync(preloadPath, 'utf8');
  for (const forbidden of ['fs', 'path', 'child_process']) {
    const pattern = new RegExp(`require\\(['"](?:node:)?${forbidden}['"]\\)`);
    assert.ok(!pattern.test(source), `preload.js 不应该 require('${forbidden}')`);
  }
});
