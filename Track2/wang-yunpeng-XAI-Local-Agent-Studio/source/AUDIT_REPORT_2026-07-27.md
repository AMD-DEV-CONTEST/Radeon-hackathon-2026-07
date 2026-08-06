# XAI 统一操作台 · 全面体检 / 自检 / 审计报告（2026-07-27）

> 审计对象：`/Users/Admin/Desktop/mask/xai/`（Phase 0 生产化加固版，React18+Vite 前端 + Python 纯标准库后端）
> 方法：**实跑审计** —— 对运行实例（:8000, PID 28040）逐个探针调用前端 `api.ts` 声明的 **49 个端点**（38 GET + 11 POST），记录 HTTP 状态 + 响应体真实度；并对代码做交叉核对。
> 对照：历史审计 `AUDIT_REPORT.md`（2026-07-18，旧架构，41 项）——本报告以其"系统性病灶"为参照，结论以**本次实跑证据**为准。

---

## 一、四个核心问题的直接回答

| # | 你的问题 | 结论 |
|---|----------|------|
| 1 | **功能是不是真的有？** | 主干功能**是真的有**：对话（真实模型，非 stub）、会话、8 层记忆、画布、Agent、能力/技能/MCP/连接器、用量统计、Memo 全部真实可用。但**进化中心(GEPA)、执行时间线(workflow)目前是"空壳数据"**（后端通、无内容）；蒸馏端点虽在但已废弃且产出低质。 |
| 2 | **后台是不是真的支持前端有的？** | **路由层 100% 接通**——前端声明的 49 个端点**无一 404/缺失**（此前担心的 `/api/agents`、`/memory/stats`、`/guardian/pending`、`/capabilities`、`/workflow/history`、`/knowledge/*`、`/memos`、`/models/list`、`/canvas/<cid>` 全在，只是注册在 `server_xai.py` 遗产链而非 `router.add`）。**但"接通"≠"能用"**：Grok Build 执行被 grok 未登录挡死，grok/sessions 接口本身坏掉。 |
| 3 | **后台能支持到什么程度？** | 见第三节逐端点表。概括：数据类端点 ~85% 返回真实数据；~10% 返回"接口通但无数据"（GEPA/workflow/guardian pending/knowledge search）；**2 个真正坏掉**（grok/sessions 报错、grok/run 鉴权失败）；1 个已废弃（distill）。 |
| 4 | **是不是都已经是通的？** | **否**。当前最关键的"不通"是 **Grok Build 执行链路**（grok 未登录）和 **grok/sessions 接口报错**。其余页面级连通性正常。 |

**为什么老出现这种问题**（根因见第五节）：本质是**"能力声明"与"真实环境"长期脱钩 + 没有启动自检/契约测试**——`wired:True` 是手写承诺，从未对实际安装的二进制/`--help` 实证；缺 key 时 `StubBackend` 静默返回假回答而非报错。

---

## 二、审计方法

- 探针脚本对 `:8000` 实跑：GET 端点取真实响应体；POST 端点发安全最小 body 判路由存在性（chat/intent/store 等已实测，测试产物已清理）。
- 交叉核对：`frontend/src/lib/api.ts`（49 端点声明）↔ `server_routes_*.py`（`router.add` 注册）↔ `server_xai.py`（遗产链）↔ 实时响应体。
- 验证 running service 是否在 StubBackend：`/api/chat` 实跑，grep `stub-answer` → **0 命中**，确认当前为真实 DeepSeek 后端（key 存于 `~/.xai/models.json`，active=DeepSeek V4 Flash）。

---

## 三、前后端契约对账（实跑结果）

`✅ 真实数据 | ⚠️ 接口通但空/降级 | ❌ 坏掉/阻塞`

