# M30 · WebSerial S1：浏览器 Feetech 协议层（类型化移植）

- **日期**：2026-08-06
- **完成了什么**：新增 `apps/web/src/lib/webserial.ts` — 浏览器直连 Feetech 串口总线的完整协议层（移植自 dora-bambot 快照，类型化 + 中文注释 + 精简日志）；新增 `scripts/webserial-protocol-smoke.mjs` 无硬件冒烟测试（15 断言全过）。
- **解决了什么**：
  - 「零安装接入」从设计落到代码：S2（UI 直连按钮）的底层已就绪。
  - 包构造/校验和/字节序经逐字节断言验证，与 Feetech 规范一致（如 `write2Byte` Goal Position → `FF FF 01 05 03 2A 01 02 C9`）。
  - 安全纪律内建：广播 ID 254 写命令被拒绝（测试覆盖）、只暴露 ping/read/write goal position 等安全命令。
  - 技术债处理：TS lib.dom 尚无 Web Serial 类型，模块内按 W3C 规范补了最小环境声明。
- **关键命令**：
  - 类型检查：`cd apps/web && npx tsc --noEmit --strict --target ES2023 --module ESNext --moduleResolution bundler --lib ES2023,DOM,DOM.Iterable --skipLibCheck --noUnusedLocals --noUnusedParameters --erasableSyntaxOnly src/lib/webserial.ts`（通过）
  - 冒烟测试：`node scripts/webserial-protocol-smoke.mjs`（15 passed, 0 failed）
- **最终结果**：15/15 断言通过；注意全仓 `tsc -b` 仍有一批历史遗留类型错误（App.tsx/B601/workflow 等，与本轮文件无关）。
- **下一步（S2）**：Robots 页 SO-101 卡片加「浏览器直连」按钮 → requestPort → open → ping 电机 1..7。
