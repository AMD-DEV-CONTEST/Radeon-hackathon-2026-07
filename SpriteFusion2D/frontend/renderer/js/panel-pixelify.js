// 像素化面板 —— FRONTEND_PLAN_V2.md §3.3
//
// 与 recover 是两件不同的事，UI 上必须区分清楚：
//   recover   源已经是像素画但格子歪了 → **找出**真实网格
//   pixelify  源是照片/插画/视频帧     → **强加**一个网格
// 导入时由 source.classify 自动判断走哪条，判断结果在界面上明说并允许一键切换。

import { PreviewPanel, advanced, field, picker, presetRow, slider, toggle } from './panel-kit.js';
import { h } from './views.js';

const WIDTH_PRESETS = [
  { id: '32', label: '32', value: 32 },
  { id: '64', label: '64', value: 64 },
  { id: '96', label: '96', value: 96 },
  { id: '128', label: '128', value: 128 },
];

// 固定调色板是这个面板最值钱的功能：纯数据、零算法成本，
// 但「我要 Game Boy 风格」是目标用户的高频真实诉求。
const PALETTES = [
  { id: 'auto', label: '自动学习' },
  { id: 'gameboy', label: 'Game Boy（4 色）' },
  { id: 'pico8', label: 'PICO-8（16 色）' },
  { id: 'nes', label: 'NES（16 色）' },
];

const DITHERS = [
  { id: 'none', label: '不抖动' },
  { id: 'bayer4', label: '有序 4×4' },
  { id: 'floyd-steinberg', label: '误差扩散' },
];

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
    this.palettePick = picker(PALETTES, this.settings.palette, (v) => {
      this.settings.palette = v;
      this.colorsRow.style.display = v === 'auto' ? '' : 'none';
      this.schedule();
    });
    this.colors = slider(this.settings.colors, { min: 4, max: 64, step: 4 }, (v) => {
      this.settings.colors = v;
      this.schedule();
    });
    this.colorsRow = field('色数', '仅「自动学习」时生效', this.colors);

    this.ditherPick = picker(DITHERS, this.settings.dither, (v) => {
      this.settings.dither = v;
      // 误差扩散会打散色块，让后续描边长出大量毛刺——对精灵图是灾难
      this.ditherWarn.style.display = v === 'floyd-steinberg' ? '' : 'none';
      this.schedule();
    });
    this.ditherWarn = h('div', {
      class: 'kit-warn',
      text: '误差扩散会打散色块，描边后会长出毛刺；精灵图建议用「不抖动」',
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
      field('输出宽度（像素）', '唯一必填项', h('div', {}, [this.widthPresets, this.widthSlider])),
      field('调色板', null, this.palettePick),
      this.colorsRow,
      advanced([
        field('抖动', '精灵图默认不抖动', this.ditherPick),
        this.ditherWarn,
        field('锐化', null, this.sharpen),
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
          ? `识别为已有像素画（网格约 ${info.detected_step}px），建议用「修复」`
          : '识别为照片/插画，按像素化处理',
      }),
      h('button', {
        class: 'px-btn px-btn--sm',
        text: isPixel ? '改用修复' : '改成修复像素画',
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
    this.status.textContent =
      `${a.source_width}×${a.source_height} → ${a.out_width}×${a.out_height}`
      + ` · ${a.colors_used} 色`
      + ` · 后端 ${Math.round(a.elapsed_ms ?? 0)}ms · 往返 ${roundTripMs.toFixed(0)}ms`;
    this.appendWarnings(result.warnings);
  }
}
