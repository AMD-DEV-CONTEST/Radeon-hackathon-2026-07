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
import { t } from './i18n.js';
import {
  GENERATION_PRESET_IDS,
  SDXL_TURBO_LIMITS,
  getGenerationPreset,
  listGenerationPresets,
  mergeGenerationPreset,
} from './generate-presets.js';

const DEFAULT_PRESET_ID = GENERATION_PRESET_IDS[0];

export class GeneratePanel {
  constructor(root, { onCommitted }) {
    this.root = root;
    this.onCommitted = onCommitted;
    this.candidates = [];
    this.picked = new Set();
    this.job = null;
    this.presetId = DEFAULT_PRESET_ID;
    // 采样参数的默认值来自预设，而预设已经按 comfyui.py 的真实 Turbo 上限
    // （steps<=4、CFG<=1.0）定死。这里不再出现会被后端悄悄砍掉的 20 steps / CFG 7。
    const preset = getGenerationPreset(DEFAULT_PRESET_ID);
    this.settings = {
      count: preset.count,
      style: 'pixel',
      model: 'default',
      size: preset.size,
      steps: preset.steps,
      cfg: preset.cfg,
    };
  }

  async mount() {
    this.root.replaceChildren();

    this.prompt = h('textarea', {
      class: 'px-input kit-prompt',
      rows: '3',
      placeholder: t('generate.promptPlaceholder'),
    });
    this.negative = h('textarea', { class: 'px-input', rows: '2', placeholder: t('generate.negativePlaceholder') });

    // 预设优先于参数（FRONTEND_PLAN_V2.md C2）：先选类别，再写主体描述。
    this.presetPick = picker(
      listGenerationPresets().map((p) => ({ id: p.id, label: t(`generate.preset.${p.id}`) })),
      DEFAULT_PRESET_ID,
      (v) => this._applyPreset(v),
    );

    this.stylePick = picker([{ id: 'pixel', label: t('generate.stylePixel') }], 'pixel', (v) => { this.settings.style = v; });
    this.modelPick = picker([{ id: 'default', label: t('generate.modelDefault') }], 'default', (v) => { this.settings.model = v; });
    this.countPick = picker(
      [1, 2, 4, 6, 8].map((n) => ({ id: String(n), label: t('generate.countUnit', { n }) })),
      '4',
      (v) => { this.settings.count = Number(v); },
    );

    this.runButton = h('button', { class: 'px-btn px-btn--accent', text: t('generate.runButton'), onclick: () => this._run() });
    this.status = h('div', { class: 'kit-status', text: '' });
    this.gallery = h('div', { class: 'gen-gallery' });
    this.commitBar = h('div', { class: 'kit-row' }, [
      h('button', { class: 'px-btn px-btn--accent', text: t('asset.addToProject'), onclick: () => this._commit() }),
      h('button', { class: 'px-btn px-btn--sm', text: t('generate.runAgainLabel'), onclick: () => this._run() }),
    ]);
    this.commitBar.style.display = 'none';

    this.providerBar = h('div', { class: 'kit-hint', text: t('generate.detectingProvider') });

    // 界面显示最终会用到的关键设置，用户不用展开「高级」也知道会发生什么。
    this.effectiveBar = h('div', { class: 'kit-hint', text: '' });

    const preset = getGenerationPreset(this.presetId);
    this.sizeSlider = slider(preset.size, { min: 256, max: 1024, step: 128 }, (v) => {
      this.settings.size = v;
      this._syncEffective();
    });
    this.stepsSlider = slider(
      preset.steps,
      { min: SDXL_TURBO_LIMITS.minSteps, max: SDXL_TURBO_LIMITS.maxSteps },
      (v) => { this.settings.steps = v; this._syncEffective(); },
    );
    this.cfgSlider = slider(
      preset.cfg,
      { min: SDXL_TURBO_LIMITS.minCfg, max: SDXL_TURBO_LIMITS.maxCfg, step: 0.1 },
      (v) => { this.settings.cfg = v; this._syncEffective(); },
    );

    this.root.append(
      this.providerBar,
      field(t('generate.presetLabel'), t('generate.presetHint'), this.presetPick),
      field(t('generate.descriptionLabel'), null, this.prompt),
      h('div', { class: 'kit-row' }, [
        field(t('generate.styleLabel'), null, this.stylePick),
        field(t('generate.modelLabel'), null, this.modelPick),
        field(t('generate.countLabel'), null, this.countPick),
      ]),
      this.effectiveBar,
      advanced([
        field(t('generate.negativeLabel'), t('generate.negativeAppendHint'), this.negative),
        field(t('generate.sizeLabel'), null, this.sizeSlider),
        field(t('generate.stepsLabel'), t('generate.turboLimitHint'), this.stepsSlider),
        field('CFG', t('generate.turboLimitHint'), this.cfgSlider),
      ]),
      this.runButton,
      this.status,
      h('div', { class: 'kit-sep', text: t('generate.candidatesSectionHint') }),
      this.gallery,
      this.commitBar,
    );

    this._syncEffective();
    await this._probeProvider();
  }

