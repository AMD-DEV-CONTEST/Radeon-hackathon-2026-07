// 应用装配 —— FRONTEND_PLAN.md 阶段 A
// 前端持有的是后端状态的投影，不是第二份真相（§3.4）。

import { installTextures } from './texture.js';
import { rpc } from './rpc.js';
import { createProject, importAsset } from './project-actions.js';
import { CanvasView, ZOOM_LEVELS } from './canvas-view.js';
import { BackgroundPanel } from './panel-background.js';
import { OutlinePanel } from './panel-outline.js';
import { PixelifyPanel } from './panel-pixelify.js';
import { GeneratePanel } from './panel-generate.js';
import { VideoPanel } from './panel-video.js';
import { PanelStack } from './panel-stack.js';
import { AnimView } from './anim-view.js';
import { jobs } from './jobs.js';
import { AssetTree, FrameBar, GridView, renderDoctor, renderHistory, toast } from './views.js';

const $ = (sel) => document.querySelector(sel);

// project-actions.js (E02) expects `dialogs.chooseProjectParent()` /
// `dialogs.chooseImportImage()`, but preload.js (E01) exposes those pickers
// as `window.workshop.newProjectDirDialog()` / `importImageDialog()`. The
// naming mismatch is a known seam between those two tasks (see
// docs/luna-workpack/TASK_GRAPH.md, E02 row) — this adapter is the one place
// that bridges it, so project-actions.js itself never has to know about it.
const projectDialogs = {
  chooseProjectParent: () => window.workshop.newProjectDirDialog(),
  chooseImportImage: () => window.workshop.importImageDialog(),
};

const state = {
  project: null,
  revision: null,
  asset: null,
  frames: [],
  frameIndex: 0,
  view: 'grid',
};

let tree;
let grid;
let framebar;
let canvasView;
let animView;
let stack;
let backgroundPanel;
const panels = {};

// ---------------------------------------------------------------- 启动

async function boot() {
  installTextures();
  wireChrome();
  wireViews();
  wireSidecarStatus();

  const hello = await rpc.call('app.hello');
  if (hello.ok) {
    setStatusText('backend', hello.result.backend);
    if (!hello.result.real_backend) {
      toast('当前连接的是 mock sidecar，数据为演示用途', { hint: hello.result.note });
    }
  }

  await refreshDoctor();

  // 有配置的默认项目就打开它，否则等用户点「打开项目」。
  const startup = await rpc.defaultProject();
  if (startup) {
    await openProject(startup);
  } else {
    setStatusText('project', '未打开项目 · 点右上角「打开项目」');
  }
}

// ---------------------------------------------------------------- chrome

function wireChrome() {
  $('#btn-open').addEventListener('click', async () => {
    const dir = await rpc.openProjectDialog();
    if (dir) await openProject(dir);
  });

  $('#btn-new-project').addEventListener('click', openNewProjectModal);
  $('#new-project-cancel').addEventListener('click', closeNewProjectModal);
  $('#new-project-confirm').addEventListener('click', submitNewProject);
  $('#new-project-modal').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitNewProject();
    if (e.key === 'Escape') closeNewProjectModal();
  });

  $('#btn-import-asset').addEventListener('click', async () => {
    const res = await importAsset({}, { rpc, dialogs: projectDialogs });
    if (!reportProjectActionFailure(res)) return;

    // 导入成功后刷新资产树并选中导入来源：把 state.asset 指到刚导入的资产，
    // reloadProject() 已有的「保留当前选中」逻辑就会自动选中它并加载帧——
    // 不额外维护第二套「当前资产」状态。
    state.asset = res.asset;
    await reloadProject(res.revision);
  });

  $('#btn-restart').addEventListener('click', async () => {
    await rpc.restart();
    toast('已请求重启后端');
  });

  $('#ui-scale').addEventListener('change', (e) => {
    document.documentElement.style.setProperty('--ui-scale', e.target.value);
    // 缩放改变后材质尺寸随之变化，但材质本身是像素图，无需重生成
    canvasView.render();
  });

  for (const btn of document.querySelectorAll('[data-view]')) {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  }

  // 撤销重做只是把后端的 head 挪一格，前端不维护第二套历史栈（§2.3 硬规则）
  $('#btn-undo').addEventListener('click', () => moveHistory('history.undo'));
  $('#btn-redo').addEventListener('click', () => moveHistory('history.redo'));

  for (const btn of document.querySelectorAll('[data-pane]')) {
    btn.addEventListener('click', () => switchPane(btn.dataset.pane));
  }
}

