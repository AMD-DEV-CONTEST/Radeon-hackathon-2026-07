# 1 万道相关 FAQ 操作说明

## 内容范围（均与私有 Agent / 企业场景相关）

生成脚本覆盖约 10 类主题，循环组合得到约 **10000** 条问答：

- VPN / SSO / 网络
- AI 合规与 PrivateLocalAgent
- 请假 / 远程办公（HR）
- 软件许可证
- 知识库与设计文档
- AMD GPU + ROCm
- 账号权限与安全
- ServiceDesk 运维
- 数据隐私
- 研发流程 / Hackathon 演示

文件输出目录：`data/sample_docs/faq_10k/faq_batch_*.md`

## 云端操作（推荐）

```bash
cd /workspace/Radeon-hackathon-2026-07
git pull origin track2-private-local-agent

# 生成 1 万道 FAQ
python scripts/generate_kb_faqs.py --n 10000

# 清空旧向量库并重新入库（首次或改 FAQ 后必做）
python scripts/rebuild_kb.py
```

或直接打开 `notebooks/private_agent_demo.ipynb`，**只运行第一个单元格**（已包含生成 + 重建 + 提问）。

入库 1 万条时 embedding 可能要 **数分钟到十几分钟**，请等到打印 `ingested chunks` / `ready`。

## 可视化还要不要？要不要隧道？

| 方式 | 隧道 | 建议 |
|------|------|------|
| `notebooks/visual_no_tunnel.ipynb` | **不需要** | **主演示 UI**（嵌在 JupyterLab） |
| 普通 Notebook / CLI | 不需要 | 备用 |
| Gradio / HTTP 独立端口 | 需要隧道或 /proxy | 本平台不稳，可不做 |

无隧道可视化：Notebook 内核 WebSocket 通信，浏览器不访问 `localhost:7860`。

## 验证提问示例

- VPN 密码怎么重置？
- 涉密文档可以用哪些 AI 工具？
- 请假需要提前几天申请？
- GPU 推理环境有什么要求？
- 如何申请软件许可证？
