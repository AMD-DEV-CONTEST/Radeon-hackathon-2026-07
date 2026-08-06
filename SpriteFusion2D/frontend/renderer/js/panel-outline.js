// 描边面板 —— FRONTEND_PLAN_V2.md §3.1
//
// 完全套用抠图面板的「预览-提交」范式：那是现有 UI 里唯一被验证好用的交互，
// 新功能应该长成一样。默认视图只有四个预设，参数全在「高级」里。

import { PreviewPanel, advanced, field, numberField, picker, presetRow, slider, toggle } from './panel-kit.js';
import { h } from './views.js';
import { t } from './i18n.js';

// 「柔和深色」= 取相邻像素自身颜色压暗，像素画里比纯黑更常用的做法
// （selective outline）。红裙子外面是暗红边而不是死黑，结果更像人画的。
function presets() {
  return [
    {
      id: 'classic',
      label: t('outline.presetClassicLabel'),
      hint: t('outline.presetClassicHint'),
      settings: { position: 'outer', thickness: 1, connectivity: 8, skipDiagonal: true, colorMode: 'fixed', color: '#000000' },
    },
    {
      id: 'soft',
      label: t('outline.presetSoftLabel'),
      hint: t('outline.presetSoftHint'),
      settings: { position: 'outer', thickness: 1, connectivity: 8, skipDiagonal: true, colorMode: 'darken-neighbor', darken: 40 },
    },
    {
      id: 'shadow',
      label: t('outline.presetShadowLabel'),
      hint: t('outline.presetShadowHint'),
      settings: { position: 'outer', thickness: 1, connectivity: 8, skipDiagonal: true, colorMode: 'fixed', color: '#000000', innerShadow: true },
    },
    { id: 'custom', label: t('outline.presetCustomLabel'), hint: t('outline.presetCustomHint'), settings: {} },
  ];
}

export class OutlinePanel extends PreviewPanel {
  constructor(root, hooks) {
    super(root, { analyzeMethod: 'outline.analyze', applyMethod: 'outline.apply', ...hooks });
    this.preset = 'classic';
    this.settings = { ...presets()[0].settings, darken: 40, innerShadow: false };
  }

  buildBody() {
    this.presets = presetRow(presets(), this.preset, (p) => {
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
      [
        { id: 'outer', label: t('outline.positionOuter') },
        { id: 'inner', label: t('outline.positionInner') },
        { id: 'center', label: t('outline.positionCenter') },
      ],
      this.settings.position,
      (v) => { this.settings.position = v; this.markCustom(); },
    );
    this.diagToggle = toggle(t('outline.skipDiagonalLabel'), this.settings.skipDiagonal, (v) => {
      this.settings.skipDiagonal = v;
      this.markCustom();
    });
    this.connToggle = toggle(t('outline.connectDiagonalsLabel'), this.settings.connectivity === 8, (v) => {
      this.settings.connectivity = v ? 8 : 4;
      this.markCustom();
    });
    this.colorPick = picker(
      [
        { id: 'fixed', label: t('outline.colorFixed') },
        { id: 'darken-neighbor', label: t('outline.colorDarkenNeighbor') },
        { id: 'hue-shift', label: t('outline.colorHueShift') },
      ],
      this.settings.colorMode,
      (v) => { this.settings.colorMode = v; this.markCustom(); },
    );
    this.darken = slider(this.settings.darken, { min: 10, max: 90 }, (v) => {
      this.settings.darken = v;
      this.markCustom();
    });
    this.uniform = toggle(t('outline.uniformAcrossFramesLabel'), true, (v) => {
      this.settings.uniformAcrossFrames = v;
      this.markCustom();
    });
    this.overlayToggle = toggle(t('outline.overlayLabel'), true, (v) => {
      this.showOverlay = v;
      this.emitPreview();
    });

    // 顺序提示：描边必须在合成之后，否则身体和武器各自带一圈边，
    // 叠起来接缝处会出现两条黑线（BACKEND_PLAN_V2.md §2.3）。
    this.orderHint = h('div', { class: 'kit-warn', text: t('outline.orderHint') });

    return h('div', {}, [
      field(t('common.presetLabel'), null, this.presets),
      this.overlayToggle,
      this.orderHint,
      advanced([
        field(t('outline.thicknessLabel'), t('outline.thicknessHint'), this.thickness),
        field(t('outline.positionLabel'), null, this.positionPick),
        h('div', { class: 'kit-row' }, [this.connToggle, this.diagToggle]),
        field(t('outline.colorLabel'), t('outline.colorHint'), this.colorPick),
        field(t('outline.darkenPercentLabel'), null, this.darken),
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
    this.status.textContent = t('outline.outlineSummary', {
      outline: a.outline_pixels,
      total: a.total_pixels,
      pct,
      ms: Math.round(a.elapsed_ms ?? 0),
      rtMs: roundTripMs.toFixed(0),
    });
    this.appendWarnings(result.warnings);
  }
}

function hexToRgb(hex) {
  const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(String(hex));
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [0, 0, 0];
}