// ---------------------------------------------------------------- 新建项目 / 导入素材 (E03)

function openNewProjectModal() {
  $('#new-project-name').value = '';
  $('#new-project-modal').hidden = false;
  $('#new-project-name').focus();
}

function closeNewProjectModal() {
  $('#new-project-modal').hidden = true;
}

async function submitNewProject() {
  if ($('#new-project-modal').hidden) return;
  const name = $('#new-project-name').value;
  const res = await createProject({ name }, { rpc, dialogs: projectDialogs });
  // 取消（用户没选父目录）和校验/后端失败都保持弹窗开着：取消不弹提示，改完名字
  // 或重选目录可以直接重试，不用重新点「新建项目」。reportProjectActionFailure()
  // 负责区分「不弹」和「弹统一 toast」这两种失败。
  if (!reportProjectActionFailure(res)) return;

  closeNewProjectModal();
  await openProject(res.path);
}

/**
 * project-actions.js（E02）的失败结果分两种：
 *  - 走过 rpc.call() 的失败（后端拒绝、找不到项目等）：rpc.js 已经在 rpc.call()
 *    内部 dispatch 了 'error' 事件，wireSidecarStatus() 里的监听器已经弹过统一
 *    toast 了——这里再弹一次就是重复提示，靠 `error.title` 是否存在来判断
 *    （describeError() 对每个错误都会补上 title/hint，本地校验错误没有经过
 *    describeError，所以不会有 title）。
 *  - 从没调用 rpc 的本地校验失败（项目名为空、id 不合法）：从来没有触发过
 *    rpc.call() 的 'error' 事件，必须在这里自己弹一次统一 toast。
 * 取消（cancelled）不算失败，调用方应该在这之前就 return，不经过这个函数弹任何提示。
 *
 * @returns {boolean} true 表示成功，调用方可以继续走成功分支。
 */
function reportProjectActionFailure(res) {
  if (res.ok) return true;
  if (!res.cancelled && !('title' in (res.error ?? {}))) {
    toast(res.error?.message ?? '操作失败', { error: true, code: res.error?.code ?? null });
  }
  return false;
}

function switchPane(name) {
  for (const el of document.querySelectorAll('.pane__body[data-pane-name]')) {
    el.dataset.active = String(el.dataset.paneName === name);
  }
  for (const btn of document.querySelectorAll('[data-pane]')) {
    btn.setAttribute('aria-selected', String(btn.dataset.pane === name));
  }
}

async function moveHistory(method) {
  const reply = await rpc.call(method, { steps: 1 });
  if (!reply.ok) return;

  const { revision, changed, warnings } = reply.result;
  for (const warning of warnings) {
    toast(warning.message, { hint: warning.code });
  }
  if (!changed) toast('已经到头了');
  await reloadProject(revision);
}

function wireSidecarStatus() {
  const dot = $('#sidecar-dot');
  const text = $('#sidecar-text');
  const apply = ({ status, detail }) => {
    dot.className = `px-dot px-dot--${status === 'ready' ? 'ready' : status === 'down' ? 'down' : 'starting'}`;
    text.textContent =
      status === 'ready' ? '后端已连接' : status === 'down' ? '后端已断开' : '后端启动中';
    if (status === 'down' && detail) toast(detail, { error: true, code: 5, hint: '点「重启后端」重试' });
  };
  apply({ status: rpc.status });
  rpc.addEventListener('status', (e) => apply(e.detail));
  rpc.addEventListener('error', (e) => {
    const { code, title, message, hint } = e.detail;
    toast(`${title}：${message}`, { error: true, code, hint });
  });
}

// ---------------------------------------------------------------- 视图

