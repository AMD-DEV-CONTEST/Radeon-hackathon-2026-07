// 抠图面板 —— FRONTEND_PLAN.md 阶段 B 的第一个操作面板。
//
// 硬规则：前端不复算遮罩。每次参数变化都调后端的 background.analyze，
// 显示的是后端渲染进 cache/ 的真实结果，不是界面自己近似出来的东西。
// 这样「预览所见」和「提交所得」不可能分叉（FRONTEND_PLAN.md 13.1）。

import { rpc } from './rpc.js';
import { h, toast } from './views.js';
import { t } from './i18n.js';

const PREVIEW_DEBOUNCE_MS = 180;

const MODE_IDS = ['exact', 'rgb', 'lab'];

function modeHints() {
  return {
    exact: t('background.modeHintExact'),
    rgb: t('background.modeHintRgb'),
    lab: t('background.modeHintLab'),
  };
}

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
      MODE_IDS.map((m) =>
        h('option', { value: m, text: m, selected: m === this.settings.mode ? '' : null }),
      ),
    );
    this.modeSelect.addEventListener('change', () => {
      this.settings.mode = this.modeSelect.value;
      this.modeHint.textContent = modeHints()[this.settings.mode];
      this.toleranceRow.style.opacity = this.settings.mode === 'exact' ? '0.4' : '1';
      this._schedulePreview();
    });

    this.modeHint = h('div', { class: 'field__label', text: modeHints().lab });

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
      class: 'px-btn px-btn--sm', text: t('background.connectivityLabel', { n: 8 }),
      onclick: () => {
        this.settings.connectivity = this.settings.connectivity === 8 ? 4 : 8;
        this.connButton.textContent = t('background.connectivityLabel', { n: this.settings.connectivity });
        this._schedulePreview();
      },
    });

    this.borderButton = h('button', {
      class: 'px-btn px-btn--sm px-btn--on', text: t('background.borderOnlyLabel'),
      title: t('background.borderOnlyHint'),
      onclick: () => {
        this.settings.borderOnly = !this.settings.borderOnly;
        this.borderButton.classList.toggle('px-btn--on', this.settings.borderOnly);
        this._schedulePreview();
      },
    });

    this.alphaButton = h('button', {
      class: 'px-btn px-btn--sm', text: t('background.alphaHard'),
      onclick: () => {
        this.settings.alpha = this.settings.alpha === 'hard' ? 'soft' : 'hard';
        this.alphaButton.textContent = this.settings.alpha === 'hard' ? t('background.alphaHard') : t('background.alphaSoft');
        this.alphaButton.classList.toggle('px-btn--on', this.settings.alpha === 'soft');
        this._schedulePreview();
      },
    });

    this.islandInput = this._numberField(t('background.minIslandLabel'), 'minIslandArea');
    this.holeInput = this._numberField(t('background.maxHoleLabel'), 'maxHoleArea');

    this.overlayButton = h('button', {
      class: 'px-btn px-btn--sm px-btn--on', text: t('background.overlayLabel'),
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
      class: 'px-btn px-btn--accent', text: t('common.applyToProject'),
      onclick: () => this._apply(),
    });

    this.root.append(
      h('div', { class: 'field' }, [
        h('div', { class: 'field__label', text: t('background.modeLabel') }),
        this.modeSelect,
        this.modeHint,
      ]),
      h('div', { class: 'field' }, [
        h('div', { class: 'field__label', text: t('background.toleranceLabel') }),
        this.toleranceRow,
      ]),
      h('div', { class: 'field panel-row' }, [this.connButton, this.borderButton]),
      h('div', { class: 'field panel-row' }, [this.alphaButton, this.overlayButton]),
      h('div', { class: 'field panel-row' }, [this.islandInput.wrap, this.holeInput.wrap]),
      h('div', { class: 'field' }, [
        h('div', { class: 'field__label', text: t('background.backendResultLabel') }),
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
      this.readout.textContent = t('common.selectAssetPrompt');
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
    this.status.textContent = t('common.calculating');
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
      this.status.textContent = t('common.previewFailed');
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
      this.readout.textContent = t('background.colorCoverage', {
        color: chosen.color,
        pct: Math.round(chosen.border_coverage * 100),
      });
    } else {
      this.swatch.style.backgroundColor = 'transparent';
      this.swatch.style.backgroundImage = 'var(--tex-checker)';
      this.readout.textContent = t('background.noCandidateColor');
    }

    const ratio = (analysis.erased_ratio * 100).toFixed(1);
    this.status.textContent = t('background.eraseSummary', {
      erased: analysis.erased_pixels,
      total: analysis.total_pixels,
      ratio,
      ms: analysis.elapsed_ms.toFixed(0),
      rtMs: roundTripMs.toFixed(0),
    });

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
    this.status.textContent = t('common.submitting');

    const reply = await rpc.call('background.apply', {
      asset: this.asset,
      ...this.settings,
    });

    this.applyButton.disabled = false;
    if (!reply.ok) {
      this.status.textContent = t('common.submitFailed');
      return;
    }

    const { revision, outputs, warnings } = reply.result;
    toast(t('background.submittedToast', { revision, outputs: outputs.join(', ') }), {
      hint: warnings.length ? t('common.warningsCountHint', { count: warnings.length }) : t('common.undoHint'),
    });
    this.status.textContent = t('background.submittedStatus', { revision });
    this.onApplied(reply.result);
  }
}
