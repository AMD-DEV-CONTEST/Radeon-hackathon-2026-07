# XAI 统一操作台 — 多轮端到端自测报告

> 目标：把系统完全调通、消除 bug，达到可交付标准。
> 方法：对照 Open-WebUI / dify / LibreChat 等成熟开源项目，做「流式 / 多轮 / 真实能力 / 治理」上市级自测。
> 环境：macOS，Python 3.13，DeepSeek 真实后端（`DEEPSEEK_API_KEY` 已配置），OpenClaw 真实模式。

## 一、自测范围与方式

零第三方依赖（`urllib` 直连 `server_xai.py`），覆盖：

- **基础健康**：`/api/status`、`/api/history`
- **斜杠命令全量**：`/help /status /diagnose /task /scan /channels /mcp /models /skill /automate /clear /approve /reject`
- **流式通用对话**：`token` 事件逐字推送
- **代码开发**：模型生成 → 写盘 → `py_compile` 语法校验
- **浏览器联网搜索**：真实 DuckDuckGo + 基于结果作答
- **多轮上下文**：同一 session 连续两轮，SQLite 历史持久化
- **P0 治理**：高危输入拦截 → 审批卡片 → 批准后真正重执行
- **记忆**：`/remember` 写入 + `/recall` 跨引擎检索
- **边界**：空输入(400)、未知命令、错误审批 ID、超长输入、并发 4 请求
- **前端静态资源**：`index.html / app.js / styles.css` 正确服务 + 新 CSS 类与关键函数就位
- **模型驱动进化**：注册技能 → `/evolve` 调用真实模型改写 prompt → 入复审队列

## 二、自测结果

| 轮次 | 用例数 | 结果 |
|------|--------|------|
| 第一轮（核心流程） | 13 | ✅ 13/13 |
| 第二轮（命令全量 + 边界 + 并发） | 13 | ✅ 13/13 |
| 第三轮（前端资源 + 模型进化） | 3 类 | ✅ 全部通过 |

**并发安全**：4 并发请求全部成功，无串台、无崩溃（ThreadingMixIn + 会话锁 + 审批锁生效）。

**模型驱动进化验证**：注册 `demo_skill` → `/evolve` 调用 DeepSeek 生成结构化「文本摘要助手」prompt 写入 `demo_skill_v2.json`（状态 `pending_review`），确认不再是字符串追加假变异。

## 三、发现并修复的 Bug（共 8 项）

| # | 严重度 | 现象 | 根因 | 修复 |
|---|--------|------|------|------|
| 1 | 🔴 阻断 | 所有 `/api/chat` 在 urllib 等严格流式客户端下挂起（90s 超时） | SSE 响应用 `Connection: keep-alive` 且无 `Content-Length`，客户端读不到 EOF | 改发 `Connection: close` + `self.close_connection = True`，流结束即关连接 |
| 2 | 🔴 功能 | `/scan server_xai.py` 报 `No such file` | `vulnerability_scan` 只在 `~/.xai/workspace` 内解析路径，越界即报错 | 新增 `_resolve_scan_target`：原样 / 工作区 / CWD / 向上三层多候选定位，找不到给清晰错误 |
| 3 | 🟠 逻辑 | `/clear` 后会话历史非空 | 斜杠分支把所有非 `diagnose` 命令（含 `/clear`）写入历史，clear 把自身留痕 | 历史记录排除集合增加 `"clear"` |
| 4 | 🟠 诚实 | `/models` 列出 gpt/claude/gemini/ollama「看似可用」 | 硬编码静态清单，未检测真实可用性 | 改为动态检测：`DEEPSEEK_API_KEY` / `ollama` CLI / 各厂商 key 实际存在才列出 |
| 5 | 🟠 诚实 | `/evolve` 仅字符串追加「优化标记」 | `darwinian_evolve`/`evolve_skill` 为假变异 | 新增 `_mutate_prompt`：调用真实模型后端生成改进版 prompt，失败才降级追加标记 |
| 6 | 🟠 治理 | P0 审批闸门聊天场景形同虚设 | `chat()` 一律 `Action(kind="general")` → 永不触发 P0 | 新增 `_guard_action` 内容级识别（rm -rf / 强制推送 / 删除 / 执行 / 联网），危险输入升级 P0 |
| 7 | 🟠 部署 | 启动器 `pkill -f server_xai.py` 误杀自身；服务端口冲突时静默漂移到 8001 | pkill 匹配到启动器自身；`main()` 端口冲突自增 | 启动器改按 `server.pid` 精确停止；`main()` 改为同端口重试（预期旧实例已退出） |
| 8 | 🟡 体验 | CLI `/skill register` 后技能 prompt 为空，进化无可改 | `register_skill` 把空 `prompt_snippet` 直接存为 prompt | prompt 为空时回退到 `description`，保证有可进化实质内容 |

## 四、对标成熟开源项目的已知差距（诚实清单）

| 能力 | Open-WebUI / dify / LibreChat | XAI 现状 | 差距 |
|------|-------------------------------|----------|------|
| 流式 + Markdown/Artifact | ✅ 内联渲染代码/文档/可视化 | ✅ 自研轻量 Markdown + 代码块复制 | 持平（够用） |
| 多轮上下文 | ✅ | ✅ SQLite 持久化 + 多会话切换 | 持平 |
| RAG / 知识库 | ✅ 9 向量库 + 混合检索 + agentic retrieval | ⚠️ 关键词 SQLite 记忆，无向量语义检索 | **待补：语义 RAG** |
| 多模型路由 | ✅ 多 provider + 成本路由 | ⚠️ 仅 DeepSeek 真实，其余按 key 动态列出 | **待补：路由 + fallback** |
| 工具/MCP | ✅ 原生 MCP + 插件市场 | ✅ OpenClaw 真实 MCP/技能桥接 | 持平（依赖 OpenClaw） |
| 智能体编排 | ✅ Agents / Workflow / DAG | ✅ 画布（OllamaFlow 式 React 前端）+ 意图路由 | 画布执行未与后端深耦合 |
| 治理/安全 | ⚠️ 企业 RBAC/SSO | ✅ P0/P1/P2 审批 + 权限分级 + 批准后重执行 | 治理领先，企业鉴权待补 |
| 企业多用户/SSO | ✅ LDAP/OIDC/SCIM | ❌ 单机单用户 | **待补（商业化前提）** |
| 语音/图像/终端 | ✅ TTS/STT/Open Terminal | ⚠️ 代码沙箱执行，无语音图像 | 非核心，可后补 |
| 可观测/成本 | ✅ 监控 + 日志 + 成本 | ⚠️ `/diagnose` 体检，无成本追踪 | **待补** |

**结论**：核心交互（流式、多轮、真实代码/搜索/记忆/治理/进化）已达上市级可用标准；
**商业化前必须补**：语义 RAG、多模型路由、企业 SSO/多用户、可观测与成本追踪。

## 五、如何复跑自测

```bash
# 确保服务在 8000 运行
python3 server_xai.py &

# 第一轮（核心流程）
python3 tests/selftest_e2e.py

# 第二轮（命令全量 + 边界 + 并发）
python3 tests/selftest_e2e_round2.py
```

> 两套自测均零第三方依赖，直接 `python3` 运行即可。