### GET 端点
| 端点 | 状态 | 数据真实度 | 判级 |
|------|------|-----------|------|
| /api/auth/token | 200 | 真实 token | ✅ |
| /api/status | 200 | 真实（引擎 running） | ✅ |
| /api/system/health | 200 | healthy=true | ✅ |
| /api/system/sandbox | 200 | sandbox-exec 生效 | ✅ |
| /api/system/errors | 200 | count=0（无崩溃） | ✅ |
| /api/system/status | 200 | 真实 | ✅ |
| /api/system/changelog | 200 | 真实 commits | ✅ |
| /api/sessions | 200 | 真实会话列表 | ✅ |
| /api/sessions/<id>/messages | 200 | 真实，但含**历史 `[stub-answer]` 残留**（旧 XAI.app 无 key 会话） | ⚠️ |
| /api/agents | 200 | 3 个真实 Agent | ✅ |
| /api/memory/stats | 200 | 8 层真实计数 | ✅ |
| /api/memory/list | 200 | 真实条目 | ✅ |
| /api/memory/search | 200 | 无匹配→[]（正常） | ✅ |
| /api/memory/context | 200 | 真实语义召回 | ✅ |
| /api/guardian/pending | 200 | []（当前无待审） | ✅ |
| /api/memos | 200 | 1 条真实备忘 | ✅ |
| /api/gepa/status | 200 | **running=false / generation=0 / frontier=0** | ⚠️ |
| /api/workflow/history | 200 | **[] 空** | ⚠️ |
| /api/capabilities | 200 | 真实能力清单 | ✅ |
| /api/skills | 200 | 真实技能 | ✅ |
| /api/mcp/list | 200 | 1 个 test-mcp（echo） | ✅ |
| /api/connectors | 200 | 真实连接器列表 | ✅ |
| /api/knowledge/stats | 200 | 8 chunks / built=true / **dense_available=false** | ✅ |
| /api/knowledge/search | 200 | **hits=[]（仅 BM25 稀疏，无向量）** | ⚠️ |
| /api/canvas/main | 200 | 真实节点 | ✅ |
| /api/canvas/node-catalog | 200 | 真实节点类型 | ✅ |
| /api/grok/health | 200 | available / v0.2.111 | ✅ |
| /api/grok/models | 200 | 11 个模型 | ✅ |
| /api/grok/capabilities | 200 | **check/best_of_n 已修正为 wired=False（上一轮修复生效）** | ✅ |
| /api/grok/inspect | 200 | 真实 | ✅ |
| /api/grok/doctor | 200 | 真实 | ✅ |
| /api/grok/sessions | 200 | **ok=false："grok sessions" 缺子命令** | ❌ |
| /api/grok/model | 200 | deepseek-flash | ✅ |
| /api/models/list | 200 | 真实模型 | ✅ |
| /api/usage/stats | 200 | 真实用量 | ✅ |
| /api/usage/recent | 200 | 真实 | ✅ |
| /api/distill | 200 | 在线但**样本低质重复**（功能已废弃） | ⚠️ |

### POST 端点
| 端点 | 状态 | 判级 |
|------|------|------|
| /api/chat (SSE) | 200 | 真实流式，**无 stub** | ✅ |
| /api/intent | 200 | 真实分类 | ✅ |
| /api/knowledge/search | 200 | hits=[] | ⚠️ |
| /api/grok/run | 200 | **ok=false："Not signed in"** | ❌ 阻塞 |
| /api/guardian/approve | 200 | 拒未知工单（正确） | ✅ |
| /api/memos (create) | 200 | 真实写入（已清理） | ✅ |
| /api/memory/store | 200 | 真实写入（已清理） | ✅ |
| /api/guardian/grok-write/request | 200 | 真实建单（已关闭） | ✅ |

---

## 四、页面功能真实度（10 个导航页）