  // 切换预设：把该类别的推荐值灌进 settings 和滑块。用户已经写的主体描述和
  // 负面提示都不动——预设只管参数，不碰用户输入。
  _applyPreset(presetId) {
    const preset = getGenerationPreset(presetId);
    if (!preset) return;
    this.presetId = presetId;
    this.settings.size = preset.size;
    this.settings.steps = preset.steps;
    this.settings.cfg = preset.cfg;
    this.settings.count = preset.count;
    this.sizeSlider.set(preset.size);
    this.stepsSlider.set(preset.steps);
    this.cfgSlider.set(preset.cfg);
    if (this.countPick) this.countPick.value = String(preset.count);
    this._syncEffective();
  }

  // 用真正会发出去的那份 payload 来渲染摘要，而不是另算一遍——避免界面显示的
  // 和实际请求的对不上。
  _syncEffective() {
    if (!this.effectiveBar) return;
    const merged = this._buildRequest(this.prompt?.value ?? '');
    this.effectiveBar.textContent = t('generate.effectiveSummary', {
      preset: t(`generate.preset.${this.presetId}`),
      size: merged.size,
      count: merged.count,
      steps: merged.steps,
      cfg: merged.cfg,
    });
  }

  // 合并预设与用户输入。mergeGenerationPreset 保证：用户的主体描述原样保留在
  // prompt 里（预设只追加风格后缀），负面提示是「用户的 + 预设的」拼接而不是
  // 覆盖，steps/cfg 无论来自哪里都会夹进 SDXL-Turbo 的真实上限。
  _buildRequest(promptText) {
    return mergeGenerationPreset(this.presetId, {
      prompt: promptText,
      negative: this.negative?.value.trim() ?? '',
      size: this.settings.size,
      count: this.settings.count,
      steps: this.settings.steps,
      cfg: this.settings.cfg,
    });
  }

  async _probeProvider() {
    const reply = await rpc.call('generate.providers');
    if (!reply.ok) {
      // 没找到后端不是错误，是一种正常状态——给可执行的下一步，不弹堆栈
      this.providerBar.textContent = t('generate.noProviderFound');
      this.runButton.disabled = true;
      return;
    }
    const { models = [], styles = [], provider } = reply.result;
    this.providerBar.textContent = t('generate.providerLabel', { provider });
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
    if (!text) { toast(t('generate.emptyPromptToast')); return; }

    this.runButton.disabled = true;
    this.status.textContent = t('generate.submittedStatus');

    const merged = this._buildRequest(text);
    const { job, promise, error } = await jobs.submit('generate.submit', {
      style: this.settings.style,
      model: this.settings.model,
      prompt: merged.prompt,
      negative: merged.negative,
      size: merged.size,
      count: merged.count,
      steps: merged.steps,
      cfg: merged.cfg,
      preset: merged.presetId,
    }, { label: t('generate.runButton') });

    if (error) {
      this.status.textContent = error.code === 2 ? t('common.backendNotWired') : t('common.submitFailed');
      this.runButton.disabled = false;
      return;
    }
    this.job = job;

    try {
      const { result } = await promise;
      this.candidates = result.candidates ?? [];
      this.picked = new Set();
      this._renderGallery();
      this.status.textContent = t('generate.resultStatus', { count: this.candidates.length });
    } catch (e) {
      this.status.textContent = e.rpc?.code === 6 ? t('generate.cancelledStatus') : t('generate.failedStatus', { message: e.message });
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
    this.status.textContent = t('generate.committingStatus');
    const reply = await rpc.call('generate.commit', {
      candidates: [...this.picked],
      recover: true,
    });
    if (!reply.ok) { this.status.textContent = t('generate.commitFailedStatus'); return; }
    const { outputs = [], recovered } = reply.result;
    toast(t('generate.committedToast', { count: outputs.length, recoveredNote: recovered ? t('generate.recoveredNote') : '' }), { hint: outputs.join(', ') });
    this.status.textContent = t('generate.committedStatus', { outputs: outputs.join(', ') });
    this.candidates = [];
    this.picked = new Set();
    this.gallery.replaceChildren();
    this.commitBar.style.display = 'none';
    this.onCommitted?.(reply.result);
  }
}
