# OMIMA MCP Skill 选型报告

**日期**: 2026-06-04  
**研究员**: Reasonix (MCP 生态研究员)  
**项目**: OMIMA — 极致私有的个人信息保险库（Cloudflare Workers + D1 + R2）  
**Agent 团队**: Claude Code / Codex / Reasonix / Hermes

---

## 推荐（3 个）

---

### 1. Cloudflare Workers Bindings MCP Server

**是什么**  
Cloudflare 官方维护的 MCP server，提供对 Workers 平台核心绑定资源的直接操作能力。  
仓库: `cloudflare/mcp-server-cloudflare` → `apps/workers-bindings`  
Stars: 3,818（整个 monorepo），Apache-2.0 许可，持续活跃维护。  
远程服务地址: `https://bindings.mcp.cloudflare.com/mcp`

**对 OMIMA 的具体用处**  
OMIMA 的核心基础设施是 Cloudflare Workers + D1 + R2。这个 MCP server 提供了以下直接可用的工具：

| 工具 | 对 OMIMA 的用途 |
|------|----------------|
| `d1_databases_list` / `d1_database_get` / `d1_database_query` | 查询 D1 数据库 schema、检查数据表状态、执行诊断 SQL |
| `r2_buckets_list` / `r2_bucket_get` / `r2_bucket_create` | 查看 R2 存储桶状态、确认用户数据存储是否正常 |
| `workers_list` / `workers_get_worker` / `workers_get_worker_code` | 查看已部署的 Worker 列表、获取线上代码做对比审查 |
| `kv_namespaces_list` / `kv_namespace_get` | 检查 KV 命名空间状态（OMIMA 可能用 KV 做会话缓存） |

具体场景举例：
- **Implementer（Claude Code/Codex）**：写完 Worker 代码后，直接查询线上 D1 表结构确认 schema 一致，或对比线上 Worker 代码与本地代码的差异。
- **Reviewer（Codex）**：审查 PR 时，调用 `d1_database_query` 验证数据迁移脚本的正确性，或调用 `workers_get_worker_code` 确认线上版本与 PR 目标一致。
- **Leader（Reasonix）**：拆任务前，先查 D1 数据库列表和 R2 桶列表，了解当前基础设施状态，做出更准确的任务分配。
- **Hermes（运维）**：巡检时查询所有 Worker 状态、D1 数据库健康度、R2 桶容量。

**所有 Agent 都能用？为什么**  
✅ 是。因为 OMIMA 的所有 Agent 角色都围绕 Cloudflare 基础设施工作：
- 开发者需要查 D1 schema 和线上代码
- 审查者需要对比线上/线下代码和数据
- 架构师需要了解当前部署状态
- 运维需要巡检所有资源

这不是"只有 code agent 才用得到"的工具——它是 OMIMA 基础设施的"仪表盘"。

**安装方式**

```json
// 在 MCP 客户端配置中添加（通过 mcp-remote 代理）
{
  "mcpServers": {
    "cloudflare-bindings": {
      "command": "npx",
      "args": ["mcp-remote", "https://bindings.mcp.cloudflare.com/mcp"]
    }
  }
}
```

如果 MCP 客户端原生支持远程 MCP（如 Claude Desktop 最新版），可直接配置 URL。

**需要的凭证**
- Cloudflare 账号（免费或付费均可）
- OAuth 授权（推荐）：首次连接时浏览器弹出 Cloudflare 登录页面，授权后自动获取 token
- 或 Cloudflare API Token：在 [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens) 创建，需要以下权限：
  - `Workers: Read`
  - `D1: Read`（或 Write 如果需要写操作）
  - `R2: Read`
  - `KV: Read`

---

### 2. Cloudflare Documentation MCP Server（via Vectorize）

**是什么**  
Cloudflare 官方提供的文档检索 MCP server，基于 Vectorize 向量数据库索引了完整的 Cloudflare 开发者文档。  
仓库: `cloudflare/mcp-server-cloudflare` → `apps/docs-vectorize`  
远程服务地址: `https://docs.mcp.cloudflare.com/mcp`

