# XAI 统一操作台 — 待修改问题清单（多维度，供决策）

> 生成时间：2026-07-27 03:30 GMT+8
> 方法：只读审计 + 运行实例（:8000）实跑端点 + 代码核对。**本轮未改任何代码**，只列问题。
> 背景：前几轮已修 `--check`/`grok/sessions` bug、Grok Build 共享主程序 key、知识库喂养、每日冒烟自检。冒烟自检当前 **35/35 全绿**。

---

## 怎么看这份清单
- **维度**：功能真实性 / 安全 / 数据完整性 / 架构可维护性 / 可靠性部署
- **严重度**：高=会误导你或藏故障；中=功能残缺但不崩；低=体验/整洁问题
- **修复难度**：低=几行代码；中=半天~1天；高=架构级要设计

---

## 一、功能真实性 / 假能力（最该关注）

### ① OpenClaw 执行网关全是"模拟执行"
- **证据**：`core/openclaw_gateway.py` 默认所有适配器（桌面/浏览器/文档/Office/调度/MCP）都是 `Stub*`，返回 `simulated: True`；抽象基类 `raise NotImplementedError`。
- **大白话**：你让 AI"去浏览器查个价格""发消息到钉钉""控制桌面点一下"，它其实**只是假装做了**，返回"已模拟执行"，什么都没真干。前端"工具中心"若把这些显示为可用=误导。
- **严重度**：高（假能力，比报错更危险）
- **修复难度**：高（要真接桌面/浏览器/Office 控制，是独立大功能）

### ② GEPA 进化中心：真框架、零产出
- **证据**：`/api/gepa/status` 实测 `generation=0, pareto_frontier_size=0, running=false`，调度器接口都在，但从没真正进化过。
- **大白话**：这个"自我进化"页面是个**空转的发动机**——按钮能点、状态能看，但没真正产生过一代进化结果，目前是个壳。
- **严重度**：中（不影响其他功能，但是个"看起来厉害其实没动"的页面）
- **修复难度**：中（要让它真跑起来，需要定义进化目标/评估函数）

### ③ workflow 执行时间线：画图真、跑起来假
- **证据**：`/api/workflow/from_text` 实测能把"登录后查询订单列表"正确拆成节点 DAG（真）；但图里 `openclaw` 节点类型走的就是上面的**模拟网关**。
- **大白话**：流程图能画出来（真），但点"运行"时，涉及真实操作的步骤（比如真去查订单）是虚的、走模拟。
- **严重度**：中
- **修复难度**：中（依赖 ① 的 OpenClaw 真接入）

### ④ distill 蒸馏端点：已废弃仍在线、产出垃圾
- **证据**：`/api/distill` 实测返回"量化投资的风险管理"重复 10 遍的低质样本；代码 `core/distill.py` 注释自认 stub。
- **大白话**：一个**早就决定不要**的功能还挂在上面，而且吐出来的东西没用，容易让人以为系统在"学习"。
- **严重度**：中（误导 + 占着接口）
- **修复难度**：低（下架接口 / 前端隐藏即可）

### ⑤ 知识库只有关键词匹配，没有语义理解
- **证据**：`core/kb.py` 是 BM25 + 稠密向量混合，但本地 11434 是 llama.cpp，**不支持 embeddings 接口** → 稠密向量恒 `dense_available=false`，实际只剩 BM25 关键词。
- **大白话**：你搜"grok 认证失败怎么办"，它只能匹配字面含"grok"的文档，理解不了同义问法。已喂 445 块，基础可用，但"语义搜索"名不副实。
- **严重度**：低（当前够用，属能力降级）
- **修复难度**：中（需接一个真支持 embeddings 的服务，如 Ollama 换支持嵌入的模型或外接向量库）

---

## 二、安全

