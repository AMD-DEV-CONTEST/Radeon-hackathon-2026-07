'use strict';

const { app, BrowserWindow, ipcMain, dialog, protocol, net } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const { Sidecar } = require('./sidecar');

let win = null;
let sidecar = null;

// 允许渲染进程读取的目录白名单。后端返回的每个像素路径都要在这里面，
// 对应 FRONTEND_PLAN.md §9.1「主进程侧再校验一次路径」。
const readableRoots = new Set();

function allowRoot(dir) {
  if (dir) readableRoots.add(path.resolve(dir));
}

function isReadable(filePath) {
  const resolved = path.resolve(filePath);
  for (const root of readableRoots) {
    const rel = path.relative(root, resolved);
    if (rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))) return true;
  }
  return false;
}

function attachPixelUrls(items, method) {
  if (!Array.isArray(items)) return;
  for (const item of items) {
    for (const [key, value] of Object.entries(item)) {
      if (!key.toLowerCase().endsWith('path') || typeof value !== 'string') continue;
      if (!isReadable(value)) {
        process.stderr.write(`[px] 拒绝越界路径（${method}.${key}）：${value}\n`);
        continue;
      }
      const urlKey = key === 'path' ? 'url' : `${key.slice(0, -4)}Url`;
      item[urlKey] = `px://f/${Buffer.from(value, 'utf8').toString('base64url')}`;
    }
  }
}

// 自定义协议：渲染进程用 px://<base64url(abs path)> 引用像素文件，
// 从而无需给渲染进程任何 fs 权限。
// corsEnabled 是必需的：取色器要对画布调 getImageData，
// 没有它 px:// 会被当成跨源资源污染画布。
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'px',
    privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true },
  },
]);

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    backgroundColor: '#1b1b1b',
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });

  win.once('ready-to-show', () => win.show());
  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  // sidecar 早于窗口启动，渲染进程会错过最初那次状态广播，
  // 所以页面加载完成后补推一次当前状态。
  win.webContents.on('did-finish-load', () => {
    if (sidecar) pushStatus({ status: sidecar.status, detail: null });
  });

  // 截图模式：供开发期视觉回归与无人值守验证使用（FRONTEND_PLAN.md §10）。
  if (process.env.SW_CAPTURE) {
    win.webContents.on('did-finish-load', () => {
      setTimeout(async () => {
        if (process.env.SW_CAPTURE_JS) {
          await win.webContents.executeJavaScript(process.env.SW_CAPTURE_JS);
          await new Promise((r) => setTimeout(r, 600));
        }
        const image = await win.webContents.capturePage();
        require('node:fs').writeFileSync(process.env.SW_CAPTURE, image.toPNG());
        process.stderr.write(`captured -> ${process.env.SW_CAPTURE}\n`);
        app.quit();
      }, Number(process.env.SW_CAPTURE_DELAY ?? 2500));
    });
  }

  // 把渲染进程的报错抬到 stderr，否则界面出错时这里一片安静
  win.webContents.on('console-message', (event) => {
    if (event.level === 'error' || event.level === 'warning') {
      process.stderr.write(`[renderer:${event.level}] ${event.message}\n`);
    }
  });
  win.webContents.on('render-process-gone', (_e, details) => {
    process.stderr.write(`[renderer gone] ${JSON.stringify(details)}\n`);
  });

  // 禁止导航到外部内容
  win.webContents.on('will-navigate', (event) => event.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
}

function pushStatus(payload) {
  if (win && !win.isDestroyed()) win.webContents.send('sidecar:status', payload);
}

function startSidecar() {
  sidecar = new Sidecar();
  sidecar.on('status', pushStatus);
  sidecar.on('log', (line) => {
    process.stderr.write(`${line}\n`);
    if (win && !win.isDestroyed()) win.webContents.send('sidecar:log', line);
  });
  sidecar.on('notification', (msg) => {
    // 异步生成结果不经过 rpc:call，候选图路径必须在通知转发前走同一套
    // 白名单校验与 px:// 转换。
    attachPixelUrls(msg?.params?.result?.candidates, `${msg.method}.candidates`);
    if (win && !win.isDestroyed()) win.webContents.send('sidecar:notification', msg);
  });
  sidecar.start();
}

app.whenReady().then(() => {
  protocol.handle('px', (request) => {
    // 必须走 pathname：URL 规范会把 hostname 强制小写，而 base64url 区分大小写。
    const encoded = new URL(request.url).pathname.replace(/^\/+/, '');
    let filePath;
    try {
      filePath = Buffer.from(encoded, 'base64url').toString('utf8');
    } catch {
      return new Response('bad path', { status: 400 });
    }
    if (!isReadable(filePath)) {
      return new Response('path outside allowed roots', { status: 403 });
    }
    return net.fetch(pathToFileURL(filePath).toString()).then(
      (res) =>
        new Response(res.body, {
          status: res.status,
          headers: { 'content-type': 'image/png', 'access-control-allow-origin': '*' },
        }),
      // 没有这个分支时，文件被外部删掉会变成 unhandled rejection 而不是 404。
      (error) => new Response(String(error?.message ?? error), { status: 404 }),
    );
  });

  startSidecar();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (sidecar) sidecar.stop();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (sidecar) sidecar.stop();
});

