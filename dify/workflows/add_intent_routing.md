# Dify 意图路由接入指南（模块 A）

给「AMD 国内市场量化智能体」工作流加**意图路由**，解决 35 题中非策略类问题被强转 DSL 导致 REJECT 的问题。

## 改造后的流程

```
start
 └─► HTTP: /api/tools/intent?text={{#sys.query#}}      (意图分类)
       └─► code: 解析 intent 字符串
             └─► if-else: intent 含 "strategy_generation" ?
                   ├─ true  → 原 RAG → DSL-LLM → code → 回测 → 报告   (主链路不变)
                   └─ false → HTTP: /api/tools/query?text=...          (统一链路：RAG→外部降级→steps)
                               └─► LLM 通用回答(带来源/置信度/时间)
                                     └─► answer
```

## 前置条件

1. FastAPI 已部署 external_tools v1（`/api/tools/intent`、`/api/tools/query`），端口 8080。
2. Dify 能访问 `host.docker.internal:8080`（现有节点已验证过这条通路）。

---

## 方案一（推荐）：Dify UI 手动配置 —— 约 5 分钟，零风险

在 Dify 画布（Chatflow）上操作，全程可撤销：

### Step 1 — 加意图分类 HTTP 节点

1. 从 `start` 拉出新节点 → 选 **HTTP Request**
2. 配置：
   - Method: `GET`
   - URL: `http://host.docker.internal:8080/api/tools/intent?text={{#sys.query#}}`
   - Authorization: `No Auth`
3. 记下该节点 id（点击节点，URL 栏上方显示，形如 `1785419999001`，下文以 `<INTENT_ID>` 代替）

### Step 2 — 加 code 解析节点

1. 从 HTTP 节点拉出 **Code** 节点，代码：

```python
def main(body: str):
    import json
    try:
        obj = json.loads(body or "{}")
        intent = obj.get("intent", "general")
    except Exception:
        intent = "general"
    return {"intent": intent}
```

2. 输入变量：`body` ← 上一步 HTTP 节点的 `body` 输出（即 `{{#<INTENT_ID>.body#}}`）
3. 输出变量：`intent`（string）—— 节点 id 记为 `<CODE_ID>`

### Step 3 — 加 if-else 路由节点

1. 从 code 节点拉出 **IF/ELSE** 节点
2. 条件：`{{#<CODE_ID>.intent#}}` 包含 `strategy_generation`（operator: contains）
3. **true 分支** → 连到原有 RAG 节点（`/api/knowledge` 那个）—— 主链路从这继续，其余连线不动
4. **false 分支** → 连到 Step 4 的 HTTP 节点

### Step 4 — 加统一查询 HTTP 节点（false 分支）

- Method: `GET`
- URL: `http://host.docker.internal:8080/api/tools/query?text={{#sys.query#}}`
- 节点 id 记为 `<QUERY_ID>`

### Step 5 — 加通用回答 LLM 节点

- 模型：`models/qwen-trader-merged`（openai_api_compatible）
- System Prompt：

```
你是运行在 AMD ROCm GPU 上的通用量化助理。基于下方「工具结果」回答用户问题。规则：1) 引用数据时必须注明来源、获取时间与置信度；2) 区分事实与推断；3) 合成/演示数据必须明确说明；4) 无法回答时说明边界并给方法建议。
```

- User Prompt：`用户问题：{{#sys.query#}}\n\n工具结果：{{#<QUERY_ID>.body#}}`
- 输出连到 **answer** 节点

### Step 6 — 验证

| 测试输入 | 预期 |
|---|---|
| 帮我写一个双均线策略，止损 5% | 走 DSL 主链路 → 回测报告（与改造前一致） |
| 510300 最新行情 | 走通用链路 → 回答含来源/时间/置信度标注 |
| A股 T+1 规则是什么 | 走通用链路 → 本地知识库回答 |
| 计算组合的 VaR | 走通用链路 → 说明本地计算能力边界 |

### 回滚

删除 Step 1-5 新增的节点与连线，把 `start` 重新连回原 RAG 节点即可。

---

## 方案二（备选）：SQL 补丁自动应用

文件：`add_intent_routing.sql`（与本指南同目录）

```bash
# 1. 备份
psql -U <dbuser> -d <difydb> -c \
"COPY (SELECT id, graph FROM workflows WHERE app_id='528cb3cb-4548-419d-8296-a68e857e83fe' AND version='draft') TO STDOUT" > workflow_backup.sql

# 2. 应用
psql -U <dbuser> -d <difydb> -f add_intent_routing.sql
```

**注意**：
- 补丁按节点**类型**动态定位 start/rag/answer，不硬编码 id；若 `RAISE EXCEPTION` 报找不到节点，说明画布结构不同，请回退用方案一。
- 不同 Dify 版本的节点 schema 有差异（尤其 code 节点的 `variables/inputs` 结构、if-else 的 `conditions` 字段）。应用后务必在画布打开检查连线与节点配置，必要时按方案一的 Step 2/3 手动修正。
- 若发现异常，用备份恢复：把 `workflow_backup.sql` 导回。

---

## 效果与注意

- **35 题兼容性**：策略类（Q5/Q7/Q33 等）走 DSL 主链路不变；信息查询类（Q24-26 等）走统一链路**有回复**（含来源标注）；计算类（Q1/Q9/Q13 等）返回能力边界说明而非 REJECT 报错。
- **主链路零改动**：DSL 管道的 RAG→LLM→code→回测→风控全部保留，不破坏已通过的 24/24 评测。
- 演示时，通用链路的回答天然带 `steps` 审计轨迹（在 LLM 输出中引用），评委能看到"意图判断 → 本地知识库 → 外部降级"的自主规划。
