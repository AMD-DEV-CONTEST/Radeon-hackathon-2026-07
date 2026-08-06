# Solo MCP Bridge — 在任意 Agent 中调用 Solo 的业务工具

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 启动 MCP Server

**Demo 模式**（使用内置演示数据，无需配置）：

```bash
npm run mcp
```

**真实数据模式**（连接你的 Supabase）：

```bash
# .env.local 中配置：
# NEXT_PUBLIC_DEMO_MODE=false
# NEXT_PUBLIC_SUPABASE_URL=...
# SUPABASE_SERVICE_ROLE_KEY=...
# SOLO_USER_ID=你的用户UUID

SOLO_USER_ID=你的UUID npm run mcp
```

### 3. 在 Agent 客户端中配置

#### Claude Desktop

编辑 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "solo-worker-os": {
      "command": "npx",
      "args": ["tsx", "path/to/solo/mcp/server.ts"],
      "env": {
        "NEXT_PUBLIC_DEMO_MODE": "true"
      }
    }
  }
}
```

#### Cursor

在 Settings → MCP 中添加：

```json
{
  "mcpServers": {
    "solo-worker-os": {
      "command": "npx",
      "args": ["tsx", "path/to/solo/mcp/server.ts"],
      "env": {
        "NEXT_PUBLIC_DEMO_MODE": "true"
      }
    }
  }
}
```

#### WorkBuddy / 其他 MCP 客户端

使用相同的 command + args 格式。Server 通过 stdio 通信，符合 MCP 标准协议。

## 可用工具（10 个，只读）

| 工具 | 功能 |
|------|------|
| `get_upcoming_deadlines` | 查询即将到期的项目截止日期 |
| `analyze_business_data` | 分析业务数据（收入、项目分布等） |
| `generate_contract` | 生成服务合同 |
| `generate_invoice` | 生成发票 |
| `generate_followup_message` | 生成催款/跟进消息 |
| `search_knowledge_base` | 搜索知识库（合同模板、客户备注等） |
| `get_pricing_benchmark` | 获取报价参考 |
| `get_exchange_rates` | 获取实时汇率 |
| `archive_deliverable` | 归档交付物 |
| `browser_automate` | 抓取网页内容（竞品研究） |

## 使用示例

在 Claude Desktop 或 Cursor 中直接说：

- "查一下我有哪些项目快到期了"
- "帮我给张明生成一份服务合同"
- "分析一下我的业务数据，看看收入情况"
- "搜索一下我的知识库里有没有催款模板"
- "帮我抓取一下 WorkBuddy 的定价页面"

## 运行形态

| 形态 | 传输 | 适用 | 状态 |
|------|------|------|------|
| 本地 stdio | stdin/stdout | 桌面 Agent | ✅ 已实现 |
| 远程 HTTP | Streamable HTTP | 手机端/IM | 📋 计划中 |

## 安全说明

- Demo 模式使用内存数据，不会修改任何真实数据
- 真实数据模式需要 `SOLO_USER_ID` 环境变量，只暴露该用户的数据
- 当前版本只暴露只读和生成类工具，不包含写操作（建项目、记收款、改状态）
- 写操作将在观察调用行为后分批加入