**对 OMIMA 的具体用处**  
OMIMA 深度依赖 Cloudflare 生态（Workers、D1、R2、KV、Queues 等），开发过程中频繁需要查阅官方文档。这个 MCP server 提供 `search_cloudflare_documentation` 工具，专门搜索 Cloudflare 文档，比通用搜索引擎更精准。

具体场景举例：
- **Implementer**：写 D1 查询代码时，搜索 "D1 batch statement syntax" 或 "Workers D1 client API"，直接获得官方最新 API 参考。
- **Reviewer**：审查代码时，搜索 "Workers pricing request size limits" 来验证实现是否符合成本约束。
- **Leader/Architect**：做架构决策时，搜索 "R2 consistency model" 或 "D1 replication limits" 获取权威信息。
- **Hermes**：排查问题时，搜索 "Workers 10012 error" 或 "D1 query timeout" 快速定位官方文档中的故障排除指南。

**为什么比通用搜索更精准**  
- 只索引 Cloudflare 官方文档，不会混入 StackOverflow 过时答案或第三方博客
- 基于 Vectorize 语义搜索，能理解"我的 Worker 在 R2 读图片很慢"这类自然语言查询
- 结果直接来自 `developers.cloudflare.com`，确保版本最新

**所有 Agent 都能用？为什么**  
✅ 是。Cloudflare 文档是所有角色日常工作的高频参考：
- 开发者查 API 用法
- 审查者验证最佳实践
- 架构师查限制和配额
- 运维查错误码和故障排除

**安装方式**

```json
{
  "mcpServers": {
    "cloudflare-docs": {
      "command": "npx",
      "args": ["mcp-remote", "https://docs.mcp.cloudflare.com/mcp"]
    }
  }
}
```

**需要的凭证**
- Cloudflare 账号（免费即可）
- OAuth 授权（首次连接时浏览器登录）

---

### 3. Fetch MCP Server（官方参考实现）

**是什么**  
MCP 官方参考实现之一，提供从互联网获取网页内容并转换为 Markdown 的能力。  
仓库: `modelcontextprotocol/servers` → `src/fetch`  
Stars: 86,698（整个 monorepo），持续维护。  
安装: `uvx mcp-server-fetch` 或 `pip install mcp-server-fetch`

**对 OMIMA 的具体用处**  
OMIMA 开发过程中需要频繁访问外部资源：

具体场景举例：
- **Implementer**：fetch Cloudflare 官方博客的技术文章（如 "D1 GA announcement"）、GitHub issue 讨论、npm 包文档。
- **Reviewer**：fetch 被引用的第三方库文档或安全公告，验证依赖是否安全。
- **Leader/Architect**：fetch 竞品分析页面、技术对比文章、RFC 文档。
- **Hermes**：fetch Cloudflare 状态页面（`cloudflarestatus.com`）或 GitHub Release Notes。

**与 Cloudflare Docs MCP 的互补关系**  
Cloudflare Docs MCP 只搜索 Cloudflare 官方文档，而 Fetch MCP 可以获取任何公开网页。两者配合使用：
- 查 Cloudflare 官方文档 → 用 Docs MCP
- 查 GitHub Issues、博客、第三方文档 → 用 Fetch MCP

**所有 Agent 都能用？为什么**  
✅ 是。Fetch 是最通用的信息获取工具，不限于任何角色或技术栈。任何 Agent 在需要查阅外部资料时都能使用。

**安装方式**

```json
{
  "mcpServers": {
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    }
  }
}
```

或使用 pip：

```json
{
  "mcpServers": {
    "fetch": {
      "command": "python",
      "args": ["-m", "mcp_server_fetch"]
    }
  }
}
```

**需要的凭证**
- 无。无需 API key，直接访问公开网页。
- 可选配置：`--ignore-robots-txt`（忽略 robots.txt 限制）、`--user-agent`（自定义 UA）

---

## 研究过的但未推荐

