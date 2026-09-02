# XAI 系统打通 · 三核可用 · 架构覆盖度 验证报告

> 验证时间：2026-07-19 · 环境：后端 `:8000`（server_xai.py）+ 前端 `:5180`（Vite）实时运行
> 验证方式：全部走真实 HTTP 端点（`/api/status`、`/api/capabilities`、`/api/intent`、`/api/chat`、`/api/workflow/run`），非静态代码推断。

---

## 一、结论速览

| 检查项 | 结论 |
|--------|------|
| 前后端打通 | ✅ 前端全部经 `lib/api.ts` 收口 `:8000`，7 大模块端点齐备 |
| Grok Build（工程核） | ✅ 真实可用（bridge available，grok 0.1.220-alpha.4，二进制在位） |
| OpenClaw（龙虾 · 执行核） | ✅ 真实可用（mode=real，OpenClaw 2026.6.11） |
| Hermes（爱马仕 · 推理核） | ✅ 真实可用（mode=real，Hermes Agent v0.18.0） |
| 意图 → 内核路由 | ✅ code→Grok / file→OpenClaw / research→Hermes 全部命中 |
| 架构图覆盖度 | ✅ 主干全覆盖；1 处命名一致性待收口（D2） |

---

## 二、三核真实状态（`/api/status` 实测）

```
model:     deepseek（云模型仅出网，隐私本地闭环）
OpenClaw:  real  · OpenClaw 2026.6.11 (e085fa1)
Hermes:    real  · Hermes Agent v0.18.0 (2026.7.1)
Grok Build: grok_build_bridge = available
            version = grok 0.1.220-alpha.4
            binary  = /Users/Admin/.grok/bin/grok
```

三核均为 `real` 模式，非 stub/mock。

## 三、意图 → 内核路由（`/api/intent` 实测）

| 输入 | intent | 路由内核 | 置信度 |
|------|--------|----------|--------|
| 帮我写一个快速排序的Python代码 | code | **grok_build**（工程核） | 0.80 |
| 把这个目录下的文件整理归档并新建report.md | file | **openclaw**（执行核） | 0.65 |
| 分析一下量化投资中的因子有效性 | research | **hermes**（推理核） | 0.65 |

三类任务分别正确分发到三个内核 —— 双内核并列 + Intent Router 仲裁的架构**真实运作**。

## 四、能力注册表（`/api/capabilities` 实测，15 项）

`agent · model_router · intent_router · skill · mcp · kb · human · reflect · code · condition · subflow · openclaw · grok_build · hermes · scheduler`

前端画布节点面板（`canvas-nodes.ts` SEM_NODES）由此驱动。

## 五、架构图覆盖度对比（对照双核融合架构宪法）

| 架构层 | 图中要素 | 系统落地 | 状态 |
|--------|----------|----------|------|
| 用户交互层 | 控制台（对话/任务/专家团/自动化/定时/画布/管理） | `xai-frontend/` 七模块，纯视图层 | ✅ |
| 双内核并列 | Hermes + Grok Build（第一类公民，无层级） | 两核均 real，Intent Router 分发 | ✅ |
| Intent Router | 任务分类自动分发 | `/api/intent`，三核命中 | ✅ |
| 认知 Control Loop | Reason→Meta→Runner→L4 Verify→Distill | `engine_xai.run_workflow`（Kahn 拓扑，逐节点真实执行） | ✅ |
| Guardian 治理闸门 | P0/P1/P2 分级 + 二次确认 | `/api/chat` 返回 guard 事件，人工审批节点在册 | ✅ |
| 7 层元认知记忆 | 单一事实源 | `memory_core`（user_profile 已积累），带 engine 标签 | ✅ |
| Substrate 执行网关 | OpenClaw 本体（工具/文件/终端/浏览器/扫描） | OpenClaw adapter real，全工具链在册 | ✅ |
| 模型策略 | 云模型出网 + 本地 Ollama 双选 | model=deepseek 出网，model_registry 单一事实源 | ✅ |
| Grok Build 整合 | 汉化源码作接口 + 原版二进制作 MCP 子服务 | GrokBuildBridge 调 `grok --single`，code 路由至此 | ✅ |
| GEPA 自进化 | prompt/技能模板进化 | Hermes adapter Darwinian evolve | ✅ |

**覆盖结论**：架构图主干**完整支撑并真实运作**，无缺层、无空壳。

## 六、唯一待收口项（D2 · 能力命名一致性，非阻断）

- 前端画布节点 `conditional` ↔ 后端能力表 `condition`：语义相同、字符串不一致。
- 前端 `general / office / research / longterm`：为意图标签/遗留节点，未进后端能力表；`input / output` 为 IO 节点（合理，非能力项）。
- **约定**：新增能力以后端 `/api/capabilities` 的 id 为准，前端 SEM_NODES 向其对齐。建议后续将 `conditional` 重命名为 `condition` 关闭此漂移。

## 七、本轮对话台交互修复（已落地）

1. **右侧状态面板默认关闭**（`live-store.rightOpen=false`）——对话输出后侧边不再堆叠冗余状态，顶栏 `PanelRight` 可按需开启。
2. **双栏鼠标滚动修复**——根因是 `FadeIn` 缺高度导致页面无有界高度；已固化 `FadeIn: height:100% + flex column`，对话区与旁挂面板独立滚动生效。
3. **上翻一键回到最新**——对话区新增滚动位置检测 + 右下角「↓ 回到最新」玻璃浮动按钮；上翻查看历史时不再被自动滚动打断。
