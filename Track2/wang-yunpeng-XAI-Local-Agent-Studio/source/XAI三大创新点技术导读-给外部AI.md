# XAI 三大创新点技术导读（写给外部 AI 的自查评估版）

> 本文档面向另一个具备本地文件读取能力的 AI。目的：把 XAI 数字员工平台中三个差异化机制的
> **设计逻辑、实现方式、精确代码位置、以及客观局限**交代清楚，供你独立阅读源码后评估
> 「这套东西到底有没有用、值不值得借用」。
>
> 阅读约定：所有路径均相对于项目根 `/Users/Admin/Desktop/mask/xai/`。
> 本文刻意包含「诚实的局限性」章节——请把它们纳入你的评估，不要只看优点。

---

## 一、8 层元认知记忆（含独有 failure_correction 层）

### 1.1 要解决的问题

多数 Agent 产品的"记忆"是 RAG 检索缓存：对话结束即失忆，或者只有一个扁平向量库。
带来三个具体病症：
1. **多 Agent 记忆割裂**——每个子 Agent 自建缓存，同一事实存 N 份、互相矛盾；
2. **失败不留痕**——同一个错误反复犯，因为"上次为什么失败"没有任何系统性落盘；
3. **记忆无结构**——用户偏好、临时上下文、因果归因混在一个池子里，召回噪声大。

### 1.2 设计逻辑（为什么是 8 层 + 单一事实源）

- **分层 = 按"记忆的生命周期和用途"切分**，模仿认知科学的工作记忆/短期/长期结构，再加 4 个 Agent 特有层：
  | 层 | 用途 |
  |---|---|
  | working | 当前任务上下文（易失） |
  | short_term | 近期交互 |
  | long_term | 稳定事实（由 short_term 巩固提升而来） |
  | anchor | 锚点·核心自我/代码模板（最稳定） |
  | reflection | 元认知反思（系统对自己行为的总结） |
  | causal | 因果链归因 |
  | user_profile | 用户画像·人格元记忆 |
  | **failure_correction** | **失败修正（本系统特有）：任务+错误+纠正 三元组** |
- **单一事实源**：所有引擎（Hermes 推理核 / Grok Build 工程核 / OpenClaw 执行网关）写同一个 SQLite，
  每条记忆带 `engine` 标签。禁止任何模块自建向量库——这是宪法级约束，防止记忆割裂复发。
- **failure_correction 的关键不是"存"，而是"读写闭环"**：
  - **写侧**：控制环异常、执行失败、审计不通过 → 自动 `record_failure(task, error, correction, meta)`；
  - **读侧**：**每次**通用对话构建 system prompt 时，显式按层召回最近 3 条失败修正，
    以「[任务]→[错误]→[纠正]」格式注入上下文，让模型推理时主动规避同类错误。
  - 只写不读 = 信息黑洞（我们早期就是这样，2026-07-21 才打通读侧）。这一点是多数"反思型 Agent"论文实现里最常缺的一环。

### 1.3 阅读路线图（按此顺序读）

| 步骤 | 文件 | 重点 |
|---|---|---|
| 1 | `core/memory_core.py`（全文 276 行） | 内核全部实现。L31-43 层枚举；L89-107 SQLite schema（layer/engine/key/value/importance/meta 索引）；L193-205 `record_failure()`（importance 固定 0.8，meta 可带 error_type/root_cause_hypothesis）；L207-222 `reflect()` 元认知反思（汇总 short_term+failures 落回 reflection 层）；L224-238 `consolidate()` 巩固（importance≥0.7 的短期记忆升长期，防膨胀）；L83-85 RLock+busy_timeout 线程安全细节 |
| 2 | `core/kernel/memory_bridge.py` L49-100 | **读侧闭环**。L51-58 recall 带 4s 线程超时隔离（防记忆检索阻塞对话）；L69-98 显式按层召回 failure_correction（limit=3）并格式化注入；L102 起 reflection 层同样注入 |
| 3 | `core/kernel/engine.py` L545-556、L567-580、L840 附近 | **写侧三个落盘点**：控制环异常 / 明确执行失败 / self-refine 前，均 `record_failure` 且带结构化 meta |
| 4 | `core/grok_build_engine.py` L657 | 跨引擎消费：工程核启动前查询自己 engine 标签下的历史失败 |
| 5 | 运行时数据 | `~/.xai/memory.db`（SQLite，可直接 `sqlite3` 查看 `SELECT layer,COUNT(*) FROM memory GROUP BY layer`） |

### 1.4 客观局限（评估时必看）

1. **召回是子串 LIKE + importance 排序，不是向量语义检索**（`memory_core.py` L161-183）。换句话说"8 层"的价值在结构化与闭环，检索精度并不先进；换成 embedding 召回是明确的升级方向。
2. failure_correction 读侧目前召回"最近 3 条"，**不是与当前任务语义匹配的 3 条**——任务不相关时是无效 token 开销。
3. consolidate/reflect 需要被调度触发，尚无自动衰减/遗忘机制，长期运行有膨胀风险（有 importance 但无 TTL）。
4. 层间没有强制的写入准入校验（谁都能往 anchor 写），靠约定而非机制。

