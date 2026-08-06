# Agent Prompt（云端沙盒版）· BotverseX Deck 素材

**重要：** 你的环境**访问不到**用户的本机路径（如 `~/下载/`、`PPT素材`）。**不要**因为找不到本地文件就停止；改为完成下面「云端可做」任务，并输出可下载成果 + 清单。

用户会在本机把文件拷进：`docs/presentations/assets/`（仓库在本地，未必已 push 到 Git）。

若用户提供了 **Git 仓库 URL**，可先 `git clone` 再读 `docs/presentations/investor-seed-2026.html` 与已有 `assets/`；**没有 URL 也照常执行云端任务**。

---

## 任务目标

为 BotverseX **Seed 投资人 pitch deck** 准备补充视觉素材，服务叙事：

> 具身智能的数据闭环入口 — 浏览器里连真机 → 录数据 → 训练 → 部署 → 装 Skill。  
> 投资人偏 web3，**先看图再看故事**；网图只作「市场/生态示意」，不能冒充已接入或客户现场。

**禁止：** AI 生成假遥操作/假真机 demo；无授权水印图；声称已量产 Unitree/已合作某大厂。

---

## 云端 Agent 必做（不依赖用户本机）

### A. 调研 + 可下载链接清单（必交付）

新建 **`MANIFEST.md`**，表格列：

| 目标文件名 | deck 用途 | 直接下载 URL 或获取步骤 | 授权说明 | 云端是否已下载 |

为每一行尽量给出 **可直接 `curl -L -o` 的 HTTPS 链接**（或官方 press 页面步骤）。

**优先搜这些公开来源：**

| 素材 | 建议来源 |
|------|----------|
| Unitree Go2 机器狗 | `unitree.com` 官网、GitHub `unitreerobotics` README 图、新闻稿配图 |
| SO-101 / LeRobot 臂 | `huggingface.co/lerobot`、GitHub `huggingface/lerobot` docs/assets、SO-101 硬件文档 |
| Reachy Mini | Pollen Robotics / Hugging Face LeRobot 文档中的 Reachy 图 |
| 四足/人形/实验室氛围 | Wikimedia Commons（筛选 CC0/CC-BY）、Unsplash/Pexels（仅 CC0 并记作者） |
| 遥操作概念 | LeRobot / ACT 论文配图、开源 repo 里 teleop 示意图（注明非 BotverseX 实拍） |

### B. 下载到输出目录（尽量完成）

在工作区创建：

```text
botversex-deck-assets/
  images/          # 已下载的 jpg/png
  diagrams/        # svg 或 html
  MANIFEST.md
  REPORT.md
  LOCAL_ONLY_FOR_FOUNDER.md
```

**P1 文件名（下载或自制后放进 `images/`）：**

- `unitree-go2-reference.jpg`
- `lerobot-so101-reference.jpg`
- `reachy-mini-reference.jpg`
- `scene-lab.jpg` 或 `scene-factory.jpg`（氛围，MANIFEST 标「示例场景」）

### C. 用 SVG/HTML 在云端「画」信息图（不依赖用户截图）

用代码生成（可导出 PNG，或交 SVG/HTML 让用户本地打开导出）：

| 输出文件 | 内容 |
|----------|------|
| `diagrams/ecosystem-runtimes.svg` | 横排三格：机械臂 / 人形 / 四足 + 小字 **「生态扩容 · 部分 Building」**；格内可嵌 `<image href="...">` 引用你已下载的图 |
| `diagrams/pipeline-6steps.svg` | 六步：连接→遥操作→录数据→训练→部署→技能，箭头连接，深色底 #0a0e14、强调色 #f59e0b |
| `diagrams/marketplace-mockup.svg` | Skill 商店线框：列表「会抓杯子 v1.2」等 + 角标 **Building** |
| `diagrams/before-after-platform.svg` | 左：ROS/脚本/终端碎片（示意）；右：一个浏览器框 + 文案「One website · full loop」 |

视觉规范：背景 `#0a0e14`，强调 `#f59e0b`，正文 `#e8edf4`，圆角 8px，少字。

若有 `chromium` / `rsvg-convert` / `inkscape`：把 SVG 导出为 `images/ecosystem-runtimes.png`（1920×1080）。

### D. 公开网页截屏（仅当沙盒有浏览器且无登录）

若可访问公网且无需登录：

- BotverseX 产品站（用户提供的 URL，如 `botversex.feispace.me`）— **仅截公开页**；需要登录的页面写入 LOCAL_ONLY。
- Hugging Face 上 `lerobot` 组织页或 SO-101 dataset 示例（公开页）。

### E. 写清「只能用户本地做」的文件

新建 **`LOCAL_ONLY_FOR_FOUNDER.md`**，列表：

| 文件 | 为何云端做不了 | 用户操作 |
|------|----------------|----------|
| `teleop-demo.gif` | 真机实拍 | 从本机 `PPT素材/遥操作演示视频.gif` 裁 15–30s |
| `botversex-*.png` 产品截图 | 需登录/内网 | 用户已有一部分在 repo `assets/` |
| `team-ethan.jpg` / `team-liuqi.jpg` | 人像 | 创始人提供 |
| `botversex-pricing.png` | 已截好 | 用户已在 repo |

---

## 云端禁止

- 不要声称已勘察用户 `~/Downloads` 并失败就结束
- 不要修改用户本地才有的 HTML（除非 clone 了 repo 且用户授权 commit）
- 不要用 AI 生成「看起来像真机演示」的照片/GIF
- 不要下载 Getty/Shutterstock 带水印预览图

---

## 交付格式（方便用户拷回本地）

1. 打包整个 `botversex-deck-assets/` 或列出所有文件的 **下载链接**（若用 GitHub Gist / artifact）。
2. **`REPORT.md`** ≤20 条：
   - 已下载哪些、已画哪些 SVG
   - 推荐 deck 插入顺序
   - 版权风险说明
3. 给用户一句合并命令示例：

```bash
# 用户在本地仓库执行（路径按实际修改）
cp -r botversex-deck-assets/images/*  docs/presentations/assets/
cp -r botversex-deck-assets/diagrams/*.png docs/presentations/assets/ 2>/dev/null || true
cp botversex-deck-assets/MANIFEST.md docs/presentations/assets/MANIFEST-cloud.md
```

---

## 可选：用户若提供 Git 仓库

```bash
git clone <REPO_URL> botversex
cd botversex
ls docs/presentations/assets/
# 只补充 assets 里还没有的文件，避免重复
```

已有文件（**不要重复找**）：`so101-hardware.jpeg`, `botversex-so101.png`, `reachymini实体图.jpg`, `botversex-reachymini.png`, `botversex-dataset.png`, `botversex-training.png`, `botversex-workflow.png`, `botversex-skill.png`, `botversex-models.png`, `botversex-aihub.png`, `botversex-localagent.png`, `so101-setup.png`, `botversex-pricing.png`。

---

## 成功标准

- 至少交付：**MANIFEST.md**（≥8 条可核实来源）+ **2 张以上** 已下载图片 **或** 3 个 SVG 信息图  
- 明确区分：**云端已完成** vs **需创始人本地提供**  
- 全程英文/中文文件名用小写+连字符

*End of cloud prompt*