### Cloudflare Code Mode MCP Server（`cloudflare/mcp`）
- **地址**: `https://mcp.cloudflare.com/mcp`
- **Stars**: 493
- **排除原因**: 虽然功能强大（覆盖 2500+ Cloudflare API 端点），但它的设计是"通用 Cloudflare API 网关"，对 OMIMA 来说过于宽泛。Workers Bindings MCP 已经覆盖了 OMIMA 最核心的 D1/R2/KV/Workers 操作，且工具更聚焦、更易用。Code Mode 需要 Agent 写 JavaScript 代码来搜索和执行 API 调用，增加了不必要的复杂度。**结论：Bindings MCP 是更精准的选择。**

### Workers Observability MCP Server
- **地址**: `https://observability.mcp.cloudflare.com/mcp`
- **排除原因**: 主要用于查询 Worker 日志和分析（`query_worker_observability`）。这对 Hermes（运维）很有用，但对 Implementer 和 Reviewer 在日常开发中用处不大。不符合"所有 Agent 装了都有用"的普适性标准。**结论：运维专用，不够普适。** 可考虑在 OMIMA 进入生产阶段后作为可选补充。

### Workers Builds MCP Server
- **地址**: `https://builds.mcp.cloudflare.com/mcp`
- **排除原因**: 管理 Worker 构建记录和日志。对 CI/CD 调试有用，但 OMIMA 目前使用 wrangler 本地部署，不依赖 Cloudflare 的 Builds 服务。**结论：OMIMA 当前不需要。**

### Browser Rendering MCP Server
- **地址**: `https://browser.mcp.cloudflare.com/mcp`
- **排除原因**: 提供网页截图和 HTML 获取。功能与 Fetch MCP 重叠但更重（需要浏览器渲染），且需要 Cloudflare 账号。Fetch MCP 更轻量、无需认证、对 LLM 更友好（直接返回 Markdown）。**结论：Fetch MCP 更优。**

### Filesystem MCP Server（官方参考实现）
- **排除原因**: 提供本地文件读写操作。虽然对 Implementer 有用（读写 wrangler.toml、D1 snapshot 等），但 Reviewer 和 Leader 不需要直接操作文件系统。且 OMIMA 的 Agent 团队运行在云端，本地文件系统访问的场景有限。**结论：不够普适，且与 Agent 运行环境不匹配。**

### Sequential Thinking MCP Server
- **排除原因**: 提供结构化思维链工具。虽然所有 Agent 都能用，但它是一个"方法论增强"工具，不直接帮助开发/维护 OMIMA。不符合"能直接或间接帮助开发/维护 OMIMA"的标准。**结论：通用思维工具，与 OMIMA 无直接关联。**

### Memory / Knowledge Graph MCP Server
- **排除原因**: 提供持久化记忆（知识图谱）。虽然所有 Agent 都能用，但 OMIMA 已经有自己的 RAG 系统和 Iron Law 上下文组装机制，功能重叠。**结论：与现有系统功能重叠，不为装而装。**

### Brave Search MCP Server
- **Stars**: 1,137
- **排除原因**: 提供 Brave 搜索引擎的 web/local 搜索。需要 Brave Search API key（免费但有速率限制）。对 OMIMA 来说，搜索 Cloudflare 相关内容时，Cloudflare Docs MCP 更精准；搜索其他内容时，Fetch MCP 可以直接获取目标页面。**结论：被 Cloudflare Docs MCP + Fetch MCP 的组合覆盖。**

---

## 结论

推荐 **3 个 MCP Skill**，按优先级排序：

1. **Cloudflare Workers Bindings MCP** — OMIMA 基础设施的"仪表盘"，所有 Agent 都能用它查询 D1/R2/KV/Workers 状态
2. **Cloudflare Documentation MCP** — 精准的 Cloudflare 文档搜索，替代通用搜索引擎
3. **Fetch MCP** — 轻量级网页内容获取，补充 Docs MCP 无法覆盖的外部资源

这三个组合覆盖了 OMIMA 开发/维护的核心需求：**查基础设施 → 查官方文档 → 查外部资料**，且每个都满足"所有 Agent 角色都受益"的普适性标准。安装配置极简（npx/uvx 一行命令），无需额外服务依赖，符合轻量和稳定的要求。