**可借用的核心**：不是 8 这个数字，而是「**失败三元组（task/error/correction）+ 每次推理强制注入读侧**」这个闭环，实现成本极低（约 60 行），收益直接。

---

## 二、Guardian 治理闸门（P0/P1/P2 + HITL 审批）

### 2.1 要解决的问题

Agent 拿到 shell/文件权限后，安全策略通常只有两个极端：全放开（危险）或全人工确认（把人变成点击器）。
需要的是**结构化的"请示边界"**：什么级别自己定、什么级别留痕放行、什么级别必须问人。

### 2.2 设计逻辑

- **三级风险分级**（数据驱动的规则表，非 if-else 散落）：
  - **P0 致命**：删除/覆盖文件、force push、凭证写入、rm -rf → **默认拒绝**，须人工显式确认（human_ok）或受控 override；
  - **P1 高危**：执行命令、网络请求、装包 → 放行但**强制留痕**；
  - **P2 常规**：读文件、纯计算 → 自动通过。
- **两个关键架构决策**：
  1. **Guardian 是控制环里的单向节点**——被调用、返回决策，绝不反向调用推理/元认知模块，从设计上杜绝"审批环路"（模型说服审批器放行自己）。
  2. **默认拒绝而非默认放行**：P0 在自动模式下无 override 一律拒绝。宁可误拦，不可漏放。
- **HITL 落地闭环**：P0 动作 → 入审批队列（工单 APR-xxxx，带风险等级）→ HTTP 接口暴露给前端 → 人工批准/拒绝 + 理由 → 幂等处置 → 续跑钩子让被挂起任务继续。
- **额外两层**（企业合规向）：GovernancePolicy（工具/LLM/MCP 白名单 = 策略而非约定）+ PermissionTier（VIEWER/OPERATOR/ADMIN 权限分级）。

### 2.3 阅读路线图

| 步骤 | 文件 | 重点 |
|---|---|---|
| 1 | `core/guardian.py`（全文 229 行） | 纯函数式内核，零外部依赖，可单测。L42-53 风险规则表 `RISK_RULES`；L56-91 `classify()`/`approve()` 分级与放行逻辑；L118-138 `ApprovalQueue` 审批队列；L141-162 `before_tool_call()` OpenClaw 风格统一前置 Hook；L169-229 权限分级 + `needs_secondary_confirmation()` 二次确认 |
| 2 | `core/kernel/guardian_bridge.py`（全文 126 行） | 引擎接线层。L20-28 危险关键词库（rm -rf/force push/drop table 等）；L47-62 `guard_action()` 从自然语言输入识别动作类型——**防止一切聊天都被当 P2 而让闸门形同虚设**；L77-104 `resolve_approval()` 幂等处置 + 续跑钩子；L107-126 `pending_approvals()` 带 level 输出 |
| 3 | `server_xai.py` | 搜 `guardian/pending` 与 `guardian/approve` 两个 HTTP 端点（HITL 前端接口） |
| 4 | 实测验证 | `scripts/security_scan.py` 中 `check_guardian()`：发起真实 P0 探针（write_file 请求）→ 断言被拦截入队 → 自动清理探针工单。可直接运行 `python3 scripts/security_scan.py` 复现 |

### 2.4 客观局限

1. **分级靠关键词启发式**（guardian_bridge L20-28），非语义理解。改写措辞（如 base64 编码命令、中文变体）可能绕过升级判定——防呆不防恶意。这是所有规则式护栏的共同弱点，缓解方向是叠加 LLM 分类器做第二意见（但要小心又引入"模型说服模型"环路）。
2. 审批队列在**进程内存**中，重启丢失未决工单（有 `_pending_approvals` 但未持久化）。
3. P1"留痕放行"的审计日志目前较弱，追溯链不完整。
4. override 参数存在即是一个可被滥用的口子——依赖调用侧纪律。

**可借用的核心**：「**规则表分级 + 默认拒绝 + 单向节点（审批器不可被推理层反向调用）+ 幂等 HITL 工单**」这四件套。整套不到 360 行、零依赖，移植成本一天以内。

---

## 三、诚实自验收体系（界面驱动黑盒调试员）

### 3.1 要解决的问题

AI 系统最隐蔽的失败模式是"**自己改卷子自己打分**"：AI 既写代码又验收，验收结论天然不可信；
更糟的是 AI 倾向于报喜——没数据时猜一个 pass，探针误报时装作没看见。
需要一个**结构性诚实**的自测量体系，而不是"提醒 AI 要诚实"。

### 3.2 设计逻辑（四条纪律 = 结构保证，非道德约束）

