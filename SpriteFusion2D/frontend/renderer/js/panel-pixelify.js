// 像素化面板 —— FRONTEND_PLAN_V2.md §3.3
//
// 与 recover 是两件不同的事，UI 上必须区分清楚：
//   recover   源已经是像素画但格子歪了 → **找出**真实网格
//   pixelify  源是照片/插画/视频帧     → **强加**一个网格
// 导入时由 source.classify 自动判断走哪条，判断结果在界面上明说并允许一键切换。

import { PreviewPanel, advanced, field, picker, presetRow, slider, toggle } from './panel-kit.js';
import { h } from './views.js';
import { t } from './i18n.js';

const WIDTH_PRESETS = [
  { id: '32', label: '32', value: 32 },
  { id: '64', label: '64', value: 64 },
  { id: '96', label: '96', value: 96 },
  { id: '128', label: '128', value: 128 },
];

// 固定调色板是这个面板最值钱的功能：纯数据、零算法成本，
// 但「我要 Game Boy 风格」是目标用户的高频真实诉求。
function palettes() {
  return [
    { id: 'auto', label: t('pixelify.paletteAuto') },
    { id: 'gameboy', label: t('pixelify.paletteGameboy') },
    { id: 'pico8', label: t('pixelify.palettePico8') },
    { id: 'nes', label: t('pixelify.paletteNes') },
  ];
}

function dithers() {
  return [
    { id: 'none', label: t('pixelify.ditherNone') },
    { id: 'bayer4', label: t('pixelify.ditherBayer4') },
    { id: 'floyd-steinberg', label: t('pixelify.ditherFloyd') },
  ];
}

export class PixelifyPanel extends PreviewPanel {
  constructor(root, hooks) {
    super(root, { analyzeMethod: 'pixelify.analyze', applyMethod: 'pixelify.apply', ...hooks });
    this.settings = { targetWidth: 64, palette: 'auto', colors: 16, dither: 'none', sharpen: 0 };
    this.classification = null;
  }

  buildBody() {
    this.widthPresets = presetRow(WIDTH_PRESETS, '64', (p) => {
      this.settings.targetWidth = p.value;
      this.widthSlider.set(p.value);
      this.schedule();
    });
    this.widthSlider = slider(this.settings.targetWidth, { min: 16, max: 256, step: 8 }, (v) => {
      this.settings.targetWidth = v;
      this.widthPresets.setActive(String(v));
      this.schedule();
    });
    this.palettePick = picker(palettes(), this.settings.palette, (v) => {
      this.settings.palette = v;
      this.colorsRow.style.display = v === 'auto' ? '' : 'none';
      this.schedule();
    });
    this.colors = slider(this.settings.colors, { min: 4, max: 64, step: 4 }, (v) => {
      this.settings.colors = v;
      this.schedule();
    });
    this.colorsRow = field(t('pixelify.colorsLabel'), t('pixelify.colorsHint'), this.colors);

    this.ditherPick = picker(dithers(), this.settings.dither, (v) => {
      this.settings.dither = v;
      // 误差扩散会打散色块，让后续描边长出大量毛刺——对精灵图是灾难
      this.ditherWarn.style.display = v === 'floyd-steinberg' ? '' : 'none';
      this.schedule();
    });
    this.ditherWarn = h('div', {
      class: 'kit-warn',
      text: t('pixelify.ditherWarnText'),
    });
    this.ditherWarn.style.display = 'none';

    this.sharpen = slider(0, { min: 0, max: 100 }, (v) => {
      this.settings.sharpen = v;
      this.schedule();
    });

    // 分类结果条：明说我们怎么判断的，并允许一键改判（§3.3）
    this.classBar = h('div', { class: 'kit-classbar' });
    this.classBar.style.display = 'none';

    return h('div', {}, [
      this.classBar,
      field(t('pixelify.widthLabel'), t('pixelify.widthHint'), h('div', {}, [this.widthPresets, this.widthSlider])),
      field(t('pixelify.paletteLabel'), null, this.palettePick),
      this.colorsRow,
      advanced([
        field(t('pixelify.ditherLabel'), t('pixelify.ditherDefaultHint'), this.ditherPick),
        this.ditherWarn,
        field(t('pixelify.sharpenLabel'), null, this.sharpen),
      ]),
    ]);
  }

  /** 由 app.js 在选中资产后调用，展示 source.classify 的判断。 */
  setClassification(info, onSwitchToRecover) {
    this.classification = info;
    if (!info) { this.classBar.style.display = 'none'; return; }
    this.classBar.style.display = '';
    this.classBar.replaceChildren();
    const isPixel = info.kind === 'pixel-art';
    this.classBar.append(
      h('span', {
        text: isPixel
          ? t('classify.detectedPixelArt', { step: info.detected_step })
          : t('classify.detectedPhoto'),
      }),
      h('button', {
        class: 'px-btn px-btn--sm',
        text: isPixel ? t('classify.switchToRecoverLabel') : t('classify.overrideToRecoverLabel'),
        onclick: () => onSwitchToRecover?.(info),
      }),
    );
  }

  analyzeParams() {
    return { ...this.settings };
  }

  applyParams() {
    return { ...this.settings };
  }

  renderReadout(result, roundTripMs) {
    const a = result.analysis ?? {};
    this.status.textContent = t('pixelify.readoutSummary', {
      sw: a.source_width,
      sh: a.source_height,
      ow: a.out_width,
      oh: a.out_height,
      colors: a.colors_used,
      ms: Math.round(a.elapsed_ms ?? 0),
      rtMs: roundTripMs.toFixed(0),
    });
    this.appendWarnings(result.warnings);
  }
}
