# AlphaNoah 3–5 Minute Demo Guide

## Before judges arrive

```bash
./start.sh
```

确认启动输出显示 `Provider: Ollama`、`Model: qwen3.5:9b`，打开 <http://127.0.0.1:5173>。

1. **Dashboard** — 指出 Local Provider、AMD Runtime、Digital Employees 和当前事件状态。
2. **Events → 异常上报** — 使用位置 `A08`，描述“闭店后冷藏区域温度持续异常升高，空调仍在异常运行”。
3. **运行 AI Analysis** — 展示本地 Ollama structured analysis；状态必须进入 `PENDING_HUMAN_REVIEW`。
4. **匹配信息** — 在 Event Detail 展示 Digital Employee / Skill、Knowledge Match 和 Responsible Owner。
5. **Human Review** — 点击 Approve。强调模型不能绕过人工复核。
6. **Create Task → Start Task** — 展示真实 Task 状态进入 `IN_PROGRESS`。
7. **Submit Evidence** — 使用比赛允许的文本 evidence；状态进入 `EVIDENCE_SUBMITTED`。
8. **Begin Final Review** — 状态进入 `UNDER_REVIEW`。
9. **Final Review: Approve** — 确认 Event 与 Task 均显示 `CLOSED`。
10. **Timeline** — 展示 20 条顺序 audit trace，包括真实 Ollama actor、人工审批、Evidence 和最终关闭。

刷新 Event Detail，确认状态仍从 SQLite/API 恢复。若现场 Ollama 不可用，只能明确使用 `ALPHANOAH_PROVIDER=fake ./start.sh` 作为 synthetic fallback，不得将其描述为真实 AI 推理。
