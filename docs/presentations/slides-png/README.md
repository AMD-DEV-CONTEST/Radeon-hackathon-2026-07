# Deck slide PNG exports

由 `scripts/export-deck-slides.mjs` 生成，用于自行组装 PPT。

## 导出

```bash
cd docs/presentations/scripts
npm install
node export-deck-slides.mjs
```

输出目录：`slides-png/investor-seed-2026/slide-01.png` … `slide-45.png`

## PPT 建议

- 幻灯片比例：**16:9**
- 每页插入对应 PNG，**适应幻灯片大小**（保持比例）
- 导出为 1920×1080 视口、`deviceScaleFactor=2`（约 3840×2160 像素），放大放映仍清晰
- 字号已在 HTML `?export=1` 模式下略放大；若仍偏小，可重跑：`node export-deck-slides.mjs --scale 2.5`