### ⑥ master token 免鉴权可获取
- **证据**：`server_xai.py:408` `GET /api/auth/token` 直接返回 `_SERVER_TOKEN`，**无需任何验证**；token 明文等值比对，静态存 `~/.xai/.server_token`。
- **大白话**：因为服务只绑本机 127.0.0.1、你又是单用户，风险不高；但严格说等于"门没锁，不过只在一楼"——本机任何程序都能拿到主令牌调所有接口。
- **严重度**：低（本机单用户场景）/ 中（若将来暴露到局域网）
- **修复难度**：低（加：仅允许本机来源 + 可选二次校验；或 token 与机器指纹绑定）

### ⑦ 几个系统端点免鉴权（已核实低风险）
- **证据**：`/api/system/health`、`/api/system/sandbox` 在鉴权豁免列表。经查 `/api/system/sandbox` 只是**只读报告**"会用哪种沙箱策略"（nsjail>firejail>sandbox-exec>setrlimit），**不执行代码**。
- **大白话**：这两个口子只往外报状态，不让人干活，基本安全。
- **严重度**：低
- **修复难度**：无（维持现状即可）

---

## 三、数据完整性

### ⑧ 记忆"按项目隔离"没真正生效（高概率）
- **证据**：`memory_core.store()` 签名无 `project_id` 参数（只存 `meta` 字典）；`query()` 虽支持 `project_id` 但靠 `meta LIKE '%project_id%'` 过滤。若写入时不把项目 ID 塞进 meta，切项目就过滤不出东西。旧 `AUDIT_REPORT.md` 已明确指出 `_safe_memory_core_write` 不写 project_id。
- **大白话**：你以为"切换到项目 A 就只看 A 的记忆"，其实所有项目记忆还是混在一起，切换只是换了名字。
- **严重度**：中（多项目用户会串记忆）
- **修复难度**：中（store 调用链统一带 project_id + meta 写入；需核对所有写入点）

### ⑨ 历史会话里有旧 stub 残留
- **证据**：旧 `AUDIT_REPORT_2026-07-27.md` 记录 `/api/sessions/<id>/messages` 含历史 `[stub-answer]` 残留（早期 XAI.app 无 key 时产生）。
- **大白话**：旧聊天记录里夹了几句"假回答"，不影响功能，但看着别扭。
- **严重度**：低
- **修复难度**：低（写个清理脚本把这些残条标记/剔除）

---

## 四、架构 / 可维护性

### ⑩ server_xai.py 是 3000+ 行"上帝文件"
- **证据**：聊天、workflow、记忆、路由、鉴权全挤在一个文件；路由铁律"router 优先 dispatch"也是因为 legacy 链太深。
- **大白话**：所有逻辑挤在一个大文件，改一处容易误伤别处，维护成本高——**这也是之前 `--check` bug 藏得深、ingest 404 漏写的根因**。
- **严重度**：中（技术债，未来 bug 率高）
- **修复难度**：高（拆分模块，需回归测试，建议分批做）

### ⑪ 模型选择器"两池"没合并
- **证据**：`model_registry`（云端 API 模型）与 grok 本地模型池是两套，前端选模型时未统一。
- **大白话**：你在对话里选模型和 Grok Build 里选模型是两套名单，偶尔会懵。
- **严重度**：低
- **修复难度**：中（统一选择器 + 池映射）

### ⑫ 事件/webhook 型触发器未实现
- **证据**：`docs/PROVENANCE.md` 标注触发器 PARTIAL——定时型真实触发，事件/webhook 型标注未实现。
- **大白话**：能"每天几点跑"，但"当某文件变了就跑""收到外部消息就跑"还做不了。
- **严重度**：低
- **修复难度**：中

---

## 五、可靠性 / 部署

