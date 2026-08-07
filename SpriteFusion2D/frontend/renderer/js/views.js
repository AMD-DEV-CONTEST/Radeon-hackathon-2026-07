// 资产树、网格视图、帧条、历史、doctor —— FRONTEND_PLAN.md §5
// 全部只读：阶段 A 不提交任何写操作。

import { t } from './i18n.js';

const h = (tag, props = {}, children = []) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) el.appendChild(c);
  return el;
};

export { h };

/**
 * 缩略图缩放系数。放大用整数倍，缩小用整数分之一——
 * 保持最近邻可预测，不出现任意小数比例（BACKEND_CLI_PLAN.md 5.1 的精神）。
 */
export function thumbScale(width, height, target) {
  const longest = Math.max(width, height);
  if (longest <= 0) return 1;
  if (longest <= target) return Math.max(1, Math.floor(target / longest));
  return 1 / Math.ceil(longest / target);
}

// ---------------------------------------------------------------- 资产树

export class AssetTree {
  constructor(root, { onSelect }) {
    this.root = root;
    this.onSelect = onSelect;
    this.selected = null;
  }

  render(groups) {
    this.root.replaceChildren();
    for (const group of groups) {
      this.root.appendChild(h('div', { class: 'px-group-title', text: group.label }));
      if (group.items.length === 0) {
        this.root.appendChild(h('div', { class: 'px-empty', text: t('common.emptyGroup') }));
        continue;
      }
      for (const item of group.items) {
        const row = h('div', {
          class: 'px-row',
          role: 'option',
          'data-id': item.id,
          'aria-selected': String(this.selected === item.id),
          onclick: () => this.select(item),
        }, [
          h('span', { class: 'px-row__label', text: item.label }),
          h('span', { class: 'px-row__note', text: item.frames > 1 ? t('asset.frameCountBadge', { count: item.frames }) : '' }),
        ]);
        row.title = `${item.id}\n${item.note ?? ''}`;
        this.root.appendChild(row);
      }
    }
  }

  select(item) {
    this.selected = item.id;
    for (const row of this.root.querySelectorAll('.px-row')) {
      row.setAttribute('aria-selected', String(row.dataset.id === item.id));
    }
    this.onSelect(item);
  }
}

// ---------------------------------------------------------------- 网格视图

export class GridView {
  constructor(root, { onOpen, onSelect }) {
    this.root = root;
    this.onOpen = onOpen;
    this.onSelect = onSelect;
    this.selected = 0;
  }

  render(frames) {
    this.root.replaceChildren();
    if (!frames || frames.length === 0) {
      this.root.appendChild(h('div', { class: 'px-empty', text: t('asset.selectToViewFrames') }));
      return;
    }

    frames.forEach((frame, index) => {
      const scale = thumbScale(frame.width, frame.height, 128);
      const img = h('img', {
        class: 'cell__thumb',
        src: frame.url,
        width: Math.max(1, Math.round(frame.width * scale)),
        height: Math.max(1, Math.round(frame.height * scale)),
        alt: frame.id,
        title: `${frame.width}×${frame.height}`,
      });
      const tags = h(
        'div',
        { class: 'cell__tags' },
        (frame.tags ?? []).map((t) => h('span', { class: 'tag tag--readonly', text: t })),
      );
      const cell = h('div', {
        class: 'cell',
        'data-index': String(index),
        'aria-selected': String(index === this.selected),
        onclick: () => this.select(index),
        ondblclick: () => this.onOpen(index),
      }, [img, h('div', { class: 'cell__id', text: frame.id }), tags]);
      this.root.appendChild(cell);
    });
  }

  select(index) {
    this.selected = index;
    for (const cell of this.root.querySelectorAll('.cell')) {
      cell.setAttribute('aria-selected', String(Number(cell.dataset.index) === index));
    }
    this.onSelect(index);
  }
}

// ---------------------------------------------------------------- 帧条

export class FrameBar {
  constructor(root, { onSelect }) {
    this.root = root;
    this.onSelect = onSelect;
    this.selected = 0;
  }

  render(frames) {
    this.root.replaceChildren();
    if (!frames || frames.length <= 1) return;
    frames.forEach((frame, index) => {
      const scale = thumbScale(frame.width, frame.height, 32);
      const img = h('img', {
        class: 'framebar__thumb',
        src: frame.url,
        width: Math.max(1, Math.round(frame.width * scale)),
        height: Math.max(1, Math.round(frame.height * scale)),
        alt: frame.id,
        title: frame.id,
        'data-index': String(index),
        'aria-selected': String(index === this.selected),
        onclick: () => this.select(index),
      });
      this.root.appendChild(img);
    });
  }

  select(index) {
    this.selected = index;
    for (const thumb of this.root.querySelectorAll('.framebar__thumb')) {
      thumb.setAttribute('aria-selected', String(Number(thumb.dataset.index) === index));
    }
    this.onSelect(index);
  }
}

// ---------------------------------------------------------------- 历史

export function renderHistory(root, { head_revision, entries }) {
  root.replaceChildren();
  for (const e of entries) {
    const isHead = e.revision === head_revision;
    const warningsPart = e.warnings ? ` · ${t('history.warningsCount', { warnings: e.warnings })}` : '';
    root.appendChild(
      h('div', { class: `hist-row${isHead ? ' hist-row--head' : ''}` }, [
        h('div', { class: 'hist-row__top' }, [
          h('span', { class: 'hist-row__rev', text: `r${e.revision}` }),
          h('span', { class: 'hist-row__op', text: e.operation }),
        ]),
        h('div', {
          class: 'hist-row__meta',
          text: `${t('history.frameCount', { frames: e.frames })}${warningsPart} · ${e.at}`,
        }),
      ]),
    );
  }
  root.appendChild(
    h('div', {
      class: 'px-empty',
      text: t('history.readOnlyNote'),
    }),
  );
}

// ---------------------------------------------------------------- doctor

const STATUS_CLASS = { ok: 'px-badge--ok', warn: 'px-badge--warn', error: 'px-badge--err', skip: 'px-badge--skip' };
function statusText() {
  return { ok: t('status.ok'), warn: t('status.warn'), error: t('status.error'), skip: t('status.skip') };
}

export function renderDoctor(root, checks) {
  root.replaceChildren();
  const STATUS_TEXT = statusText();
  for (const c of checks) {
    const row = h('div', { class: 'doctor-row' }, [
      h('span', { class: 'doctor-row__name', text: c.name }),
      h('span', { class: `px-badge ${STATUS_CLASS[c.status] ?? ''}`, text: STATUS_TEXT[c.status] ?? c.status }),
    ]);
    row.title = c.detail ?? '';
    root.appendChild(row);
  }
}

// ---------------------------------------------------------------- 提示条

let toastTimer = null;

export function toast(message, { error = false, code = null, hint = '' } = {}) {
  document.querySelector('.px-toast')?.remove();
  clearTimeout(toastTimer);

  const el = h('div', { class: `px-toast${error ? ' px-toast--err' : ''}` }, [
    code !== null ? h('div', { class: 'px-toast__code', text: t('status.exitCode', { code }) }) : null,
    h('div', { text: message }),
    hint ? h('div', { class: 'px-toast__code', text: hint }) : null,
  ]);
  document.body.appendChild(el);
  toastTimer = setTimeout(() => el.remove(), error ? 8000 : 3500);
}
