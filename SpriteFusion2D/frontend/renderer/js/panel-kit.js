// 面板工具箱 —— 四个新面板共享的结构。
//
// 抽出来的两件事：
//  1. 预设优先、参数折叠的控件组合（FRONTEND_PLAN_V2.md 约束 C2）；
//  2. 「预览-提交」面板的请求节流：debounce + 单飞 + pending 合并。
//     第 3 条最关键——不补跑的话，拖动过程中最后一次参数会被丢掉。
//     这套模式在抠图面板上验证过，是现有 UI 里唯一被证明好用的交互。

import { rpc } from './rpc.js';
import { h, toast } from './views.js';

export const PREVIEW_DEBOUNCE_MS = 180;

// ---------------------------------------------------------------- 控件

/** 预设按钮行。预设是面板的默认视图，参数进「高级」。 */
export function presetRow(presets, current, onPick) {
  const buttons = new Map();
  const row = h('div', { class: 'preset-row' },
    presets.map((p) => {
      const btn = h('button', {
        class: `px-btn px-btn--sm${p.id === current ? ' px-btn--on' : ''}`,
        text: p.label,
        title: p.hint ?? '',
        onclick: () => {
          for (const [id, b] of buttons) b.classList.toggle('px-btn--on', id === p.id);
          onPick(p);
        },
      });
      buttons.set(p.id, btn);
      return btn;
    }));
  row.setActive = (id) => {
    for (const [key, b] of buttons) b.classList.toggle('px-btn--on', key === id);
  };
  return row;
}

/** 带标题和副标题的字段容器。副标题用来把术语翻成后果（C3）。 */
export function field(label, hint, control) {
  return h('div', { class: 'kit-field' }, [
    h('div', { class: 'field__label', text: label }),
    hint ? h('div', { class: 'kit-hint', text: hint }) : null,
    control,
  ]);
}

export function slider(value, { min = 0, max = 100, step = 1 } = {}, onInput) {
  const input = h('input', {
    type: 'range', min: String(min), max: String(max), step: String(step), value: String(value),
  });
  const out = h('b', { text: String(value) });
  input.addEventListener('input', () => {
    out.textContent = input.value;
    onInput(Number(input.value));
  });
  const row = h('div', { class: 'px-slider' }, [input, h('span', { class: 'px-slider__value' }, [out])]);
  row.set = (v) => { input.value = String(v); out.textContent = String(v); };
  return row;
}

export function toggle(label, value, onChange) {
  const btn = h('button', {
    class: `px-btn px-btn--sm${value ? ' px-btn--on' : ''}`,
    text: label,
    onclick: () => {
      const next = !btn.classList.contains('px-btn--on');
      btn.classList.toggle('px-btn--on', next);
      onChange(next);
    },
  });
  btn.set = (v) => btn.classList.toggle('px-btn--on', v);
  return btn;
}

export function picker(options, value, onChange) {
  const sel = h('select', { class: 'px-btn px-btn--sm' },
    options.map((o) => h('option', { value: o.id, text: o.label, selected: o.id === value ? '' : null })));
  sel.addEventListener('change', () => onChange(sel.value));
  return sel;
}

export function numberField(label, value, onChange) {
  const input = h('input', { type: 'number', class: 'px-input', value: String(value), min: '0' });
  input.addEventListener('change', () => onChange(Number(input.value) || 0));
  return h('div', { class: 'kit-row' }, [h('span', { class: 'field__label', text: label }), input]);
}

/** 折叠的「高级」区。默认收起——绝大多数用户永远不需要展开。 */
export function advanced(children, { label = '高级参数', open = false } = {}) {
  const body = h('div', { class: 'kit-adv__body' }, children);
  body.style.display = open ? '' : 'none';
  const head = h('button', {
    class: 'kit-adv__head px-btn px-btn--sm',
    text: `${open ? '▾' : '▸'} ${label}`,
    onclick: () => {
      const shown = body.style.display !== 'none';
      body.style.display = shown ? 'none' : '';
      head.textContent = `${shown ? '▸' : '▾'} ${label}`;
    },
  });
  return h('div', { class: 'kit-adv' }, [head, body]);
}

