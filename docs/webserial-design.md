# WebSerial 零安装接入 · 设计文档

> **日期**：2026-08-06 ｜ **状态**：设计完成，待实施 ｜ **归属**：最高纲领「降低有硬件→第一次能动的门槛」的执行主线
> **依据**：`docs/strategy/2026-07-31-product-truth-and-next.md`（执行权威：证明不装 2.9GB Agent 让人第一次让机械臂动起来）
> **相关**：`docs/research-log.md`（2026-08-06 两篇）

---

## 1. 一句话

**浏览器直连串口（navigator.serial）控制 Feetech 总线机械臂：插上 USB，打开网页，点一下，臂动起来——全程不装 Python、不装 Agent、不装 2.9GB 依赖。**

## 2. 为什么是 WebSerial（选型结论）

| 维度 | 结论 |
|------|------|
| 技术 | Web Serial API（W3C 孵化规范），Chrome 89+/Edge 89+ 全桌面平台，全球覆盖 ~72% |
| 零安装 | 浏览器即驱动；不需要原生 App、驱动、CLI |
| 性能 | Web Streams 读写，实测可达 ~4 MB/s；单电机 115200 波特率、整条总线 1e6 波特率余量充足 |
| 先例 | 2026 浏览器 IDE 用 WebSerial 直接给 ESP32 烧录；在线串口调试助手产品成熟 |
| 风险 | Safari/Firefox 不支持（降级：提示用 Chrome/Edge）；HTTPS 必需（localhost 免）；单 tab 持有端口（正好匹配单机 demo） |

**不选**：MuJoCo 虚拟（已有，是另一条路，不与真机互斥）；TWA/原生壳（重，违背零安装）。

## 3. 适用边界（不吹跨机型 — 内部共识红线）

| 机型 | 总线 | WebSerial 直连 |
|------|------|----------------|
| **SO-101 / SO-100** | Feetech STS3215 串口总线 | ✅ **本设计范围**（LeRobot 同款协议） |
| Reachy Mini | Dynamixel / U2D2 | ❌ 不属本路径 |
| B601-RS | Robstride CAN（MotorBridge） | ❌ 不属本路径 |

> 口播：WebSerial 先服务 SO-101 主线；其它机型各自走既有 Runtime。**不把 WebSerial 说成万能串口。**

## 4. 目标架构

```
浏览器 (Chrome/Edge, HTTPS/localhost)
  └─ apps/web/src/lib/webserial.ts   ← 新 TS 模块（本设计的核心交付）
       ├─ requestPort()              用户手势 → 设备选择
       ├─ open({baudRate: 1_000_000}) Feetech 总线标准波特率
       ├─ Feetech 协议层
       │    ├─ writeTxRx(id, addr, data…)  指令 0x03 (WRITE)
       │    ├─ readTxRx(id, addr, count)   指令 0x02 (READ)
       │    ├─ syncReadTx(addr, ids…)      指令 0x82 (SYNC READ, 广播 0xFE)
       │    └─ 校验和 ~Σ(ID..data) & 0xFF + 响应超时/时序（txTimePerByte）
       └─ 高精度命令
            ├─ ping(id)              Present_Position 读取 = 电机在线
            ├─ writeGoal(id, pos)    写入 Goal_Position（可含 2/4 字节变长）
            └─ readState(id)         位置/速度/负载轮询
  └─ 现有 UrdfViewer / 3D twin      ← 本地状态直接驱动，不走 WS
  └─ 现有 API 层（可选）            ← 数据落库/录制时经后端（复用既有 Record 管线）
```

