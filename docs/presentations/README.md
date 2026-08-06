# Presentations

## 两套 Deck

| 用途 | 短链 | 主文件 | 页数约 |
|------|------|--------|--------|
| **愿景故事**（无融资） | `story-deck.html` | `story-vision-2026.html` | ~25 |
| **投资人 Seed · 首聊** | `investor-deck.html` → Teaser | `investor-seed-teaser-2026.html` | **15** |
| **投资人 Seed · 尽调** | `investor-full-deck.html` | `investor-seed-2026.html` | 43 |

线上入口：http://43.156.102.67/deck/

## Seed Investor Deck 2026

- **Teaser（首聊）:** `investor-seed-teaser-2026.html` — 15 slides · Manus 瘦身框架 · 封面 Vercel 叙事 · 无估值页 · 第 5 页 Live Demo
- **Deep Dive（Data Room）:** `investor-seed-2026.html` — 43 slides · 全平台截图 · 估值/Cap 面谈 · 风险 Q&A 仅 Data Room（`investor-red-team-memo.md`）
- **口播:** `口播稿-Investor-Teaser-2026.md` · `口播稿-Investor-Seed-2026.md`
- **导出 PPT 用 PNG：** `slides-png/investor-seed-2026/slide-01.png` … `slide-45.png`（见下方命令重导）
- **创始人：** 杨智超 @ethanyeang · CTO 刘琦
- **截图资源:** `assets/`（SO-101 / Reachy，从 AMD deck 同步）
- **待补素材清单:** `投资人-deck-素材清单.md`
- **给 Agent 的 prompt:** 本机 `prompt-素材搜集-agent.md` · 云端 `prompt-素材搜集-agent-云端版.md`
- **口播稿:** `口播稿-Investor-Seed-2026.md`
- **FAQ:** `../strategy/investor-faq.md`
- **反对派备忘:** `../strategy/investor-red-team-memo.md`
- **内部共识（机密）:** `../strategy/internal-consensus-memo.md`

```bash
xdg-open docs/presentations/investor-deck.html   # 短链，跳转到 investor-seed-2026.html
xdg-open docs/presentations/investor-seed-2026.html
```

**在线 Deck（MetaHub 机 `43.156.102.67`，`/deck/` 路径，不动 :3000）：**

| 用途 | URL |
|------|-----|
| 入口 | http://43.156.102.67/deck/ |
| 愿景故事 | http://43.156.102.67/deck/story-deck.html |
| 投资人 Teaser | http://43.156.102.67/deck/investor-deck.html |
| 投资人 Deep Dive | http://43.156.102.67/deck/investor-full-deck.html |
| MetaHub | http://43.156.102.67:3000（不动） |

口播：`口播稿-Story-Vision-2026.md` · `口播稿-Investor-Seed-2026.md`

跨本体叙事（换机税、兼容层、诚实边界）：`../strategy/cross-embodiment-narrative.md`

故事 Deck 架构图（SVG，已嵌入幻灯片）：`assets/diagrams/` · 可选 AI 补图见 `素材-故事deck-AI图可选.md`

部署：`./scripts/deploy-investor-deck.sh` → 见 `deploy/README.md`

动效：Deck 已接入 GSAP 翻页与元素 stagger；`?export=1` 导出 PNG 时自动关闭动效。

**整份 deck 导出为图片（自行拼 PPT）：**

```bash
cd docs/presentations/scripts && npm install && node export-deck-slides.mjs
```

输出：`slides-png/investor-seed-2026/` · 16:9 · 3840×2160px · 已隐藏翻页条/页码 · 字号略放大（`?export=1`）

## AMD AI Developer Conference 2026

- **Deck (HTML):** `amd-devconf-2026.html` — open with assets in `~/下载/PPT素材/`
- **Deck (PPTX):** `BotverseX-AMD-DevConf-2026.pptx` — pixel match via Chromium screenshots; GIF slides keep animation
- **Re-export:** `~/下载/PPT素材/.venv-export/bin/python ~/下载/PPT素材/export_to_pptx.py`

Open from this directory:

```bash
xdg-open docs/presentations/amd-devconf-2026.html
```

Speaker cues: see `~/下载/PPT素材/AMD-PPT-README.md`
