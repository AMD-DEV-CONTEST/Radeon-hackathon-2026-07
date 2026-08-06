# M36 · 工作区盘点：137 个未提交文件按功能块快照提交

- **日期**：2026-08-06
- **完成了什么**：把工作区全部未提交改动（74 个未跟踪路径 + 63 个已跟踪修改）按功能块拆成若干「as-is 快照」提交，消除「小改动落在 WIP 上整文件混入提交」的反复事故（M34/M35 各发生一次）。
- **背景**：连续两轮 `git add` 整文件混入别人 WIP 的根因 = 工作区 130+ 文件未提交。本轮全部按块 checkpoint（repo 历史本有 checkpoint 惯例，如 a0e8d28），**不改变任何代码内容**，只归位。用户可随时 amend/squash。
- **块划分（按功能）**：
  1. realtime：LeKiwi runtime + remote_compute + quest_teleop + URDF 资产（lekiwi/unitree_g1/amazing_hand）+ outputs
  2. web：LeKiwi / RemoteCompute / VirtualPlay 页面 + lib + workbench 组件
  3. web：i18n 辅助（index/store/useT，补齐 locales 块）
  4. web：已跟踪修改（App/pages/components/lib/store/types/index 快照）
  5. realtime：已跟踪修改（api/runtimes/config 快照）
  6. api：trainings.py + copilot_site_knowledge 快照
  7. scripts：deploy/sync/robot 工具快照
  8. docs：strategy + playbooks + M28 快照（含执行权威 2026-07-31-product-truth-and-next.md——此前未入库有丢失风险）
  9. data：Reachy Mini moves（emotions + dances，含上游 LICENSE）
- **安全检查**：未跟踪清单 grep `.env/token/secret/key/pem/cert/password` 零命中；`botversex_dev.db` 不在改动列表。
- **执行状态**：提交时模型安全分类器（deepseek-v4-pro）间歇性不可用，写命令多次被拦；块 1 起在重试中完成。**每块 commit message 均标注 "working-tree WIP as-is"**。
- **最终结果**：完成后 `git status` 应归零（除 .gitignore 排除项）；M36 记录块清单供追溯。
