# M43 · UX 审计修复轮（去 AI slop + 真实化 + 第一动作叙事修复）

- **日期**：2026-08-06
- **背景**：用户要求「功能/内容全面看、前端好看、高级不要 AI slop、用 UI UX ProMax」。执行：安装 UI/UX Pro Max 技能（uipro init -a claude，7 个技能）+ 子代理全量源码 UX 审计（H4 级发现）+ 按 ui-ux-pro-max 规则库实施修复。
- **完成了什么**（按严重度）：
  1. **H1 🔴 首录存的是静态姿态（我写的 bug）**：录制在挥手结束后才采样 3 秒 → 存的是静止基准位。修复：**录制 = 重放挥手序列期间逐姿态采样**（存的是真的「第一次挥手」动作）。
  2. **H3 🔴 Dashboard 假弹窗**：Record/Train 弹窗是假进度+假成功+不保存。修复：删除两个假 Modal，按钮改为真实跳转（/teleop、/training），顺带清掉 datasets 死状态。
  3. **H4 🔴 CopilotWidget 全站 AI slop**：indigo 紫皮（14 处）+ FAB 常驻脉冲 + ✅⚠️❌ emoji + 三个跳动点。修复：全部换 `--primary` 品牌色、去脉冲、emoji 换 lucide（CheckCircle2/AlertTriangle/XCircle）、跳动点换「正在思考…」。
  4. **H2 🟡 浏览器首录是训练死路**：无摄像头数据在训练页被 blocked 且指引回需要 Local Agent 的 /teleop。修复：blocked 提示拆两条路（Local Agent → /teleop 重录；浏览器直连 → 回直连页，注明 S5 相机对齐后可用）。
  5. **M8 🟡 AIHub emoji 头像**：🤖×3 + 🔍 → lucide Bot/Search。
  6. **M7 🟡 hero 92vh → 75vh**：fleet 不再被压出首屏。
  7. **L2 🟢 🎉 emoji 去重**：通知栏/标题去 emoji（PartyPopper 图标保留）。
- **验证**：8 个改动文件逐文件 tsc 严格检查——仅剩 Dashboard 一个**历史遗留**错误（RuntimeEntry[] vs RuntimeInfo[]，stash 对比确认先于本轮存在，未动）；协议冒烟 34/34 保持；工作区干净。
- **关键命令**：`uipro init -a claude -f -o`（安装技能）；`python3 scripts/search.py <q> -d ux`（规则查询）。
- **下一步（未做，记录决策）**：M1 导航重构（reachy apps 移出实验室/teleop 入口）、M2 按钮体系收敛、M5 三页 i18n 迁移、L1 死样式删除——中长线，避免本轮一次改太多；M4 violet 语义统一、M6 45s 门控等留待下轮。
