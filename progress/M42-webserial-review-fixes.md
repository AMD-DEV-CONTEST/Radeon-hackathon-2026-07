# M42 · 真机前独立审查：修复 2 个高危 bug（hermes 审查）

- **日期**：2026-08-06
- **完成了什么**：真机验收前最后一次把关——让 hermes 独立审查 `lib/webserial.ts`（pi 因超时未产出）。审查抓到 **2 个高危 + 2 个中低危 bug**，全部修复；顺带补 `emergencyStop` 急停 API。冒烟测试 31 → **34 断言**。
- **解决的 bug**（按严重度）：
  1. **🔴 reader 永久死锁（高危）**：`read()` 超时后 `Promise.race` 丢弃 pending read，下一次 `reader.read()` 抛 TypeError（Web Streams 同一 reader 只允许一个 pending read），被 catch 吞掉后 reader 卡死——后续所有事务 -3，**刷新页面才能恢复**。触发条件恰是首次上电最常见的「无响应」。修复：pending read **复用**同一 promise（数据到达后由下一次 read 消费）；`clear()`/`close()` 对 pending 场景加防护。验证：8.8 断言「超时事务后后续事务仍工作」。
  2. **🔴 广播写清零 GOAL_TIME（高危）**：`writePositionsMany` 4 字节布局的第 4 字节落在 GOAL_TIME(0x2C)，写 0 = 全速冲击（平滑动作被毁、可能撞限位）；且与单播行为不一致。修复：改 count=2（每电机 [ID, lo, hi]），完全不碰 GOAL_TIME。验证：8.6 断言新包布局。
  3. **🟡 广播拒绝语义颠倒（中）**：`writeTxRx(254)` 返回 `[-9, 0]`，只查 error 的调用方误判成功。修复：返回 `[0, -9]`。
  4. **🟢 超读字节丢失（低→中）**：审查建议 slice 裁剪，实测会**丢字节**（Web Streams 按 chunk 整块交付，切掉的尾巴回不到流里，rxPacket 凑不齐包）→ 回归被 8.2 抓到。正确修复：**rxBuf 超读缓冲**（超读部分留给下一次 read，事务边界 clear() 清掉——即原 sts3215.ts 的设计）。
- **新增**：`StsSerialBus.emergencyStop()` —— 广播关扭矩（每电机 [ID, 0]），真机安全操作。验证：8.7 断言。
- **审查确认无问题**：校验和/包长/帧同步/广播保护/事务串行化/字节序/钳制（hermes 逐条核对）。
- **关键命令**：`node scripts/webserial-protocol-smoke.mjs` → **34 passed, 0 failed**；tsc 严格检查通过。
- **最终结果**：已提交。真机验收协议（`docs/webserial-hardware-acceptance.md`）不变，风险面显著收窄——首次上电的「无响应即死锁」和「全速冲击」两类事故已被堵死。
- **教训**：独立审查（e 类任务）在真机前价值极高；审查建议要经过测试验证再采纳（slice 建议就是反例）。
