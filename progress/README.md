# BotverseX 进度报告 / Progress Journal

本目录记录每个重大里程碑的小结，与 Git 提交历史一一对应。

## 规则

每完成一个里程碑（通常对应一次或几次 commit），就新增一份 `MXX-标题.md`：

- 文件名格式：`MXX-短标题.md`（例：`M10-rocm-gfx1151-unblocked.md`）
- 必含字段：
  - **日期**：`YYYY-MM-DD`
  - **完成了什么**：1–3 句话说明这次推进的范围
  - **解决了什么问题**：列出本次修复的 root cause（越具体越好）
  - **关键命令 / 配置**：可以直接复制粘贴的代码块
  - **最终结果**：验证用的命令 + 输出 / 截图 / benchmark 数字

里程碑号（M10、M11……）跟 Git tag / commit 对齐，方便回溯。

## 已完成清单

| 编号 | 标题 | 日期 | 文件 |
|------|------|------|------|
| M10 | ROCm gfx1151 + torch 2.10 打通 | 2026-04-21 | [M10-rocm-gfx1151-unblocked.md](./M10-rocm-gfx1151-unblocked.md) |
| M11 | Step 4 数据采集：lerobot-record CLI 包装 + 中文 UI | 2026-04-21 | [M11-step4-record-cli-wrapper.md](./M11-step4-record-cli-wrapper.md) |
| M12 | Camera UX hardening（Step1/Step4） | 2026-04-21 | [M12-camera-ux-hardening.md](./M12-camera-ux-hardening.md) |
| M13 | Step1-4 稳定可复现录制 | 2026-04-21 | [M13-stable-record.md](./M13-stable-record.md) |
| M14 | Training 支持 so101 HF 数据集选择 | 2026-04-21 | [M14-training-so101-datasets.md](./M14-training-so101-datasets.md) |
| M15 | 当前进度审计与下一阶段执行方案 | 2026-04-23 | [M15-current-state-and-next-execution.md](./M15-current-state-and-next-execution.md) |
| M16 | BotClaw v0.9 执行清单 | 2026-04-23 | [M16-day-by-day-execution-checklist.md](./M16-day-by-day-execution-checklist.md) |
| M17 | 三档订阅实现记录 | 2026-05-12 | [M17-subscription-implementation.md](./M17-subscription-implementation.md) |
| M18 | 当前状态审计与生产同步确认 | 2026-05-17 | [M18-current-state-production-sync.md](./M18-current-state-production-sync.md) |
| M19 | Reachy Mini 控制台、云端路由与生产 E2E | 2026-05-17 | [M19-reachy-mini-ux-cloud-e2e.md](./M19-reachy-mini-ux-cloud-e2e.md) |
| M20 | Reachy 串口自动探测、Local Agent 发布与 Setup 四步化 | 2026-05-18 | [M20-reachy-serial-autodetect-and-agent-release.md](./M20-reachy-serial-autodetect-and-agent-release.md) |
| M28 | 平台收敛执行计划（止血：删假数据 / 救零安装入口 / 死字段清理） | 2026-07-31 | [M28-consolidation-execution-plan.md](./M28-consolidation-execution-plan.md) |
| M29 | WebSerial 零安装接入设计（当前执行主线立项） | 2026-08-06 | [M29-webserial-design.md](./M29-webserial-design.md) |
| M30 | WebSerial S1：浏览器 Feetech 协议层（类型化移植，15 断言） | 2026-08-06 | [M30-webserial-s1-protocol-layer.md](./M30-webserial-s1-protocol-layer.md) |
| M31 | 第一次动作体验 brief（三方 agent 咨询 + LeLab/PrismaX 对标） | 2026-08-06 | [M31-first-move-experience-brief.md](./M31-first-move-experience-brief.md) |
| M32 | WebSerial S2：两套实现合并 + 面板接入通用层（23 断言） | 2026-08-06 | [M32-webserial-s2-merge-and-panel.md](./M32-webserial-s2-merge-and-panel.md) |
| M33 | U1 第一动作仪式（90 秒三步 + 挥手 + 🎉；修 sync-write 包 bug） | 2026-08-06 | [M33-first-move-ceremony-u1.md](./M33-first-move-ceremony-u1.md) |
| M34 | U2 首页二元入口（浏览器直连变主 CTA）+ 提交拆分纪律 | 2026-08-06 | [M34-homepage-binary-entry-u2.md](./M34-homepage-binary-entry-u2.md) |
| M35 | U5 导航收敛第一刀（Build → 实验室） | 2026-08-06 | [M35-nav-convergence-u5.md](./M35-nav-convergence-u5.md) |
| M36 | 工作区盘点：137 个未提交文件按功能块快照提交（git 归零） | 2026-08-06 | [M36-workspace-sweep.md](./M36-workspace-sweep.md) |
| M37 | WebSerial S3：3D 孪生跟动（URDF 关节名 = 电机 ID） | 2026-08-06 | [M37-webserial-s3-3d-twin.md](./M37-webserial-s3-3d-twin.md) |
| M38 | U3 3 秒首录闭环（POST /api/datasets/record + 面板录制） | 2026-08-06 | [M38-webserial-u3-first-record.md](./M38-webserial-u3-first-record.md) |
| M39 | U4 串口诊断（端口枚举/波特率探测/ID 扫描/日志导出） | 2026-08-06 | [M39-webserial-u4-serial-diagnostics.md](./M39-webserial-u4-serial-diagnostics.md) |
| M40 | 访谈门禁材料（H1/H2/H3 假设验证流程与决策规则） | 2026-08-06 | [M40-interview-gate-materials.md](./M40-interview-gate-materials.md) |
| M41 | M28 止血清单复核：13/13 全部落地（T2-1 由 WebSerial 主线完成） | 2026-08-06 | [M41-m28-reaudit.md](./M41-m28-reaudit.md) |
| M42 | 真机前独立审查：修复 2 个高危 bug（pending-read 死锁 / GOAL_TIME clobber，hermes 审查） | 2026-08-06 | [M42-webserial-review-fixes.md](./M42-webserial-review-fixes.md) |
| M43 | UX 审计修复轮（去 AI slop + 真实化 + 第一动作叙事修复） | 2026-08-06 | [M43-ux-audit-fixes.md](./M43-ux-audit-fixes.md) |
| M44 | 导航收敛第二刀（M1 审计项）+ L1 死样式清理 | 2026-08-06 | [M44-nav-convergence-round2.md](./M44-nav-convergence-round2.md) |
| M45 | 全 runtime 社区资源区块（用户/社区/设计三角度，打样+三页落地） | 2026-08-06 | [M45-runtime-community-resources.md](./M45-runtime-community-resources.md) |
| M46 | 社区资源区块补齐：Reachy Mini + Unitree G1 | 2026-08-06 | [M46-community-resources-reachy-g1.md](./M46-community-resources-reachy-g1.md) |
| M47 | 首次访客即时玩：hero 主 CTA 换为虚拟 Reachy | 2026-08-06 | [M47-first-visitor-instant-play.md](./M47-first-visitor-instant-play.md) |
| M48 | 本机计算设备探测（ROCm/CUDA 面补齐） | 2026-08-06 | [M48-local-device-probe.md](./M48-local-device-probe.md) |
| M49 | Dashboard 中文化（M5 审计项，用户角度） | 2026-08-06 | [M49-dashboard-chinese.md](./M49-dashboard-chinese.md) |
| M50 | 本机 Agent https 残留回退（线上 ERR_SSL_PROTOCOL_ERROR 修复） | 2026-08-06 | [M50-agent-https-fallback.md](./M50-agent-https-fallback.md) |
| M51 | 「登录已过期」全局横幅（401 不再静默） | 2026-08-06 | [M51-auth-required-banner.md](./M51-auth-required-banner.md) |
| M52 | 生产重建上线（M38–M51 全量部署）+ 设备探测 asyncio 修复 | 2026-08-06 | [M52-production-rebuild-and-asyncio-fix.md](./M52-production-rebuild-and-asyncio-fix.md) |

**战略（不进里程碑号，进 strategy/）：**  
[2026-07-31 产品真相与下一步](../docs/strategy/2026-07-31-product-truth-and-next.md) — M28 止血后的造血判断：空转数据、买家修正、访谈门禁、WebSerial 含义。**当前执行以该文件为准。**
