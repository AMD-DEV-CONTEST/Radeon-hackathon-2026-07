package ironlaw

// Version is the current ILS version. Orchestrator checks this.
const Version = "3.1.0"

const AGENTS_MD = `# AGENTS.md — UnionAgents 铁律 v3.1

> 这是你的行为契约。每执行一条任务之前，先过这五条。

## 铁律五条

| # | 规则 |
|---|------|
| 1 | 先召回相似案例再做 |
| 2 | 结构化输出必须用户确认 |
| 3 | 单任务 ≤ 1 小时，超时拆分 |
| 4 | 需决策时暂停，提交 needs_user_insight |
| 5 | 完成后必须沉淀案例教训 |

## 接收任务时自检

拿到任务后，三秒内回答：
1. 这个任务我见过类似的吗？（查历史案例）
2. 有没有歧义需要澄清？（指代词、模糊描述）
3. 有没有危险操作需要确认？（删库、改权限、关服务）

## 执行期间约束

- 所有文件操作限 workspace 目录
- 禁止：rm -rf /、git push --force、DROP TABLE、chmod 777、curl | bash
- 超时 1 小时强制 split handoff
- 遇到权限/鉴权错误 → 立即停，不回重试

## 交付标准

你的 summary 必须回答：
1. 做了什么？（具体）
2. 结果是什么？（可验证）
3. 有没有需要注意的？

## 异常处理

| 错误类型 | 做法 |
|---------|------|
| API 401/403 | 不重试，报告 permanent 错误 |
| 网络超时 | 重试最多 3 次，指数退避 |
| 任务超时 | 提交 partial handoff |
| 需要决策 | 暂停，提交 needs_user_insight |
`
