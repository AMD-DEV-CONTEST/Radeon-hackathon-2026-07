# M44 · 导航收敛第二刀（M1 审计项）+ L1 死样式清理

- **日期**：2026-08-06
- **完成了什么**：
  1. **实验室组补入口**：/teleop（遥操）与 /inference（推理）加入 Navbar 实验室分组——这两个真实功能页此前**在导航里完全不可达**（只能靠页面内深链），M43 审计 M1 项。
  2. **Settings 摊平**：只有单子项（算力节点）的下拉分组改为直接顶层入口。
  3. **L1 死样式删除**：`.btn-pill` / `.card-glass` / `.status-dot` 三件套（全站零引用）从 index.css 移除；保留 `.botverse-gradient`（Dashboard 在用）。
- **解决了什么**：实验室分组从「6 个平级入口」补全为「数据闭环的主干入口」（datasets/training/models/skills/workflow/teleop/inference），遥操（录制必经之路）与推理不再深藏。
- **记录决策（不做）**：Reachy Apps 单机型页与平台级入口平级不成立，但 **Reachy 页内无 /apps 入口，移除会孤儿化该页**——保留至 T2-2 通用工作台落地后随机器人页内导航自然解决（Navbar 注释写明）。
- **关键命令**：tsc（Navbar + locales 三语键表）零错误；grep 死样式零引用。
- **最终结果**：已提交。
- **下一步**：M4 violet 语义统一（引导色固定为教学语义，其余换品牌色）或训练页 GPU 状态可视化（ROCm/CUDA 面）；均无硬件依赖。