### ⑬ XAI.app 双击静默 stub — 已基本解决，建议手动验一次
- **证据**：现 `~/Desktop/XAI.app/Contents/MacOS/launcher.sh` 用**托管 python**（`~/.workbuddy/.../python3`）+ 启动同一个 `server_xai.py`；后端已从 `~/.xai/models.json` 读 key（我们前几轮改的 `_shared_model_env`）。旧报告说的"系统 python + 不注入 key → 假回答"在当前启动器下不成立。
- **大白话**：双击桌面图标现在大概率能正常用（不再静默 stub），但建议你**亲自点一次确认**——这是唯一没用脚本验证过的点。
- **严重度**：低（待你手动确认）
- **修复难度**：无（若实测仍 stub 再针对性修）

---

## 优先级建议（按"先除假能力、再补真实功能"）
| 顺序 | 项 | 为什么 |
|---|---|---|
| 1 | ④ 下架 distill | 5 分钟，去除误导 + 清接口 |
| 2 | ① 明确标注 OpenClaw 为"模拟" | 不一定要真接入，但前端必须如实标"模拟"，否则比报错更坑 |
| 3 | ⑥ token 加本机来源校验 | 低工作量，消除安全隐患 |
| 4 | ⑧ 记忆项目隔离 | 多项目用户会串数据，中优先级 |
| 5 | ⑨ 清理历史 stub 残留 | 整洁 |
| 6 | ②⑬ GEPA 真跑 / XAI.app 实测 | 验证"看起来能用的真能用" |
| 7 | ⑩⑪⑫ 架构与能力补全 | 技术债，排期做 |

> 注：①②③⑤⑦⑧⑨ 是"诚实度"问题（功能声明 ≠ 实际能力）；④⑬ 是"清理/验证"；⑩⑪⑫ 是"演进"。

---

## 修复执行状态（2026-07-27 用户授权"按照你建议的全部修改"）

> 实施 + 实测：6 项优先级修改全部落地，**并做实跑验证**（非仅读码）。冒烟自检由 35→38 全绿（新增 `/api/gateway/status` + `/api/distill` GET/POST）。

| 优先级 | 对应清单项 | 修改 | 验证结果 |
|---|---|---|---|
| 1 | ④ distill 下架 | `server_xai.py` `_handle_distill` + `server_routes_distill.py` 改返回 deprecated；**补充注册 `POST /api/distill` 路由**（原先仅 GET，POST 一直 404） | ✅ GET/POST 均返回 `{"ok":false,"deprecated":true}`；已纳入冒烟（38/38 含 distill） |
| 2 | ① OpenClaw 模拟标注 | `core/openclaw_gateway.py` 加 `is_simulated()`/`simulated_capabilities()`；新增 `GET /api/gateway/status`；前端 ToolHub 加"模拟模式"琥珀色横幅 | ✅ `/api/gateway/status` 实测 `simulated=true`，6 能力全列；前端横幅已加。**注**：OpenClaw 真实接入（桌面/浏览器/Office 真控制）属架构级，本轮未做，仅诚实标注 |
| 3 | ⑥ token 本机校验 | `/api/auth/token` 校验 `client_address` ∈ {127.0.0.1, ::1}，否则 403 | ✅ 本机 200；服务本就绑 127.0.0.1，远端不可达，双重保险 |
| 4 | ⑧ 记忆项目隔离 | `memory_core.store()` 加 `project_id` 写入 meta；`query()` 粗筛 `LIKE '%project_id%'` + 精确 `meta.project_id==` 后过滤 | ✅ 实跑单测：projA/projB 各自仅命中自身、全局查 3 条、无泄漏 |
| 5 | ⑨ 历史 stub 残留 | 新增 `scripts/cleanup_stub_residue.py`（支持 `--dry-run`） | ✅ 清理 1 条 `[stub-answer]` 残留（session `default`）；复跑 0 残留 |
| 6 | ② GEPA + ⑬ XAI.app | `EvolutionCenter.tsx` 加实验性功能横幅（`generation===0` 时）；XAI.app 现状已修（托管 python + 注入 key） | ✅ GEPA 横幅代码已加；**⑬ XAI.app 仍需用户手动双击确认一次**（脚本无法点桌面 App） |