// ------------------------------------------------------------------ IPC

ipcMain.handle('rpc:call', async (_event, { method, params }) => {
  try {
    const envelope = await sidecar.call(method, params);
    const result = envelope.result;

    // 信任锚点只有一个：用户自己选中/配置的项目根，外加后端为 project.open
    // 确认的那个根。除此之外，后端返回的路径一律只被「校验」，不被「采信」。
    // 早先这里对每个 *path 字段做 allowRoot(dirname)，等于让后端自己给自己
    // 发通行证 —— 一个手工改过 meta.json 的项目就能把仓库外的文件喂进渲染
    // 进程。frame.id 现在在 Python 侧也过 validate_id，这里是第二道。
    if (method === 'project.open' && result && typeof result.path === 'string') {
      allowRoot(result.path);
    }

    attachPixelUrls(result?.frames, `${method}.frames`);
    attachPixelUrls(result?.candidates, `${method}.candidates`);
    return { ok: true, envelope };
  } catch (error) {
    return { ok: false, error: error.rpc ?? { code: 4, message: String(error.message) } };
  }
});

ipcMain.handle('rpc:cancel', (_event, requestId) => {
  sidecar.cancel(requestId);
  return true;
});

ipcMain.handle('app:defaultProject', () => {
  // Convenience for development: a project to open on launch.  Configured per
  // machine, never stored in the project itself.
  try {
    const config = JSON.parse(
      require('node:fs').readFileSync(
        path.join(__dirname, '..', 'sidecar.config.json'),
        'utf8',
      ),
    );
    if (config.defaultProject) {
      const resolved = path.resolve(__dirname, '..', config.defaultProject);
      allowRoot(resolved);
      return resolved;
    }
  } catch {
    /* no config, no default */
  }
  return null;
});

ipcMain.handle('sidecar:restart', () => {
  sidecar.stop();
  sidecar.start();
  return true;
});

// 用户自己选的文件是可信锚点，和项目目录同级别：选中即加入白名单。
ipcMain.handle('dialog:openFile', async (_event, { title, extensions } = {}) => {
  const result = await dialog.showOpenDialog(win, {
    title: title ?? '选择文件',
    properties: ['openFile'],
    filters: extensions?.length ? [{ name: '支持的文件', extensions }] : undefined,
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  const file = result.filePaths[0];
  allowRoot(path.dirname(file));
  return file;
});

ipcMain.handle('dialog:openProject', async () => {
  const result = await dialog.showOpenDialog(win, {
    title: '打开 Sprite Workshop 项目',
    properties: ['openDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  const dir = result.filePaths[0];
  allowRoot(dir);
  return dir;
});

// 常见位图后缀。只是对话框层的过滤器，不是后端解码能力声明——
// 真正能不能导入由 Python 侧的 Pillow 决定。
const IMPORT_IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp', 'tga'];

// 选新项目要放进哪个父目录。此刻项目还不存在，所以这里不 allowRoot：
// 白名单只在 rpc:call 里 project.open 真正成功后才按既有规则加入根目录，
// 避免用户随手点开的目录（哪怕最终没建成项目）也能读取。
ipcMain.handle('dialog:newProjectDir', async () => {
  const result = await dialog.showOpenDialog(win, {
    title: '选择新项目的位置',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// 选一张图片导入到当前项目。同样不在这里 allowRoot：源文件在项目目录之外，
// 真正可信的是 asset.import 落盘到项目里之后的帧路径，那些路径走 attachPixelUrls
// 已有的 isReadable 校验。
ipcMain.handle('dialog:importImage', async () => {
  const result = await dialog.showOpenDialog(win, {
    title: '选择要导入的图片',
    properties: ['openFile'],
    filters: [{ name: '图片', extensions: IMPORT_IMAGE_EXTENSIONS }],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// 选导出目标目录。导出只写文件，不需要读权限，所以不 allowRoot。
ipcMain.handle('dialog:exportDir', async () => {
  const result = await dialog.showOpenDialog(win, {
    title: '选择导出目录',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// 测试专用导出面：Electron 把这个文件当入口脚本直接执行，从不读取
// module.exports，所以这里追加导出不影响运行时行为；只是让 rpc.test.mjs
// 能在不起真实 Electron 的情况下校验白名单没有被新接口意外扩大。
module.exports = { isReadable, allowRoot, readableRoots, IMPORT_IMAGE_EXTENSIONS };