| 页面 | 依赖端点 | 真实度 | 备注 |
|------|----------|--------|------|
| 控制台 | /api/chat, /api/sessions | ✅ | 真实模型对话 |
| Grok Build | /api/grok/* | ⚠️ | 健康检查/模型/能力/inspect 通；**执行被 grok 登录挡死**；sessions 接口坏 |
| Demo 测试 | /api/chat + /api/canvas/main | ✅ | |
| 工作台 | /api/agents + /api/canvas + Dashboard/AgentWorkspace/TaskCanvas(子组件) | ✅ | |
| 执行时间线 | /api/workflow/history | ⚠️ | 接口通但永远空，UI 空态 |
| Memory | /api/memory/* + KnowledgeBase/EvolutionCenter(子组件) | ✅ | 进化子页靠 GEPA（空） |
| 能力注册表 | /api/capabilities/skills/mcp | ✅ | |
| 工具中心 | /api/skills/mcp/connectors | ✅ | |
| Guardian | /api/guardian/* | ✅ | 当前无待审 |
| 备忘录日历 | /api/memos | ✅ | 414 行组件 + API 通（日历视图为列表式，非完整 Big Calendar，但可用） |

**全部页面组件均可达**（无真正孤儿文件；Dashboard/进化/知识库 是 工作台/Memory 的子视图）。

---

## 五、本次新发现的缺陷（同一类病灶的再次发作）

1. **`/api/grok/sessions` 接口坏掉** —— `_handle_grok_sessions` 调 `gb.list_sessions()` → 执行 `grok sessions`（无子命令）；grok 0.2.111 要求 `grok sessions list` → 返回 `ok=false`。能力清单却标 `sessions | grok sessions | wired=True`。**与 `--check` bug 同一类：手写 wired 声明 ≠ 实际二进制能力**。
2. **Grok Build 执行被 grok 鉴权挡死** —— `grok run` 返回 `Not signed in`，需 `XAI_API_KEY` 或 `grok login`。这是 Grok Build 页"不通"的真正根因（`--check` 只是挡在前面让它一直没暴露）。
3. **知识库搜索实际无用** —— 仅 8 chunks、BM25 稀疏、dense 不可用，任意查询均 `hits=[]`。统计面板"可用"，但检索不可用。
4. **蒸馏端点已废弃却仍在线** —— `/api/distill` 返回重复低质样本；与"蒸馏功能 ❌ 终止"的约定冲突，应下线或标注 deprecated。
5. **`XAI.app` 桌面启动静默 stub（部署陷阱，非当前运行状态）** —— `XAI.app` 用系统 python 且不注入 key → `StubBackend` 返回 `[stub-answer]`。历史会话里的 `[stub-answer]回个一字` 即源于此。当前 launchd 服务（key 在 models.json）是真实后端，**但双击桌面 App 会落入 stub**。

---

## 六、与历史审计（2026-07-18）的对照

旧报告 41 项多针对旧架构（`web/app.js` 旧前端、`core/engine_xai.py` 旧引擎、`/loop` 命令、双引擎重复）。本轮 Phase 0 重构后，前端已换 React18+Vite、引擎换 `core/kernel/engine.py`，旧前端死 UI/双引擎等**大部分已随重构消失**。但**系统性病灶未消**：

| 旧报告病灶 | 本轮是否仍在 |
|------------|--------------|
| 能力声明虚高（wired 假） | ✅ 仍在（grok/sessions 即新例；--check 已修） |
| StubBackend 静默降级 | ✅ 仍在（XAI.app 路径） |
| 缺乏启动自检/契约测试 | ✅ 仍在（故老问题反复靠人工审计发现） |
| 模型切换对推理无效果 | ⚠️ 待复核（本轮 active 模型经 models.json key 真实生效，旧结论或已变） |
| 群聊/拓扑死 UI | ❌ 旧前端已弃，新前端无此 Tab |

---

## 七、根因分析：为什么老出现这种问题

1. **能力声明与真实环境脱钩，且无契约测试**。 `grok/capabilities` 用硬编码 `wired:True` 描述 flag/子命令，但从未对**实际安装的 grok 0.2.111 二进制**做 `--help`/子命令实测。`--check`、`--best-of-n`、`grok sessions` 都是"代码假设了二进制没有的能力"——版本漂移无护栏。
2. **StubBackend 静默降级掩盖故障**。 缺 key/缺依赖时不报错，返回 `[stub-answer]…`，用户看到"有回答"误以为通了，故障被掩盖到审计才暴露。
3. **文档/记忆描述的系统 > 实际代码**。 记忆里写"9 页+3 组件全接真实后端""蒸馏功能"等，与实际（子组件视图、蒸馏已终止）存在漂移；能力清单 `wired:True` 也是文档性虚假。
4. **无 e2e 连通性冒烟测试**。 41 项旧审计 + 本轮全靠人工/脚本临时探针发现，没有 CI 在每次启动后自动 curl 每个端点、断言 `200` 且 body 不含 `stub-answer`/`Not signed in`/`ok:false`。

---

## 八、治理建议（防止复发）

1. **加启动自检冒烟脚本** `scripts/smoke_test.py`：启动后遍历 49 端点，断言 `status==200` + 关键字段存在 + body 不含 `stub-answer`/`Not signed in`/`ok: false`；纳入 launchd 启动后钩子（Phase 0 已有 backup/restore/health，缺 contract 冒烟）。
2. **grok 能力动态探测**：启动时跑 `grok --help` + 子命令探测，动态决定 `wired` 值，删除硬编码声明（本轮 `--check` 已修，sessions 待修 + 改为动态）。
3. **StubBackend 改为显式报错/横幅**，绝不静默返回假回答。
4. **修 `grok/sessions`**：`gb.list_sessions()` 改调 `grok sessions list`；同步修正 capability 的 `flag`。
5. **Grok Build 执行**：需你提供 `XAI_API_KEY`（或跑 `grok login`），我写进 launchd plist `EnvironmentVariables` 重启即可通。
6. **蒸馏端点**下线或标 deprecated；知识库补 dense 嵌入或明确"仅稀疏检索"。
7. **文档/记忆**中"已接真实后端"类声明改为由冒烟测试生成，而非手写。

---

*本轮审计：实跑 49 端点全通过路由层；真实功能 ~85%；2 个硬伤（grok/sessions、grok/run 鉴权）+ 3 个降级项（GEPA/workflow/knowledge search）+ 1 个废弃端点（distill）。修复 `--check` 已验证生效。测试产物已清理。*

---

## 三（补）、治理修复执行记录（2026-07-27 第二轮）

> 老大拍板"按你说的来"：落地防复发治理包（冒烟自检 + 修接口 bug + grok 能力动态探测 + Stub 显式告警）。

### 改动清单（全部在 XAI 桥接层，**未碰 grok 二进制 / HTTP 接口 / 页面结构**）

| 文件 | 改动 | 类型 |
|------|------|------|
| `core/grok_build_engine.py` | `list_sessions()`：`grok sessions` → `grok sessions list`（子命令缺失导致 clap 报错，修复后返回 20 条真实会话） | 修 bug |
| `core/grok_build_engine.py` | 新增 `_detect_grok_features()`：运行时跑 `grok --help` 解析实际支持的 flag/子命令，结果缓存复用 | 根治假 wiring |
| `core/grok_build_engine.py` | `capabilities()`：`wired` 不再硬编码，改为动态探测结果驱动（`dynamic_detected=True`） | 根治假 wiring |
| `core/model_backend.py` | `StubBackend.complete()`：静默返回 `[stub-answer]` → 改为先 `logger.warning(...)` 显式告警，避免"整页假数据误判为通" | 防复发 |
| `scripts/smoke_test.py` | **新增**：遍历前端声明的 35 个端点（30 GET + 5 安全 POST），断言 200 且无 `stub-answer`/`unexpected argument`，grok 未登录等凭证问题标 WARN。支持 `--write` 验证写入路径并清理 | 防复发巡检 |

### 验证结果（重启服务后实跑）

```
XAI 冒烟自检 @ http://127.0.0.1:8000
✅ GET  /api/grok/sessions        ← 修复前 ok:false，现 ok:true（20 条真实会话）
✅ GET  /api/grok/capabilities    ← dynamic_detected=True
✅ POST /api/grok/run             ← ⚠️ Not signed in（仅凭证类，非代码 bug）
总计 35 | ✅ 34 | ⚠️ 1 | ❌ 0   （0 硬失败）
```

**grok/capabilities 动态探测实测（不再骗人）：**
```
check        wired=False   flag=--check
best_of_n    wired=False   flag=--best-of-n N
sessions     wired=True    flag=grok sessions list
json_schema  wired=True    flag=--json-schema
...（其余与 grok 0.2.111 实际 --help 对齐）
```

### 仍处于"需用户处理"的事项（非代码 bug）
1. ~~**grok 未登录**：Grok Build 执行链路被 `Not signed in` 挡死。需补 `XAI_API_KEY`（写入 launchd plist `EnvironmentVariables`）或终端跑 `grok login --device-code`。~~
   **【已解决 2026-07-27】** 老大拍板"Grok Build 直接复用主程序 key"。方案：bridge 运行时从 `~/.xai/models.json` 读取激活模型（DeepSeek V4 Flash）的 `api_key`，注入 grok 子进程 `env[DEEPSEEK_API_KEY]`，实现主控制台与 Grok Build 共用同一套凭证、key 轮换自动同步。已实测 `/api/grok/run` 返回真实代码、`modelUsage=deepseek-v4-flash`，冒烟自检 grok/run 由 ⚠️ 转为 ✅。
2. **连接器全 disconnected**：钉钉/飞书/腾讯文档等需用户扫码/OAuth/贴 Key，XAI 无法代授权（用户已确认"连上的够用，不连更多"）。
3. **空壳数据**：GEPA、workflow 时间线为设计性空态（需架构设计，非快速修复）。知识库**已升级**——见下方"第二轮升级 03:01"。
4. **`XAI.app` 双击陷阱**：用系统 python 启动不注入 Key → 静默 stub。建议改用 launchd 服务（当前已真实后端，且 bridge 动态注入 key，无需 plist 写死）。

### 后续可固化（待拍板）
- 模型 Key 管理：把 `XAI_API_KEY`/`DEEPSEEK_API_KEY` 集中写入 launchd plist，避免 App 启动踩坑。

### 第二轮升级（老大 03:01 "其他的还有哪些要升级的，你帮我弄起来"）

**① 知识库（KB）真正可用**【已修复+验证】
- 根因（两处）：
  - `server_xai.py` `do_POST` legacy 链只处理了 `/api/knowledge/search`，**漏了 `/api/knowledge/ingest`**（ingest 只写在 `do_GET`，但它是 POST）→ router 未命中直接 404。已在 `do_POST` 补 ingest 分支（与 `do_GET` 对称）。
  - 旧库仅 8 块且含 3 块完全相同文本（重复命中 bug 源于此）；稠密向量本地 11434 是 llama.cpp 服务、不支持 `/v1/embeddings`（带 model 也 400），故 `dense_available=false`，BM25-only 是预期降级（非 bug）。
- 修复：补 ingest 路由 → 清空旧 8 块 → 摄入 XAI 项目 24 个 .md 文档 → **445 块 / 26 源**，检索返回 5 条多样相关无重复命中（score 1.0/0.86/0.82/0.78/0.61）。
- 结论：KB 从"恒空"变为可召回真实项目知识。后续若想跨项目，可再摄入 `~/Workbuddy/Claw/docs`（北斗系统 153 篇）等。

**② 冒烟自检接入每日定时（防复发）**【已落地+验证】
- 新建 `~/Library/LaunchAgents/com.xai.smoke.plist`：每日 4:10 跑 `scripts/smoke_test.py`（只读 35 端点断言 200+无 stub/error），日志写 `~/.xai/logs/smoke.log`。不动原备份 plist。
- 已 `launchctl load` 并手动验证：35 ✅ / 0 ⚠️ / 0 ❌。

**仍待设计决策（非快速修复，需老大拍板是否构建）**：
- 进化中心 GEPA：空壳（running=false/gen=0），需架构设计。
- 执行时间线 workflow：空壳（history 恒空），需执行追踪设计。
- 可选：XAI.app 静默 stub 修复（让桌面 App 走 launchd 服务或注入 key）。
