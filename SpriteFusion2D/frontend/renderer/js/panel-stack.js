// 操作栈 —— FRONTEND_PLAN_V2.md §1.2(a)
//
// 右栏从「抠图 / 信息」两个 tab 改成按流水线顺序竖排的操作栈。
// 这解决的是"用户不知道下一步该干什么"——**顺序本身就是教学**。
// 同一时刻只展开一项，避免右栏变成参数瀑布。

import { h } from './views.js';

export class PanelStack {
  constructor(root) {
    this.root = root;
    this.items = new Map(); // id -> {section, head, body, mount, mounted, enabled}
    this.openId = null;
  }

  /**
   * @param spec.id       稳定标识
   * @param spec.index    显示的序号
   * @param spec.label    标题
   * @param spec.hint     一句话说明这一步干什么
   * @param spec.mount    (bodyEl) => void   首次展开时调用，惰性挂载
   */
  add(spec) {
    const body = h('div', { class: 'stack__body' });
    body.style.display = 'none';

    const badge = h('span', { class: 'stack__badge', text: String(spec.index) });
    const title = h('span', { class: 'stack__title', text: spec.label });
    const check = h('span', { class: 'stack__check', text: '' });
    const head = h('button', {
      class: 'stack__head',
      onclick: () => this.toggle(spec.id),
    }, [badge, title, check]);

    const section = h('div', { class: 'stack__item', 'data-id': spec.id }, [
      head,
      spec.hint ? h('div', { class: 'stack__hint', text: spec.hint }) : null,
      body,
    ]);
    this.root.appendChild(section);
    this.items.set(spec.id, { ...spec, section, head, body, check, mounted: false, enabled: true });
    return section;
  }

  toggle(id) {
    if (this.openId === id) { this.close(id); return; }
    this.open(id);
  }

  open(id) {
    const item = this.items.get(id);
    if (!item || !item.enabled) return;
    for (const [key, other] of this.items) {
      if (key === id) continue;
      other.body.style.display = 'none';
      other.section.dataset.open = 'false';
    }
    if (!item.mounted) {
      item.mount?.(item.body);
      item.mounted = true;
    }
    item.body.style.display = '';
    item.section.dataset.open = 'true';
    this.openId = id;
    item.onOpen?.();
  }

  close(id) {
    const item = this.items.get(id);
    if (!item) return;
    item.body.style.display = 'none';
    item.section.dataset.open = 'false';
    if (this.openId === id) this.openId = null;
  }

  /** 当前步骤不可用时置灰——例如没抠图之前描边意义不大。 */
  setEnabled(id, enabled, reason = '') {
    const item = this.items.get(id);
    if (!item) return;
    item.enabled = enabled;
    item.section.dataset.disabled = String(!enabled);
    item.head.title = enabled ? '' : reason;
    if (!enabled && this.openId === id) this.close(id);
  }

  setDone(id, done) {
    const item = this.items.get(id);
    if (!item) return;
    item.check.textContent = done ? '✓' : '';
  }
}
