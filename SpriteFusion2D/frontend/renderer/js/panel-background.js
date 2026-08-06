// 抠图面板 —— FRONTEND_PLAN.md 阶段 B 的第一个操作面板。
//
// 硬规则：前端不复算遮罩。每次参数变化都调后端的 background.analyze，
// 显示的是后端渲染进 cache/ 的真实结果，不是界面自己近似出来的东西。
// 这样「预览所见」和「提交所得」不可能分叉（FRONTEND_PLAN.md 13.1）。

import { rpc } from './rpc.js';
import { h, toast } from './views.js';

const PREVIEW_DEBOUNCE_MS = 180;

const MODE_HINTS = {
  exact: '颜色完全相等。纯色背景最快最稳，容差无效。',
  rgb: '加权 sRGB 距离，容差单位约等于 0–255 色差。',
  lab: '感知色差 ΔE，容差 10 上下适合大多数近似背景。',
};

export class BackgroundPanel {
  constructor(root, { onPreview, onApplied }) {
    this.root = root;
    this.onPreview = onPreview;
    this.onApplied = onApplied;

    this.asset = null;
    this.busy = false;
    this.pending = null;
    this.timer = null;
    this.lastAnalysis = null;

    this.settings = {
      mode: 'lab',
      samples: 'corners',
      tolerance: 10,
      connectivity: 8,
      borderOnly: true,
      minIslandArea: 0,
      maxHoleArea: 0,
      alpha: 'hard',
    };

    this._build();
    this.setAsset(null);
  }

  // ------------------------------------------------------------ 构建

  _build() {
    this.root.replaceChildren();

    this.modeSelect = h('select', { class: 'px-btn px-btn--sm' },
      Object.keys(MODE_HINTS).map((m) =>
        h('option', { value: m, text: m, selected: m === this.settings.mode ? '' : null }),
      ),
    );
    this.modeSelect.addEventListener('change', () => {
      this.settings.mode = this.modeSelect.value;
      this.modeHint.textContent = MODE_HINTS[this.settings.mode];
      this.toleranceRow.style.opacity = this.settings.mode === 'exact' ? '0.4' : '1';
      this._schedulePreview();
    });

    this.modeHint = h('div', { class: 'field__label', text: MODE_HINTS.lab });

    this.tolerance = h('input', {
      // 上限 100：干净的像素画在 0–60 之间常常毫无变化，够不到开始吃角色的
      // 那一段就看不出滑块在做什么。
      type: 'range', min: '0', max: '100', step: '1', value: String(this.settings.tolerance),
    });
    this.toleranceValue = h('b', { text: String(this.settings.tolerance) });
    this.tolerance.addEventListener('input', () => {
      this.settings.tolerance = Number(this.tolerance.value);
      this.toleranceValue.textContent = this.tolerance.value;
      this._schedulePreview();
    });
    this.toleranceRow = h('div', { class: 'px-slider' }, [
      this.tolerance,
      h('span', { class: 'px-slider__value' }, [this.toleranceValue]),
    ]);

    this.connButton = h('button', {
      class: 'px-btn px-btn--sm', text: '8 邻域',
      onclick: () => {
        this.settings.connectivity = this.settings.connectivity === 8 ? 4 : 8;
        this.connButton.textContent = `${this.settings.connectivity} 邻域`;
        this._schedulePreview();
      },
    });

    this.borderButton = h('button', {
      class: 'px-btn px-btn--sm px-btn--on', text: '仅边界连通',
      title: '关掉会连角色内部的同色区域一起擦掉',
      onclick: () => {
        this.settings.borderOnly = !this.settings.borderOnly;
        this.borderButton.classList.toggle('px-btn--on', this.settings.borderOnly);
        this._schedulePreview();
      },
    });

    this.alphaButton = h('button', {
      class: 'px-btn px-btn--sm', text: '硬 alpha',
      onclick: () => {
        this.settings.alpha = this.settings.alpha === 'hard' ? 'soft' : 'hard';
        this.alphaButton.textContent = this.settings.alpha === 'hard' ? '硬 alpha' : '软 alpha';
        this.alphaButton.classList.toggle('px-btn--on', this.settings.alpha === 'soft');
        this._schedulePreview();
      },
    });

    this.islandInput = this._numberField('去孤岛 <', 'minIslandArea');
    this.holeInput = this._numberField('填孔洞 ≤', 'maxHoleArea');

    this.overlayButton = h('button', {
      class: 'px-btn px-btn--sm px-btn--on', text: '标出擦除区',
      onclick: () => {
        this.showOverlay = !this.showOverlay;
        this.overlayButton.classList.toggle('px-btn--on', this.showOverlay);
        this._emitPreview();
      },
    });
    this.showOverlay = true;

    this.swatch = h('span', { class: 'swatch' });
    this.readout = h('div', { class: 'field__value', text: '—' });
    this.status = h('div', { class: 'field__label', text: '' });

    this.applyButton = h('button', {
      class: 'px-btn px-btn--accent', text: '应用到项目',
      onclick: () => this._apply(),
    });

    this.root.append(
      h('div', { class: 'field' }, [
        h('div', { class: 'field__label', text: '模式' }),
        this.modeSelect,
        this.modeHint,
      ]),
      h('div', { class: 'field' }, [
        h('div', { class: 'field__label', text: '容差' }),
        this.toleranceRow,
      ]),
      h('div', { class: 'field panel-row' }, [this.connButton, this.borderButton]),
      h('div', { class: 'field panel-row' }, [this.alphaButton, this.overlayButton]),
      h('div', { class: 'field panel-row' }, [this.islandInput.wrap, this.holeInput.wrap]),
      h('div', { class: 'field' }, [
        h('div', { class: 'field__label', text: '后端判定' }),
        h('div', { class: 'panel-row' }, [this.swatch, this.readout]),
        this.status,
      ]),
      h('div', { class: 'field' }, [this.applyButton]),
    );
  }

