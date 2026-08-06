// 描边面板 —— FRONTEND_PLAN_V2.md §3.1
//
// 完全套用抠图面板的「预览-提交」范式：那是现有 UI 里唯一被验证好用的交互，
// 新功能应该长成一样。默认视图只有四个预设，参数全在「高级」里。

import { PreviewPanel, advanced, field, numberField, picker, presetRow, slider, toggle } from './panel-kit.js';
import { h } from './views.js';

// 「柔和深色」= 取相邻像素自身颜色压暗，像素画里比纯黑更常用的做法
// （selective outline）。红裙子外面是暗红边而不是死黑，结果更像人画的。
const PRESETS = [
  {
    id: 'classic',
    label: '经典黑边',
    hint: '外描边 1px 纯黑，跳过纯对角接触',
    settings: { position: 'outer', thickness: 1, connectivity: 8, skipDiagonal: true, colorMode: 'fixed', color: '#000000' },
  },
  {
    id: 'soft',
    label: '柔和深色',
    hint: '取相邻像素自身颜色压暗，比纯黑高级',
    settings: { position: 'outer', thickness: 1, connectivity: 8, skipDiagonal: true, colorMode: 'darken-neighbor', darken: 40 },
  },
  {
    id: 'shadow',
    label: '描边加内阴影',
    hint: '外黑边 + 内侧一圈暗色',
    settings: { position: 'outer', thickness: 1, connectivity: 8, skipDiagonal: true, colorMode: 'fixed', color: '#000000', innerShadow: true },
  },
  { id: 'custom', label: '自定义', hint: '展开高级参数自行调整', settings: {} },
];

export class OutlinePanel extends PreviewPanel {
  constructor(root, hooks) {
    super(root, { analyzeMethod: 'outline.analyze', applyMethod: 'outline.apply', ...hooks });
    this.preset = 'classic';
    this.settings = { ...PRESETS[0].settings, darken: 40, innerShadow: false };
  }

  buildBody() {
    this.presets = presetRow(PRESETS, this.preset, (p) => {
      this.preset = p.id;
      if (p.id !== 'custom') {
        this.settings = { ...this.settings, ...p.settings };
        this.syncControls();
      }
      this.schedule();
    });

    this.thickness = slider(this.settings.thickness, { min: 1, max: 4 }, (v) => {
      this.settings.thickness = v;
      this.markCustom();
    });
    this.positionPick = picker(
      [{ id: 'outer', label: '外描边' }, { id: 'inner', label: '内描边' }, { id: 'center', label: '居中' }],
      this.settings.position,
      (v) => { this.settings.position = v; this.markCustom(); },
    );
    this.diagToggle = toggle('跳过纯对角', this.settings.skipDiagonal, (v) => {
      this.settings.skipDiagonal = v;
      this.markCustom();
    });
    this.connToggle = toggle('连对角线', this.settings.connectivity === 8, (v) => {
      this.settings.connectivity = v ? 8 : 4;
      this.markCustom();
    });
    this.colorPick = picker(
      [
        { id: 'fixed', label: '固定颜色' },
        { id: 'darken-neighbor', label: '相邻取色压暗' },
        { id: 'hue-shift', label: '色相偏移' },
      ],
      this.settings.colorMode,
      (v) => { this.settings.colorMode = v; this.markCustom(); },
    );
    this.darken = slider(this.settings.darken, { min: 10, max: 90 }, (v) => {
      this.settings.darken = v;
      this.markCustom();
    });
    this.uniform = toggle('跨帧统一', true, (v) => {
      this.settings.uniformAcrossFrames = v;
      this.markCustom();
    });
    this.overlayToggle = toggle('标出描边区', true, (v) => {
      this.showOverlay = v;
      this.emitPreview();
    });

    // 顺序提示：描边必须在合成之后，否则身体和武器各自带一圈边，
    // 叠起来接缝处会出现两条黑线（BACKEND_PLAN_V2.md §2.3）。
    this.orderHint = h('div', { class: 'kit-warn', text: '描边应在合成之后做，否则接缝会出现双线' });

    return h('div', {}, [
      field('预设', null, this.presets),
      this.overlayToggle,
      this.orderHint,
      advanced([
        field('粗细（格）', '单位是恢复后的 1x 网格像素', this.thickness),
        field('位置', null, this.positionPick),
        h('div', { class: 'kit-row' }, [this.connToggle, this.diagToggle]),
        field('颜色', '「相邻取色压暗」通常比纯黑好看', this.colorPick),
        field('压暗程度 %', null, this.darken),
        this.uniform,
      ]),
    ]);
  }

  markCustom() {
    this.preset = 'custom';
    this.presets.setActive('custom');
    this.schedule();
  }

  syncControls() {
    const s = this.settings;
    this.thickness.set(s.thickness ?? 1);
    this.positionPick.value = s.position ?? 'outer';
    this.colorPick.value = s.colorMode ?? 'fixed';
    this.darken.set(s.darken ?? 40);
    this.connToggle.set((s.connectivity ?? 8) === 8);
    this.diagToggle.set(s.skipDiagonal !== false);
  }

  analyzeParams() {
    return { preset: this.preset, ...this.settings, color: hexToRgb(this.settings.color ?? '#000000') };
  }

  applyParams() {
    return this.analyzeParams();
  }

  renderReadout(result, roundTripMs) {
    const a = result.analysis ?? {};
    const pct = a.total_pixels ? ((a.outline_pixels / a.total_pixels) * 100).toFixed(1) : '0.0';
    this.status.textContent =
      `描边 ${a.outline_pixels}/${a.total_pixels} 像素（${pct}%）`
      + ` · 后端 ${Math.round(a.elapsed_ms ?? 0)}ms · 往返 ${roundTripMs.toFixed(0)}ms`;
    this.appendWarnings(result.warnings);
  }
}

function hexToRgb(hex) {
  const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(String(hex));
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [0, 0, 0];
}
