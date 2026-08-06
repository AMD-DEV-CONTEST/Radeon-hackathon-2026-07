// 视频转动帧面板 —— FRONTEND_PLAN_V2.md §3.4
//
// 流程比其他面板长，所以用**分步条**而不是一堆参数堆在一起。
// 处理完自动跳到动画预览播放——那是这个功能唯一的验收界面。

import { advanced, field, picker, presetRow, slider } from './panel-kit.js';
import { jobs } from './jobs.js';
import { rpc } from './rpc.js';
import { h, toast } from './views.js';

const FPS_PRESETS = [
  { id: '6', label: '6', value: 6 },
  { id: '8', label: '8', value: 8 },
  { id: '12', label: '12', value: 12 },
  { id: '24', label: '24', value: 24 },
];

export class VideoPanel {
  constructor(root, { onImported, onPickFile }) {
    this.root = root;
    this.onImported = onImported;
    this.onPickFile = onPickFile;
    this.probe = null;
    this.range = { from: 0, to: 0 };
    this.settings = { fps: 8, targetWidth: 64, palette: 'auto', paletteStats: 'diff', dither: 'none' };
  }

  mount() {
    this.root.replaceChildren();

    this.fileBar = h('div', { class: 'kit-row' }, [
      h('button', { class: 'px-btn px-btn--sm', text: '选择视频…', onclick: () => this._pick() }),
      h('span', { class: 'kit-hint', text: '也可以直接把视频拖进窗口' }),
    ]);

    this.timeline = h('div', { class: 'vid-timeline' });
    this.rangeLabel = h('div', { class: 'kit-hint', text: '' });
    this.step1 = this._step('① 选片段', [this.timeline, this.rangeLabel]);

    this.fpsPresets = presetRow(FPS_PRESETS, '8', (p) => {
      this.settings.fps = p.value;
      this._updateEstimate();
    });
    this.fpsHint = h('div', { class: 'kit-hint', text: '' });
    this.step2 = this._step('② 目标帧率', [this.fpsPresets, this.fpsHint]);

    this.widthSlider = slider(64, { min: 16, max: 256, step: 8 }, (v) => { this.settings.targetWidth = v; });
    this.palettePick = picker(
      [
        { id: 'auto', label: '自动学习' },
        { id: 'gameboy', label: 'Game Boy' },
        { id: 'pico8', label: 'PICO-8' },
        { id: 'nes', label: 'NES' },
      ],
      'auto',
      (v) => { this.settings.palette = v; },
    );
    this.statsPick = picker(
      [
        { id: 'diff', label: '偏重运动主体（推荐）' },
        { id: 'full', label: '全画面均衡' },
      ],
      'diff',
      (v) => { this.settings.paletteStats = v; },
    );
    this.step3 = this._step('③ 像素化设置', [
      field('输出宽度', null, this.widthSlider),
      field('调色板', null, this.palettePick),
      advanced([
        field('调色板取样', '静态背景会白白吃掉色位，偏重运动主体通常更好', this.statsPick),
      ]),
    ]);

    this.runButton = h('button', { class: 'px-btn px-btn--accent', text: '开始处理', onclick: () => this._run() });
    this.runButton.disabled = true;
    this.status = h('div', { class: 'kit-status', text: '' });
    this.resultCard = h('div', { class: 'vid-result' });
    this.resultCard.style.display = 'none';

    // 这两条是本功能能不能用的关键，必须在界面上体现（BACKEND_PLAN_V2.md §5.2）
    this.coherenceNote = h('div', { class: 'kit-hint' }, [
      h('div', { text: '整段共用一套颜色和一套网格，逐帧各算会让画面「沸腾」。' }),
    ]);

    this.root.append(
      this.fileBar,
      this.step1,
      this.step2,
      this.step3,
      this.coherenceNote,
      this.runButton,
      this.status,
      this.resultCard,
    );
  }

  _step(title, children) {
    return h('div', { class: 'vid-step' }, [h('div', { class: 'vid-step__head', text: title }), ...children]);
  }

  async _pick() {
    const path = await this.onPickFile?.();
    if (path) await this.load(path);
  }

  /** 由面板自身或窗口拖放调用。 */
  async load(path) {
    this.status.textContent = '读取视频信息…';
    const reply = await rpc.call('video.probe', { path });
    if (!reply.ok) {
      this.status.textContent = reply.error?.code === 2 ? '该功能后端尚未接入' : '读取失败';
      return;
    }
    this.probe = reply.result;
    this.range = { from: 0, to: this.probe.duration };
    this._renderTimeline();
    this._updateEstimate();
    this.runButton.disabled = false;
    this.status.textContent = '';
  }

  _renderTimeline() {
    this.timeline.replaceChildren();
    if (!this.probe) return;
    for (const t of this.probe.thumbnails ?? []) {
      this.timeline.appendChild(h('img', {
        class: 'vid-thumb',
        src: t.url,
        title: `${t.t}s`,
        onclick: () => {
          // 单击设起点，再单击靠后的设终点
          if (t.t < this.range.to) this.range.from = t.t;
          else this.range.to = t.t;
          this._updateEstimate();
        },
      }));
    }
  }

  _updateEstimate() {
    if (!this.probe) return;
    const span = Math.max(0, this.range.to - this.range.from);
    const frames = Math.max(1, Math.round(span * this.settings.fps));
    this.rangeLabel.textContent =
      `${this.range.from.toFixed(1)}s – ${this.range.to.toFixed(1)}s · 时长 ${span.toFixed(1)} 秒`;
    this.fpsHint.textContent =
      `预计 ${frames} 帧 · 原视频 ${this.probe.fps} fps · 像素动画常用 8–12 fps`;
  }

  async _run() {
    if (!this.probe) return;
    this.runButton.disabled = true;
    this.resultCard.style.display = 'none';
    this.status.textContent = '已提交…';

    const { job, promise, error } = await jobs.submit('video.import', {
      path: this.probe.path,
      from: this.range.from,
      to: this.range.to,
      ...this.settings,
    }, { label: '视频转动帧' });

    if (error) {
      this.status.textContent = error.code === 2 ? '该功能后端尚未接入' : '提交失败';
      this.runButton.disabled = false;
      return;
    }
    this.job = job;

    try {
      const { result } = await promise;
      this._renderResult(result);
      toast(`视频已转为 ${result.frames_kept} 帧`, { hint: '已切到动画预览' });
      this.onImported?.(result);
    } catch (e) {
      this.status.textContent = e.rpc?.code === 6 ? '已取消' : `失败：${e.message}`;
    } finally {
      this.job = null;
      this.runButton.disabled = false;
    }
  }

  /** 结果卡片：用几个数字让用户判断参数对不对，不需要理解算法。 */
  _renderResult(r) {
    this.status.textContent = '';
    this.resultCard.style.display = '';
    this.resultCard.replaceChildren(
      h('div', { class: 'vid-result__head', text: '处理完成' }),
      h('div', { class: 'vid-result__row', text: `${r.frames_decoded} 帧 → 去重后 ${r.frames_kept} 帧` }),
      h('div', { class: 'vid-result__row', text: `用了 ${r.colors_used} 种颜色` }),
      h('div', { class: 'vid-result__row', text: `网格 ${r.grid_step}px` }),
      h('div', { class: 'kit-hint', text: '背景在所有帧是同一个精确值，抠图可以用「完全相等」模式' }),
    );
  }
}