// ---------------------------------------------------------------- 预览面板基类

/**
 * 「预览-提交」面板：参数一变就调后端 analyze，显示后端算出来的真实结果，
 * 满意了再 apply。前端**不复算**任何算法（FRONTEND_PLAN_V2.md 硬规则 2.3）。
 *
 * 子类要实现：
 *   buildBody(): HTMLElement      控件区
 *   analyzeParams(): object       调 analyze 用的参数
 *   applyParams(): object         调 apply 用的参数
 *   renderReadout(result, ms)     把后端返回值写成人话
 */
export class PreviewPanel {
  constructor(root, { analyzeMethod, applyMethod, applyLabel = '应用到项目', onPreview, onApplied }) {
    this.root = root;
    this.analyzeMethod = analyzeMethod;
    this.applyMethod = applyMethod;
    this.applyLabel = applyLabel;
    this.onPreview = onPreview;
    this.onApplied = onApplied;

    this.asset = null;
    this.busy = false;
    this.pending = false;
    this.timer = null;
    this.last = null;
    this.showOverlay = true;
  }

  mount() {
    this.root.replaceChildren();
    this.status = h('div', { class: 'kit-status', text: '选择一个资产' });
    this.applyButton = h('button', {
      class: 'px-btn px-btn--accent kit-apply',
      text: this.applyLabel,
      onclick: () => this._apply(),
    });
    this.root.append(this.buildBody(), this.status, this.applyButton);
    this.setAsset(null);
  }

  setAsset(asset) {
    this.asset = asset;
    const usable = Boolean(asset);
    for (const el of this.root.querySelectorAll('input, select, button')) el.disabled = !usable;
    if (!usable) {
      this.status.textContent = '选择一个资产';
      this.last = null;
      this.onPreview?.({ url: null, maskUrl: null });
      return;
    }
    this.schedule();
  }

  schedule() {
    clearTimeout(this.timer);
    if (!this.asset) return;
    this.status.textContent = '计算中…';
    this.timer = setTimeout(() => this._run(), PREVIEW_DEBOUNCE_MS);
  }

  async _run() {
    if (!this.asset) return;
    if (this.busy) { this.pending = true; return; }
    this.busy = true;

    const started = performance.now();
    const reply = await rpc.call(this.analyzeMethod, { asset: this.asset, ...this.analyzeParams() });

    this.busy = false;
    // 补跑最新参数——少了这一步，拖动的最后一下会被丢掉
    if (this.pending) { this.pending = false; this._run(); return; }

    if (!reply.ok) {
      this.status.textContent = reply.error?.code === 2 ? '该功能后端尚未接入' : '预览失败';
      return;
    }
    this.last = reply.result;
    this.renderReadout(reply.result, performance.now() - started);
    this.emitPreview();
  }

  emitPreview() {
    const frame = this.last?.frames?.[0];
    if (!frame) return;
    this.onPreview?.({ url: frame.url, maskUrl: this.showOverlay ? frame.maskUrl : null });
  }

  async _apply() {
    if (!this.asset) return;
    this.applyButton.disabled = true;
    this.status.textContent = '提交中…';
    const reply = await rpc.call(this.applyMethod, { asset: this.asset, ...this.applyParams() });
    this.applyButton.disabled = false;

    if (!reply.ok) {
      this.status.textContent = reply.error?.code === 2 ? '该功能后端尚未接入' : '提交失败';
      return;
    }
    const { revision, outputs = [], warnings = [] } = reply.result;
    toast(`已提交：${outputs.join(', ')}`, {
      hint: warnings.length ? `${warnings.length} 条警告` : '可用标题栏的撤销回退',
    });
    this.status.textContent = `已提交 · ${outputs.join(', ')}`;
    this.onApplied?.(reply.result, revision);
  }

  /** 后端返回的警告统一追加到状态行。 */
  appendWarnings(warnings) {
    for (const w of warnings ?? []) this.status.textContent += ` · ⚠ ${w.message ?? w.code}`;
  }
}
