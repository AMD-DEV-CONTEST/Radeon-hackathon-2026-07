# M16 执行清单（Day-by-Day）

目标：把 BotClaw v0.9 从“协议草案 + 占位 schema”推进到“安全层最小可用 + 脚本验收闭环”。

执行原则：

1. 每天结束必须更新「完成证据」。
2. 任何“完成了”结论必须跑 `scripts/botclaw-acceptance-gate.sh`。
3. 先功能最小闭环，再谈扩展。

---

## Day 1-2：Lease（租约系统）

### Day 1

- [ ] 在 realtime 增加租约状态存储（内存版即可）
- [ ] 增加 lease 获取 / 释放 API（最小接口）
- [ ] skill run 入口接入租约检查（无 lease 不执行）

**完成证据**
- `GET lease` 可返回 `idle/leased`
- 冲突请求返回可诊断错误（lease_conflict）

### Day 2

- [ ] 给 `skill_run_event` 写入 lease 相关字段（`lease_holder`, `phase=lease`）
- [ ] UI/日志层输出租约冲突信息
- [ ] 增加 lease 超时释放（expired）

**完成证据**
- 同 runtime 并发执行时，第 2 个请求被拒绝并有清晰错误
- 日志可追踪 `lease -> execute -> release`

---

## Day 3-4：Run Event（执行事件）

### Day 3

- [ ] 定义 run lifecycle phases：`validate -> lease -> preflight -> execute -> monitor -> cleanup -> done`
- [ ] 在 API skills run 路径打点，写入结构化事件
- [ ] 失败场景映射统一错误码（`runtime_unavailable`, `lease_conflict`, `estop`）

**完成证据**
- 任意 run 至少产出 4 条 phase 事件
- `failed` run 有事件级错误码，而不仅是字符串错误

### Day 4

- [ ] 让 workflow `skill_invoke` 展示 run phase（最小可视化）
- [ ] run 详情接口返回事件序列
- [ ] 增加事件回放（按时间排序返回）

**完成证据**
- 前端可看到 run 进入哪个 phase 卡住
- 能复盘最近一次失败 run 的完整 phase timeline

---

## Day 5-7：Safety Envelope + 验收脚本

### Day 5

- [ ] 在 runtime 写入 joint limit clamp（先做 SO-101）
- [ ] 把 clamp 结果打到 `skill_run_event.safety_violation`
- [ ] `mode=warn/clamp/estop` 三种策略最小实现（哪怕 estop 先返回错误）

**完成证据**
- 超限动作会触发可见 safety 事件
- `warn` 不拦截，`clamp` 修正，`estop` 阻断

### Day 6

- [ ] 将 `scripts/botclaw-acceptance-gate.sh` 升级为 CI 可执行
- [ ] 增加 safety 相关断言（schema + 最小行为）
- [ ] 在 progress 文档登记 gate 输出样例

**完成证据**
- gate 一次跑完并 PASS
- gate fail 时能准确定位是哪一层失败

### Day 7

- [ ] 进行一次 M16 mini acceptance（本地复现）
- [ ] 输出 M16 周报：已落地 / 风险 / 下周计划
- [ ] 决策是否进入 M17（真实 Rewind + Auto-hold 行为）

**完成证据**
- 产出一份可分享的验收记录（脚本输出 + 简短结论）
- 明确 M17 scope，不再边做边漂移

---

## 每日固定命令（下班前必须跑）

```bash
bash scripts/botclaw-acceptance-gate.sh
```

若失败：不允许标记“完成”，先修复后再记录进度。

---

## 风险提示

- Lease 与现有 teleop/run 入口可能出现状态竞争，先以内存锁解决，再考虑持久化。
- Safety Envelope 先做关节限位，不要第一周硬上 3D workspace 复杂几何。
- run event 一定先统一 phase 命名，否则后续日志会再次碎片化。
