// AI 生成面板 —— FRONTEND_PLAN_V2.md §3.2
//
// 唯一**不能**用「预览-提交」范式的面板：生成太慢，没法跟着参数实时预览。
// 改用**暂存区**范式：生成结果先进候选区（不占项目历史），用户挑中的才 commit。
// 否则试十次就在历史里塞十条垃圾。
//
// 「收入项目」实际执行的是 generate → recover → 提交：通用模型产出的"像素风"
// 格子是歪的，而本仓库的核心算法正是修这个。没有这一步我们只是又一个套壳生成器
// （BACKEND_PLAN_V2.md §6.4）。

import { advanced, field, picker, slider } from './panel-kit.js';
import { jobs } from './jobs.js';
import { rpc } from './rpc.js';
import { h, toast } from './views.js';

export class GeneratePanel {
  constructor(root, { onCommitted }) {
    this.root = root;
    this.onCommitted = onCommitted;
    this.candidates = [];
    this.picked = new Set();
    this.job = null;
    this.settings = { count: 4, style: 'pixel', model: 'default', size: 512, steps: 20, cfg: 7 };
  }

  async mount() {
    this.root.replaceChildren();

    this.prompt = h('textarea', {
      class: 'px-input kit-prompt',
      rows: '3',
      placeholder: '描述你想要的角色，例如：一个穿红裙子的女孩，正面站立',
    });
    this.negative = h('textarea', { class: 'px-input', rows: '2', placeholder: '不想要的内容（可留空）' });

    this.stylePick = picker([{ id: 'pixel', label: '像素画' }], 'pixel', (v) => { this.settings.style = v; });
    this.modelPick = picker([{ id: 'default', label: '默认' }], 'default', (v) => { this.settings.model = v; });
    this.countPick = picker(
      [1, 2, 4, 6, 8].map((n) => ({ id: String(n), label: `${n} 张` })),
      '4',
      (v) => { this.settings.count = Number(v); },
    );

    this.runButton = h('button', { class: 'px-btn px-btn--accent', text: '生成', onclick: () => this._run() });
    this.status = h('div', { class: 'kit-status', text: '' });
    this.gallery = h('div', { class: 'gen-gallery' });
    this.commitBar = h('div', { class: 'kit-row' }, [
      h('button', { class: 'px-btn px-btn--accent', text: '收入项目', onclick: () => this._commit() }),
      h('button', { class: 'px-btn px-btn--sm', text: '再来一批', onclick: () => this._run() }),
    ]);
    this.commitBar.style.display = 'none';

    this.providerBar = h('div', { class: 'kit-hint', text: '正在检测生成后端…' });

    this.root.append(
      this.providerBar,
      field('描述', null, this.prompt),
      h('div', { class: 'kit-row' }, [
        field('风格', null, this.stylePick),
        field('模型', null, this.modelPick),
        field('数量', null, this.countPick),
      ]),
      advanced([
        field('反向描述', null, this.negative),
        field('尺寸', null, slider(512, { min: 256, max: 1024, step: 128 }, (v) => { this.settings.size = v; })),
        field('步数', null, slider(20, { min: 4, max: 50 }, (v) => { this.settings.steps = v; })),
        field('CFG', null, slider(7, { min: 1, max: 15 }, (v) => { this.settings.cfg = v; })),
      ]),
      this.runButton,
      this.status,
      h('div', { class: 'kit-sep', text: '候选（不占项目，关掉就没了）' }),
      this.gallery,
      this.commitBar,
    );

    await this._probeProvider();
  }

  async _probeProvider() {
    const reply = await rpc.call('generate.providers');
    if (!reply.ok) {
      // 没找到后端不是错误，是一种正常状态——给可执行的下一步，不弹堆栈
      this.providerBar.textContent = '没找到生成后端。请先启动 ComfyUI，或到设置里填地址。';
      this.runButton.disabled = true;
      return;
    }
    const { models = [], styles = [], provider } = reply.result;
    this.providerBar.textContent = `生成后端：${provider}`;
    if (models.length > 0) {
      this.modelPick.replaceChildren(
        ...models.map((m) => h('option', { value: m.id, text: m.label })),
      );
    } else {
      // 没有可用模型时隐藏下拉，不报错（§6.5）
      this.modelPick.parentElement.style.display = 'none';
    }
    if (styles.length > 0) {
      this.stylePick.replaceChildren(...styles.map((s) => h('option', { value: s.id, text: s.label })));
    }
    this.runButton.disabled = false;
  }

  async _run() {
    const text = this.prompt.value.trim();
    if (!text) { toast('先写一句描述'); return; }

    this.runButton.disabled = true;
    this.status.textContent = '已提交…';

    const { job, promise, error } = await jobs.submit('generate.submit', {
      prompt: text,
      negative: this.negative.value.trim(),
      ...this.settings,
    }, { label: '生成' });

    if (error) {
      this.status.textContent = error.code === 2 ? '该功能后端尚未接入' : '提交失败';
      this.runButton.disabled = false;
      return;
    }
    this.job = job;

    try {
      const { result } = await promise;
      this.candidates = result.candidates ?? [];
      this.picked = new Set();
      this._renderGallery();
      this.status.textContent = `生成了 ${this.candidates.length} 张，挑中的才会进项目`;
    } catch (e) {
      this.status.textContent = e.rpc?.code === 6 ? '已取消' : `失败：${e.message}`;
    } finally {
      this.job = null;
      this.runButton.disabled = false;
    }
  }

  _renderGallery() {
    this.gallery.replaceChildren();
    for (const c of this.candidates) {
      const cell = h('div', {
        class: 'gen-cell',
        'aria-selected': 'false',
        onclick: () => {
          const on = this.picked.has(c.id);
          if (on) this.picked.delete(c.id); else this.picked.add(c.id);
          cell.setAttribute('aria-selected', String(!on));
          this.commitBar.style.display = this.picked.size > 0 ? '' : 'none';
        },
      }, [
        h('img', { class: 'gen-cell__img', src: c.url, alt: c.id }),
        h('div', { class: 'gen-cell__seed', text: `seed ${c.seed}` }),
      ]);
      this.gallery.appendChild(cell);
    }
    this.commitBar.style.display = 'none';
  }

  async _commit() {
    if (this.picked.size === 0) return;
    this.status.textContent = '收入项目中（会自动接修复）…';
    const reply = await rpc.call('generate.commit', {
      candidates: [...this.picked],
      recover: true,
    });
    if (!reply.ok) { this.status.textContent = '收入失败'; return; }
    const { outputs = [], recovered } = reply.result;
    toast(`已收入 ${outputs.length} 张${recovered ? '（已接修复）' : ''}`, { hint: outputs.join(', ') });
    this.status.textContent = `已收入：${outputs.join(', ')}`;
    this.candidates = [];
    this.picked = new Set();
    this.gallery.replaceChildren();
    this.commitBar.style.display = 'none';
    this.onCommitted?.(reply.result);
  }
}