  _numberField(label, key) {
    const input = h('input', {
      class: 'px-number', type: 'number', min: '0', max: '9999',
      value: String(this.settings[key]),
    });
    input.addEventListener('change', () => {
      this.settings[key] = Math.max(0, Number(input.value) || 0);
      input.value = String(this.settings[key]);
      this._schedulePreview();
    });
    return {
      input,
      wrap: h('label', { class: 'panel-field' }, [
        h('span', { class: 'field__label', text: label }),
        input,
      ]),
    };
  }

  // ------------------------------------------------------------ 生命周期

  setAsset(asset) {
    this.asset = asset;
    const usable = Boolean(asset);
    this.applyButton.disabled = !usable;
    for (const el of this.root.querySelectorAll('input, select, button')) {
      if (el !== this.applyButton) el.disabled = !usable;
    }
    if (!usable) {
      this.readout.textContent = '选择一个资产';
      this.status.textContent = '';
      this.lastAnalysis = null;
      this.onPreview({ url: null, maskUrl: null });
      return;
    }
    this._schedulePreview();
  }

  _schedulePreview() {
    // 拖滑块会连发事件；只保留最后一次，且同一时刻只允许一个请求在飞。
    clearTimeout(this.timer);
    this.status.textContent = '计算中…';
    this.timer = setTimeout(() => this._runPreview(), PREVIEW_DEBOUNCE_MS);
  }

  async _runPreview() {
    if (!this.asset) return;
    if (this.busy) {
      this.pending = true;
      return;
    }
    this.busy = true;

    const started = performance.now();
    const reply = await rpc.call('background.analyze', {
      asset: this.asset,
      ...this.settings,
    });

    this.busy = false;
    if (this.pending) {
      this.pending = false;
      this._runPreview();
      return;
    }

    if (!reply.ok) {
      this.status.textContent = '预览失败';
      return;
    }

    this.lastAnalysis = reply.result;
    this._renderReadout(reply.result, performance.now() - started);
    this._emitPreview();
  }

  _renderReadout(result, roundTripMs) {
    const analysis = result.analysis;
    const chosen = analysis.chosen;

    if (chosen) {
      this.swatch.style.backgroundColor = chosen.color;
      this.swatch.style.backgroundImage = 'none';
      this.readout.textContent =
        `${chosen.color} · 覆盖边界 ${Math.round(chosen.border_coverage * 100)}%`;
    } else {
      this.swatch.style.backgroundColor = 'transparent';
      this.swatch.style.backgroundImage = 'var(--tex-checker)';
      this.readout.textContent = '未找到候选背景色';
    }

    const ratio = (analysis.erased_ratio * 100).toFixed(1);
    this.status.textContent =
      `将擦除 ${analysis.erased_pixels}/${analysis.total_pixels} 像素（${ratio}%）` +
      ` · 后端 ${analysis.elapsed_ms.toFixed(0)}ms · 往返 ${roundTripMs.toFixed(0)}ms`;

    for (const warning of result.warnings ?? []) {
      this.status.textContent += ` · ⚠ ${warning.code}`;
    }
  }

  _emitPreview() {
    const frame = this.lastAnalysis?.frames?.[0];
    if (!frame) return;
    this.onPreview({
      url: frame.url,
      maskUrl: this.showOverlay ? frame.maskUrl : null,
    });
  }

  async _apply() {
    if (!this.asset) return;
    this.applyButton.disabled = true;
    this.status.textContent = '提交中…';

    const reply = await rpc.call('background.apply', {
      asset: this.asset,
      ...this.settings,
    });

    this.applyButton.disabled = false;
    if (!reply.ok) {
      this.status.textContent = '提交失败';
      return;
    }

    const { revision, outputs, warnings } = reply.result;
    toast(`已提交 revision ${revision}：${outputs.join(', ')}`, {
      hint: warnings.length ? `${warnings.length} 条警告` : '可用标题栏的撤销回退',
    });
    this.status.textContent = `已提交 r${revision}`;
    this.onApplied(reply.result);
  }
}
