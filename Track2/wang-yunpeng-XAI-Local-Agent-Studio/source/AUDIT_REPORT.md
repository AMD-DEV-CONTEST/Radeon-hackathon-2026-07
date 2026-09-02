# XAI 项目健康度审计报告

> 审计时间： 2026-07-18 · 审计对象： `/Users/Admin/Desktop/mask/xai/`
> 方法： 全量静态代码审查（core/ 24 个模块 + adapters + server_xai.py + web/ + 启动链 + 文档）+ 动态实证（73 单测、意图分类实测、3 个运行时 bug 复现、路径穿越复现）
> 环境： Python 3.13.12 / pytest 9.1.1 / macOS

## 一、项目进度报告（现状总览）

**总体完成度：约 60%** —— 主对话链路真实可用且达上市级交互标准；但宪法（MEMORY.md Dual-Kernel Fusion）验收标准 ③④⑤ 均未达成，存在多处"假信号"（看似能跑、实际未接线）。

| 层面 | 完成度 | 一句话结论 |
|---|---|---|
| 1. 代码层面 | 70% | 73 单测绿、注释良好，但有 2 个实证 P0 运行时 bug + 双引擎/三前端重复 |
| 2. 逻辑层面 | 55% | 意图分发、模型切换、Project 隔离三条数据流断裂；SSE 事件流完整 |
| 3. 架构层面 | 45% | 13 个架构组件仅 8 个真实被调用；ControlLoop/LoopSafety/ProviderFallback 是摆设 |
| 4. 使用层面 | 60% | 对话/画布可用；群聊 Tab、拓扑 Tab 是死 UI；2 个前端逻辑 bug |
| 5. 部署层面 | 65% | 脚本启动可靠；XAI.app 启动即落 Stub（无 key）；1 个路径穿越漏洞 |
| 6. 对比层面 | 55% | 主链路已去 mock，但新假信号（群聊/拓扑/模型切换/LoopSafety UI）未消除 |

**验证基线**：`tests/` 下 73 个单元测试全部通过（65 + 8 分批实测，与 README 一致）；`tests/test_platform.py`（旧引擎集成测试）在本次审计沙箱中卡于 `test_substrate_shell`（`shell=True` 子进程管道未关闭，30s 超时也未救回），该文件在开发机此前为绿，判定为环境差异 + 代码气味。

---

## 二、各层面具体问题清单（按严重性排序）

### 层面 1：代码层面

**P0 — 实证运行时 bug（2 个）**

1. `/loop` 命令 100% 报错。`core/engine_xai.py:876` 调用 `self.control_loop.run(task)`，但 `core/control_loop.py` 的 `ControlLoop` 只有 `act()` 方法，**没有 `run`**。实证：`hasattr(e.control_loop, 'run') == False`。异常被 try/except 捕获转为 error 事件，用户看到"控制环异常： 'ControlLoop' object has no attribute 'run'"。**认知控制环唯一入口是断的。**
2. `_guard_for_coordination` 100% TypeError。`engine_xai.py:1179`：`classify(Action(task=task, tool=kind))`，而 `core/guardian.py:26` 的 `Action` 字段是 `(kind, target, scope)`，无 `task`/`tool`。实证复现：`TypeError: Action.__init__() got an unexpected keyword argument 'task'`。群聊治理提案（`propose_action`）一旦被调用即崩。

**P1 — 功能缺陷**

3. 联网搜索结果永远没有 URL。`engine_xai.py:603`：`"url": ""` —— `_web_search` 解析了标题和摘要，**从未提取 href**，导致给模型的引用上下文 `URL: ` 全为空，"[1][2]" 引用无落点。
4. 意图分类双轨制重复代码。`engine_xai.py:353` 的 `_classify_intent` 内置一套 rules（含 browser/memory），`core/intent_router.py` 另一套词表（不含 browser/memory、不含"分析"），两套 taxonomy 不一致且均需维护。`IntentRouter.routing` 字段计算后无人消费。
5. 双引擎 + 双服务端 + 三前端重复。`core/engine.py`（XAIEngine/run_task，被 `server.py` 和 `tests/test_platform.py` 引用）与 `core/engine_xai.py`（XAIEngine/chat，被 `server_xai.py` 引用）同名同类并存；前端有 `web/`（交付所用）、`frontend/`（旧 React+Vite）、`xai-frontend/`（849M OllamaFlow Electron）三套。
6. `_retrieve_memory_context` 有 4 处 `except Exception: pass`（`engine_xai.py:624/631/645/648`），与模块头"零静默失败"原则直接冲突，记忆/知识库检索失败完全无痕。

