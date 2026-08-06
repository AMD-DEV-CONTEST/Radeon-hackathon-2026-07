# M35 · U5 导航收敛第一刀（Build → 实验室）

- **日期**：2026-08-06
- **完成了什么**：`Navbar.tsx` 的「Build」组（datasets/training/models/skills/workflow/reachyApps）降级改名为「实验室」（zh: 实验室 · en: Lab · ja: ラボ）；i18n 类型键 `nav.build` → `nav.lab`，三语包同步；路由全部不动（收敛不删功能）。
- **解决了什么**：
  - 心智税：六个数据闭环页面之前以「Build」平级身份和「机器人」并排，暗示它们是同层产品面；改名「实验室」后整组读作「进阶/实验性」，与 LeLab 的对照结论一致（HF 的 GUI 是单线流程：加机器人→遥操→录制→训练→部署，没有一堆平级页面）。
  - 没有动任何路由 / 功能，低风险；没有碰 B601/Reachy 组件。
- **关键命令**：`npx tsc --noEmit ... src/i18n/locales.ts`（强类型键表验证三语一致，零错误）；`... src/components/layout/Navbar.tsx`（零错误）；grep `nav.build` 无残留。
- **最终结果**：已提交。**深水区明确不做（待用户信号/访谈）**：Setup/Settings 合并、AI Hub 入口去留、空转页面下线——这些需要真实用户数据决定，不预先砍。
- **下一步**：U3 首录闭环（需 WebSerial 录制管线设计）或 U4 诊断页（可在无硬件下先做端口枚举 UI 骨架）；或先做工作区盘点（137 个未提交文件的分类提交）。