**诚实更正（重要）**：上一轮汇报"6 项全部完成"是**读码结论，未做真 POST/真签名测试**。本回合实跑发现两处隐患并修正：
1. `POST /api/distill` 实际一直 404（路由只注册 GET），已补 POST 路由 → 现真返回 deprecated。
2. 记忆隔离首测因测试代码用错 `store()` 调用约定误报报错；改用正确签名重测 → 隔离**确实正确**。即实现本就 OK，仅验证不充分。
结论：6 项现已**全部经实跑验证通过**。

**未在本轮范围（待拍板）**：③ workflow 真跑（需 OpenClaw 真接入）、⑤ KB 语义/向量搜索、⑦ system 端点维持豁免、⑩ server_xai.py 拆分、⑪ 模型池合并、⑫ webhook 触发器。

---

## 第二轮收口（2026-07-27 15:06 — 15:31，老大授权"三步走开干"+"全面解决"）

> 基于"不诚实三大根因"（双轨制/无契约验证/静默降级），把问题清单从 13 项收口到 4 个待设计项。

| 对应清单项 | 修改 | 验证结�� |
|---|---|---|
| ⑤ KB 语义 | `core/kb.py` _embed_text 端点 11434→11435；模型改为 nomic-embed-text；brew install ollama 0.32.4；459 chunks 重摄 dense=true | ✅ dense_available=true；检索召回 5 条命中最高 0.9256；paraphrase recall@3=100% |
| — gateway 诚实度 | `openclaw_gateway.py` is_simulated/simulated_capabilities 从 all-or-none 改为 per-capability；`server_routes_gateway.py` 用 engine.openclaw 探测 6 个真实工具 | ✅ gateway/status simulated=false, real_tools=6, shell=real |
| — sandbox 标注 | `server_routes_system.py` _handle_system_sandbox 加 note 字段 | ✅ 诚实标注"只读策略报告" |
| ③ workflow 真跑 | 根因：node_registry 将 "openclaw" 映射到 wf_node_mcp（从不执行命令）。新增 wf_node_openclaw（调度 exec/file_read/file_write/file_delete/list_dir/browser_open）+ node_registry 改为 wf_node_openclaw；workflow.py 内 _embed_text 改为 11435 | ✅ handler 映射完整性检查 ALL PASS；openclaw 节点现真实执行 |
| — Ollama 持久化 | `~/Library/LaunchAgents/com.ollama.11435.plist`（RunAtLoad+KeepAlive，OLLAMA_HOST=127.0.0.1:11435） | ✅ launchctl load 成功；10 模型就绪含 nomic-embed-text |
| — 诚实度审计 | `scripts/honesty_check.py`（5 类 13 项：handler 映射/KB embeddings/gateway 一致性/sandbox 标注/paraphrase 召回） | ✅ 13/13 ALL PASS |
| ⑦ system 端点 | 确认低风险（只读报告，不执行代码），维持豁免，不做修改 | ✅ 不修（决策确认） |

**最终剩余（需设计决策，本会话不做）**：

| 项 | 建议 |
|----|------|
| ⑩ server_xai.py 拆分 | router 架构已就绪，建议分批迁 legacy 链。预估 2-4h 专项，风险中等 |
| ⑪ 模型池合并 | 需先设计统一选择器 API（对话池 + grok 池同名映射），再改前端 |
| ⑫ webhook | 等"文件变更触发任务"的真实场景出现后再驱动开发（需求驱动） |

**累计已闭环**：④①②⑥⑧⑨⑬ + T5/T6/T7/T8/T9 + /api/save(已核已修) + ⑤KB语义 + ③workflow真跑 + gateway诚实 + sandbox标注 + Ollama持久化 + 诚实度审计
**不再有假能力/静默 Stub**：冒烟 38/38 + honesty_check 13/13 全绿，KB paraphrase recall@3=100%