**P2 — 质量与兼容性**

7. `_cmd_approve` 硬编码会话 `"default"`（`engine_xai.py:852-854`）：非 default 会话发起的 P0 审批，批准后重执行会丢失原会话上下文。
8. `/api/chat/send`（非流式）只收集 `answer` 事件（`server_xai.py:220-229`），通用对话走 `token` 事件 → 非流式接口对普通聊天**永远返回空答案**。
9. `MemoryAdapter`（`core/adapters/memory_adapter.py`）共享单连接 + `BEGIN IMMEDIATE` 但**无线程锁**（SessionStore 和 MemoryCore 都有锁，唯独它没有），ThreadingMixIn 并发下事务可交叉。
10. `hermes_adapter.py:280` 传 `system=` kwarg，但 `DeepSeekBackend._build`（`core/deepseek_backend.py:127`）静默丢弃 system 消息 → 技能进化时系统指令失效。
11. `xai_mock_server.py:25`：bytes 字面量含无效 `\u` 转义（Python 3.12+ SyntaxWarning），mock 的 start 文本输出乱码。
12. 命名/注释：docstring 覆盖率高、函数长度可控（最长 `chat()` ~95 行可接受）；扣分项是 `_classify_intent` 用中文字段名（`"权重"`/`"关键词"`）和不必要的中文变量命名。
13. Python 兼容性：全部 core/*.py 在 3.13.12 编译通过；`str | None`、`list[str]` 均在 `from __future__ import annotations` 保护下，3.10+ 可用；**但 `XAI.app` 使用 `/usr/bin/python3`（系统解释器，版本不可控）**，而 `xai_go.sh`/`启动XAI.command` 硬编码 3.13.12 绝对路径（升版即断）。
14. `engine_xai.py` 方法调用审计：41 个 `def` 中 40 个可达；唯一"死方法"实为 `_cmd_loop`（可达但目标不存在，见 P0-1）。静态方法 `_wf_node_system/_wf_node_prompt/_extract_code` 均被 `_run_wf_node/_execute_code` 调用。

### 层面 2：逻辑层面

**P0 — 数据流断裂（3 条主链路）**

15. **联网搜索意图被旁路**。实证：`"搜索 2026 最新 AI 新闻"` → `IntentRouter` 判 `research`（conf=1.00，因"搜索"在 RESEARCH 词表）→ `engine_xai.py:359-368` 映射为 `research` → `_execute_intent` 无 research 分支 → 落入 `_execute_general` 普通对话。**`_execute_browser` 实际成为死区**。
16. **模型切换对推理零效果**。`engine_xai.py:114-119` 在 `__init__` 时一次性用环境变量构造 `DeepSeekBackend`；前端激活模型只改 `~/.xai/models.json`（`model_registry.activate`），运行中的后端永不重建；`provider_fallback.infer`（`core/provider_fallback.py:55`）**全代码库零调用**（grep 实证）。管理面板的添加/切换/删除 → registry 层面工作正常，但对实际推理无影响。
17. **Project 切换无记忆隔离**。`core/project.py` docstring 声称"每条记忆 meta 带 project_id → store/query 加 project 过滤"，但 `memory_core.store/query` 无 project 参数、`_safe_memory_core_write` 不写 project_id、`session_store` 不按项目分会话、workspace 不随项目切换。**隔离完全未实现**，仅 UI 上换了个名字。

**P1 — 一致性缺陷**

18. 记忆双轨写入违反宪法"单一事实源"：每轮对话同时写 `MemoryAdapter`（`~/.xai/memos.db`，层名 `short/long`）和 `memory_core`（`~/.xai/memory.db`，层名 `short_term/long_term`）（`engine_xai.py:282-289`）。两套层名不一致、两个 SQLite 文件、检索时又双库合并，重复上下文 + 概念漂移。
19. `IntentRouter.routing`（`openclaw_gateway/grok_build_engine/orchestrator/kb/reason`）算出后无任何消费者；office/research/automation 全落通用对话，"Intent Router 仲裁分发至最优内核"名不副实。
20. `CoordinationBus.publish` 每条群聊消息都写 `memory_core` short_term（`coordination.py:123`），无 `consolidate()` 定期调度 → 记忆单调膨胀。
21. SSE 事件流本身**完整**（start→intent→guard→progress→token→answer→approval→error→done 全有，slash 命令按设计无 intent/guard）；缺陷见 P2-8（非流式端点丢 token）。

### 层面 3：架构层面（对照 MEMORY.md 宪法）

**Dual-Kernel Fusion 13 组件通电检查（真实调用 ≠ 仅导入）：**

| # | 组件 | 状态 | 证据 |
|---|---|---|---|
| 1 | Hermes 内核 | ✅ 在用 | `hermes_adapter.infer/evolve`，但主要走 model_backend 而非 hermes CLI |
| 2 | Grok Build 内核 | ⚠️ 半通 | `_execute_code` 桥接 grok CLI 有回退；但画布 `gb_gen/gb_refactor/gb_test/git` 节点全落通用推理，"全部能力可用"未达成 |
| 3 | IntentRouter | ⚠️ 调用但分发断 | 见逻辑层 P0-15/19 |
| 4 | ControlLoop | ❌ 断 | 唯一入口 `/loop` 调用了不存在的方法（P0-1） |
| 5 | Reason（思考增强） | ❌ 断 | 仅经 ControlLoop（断）和旧 engine（弃用态）可达 |
| 6 | Meta（Brier 校准/L8 审计） | ❌ 断 | 同上 |
| 7 | Runner（长任务） | ❌ 未接入新引擎 | `core/runner.py` 无人调用 |
| 8 | L4 Verify | ❌ 不存在 | 代码库无此组件 |
| 9 | Distill | ⚠️ 简陋 | `/api/distill` 只是拼接近期记忆存 anchor；`hermes.darwinian_evolve` 真实 |
| 10 | Guardian | ✅ 真实生效 | 内容级 P0 识别 + 审批后真重执行 |
| 11 | memory_core（7 层单一事实源） | ⚠️ 在用但双轨 | 见逻辑层 P1-18 |
| 12 | Substrate/OpenClaw | ✅ 在用 | 本地 6 工具 + CLI 桥接 |
| 13 | 控制台（纯视图） | ⚠️ 四 Tab 有俩空壳 | 群聊/拓扑死 UI（层面 4） |
| 附 | LoopSafety 5 闸门 | ❌ 零调用 | `check/record_error/record_result/check_context/reset` 全无调用点（grep 实证）——**数值不生效，等于被跳过** |
| 附 | ProviderFallback | ❌ 零调用 + 零测试 | `infer` 无调用点；tests/ 无任何 fallback 用例（grep 实证），**无真实主备切换测试** |

**架构完成度：8/13 真实在用 ≈ 60%**。宪法验收标准 ③（认知/Guardian/记忆全打通在用）④（Grok Build 全部能力可用）未达成。

22. IntentRouter 分类质量：单关键词命中即 conf=1.0（`best/total` 归一化导致过度自信）；同分平局按 dict 遍历序偏向 CODE_DEV；RESEARCH 词表缺"分析"（靠 engine 兜底规则救回，实测 conf 0.695 判对）。整体"可用但粗糙"。

### 层面 4：使用层面

**P1 — 前端逻辑 bug（实证代码推理）**

23. **所有 slash 命令回答后误报"⚠️ 暂未收到回复，请重试"**。`web/app.js:1307-1313`：`handleSSEEvent` 被拓扑包装后**吞掉返回值**（`origHandleSSE_for_topo(ev)` 未 return）→ `sendMessage` 里 `gotContent` 永远为 false → 非 token 流场景（`/help`、`/status` 等纯 answer 场景）必现误报。
24. **Loop Safety 配置 UI 修改无效**。`app.js:1197-1206` `updateSafety` 发送 `{key:"token_budget", value:N}`；`server_xai.py:423-424` 透传 kwargs 给 `loop_safety.save()`，而 `save()` 只认 `SafetyConfig` 的扁平字段名（`core/loop_safety.py:86-91`），`key`/`value` 被 `hasattr` 检查**静默丢弃**。UI 显示"已修改"，实际从未生效。
25. 群聊 Tab 是纯静态占位。`web/index.html:274-284` 只有一个提示 div；`app.js` 全文 grep 不到 `room`/`coordination` —— 后端 `/api/agents`、`/api/coordination/rooms`、`/api/coordination/chat` 三个接口齐全却零前端调用。**死 UI（假信号）**。
26. 拓扑 Tab 事实损坏：(a) `topoFromIntent`（`app.js:1285-1304`）拿针对用户中文文本设计的正则去匹配 `ev.intent`（"code_dev"/"general" 等英文类型串），几乎永不命中；(b) `web/index.html:155` 的 `<svg id="topo-edges">` 无 `<defs><marker id="arrow">`，`app.js:1279` 的 `marker-end="url(#arrow)"` 悬空 → 连线无箭头；(c) 规则里还有重复 alternation `"扫描|扫描"`。
27. 顶部 `model-select` 下拉无 onchange 处理（`app.js:67-81` 只填充选项）→ 纯装饰。
28. `to-canvas-btn`（`app.js:1217-1224`）点"去画布"后 100ms 又点回对话视图 → 跳转失效。
29. 画布执行：20 种可拖节点中仅 `input/scan/mcp/exec/file/git` 6 类有真实后端语义（`engine_xai.py:_run_wf_node`），`gb_*/agent_*/mem_query/condition/loop` 全部落入通用模型推理；画布节点不是"引用已注册能力"（无能力注册表驱动）。DAG 拓扑排序 + 环路检测 + 逐节点 SSE 反馈本身实现正确。
30. 未发现 JS 语法错误/未定义引用（所有 getElementById 目标均在 index.html 存在，逐一核对 68 个 ID）；XSS 面尚可（先 escapeHtml 再 inlineMd，链接白名单 http(s)）。

### 层面 5：部署层面

**P1**

31. **`XAI.app` 双击启动即落 Stub**。`/Users/Admin/Desktop/mask/xai/XAI.app/Contents/MacOS/XAI` 直接 `exec /usr/bin/python3 xai_launcher.py`，既不注入 `DEEPSEEK_API_KEY`（`xai_launcher.py` 只拷贝 `os.environ`，不像 `xai_go.sh`/`启动XAI.command` 会解析 `~/.zshrc`），又用系统解释器（版本漂移）。GUI 启动 → 无 key → `StubBackend` → 所有回答都是 `[stub-answer]...`。**桌面 App 封装当前不可用（假启动）**。
32. **`/api/save` 路径穿越漏洞（实证）**。`server_xai.py:325-329`：`ext` 仅 `lstrip(".")` 未净化，`name` 净化了但 ext 没有。实证：`ext="a/../../../escape"` → 解析到 workspace 之外（`/private/tmp/escape`，`inside_workspace=False`）。本机单用户场景评级 P1，可写任意用户权限内文件。

**P2**

33. 解释器路径硬编码：`xai_go.sh:9` 与 `启动XAI.command:9` 写死 `.../python/versions/3.13.12/bin/python3`；`XAI.app` 又是另一套（/usr/bin/python3）——三处不一致。
34. `xai_launcher.py:41` 仍用 `pkill -f server_xai.py`（QA 报告称已修，但只修了 `启动XAI.command`）；并有 2 处 bare `except: pass`（119/123 行）。
35. 缺 `/api/health`（`server.log:64` 可见外部探测 404）与 `do_HEAD`（同 log 501）；`/api/models/activate/<id>` 用 GET 产生副作用；`/api/models/list` 是死端点（前端走 `/api/status`）。
36. 仓库根有残留 `server_xai.pid`（与运行期 `~/.xai/server.pid` 双 pid 文件，困惑源）；`xai_mock_server.py` 也绑 8000，与真实服务互踢端口。
37. 工程卫生：**项目无 git 版本控制**，靠 19 个 `.bak.2026...` 时间戳备份文件撑回滚（core/ 3 个、web/ 8 个、server_xai.py 3 个等）；`vendor/` 728M + `xai-frontend/` 849M 裸放无 .gitignore 策略。
38. 环境变量依赖：`DEEPSEEK_API_KEY` 单点硬依赖，缺失时静默降 Stub（状态栏有显示，可接受，建议启动日志加醒目告警）。

### 层面 6：对比层面

39. **对 WorkBuddy 三栏式**：三栏骨架（会话栏 / 对话 / 成果区）+ 主题 + 审批卡片已就位；差距在：群聊/拓扑空壳、模型切换无效、无技能市场交互、交付物仅代码块级（无 Artifacts 级富渲染）。
40. **对 Cate/Flowith/Cowork/ComfyUI 借鉴**：ComfyUI 式"后端 JSON 驱动 DAG 执行"已真实打通（`/api/workflow/run` 拓扑排序真实执行）；Flowith 式"画布即对话"未通（画布与对话数据不互通）；蓝图§6"画布只引用已注册能力（by name）"未做到（无能力注册表驱动 UI 节点）；OCTO_VEC 群聊/kanban 仅前端占位。
41. **对 S1 失败教训（假信号/mock 当真实）**：主对话链路已真实（无 simulator、搜索/代码/记忆/进化全真）✅；但**新一代假信号已出现**：群聊 Tab、拓扑 Tab、模型切换、LoopSafety 阈值 UI、`/loop` 命令、`xai_mock_server.py` 提供的假 status。教训**未完全消除**。

---

## 三、立即可修的 Top 5（今天，均在 30 分钟内）

1. **修 `/loop`**：`engine_xai.py:876` → `result = self.control_loop.act(task)`（`LoopResult` 字段 `answer/calibrated_confidence` 与现有输出代码兼容）。
2. **修 `_guard_for_coordination`**：`engine_xai.py:1179` → `classify(Action(kind=kind or "general", target=task[:200]))`。
3. **修误报"暂未收到回复"**：`web/app.js:1309` → `return origHandleSSE_for_topo(ev);`。
4. **修 Loop Safety UI 无效**：`server_xai.py:_handle_loop_safety_update` 兼容 `{key,value}` → `kwargs = {data["key"]: data["value"]}`（或改前端发扁平字段）。
5. **堵 `/api/save` 路径穿越**：`server_xai.py:325` → `ext = "".join(c for c in ext if c.isalnum())[:10] or "md"`。

## 四、下周应优先解决的 Top 5

1. **模型切换真实生效**：推理前从 `model_registry.active()` 动态构建/缓存后端（`DeepSeekBackend(api_key=entry.api_key, model=entry.model, base_url=entry.base_url)`），并把 `provider_fallback.infer` 包装进 `_execute_general/hermes.infer`；补主备切换单测。
2. **意图分发修复与双轨合并**：以 `IntentRouter` 为唯一分类器（补 `browser`/`memory` 意图与"分析"词），engine 真正消费 `routing`；"搜索/查一下"类必须落到 `_execute_browser`，同时修 `_web_search` 的 URL 提取。
3. **群聊 Tab 接线**：app.js 补 `/api/agents`、`/api/coordination/rooms`、`/api/coordination/chat` 的调用与历史轮询，消灭死 UI（后端已就绪）。
4. **LoopSafety 接线**：在 `chat()` 与 `run_workflow()` 循环中调用 `reset/check/record_error/record_result`，让 5 重闸门真实生效并补测试（当前阈值 UI 已修好后仍只是写文件）。
5. **记忆单一事实源 + Project 隔离**：下线 `MemoryAdapter` 双写（或改为 `memory_core` 的代理壳），统一层名；`store/query/recall` 增加 `project_id` 过滤并在 `_safe_memory_core_write` 注入当前项目；`consolidate()` 加定时调度防膨胀。

**附加建议（ fortnight 级）**：`git init` 纳入版本控制并清理 19 个 .bak；归档/删除旧 `engine.py` + `server.py` + `frontend/`；`XAI.app` 改为复用 `启动XAI.command` 逻辑（注入 key + 固定解释器）；补 `/api/health` 与 `do_HEAD`；把 `substrate._exec_shell` 的 `shell=True` 改为 `shlex.split` 数组形式（与 openclaw 适配器一致，同时消除本次审计中发现的管道悬挂气味）。

---

*报告生成：2026-07-18 · 审计对象：XAI 项目（自研 AI Agent 工作台）· 73 单测通过 · 3 个运行时 bug 实证复现 · 路径穿越漏洞实证复现*