function wireViews() {
  tree = new AssetTree($('#asset-tree'), {
    onSelect: (item) => loadAsset(item.id, item.kind),
  });

  grid = new GridView($('#grid-view'), {
    onSelect: (i) => selectFrame(i, { syncCanvas: false }),
    onOpen: (i) => {
      selectFrame(i);
      switchView('canvas');
    },
  });

  framebar = new FrameBar($('#framebar'), { onSelect: (i) => selectFrame(i) });

  // 画布必须先于面板构造：面板一挂上就可能回调预览
  canvasView = new CanvasView($('#canvas'));

  animView = new AnimView({
    img: $('#anim-img'),
    meta: $('#anim-meta'),
    playBtn: $('#btn-play'),
    prevBtn: $('#btn-prev'),
    nextBtn: $('#btn-next'),
    speedSelect: $('#anim-speed'),
  });

  buildStack();
  wireTaskBar();
  canvasView.addEventListener('cursor', (e) => {
    const { point, color } = e.detail;
    setStatusText('coord', point ? `${point.x}, ${point.y}` : '--, --');
    setStatusText('color', CanvasView.formatColor(color));
    const sw = $('#status-swatch');
    sw.style.backgroundColor = color && color.a > 0 ? `rgb(${color.r},${color.g},${color.b})` : 'transparent';
    sw.style.backgroundImage = color && color.a > 0 ? 'none' : 'var(--tex-checker)';
  });
  canvasView.addEventListener('viewchange', (e) => {
    const { zoom, width, height } = e.detail;
    setStatusText('canvas', width ? `${width}×${height}` : '--');
    setStatusText('zoom', `${zoom}x`);
    $('#zoom-range').value = String(ZOOM_LEVELS.indexOf(zoom));
  });
  canvasView.addEventListener('pick', (e) => {
    toast(`取色 ${CanvasView.formatColor(e.detail.color)}`, {
      hint: '阶段 D 接入调色板后，这里会直接写入当前色',
    });
  });

  $('#zoom-range').addEventListener('input', (e) => canvasView.setZoomIndex(Number(e.target.value)));
  $('#btn-fit').addEventListener('click', () => canvasView.fit());
  $('#btn-checker').addEventListener('click', (e) => {
    canvasView.toggleChecker();
    e.currentTarget.classList.toggle('px-btn--on', canvasView.lightChecker);
  });
  $('#btn-grid').addEventListener('click', (e) => {
    canvasView.toggleGrid();
    e.currentTarget.classList.toggle('px-btn--on', canvasView.showGrid);
  });
  $('#btn-grid').classList.add('px-btn--on');
}

function switchView(name) {
  state.view = name;
  for (const el of document.querySelectorAll('.view')) {
    el.dataset.active = String(el.dataset.viewName === name);
  }
  for (const btn of document.querySelectorAll('[data-view]')) {
    btn.setAttribute('aria-selected', String(btn.dataset.view === name));
  }
  // 用 display 而不是 visibility：隐藏的工具条若仍占横向空间，
  // 两条加起来会把中间列撑宽，进而挤掉右栏。
  $('#canvas-toolbar').style.display = name === 'canvas' ? '' : 'none';
  $('#anim-toolbar').style.display = name === 'anim' ? '' : 'none';
  if (name === 'canvas') canvasView.render();
  if (name === 'anim') animView.load(state.frames);
  else animView.pause();
}

// ---------------------------------------------------------------- 操作栈

/**
 * 按流水线顺序装配右栏。惰性挂载：面板首次展开时才构造，
 * 避免打开项目就发出五个面板的预览请求。
 */
function buildStack() {
  stack = new PanelStack($('#panel-stack'));

  const previewToCanvas = async ({ url, maskUrl }) => {
    // 预览只改画布显示，不动项目里的资产
    if (url) await canvasView.load(url, { keepView: true });
    await canvasView.setMaskOverlay(maskUrl);
    if (state.view !== 'canvas') switchView('canvas');
  };
  const afterApply = async () => { await reloadProject(); };

  stack.add({
    id: 'generate', index: 1, label: 'AI 生成', hint: '描述你想要的，挑中的才进项目',
    mount: (body) => {
      panels.generate = new GeneratePanel(body, { onCommitted: afterApply });
      panels.generate.mount();
    },
  });

  stack.add({
    id: 'video', index: 2, label: '视频转动帧', hint: '把一段视频变成像素动画',
    mount: (body) => {
      panels.video = new VideoPanel(body, {
        onPickFile: () => rpc.pickVideo?.(),
        onImported: async (result) => {
          await reloadProject();
          if (result?.asset) await loadAsset(result.asset, 'frameset');
          switchView('anim');
        },
      });
      panels.video.mount();
    },
  });

  stack.add({
    id: 'pixelify', index: 3, label: '像素化', hint: '把照片、插画、视频帧变成像素画',
    mount: (body) => {
      panels.pixelify = new PixelifyPanel(body, { onPreview: previewToCanvas, onApplied: afterApply });
      panels.pixelify.mount();
      panels.pixelify.setAsset(currentOperableAsset());
    },
    onOpen: () => panels.pixelify?.setAsset(currentOperableAsset()),
  });

  stack.add({
    id: 'background', index: 4, label: '抠图', hint: '把背景变透明',
    mount: (body) => {
      backgroundPanel = new BackgroundPanel(body, { onPreview: previewToCanvas, onApplied: afterApply });
      panels.background = backgroundPanel;
      backgroundPanel.setAsset(currentOperableAsset());
    },
    onOpen: () => backgroundPanel?.setAsset(currentOperableAsset()),
  });

  stack.add({
    id: 'outline', index: 5, label: '描边', hint: '沿边缘加一圈黑边，像素风的标志',
    mount: (body) => {
      panels.outline = new OutlinePanel(body, { onPreview: previewToCanvas, onApplied: afterApply });
      panels.outline.mount();
      panels.outline.setAsset(currentOperableAsset());
    },
    onOpen: () => panels.outline?.setAsset(currentOperableAsset()),
  });

  stack.open('background');
}