1. **只测量不修复**：验收角色只走公开 HTTP 接口/只读 CLI 探针，禁止改内核/记忆/Guardian。发现问题 → 报告 → 修复走 Guardian 闸门另行审批。角色分离在接口层物理隔离，不靠自觉。
2. **六维验收全景**：功能/性能/安全/数据/运维/诚实治理，每维独立打分（pass/warn/fail/**unknown**）。
3. **unknown 是一等状态**：无数据时报 unknown 而不是猜 pass 或谎报 fail（例：服务刚重启、tracer 零流量 → 性能=unknown）。**"我不知道"是合法答案**——这一条是整个体系的灵魂。
4. **账本只追加**：每次跑批结果追加写 `acceptance_ledger.jsonl`，历史不可篡改，趋势可回溯。

### 3.3 阅读路线图

| 步骤 | 文件 | 重点 |
|---|---|---|
| 1 | `server_routes_acceptance.py`（全文 339 行） | 聚合器。`_self_get()` 自 HTTP 驱动操作员接口（黑盒姿态——即使代码就在旁边也只走公开面）；`_run_probe()` subprocess+超时跑 CLI 探针；`_compute_dims()` 六维计算——**注意 tracer_total==0 → status=unknown 的处理**；`_overall()` 汇总；限频锁 `_MIN_INTERVAL=60` 防跑批风暴；三个端点 GET /api/acceptance、GET /history、POST /run |
| 2 | `scripts/security_scan.py`（231 行） | 安全维探针：SAST 扫硬编码密钥/危险模式 + 鉴权门探测 + Guardian 真实拦截探测。**重点看 `_inside_string()`**——检测模式字符串字面量本身曾被误报为危险代码（狼来了问题），此函数即诚实性修正的实例 |
| 3 | `scripts/honesty_check.py`（178 行） | 诚实维探针：15 项检查系统自述与真实能力的一致性（模型宣称 vs 实际路由、能力清单 vs 端点存在性） |
| 4 | `scripts/smoke_test.py`（219 行） | 功能维探针：38 项端点冒烟。曾有双重计数 bug（报 76/38），修复过程本身说明探针也要被质疑 |
| 5 | `acceptance_ledger.jsonl` | 只追加账本实例，每行一次完整跑批记录 |
| 6 | `frontend/src/AcceptancePanel.tsx` | 前端验收调试台（六维实时 + 跑批 + 历史趋势），视图只读 |
| 7 | `ACCEPTANCE_DEBUG_RUN_2026-07-28.md` | 一次实弹全面调试报告样例 |
| 8 | `/Users/Admin/Desktop/mask/AI协作生产系统方法论-v3.1.md` 第十二章 | 模式的方法论沉淀（四条纪律的完整论述） |

### 3.4 一个有说服力的实证

首次跑批时，安全探针报 `secrets=1`——**抓到的是验收模块自己代码里的硬编码 token**（从旧脚本复制来的默认值）。调试员抓出了自己的问题并走正规流程修复。这证明"角色分离 + 机器判定"不是摆设：它对自己人同样无情。

### 3.5 客观局限

1. 六维中数据/运维维目前是**浅探测**（KB 可用性、健康位、错误计数），不含数据恢复演练、混沌注入等深度验证——覆盖广度够、深度分维不均。
2. 探针本身也是代码，也会有 bug（双重计数、SAST 误报都真实发生过）——体系没有"探针的探针"，最终仍需人抽查。
3. 聚合器与被测系统**同进程部署**，进程级故障会连验收能力一起带走（独立进程部署是明确改进方向）。
4. "诚实维"检查的是自述一致性，无法检测模型输出内容层面的幻觉。

**可借用的核心**：「**验收角色只走公开接口（物理黑盒）+ unknown 一等状态 + 只追加账本 + 修复必须走另一个闸门**」。这套约束与具体技术栈无关，任何 Agent 系统都能移植，成本主要在纪律而非代码。

---

## 四、给评估者的总结

三个机制的共同哲学：**不依赖模型的自觉，用结构保证行为**——
- 记忆闭环：不指望模型"记得教训"，而是每次推理强制注入失败史；
- Guardian：不指望模型"守规矩"，而是默认拒绝 + 单向审批节点；
- 自验收：不指望模型"说实话"，而是接口层物理隔离 + unknown 合法化 + 账本不可篡改。

评估建议：先跑 `python3 scripts/smoke_test.py --json`、`python3 scripts/security_scan.py --json`、
`python3 scripts/honesty_check.py --json`（只读，无副作用），再读上述源码，最后用
`sqlite3 ~/.xai/memory.db` 查 failure_correction 层的真实数据。三块中工程复杂度都不高
（内核合计约 2000 行），**价值在设计约束而非代码量**——这既是优点（易移植）也意味着
它们不构成技术壁垒，真正的壁垒是持续执行这些纪律的运营惯性与积累的记忆/账本数据。

*生成于 2026-07-29，基于当日代码实况核对（文件行号以当日版本为准）。*