**关键架构决策**：
1. **浏览器 ↔ 串口直连，绕过 realtime 服务器**。这是「零安装」的兑现点：真机路径不再依赖 Local Agent / 证书 / 常开终端。
2. **3D 跟随用本地状态**：WebSerial 轮询的关节值直接驱动现有 `UrdfViewer`（复用 B601/Reachy 的虚拟预览模式组件），不需要 WS。
3. **Agent 路径保留**：已装 Agent 的用户仍走既有 `lerobot-teleoperate`；WebSerial 是**同一条能力的另一扇门**（13 级台阶 → 推门就进），两条路径并存，互不破坏。
4. **录制的数据格式与 LeRobot 对齐**：协议一致 → 后续 WebSerial 录制产出可直接进现有 Record/Dataset 管线（本轮不实现，留作验证后的下一步）。
5. **安全纪律沿用**：只读/安全命令（ping、read、write goal position），不写寄存器、不改电机 ID、不设零点；电机 ID 唯一化引导沿用 `ping 1..N` 检测的既有做法（LeRobot issue #526 的教训）。

## 5. 参考实现（已确认存在，可直接移植）

`apps/realtime/dora-bambot/_next/static/chunks/881-47c588f365fe1541.js`（bambot.org 快照）内已含**完整浏览器 Feetech 驱动**，提取到的关键件：

- `requestPort()` / `openPort({baudRate: 1e6})` / `readable.getReader()` + `writable.getWriter()`
- `writeTxRx(id, addr, data)` → 包形 `[FF FF ID LEN(3+n) 0x03 ADDR DATA… CHK]`
- `readTxRx(id, addr, count)` → 包形 `[FF FF ID 4 0x02 ADDR CNT CHK]`
- `syncReadTx` → 广播 0xFE、指令 0x82、LEN=4+n、逐 ID 读
- 校验和：`~(Σ(ID…DATA)) & 0xFF`；`txTimePerByte = 1000/baud × 10` 控制包间隔
- 广播 ID 254 只读保护（写命令拒绝 254）

**移植要求**：类型化 TS（`webserial.ts`）、中文注释、去掉快照里的控制台噪声、错误分类（用户取消选口 / 端口占用 / 超时）。

## 6. 实施计划（分步可验收，每步可独立提交）

| 步 | 交付 | 验收 |
|----|------|------|
| **S1** | `apps/web/src/lib/webserial.ts`：协议层移植 + 类型化 | tsc 通过；单元验证包构造（手工比对 Feetech 规范样例包） |
| **S2** | Robots 页 SO-101 卡片加「浏览器直连」按钮：requestPort → open → **ping 电机 1..7** | Chrome + SO-101 USB：页面显示各电机在线状态，**不装任何 Python** |
| **S3** | 第一个动作：`writeGoal` 单关节 → 3D twin 本地跟随 | 页面滑条/按钮驱动真实关节 + 3D 同步 |
| **S4** | 状态轮询 + 连接/断开生命周期（`connect`/`disconnect` 事件、tab 竞争处理） | 拔线/关端口 UI 状态正确 |
| **S5**（验证后） | WebSerial 录制 → 现有 Record/Dataset 管线（LeRobot 对齐） | 录一段 → 现有训练流程可消费 |

**当前状态**：S1 未开始（本轮产出设计文档 + 研究日志）。下一步从 S1 开始。

## 7. 风险与对策

| 风险 | 对策 |
|------|------|
| Safari/Firefox 不支持 | `navigator.serial` 特性检测 + 明确降级提示（用 Chrome/Edge）；不做浏览器全支持承诺 |
| HTTPS 必需 | 线上已是 HTTPS；localhost 开发免证书；局域网 IP 访问需证书（既有证书流程已存在） |
| 端口被其他程序占用（如 Agent 也在开串口） | 连接前提示释放；`getPorts()` + 占用错误分类 |
| 电机 ID 未唯一化导致读失败 | S2 的 ping 检测即诊断；引导沿用既有 MotorBridge/LeRobot 标定流程 |
| 帧同步/时序问题 | 移植时保留 `txTimePerByte` 间隔与响应超时逻辑，不简化 |

## 8. 与最高纲领的对应

> 执行定义：**证明能否在不装 2.9GB Agent 的前提下，让人第一次让机械臂动起来** ← 本设计的全部目的。
> 纲领：把「场景→数据→技能→真机」链路做短做便宜 ← WebSerial 先降「接入」这一环的门槛；录制（S5）再降「数据」一环。