/** 抠图/描边/像素化只作用于已提交的资产，源文件和遮罩自己不算。 */
function currentOperableAsset() {
  const { asset, assetKind } = state;
  if (!asset) return null;
  if (assetKind === 'clip') return null;
  if (String(asset).endsWith('_mask')) return null;
  return asset;
}

// ---------------------------------------------------------------- 任务条

function wireTaskBar() {
  const bar = $('#task-bar');
  const text = $('#task-text');
  const fill = $('#task-fill');
  const cancel = $('#task-cancel');
  let currentId = null;

  cancel.addEventListener('click', () => { if (currentId) jobs.cancel(currentId); });

  jobs.addEventListener('change', () => {
    const active = jobs.active;
    if (active.length === 0) {
      bar.style.display = 'none';
      currentId = null;
      return;
    }
    const first = active[0];
    currentId = first.id;
    bar.style.display = '';
    const more = active.length > 1 ? `（还有 ${active.length - 1} 个）` : '';
    text.textContent = `${first.label} · ${first.stage}${first.total ? ` ${first.done}/${first.total}` : ''}${more}`;
    fill.style.width = `${Math.round((first.total ? first.done / first.total : 0) * 100)}%`;
  });
}

// ---------------------------------------------------------------- 数据

async function openProject(path) {
  const opened = await rpc.call('project.open', { path });
  if (!opened.ok) return;

  state.project = opened.result;
  state.revision = opened.result.head_revision;
  $('#title-name').textContent = `${opened.result.name} · ${opened.result.project_id}`;
  $('#title-rev').textContent = `revision ${opened.result.head_revision}`;
  setStatusText('project', opened.result.path);
  // 新建/打开都走这里：有项目可导入了，之前「无项目时 Import 禁用」的
  // 提示状态到此解除。
  $('#btn-import-asset').disabled = false;
  $('#btn-import-asset').title = '';

  const treeReply = await rpc.call('project.tree');
  if (treeReply.ok) {
    tree.render(treeReply.result.groups);
    const first = treeReply.result.groups.flatMap((g) => g.items).find((i) => i.kind !== 'clip');
    if (first) tree.select(first);
  }

  const hist = await rpc.call('history.list');
  if (hist.ok) renderHistory($('#history'), hist.result);
}

/** Re-read the tree, history and current asset after the head moved. */
async function reloadProject(revision = null) {
  const treeReply = await rpc.call('project.tree');
  if (treeReply.ok) {
    const items = treeReply.result.groups.flatMap((g) => g.items);
    tree.render(treeReply.result.groups);
    const current = items.find((i) => i.id === state.asset);
    if (current) {
      tree.selected = state.asset;
      await loadAsset(current.id, current.kind);
    } else {
      const first = items.find((i) => i.kind !== 'clip');
      if (first) tree.select(first);
      else {
        state.asset = null;
        await syncPanels();
      }
    }
  }

  const hist = await rpc.call('history.list');
  if (hist.ok) {
    renderHistory($('#history'), hist.result);
    $('#title-rev').textContent = `revision ${hist.result.head_revision}`;
    state.revision = hist.result.head_revision;
  } else if (revision !== null) {
    $('#title-rev').textContent = `revision ${revision}`;
  }
}

async function loadAsset(assetId, kind = 'asset') {
  const reply = await rpc.call('asset.frames', { asset: assetId });
  if (!reply.ok) return;

  state.asset = assetId;
  state.assetKind = kind;
  state.frames = reply.result.frames;
  state.frameIndex = 0;

  grid.selected = 0;
  grid.render(state.frames);
  framebar.selected = 0;
  framebar.render(state.frames);

  setStatusText('asset', `${assetId} · ${state.frames.length} 帧`);
  await selectFrame(0);

  await syncPanels();
}

/**
 * 把当前选中资产推给已挂载的面板。
 * 各面板的适用范围不同：像素化的输入本来就是原图（照片/插画），
 * 而抠图和描边只作用于已提交的资产——源文件还没进 assets/，
 * 遮罩自己也不需要再抠一次。
 */
async function syncPanels() {
  const { asset, assetKind } = state;
  const isMask = String(asset ?? '').endsWith('_mask');
  const committed = asset && assetKind !== 'source' && assetKind !== 'clip' && !isMask;
  const pixelifiable = asset && assetKind !== 'clip' && !isMask;

  backgroundPanel?.setAsset(committed ? asset : null);
  panels.outline?.setAsset(committed ? asset : null);
  panels.pixelify?.setAsset(pixelifiable ? asset : null);

  stack?.setEnabled('background', Boolean(committed), '先选一个已处理的资产');
  stack?.setEnabled('outline', Boolean(committed), '先选一个已处理的资产');
  stack?.setEnabled('pixelify', Boolean(pixelifiable), '先选一张图');

  // 像素化面板要显示"我们认为这是照片还是已有像素画"，并允许一键改判
  if (panels.pixelify && pixelifiable) {
    const reply = await rpc.call('source.classify', { source: asset });
    if (reply.ok) {
      panels.pixelify.setClassification(reply.result, () => {
        toast('修复（recover）面板尚未接入', { hint: '后端 recover.apply 待实现' });
      });
    } else {
      panels.pixelify.setClassification(null);
    }
  }
}

async function selectFrame(index, { syncCanvas = true } = {}) {
  if (!state.frames[index]) return;
  state.frameIndex = index;
  framebar.selected = index;
  for (const t of $('#framebar').querySelectorAll('.framebar__thumb')) {
    t.setAttribute('aria-selected', String(Number(t.dataset.index) === index));
  }

  const frame = state.frames[index];
  renderFrameInfo(frame);
  if (syncCanvas) await canvasView.load(frame.url, { keepView: true });
}

function renderFrameInfo(frame) {
  const root = $('#frame-info');
  root.replaceChildren();
  const rows = [
    ['帧 ID', frame.id],
    ['尺寸', `${frame.width} × ${frame.height}`],
    ['序号', `${frame.index}`],
    ['时长', `${frame.durationMs} ms`],
    ['标签', (frame.tags ?? []).join(' / ') || '（无）'],
  ];
  for (const [label, value] of rows) {
    const field = document.createElement('div');
    field.className = 'field';
    field.innerHTML = '';
    const l = document.createElement('div');
    l.className = 'field__label';
    l.textContent = label;
    const v = document.createElement('div');
    v.className = 'field__value';
    v.textContent = value;
    field.append(l, v);
    root.appendChild(field);
  }
}

async function refreshDoctor() {
  const reply = await rpc.call('doctor');
  if (reply.ok) renderDoctor($('#doctor'), reply.result.checks);
}

// ---------------------------------------------------------------- 状态栏

const statusSlots = {};

function setStatusText(slot, text) {
  if (!statusSlots[slot]) statusSlots[slot] = $(`#status-${slot}`);
  if (statusSlots[slot]) statusSlots[slot].textContent = text;
}

// 自动化钩子：供截图模式与后续 Playwright 端到端测试驱动界面（§10）。
// 只暴露视图操作，不暴露任何写项目的能力。
window.__sw = {
  state,
  switchView,
  loadAsset,
  selectFrame,
  get canvas() {
    return canvasView;
  },
  // V2：让截图模式和端到端测试能驱动操作栈与各面板。
  // 仍然只暴露视图操作——写项目要走面板上的按钮，不从这里开后门。
  get stack() {
    return stack;
  },
  get panels() {
    return panels;
  },
  get anim() {
    return animView;
  },
};

boot();
