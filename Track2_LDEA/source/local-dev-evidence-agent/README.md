# Local Dev Evidence Agent (LDEA)

本地开发证据整理智能体：**拒绝未验证的完成叙事**——弄清「到底做成了什么」，而不是复述 AI 聊天或恭维式总结。

面向 **AMD DevMaster 赛道二（私有 AI 智能体本地部署）**：

- **Agent**：含糊目标下规划 → 工具调用 → 记忆（L0/L1 证据账本）
- **门禁**：仅 `verified` = 已完成；空口 claim → `abandoned`；LLM **不能**自证
- **本地推理**：AMD Radeon + ROCm + vLLM（OpenAI-compatible）

## 30 秒理解差异

| 故事 | 输入 | LDEA 结果 |
|------|------|-----------|
| A | 「今天全做完了」（无 git/测试） | `abandoned`，成果栏为空 |
| B | 只有代码 diff、无测试 | `evidenced`，**不得**写已完成 |
| C | 声称已修 + 测试仍红 | `evidenced`，**不得** verified |
| D | 代码 diff + 测试 fail→pass | `verified`，可写「已修复」 |
| — | 对话里模型自己说完成 | **不算**；必须工具证据进账本 |

一条命令看全矩阵（无需 GPU）：`node dist/cli.js demo --suite`

## 产品面

| 栏目 | 含义 |
|------|------|
| 成果 | 仅 `verified` 可写「已完成」 |
| 代码证据 | git file_change 绑定的路径 |
| 验证证据 | 测试 / verification anchors |
| 决策依据 | claim / decision 链路 |
| 公开风险 | 邮箱、密钥、连接串扫描 |
| 未闭合 | claimed / evidenced / abandoned |

硬规则来自 [AiRecap Plus](../AiRecap%20Plus) outcome 状态机：`claimed → evidenced → verified`；LLM **不能**直接写 `verified`。

## 架构

```
用户目标
   │
   ▼
LDEA Agent loop (本地 Qwen / 任意 OpenAI-compatible)
   │  tools: claim / git_diff / run_tests / scan_privacy / render_report …
   ▼
airecap-plus  L0 events.jsonl  →  L1 store.json（规则聚合）
   │
   ▼
确定性 Markdown/JSON 报告（.ldea/sessions/<id>/）
```

本仓库 = 工具层 + 隐私扫描 + 报告 + Agent 编排 + CLI。  
证据核与状态机复用 `airecap-plus`（`file:../AiRecap Plus`）。

## 快速开始

```bash
# 0) 构建证据核
cd "../AiRecap Plus" && npm install && npm run build

# 1) 本项目
cd "../Local Dev Evidence Agent"
npm install
npm run build
npm test

# 2) 离线演示（不需要 GPU）
npm run demo
# 或: node dist/cli.js demo              # 双故事：abandoned vs verified
#     node dist/cli.js demo --suite      # 四故事全景矩阵（录像推荐）
# 单故事: demo --empty | --code | --failing | --verified
# 本地 LLM: demo --live（含糊目标，需 vLLM）
```

### 连接本机隧道上的 ROCm vLLM

在 GPU 机器（已验证：gfx1100 / ROCm 7.2.1 / vLLM 0.16.1-rocm）：

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 若官方 HF 不可达
vllm serve /models/Qwen2.5-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --attention-backend TRITON_ATTN \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --max-model-len 8192
```

在开发机：

```bash
ssh -L 8000:127.0.0.1:8000 radeon-gpu
export LDEA_LLM_BASE_URL=http://127.0.0.1:8000/v1
export LDEA_LLM_MODEL=qwen2.5-7b-instruct   # 与 vLLM served name 一致
npm run doctor
node dist/cli.js demo --live
node dist/cli.js run "核验本次登录错误分类是否真的修完并有测试"
```

## CLI

```
# 日常收工账本（无需 GPU）
ldea close --claim "已修复登录错误分类" --test "pytest -q"
ldea close --claim "今天全做完了" --no-git          # 空口 → abandoned
ldea ls
ldea ls --status abandoned
ldea show                       # 最近一条报告
ldea show <id> --outcomes

# Agent / 演示
ldea doctor
ldea init [sessionId]
ldea run <goal...>              # 本地 LLM 工具循环（可给含糊目标）
ldea demo                       # 双故事：abandoned vs verified
ldea demo --suite               # 四故事门禁矩阵（A/B/C/D，录像推荐）
ldea demo --empty|--code|--failing|--verified
ldea demo --live                # 含糊核验 + AMD vLLM
```

## 环境变量

见 `.env.example`：

- `LDEA_LLM_BASE_URL`（默认 `http://127.0.0.1:8000/v1`）
- `LDEA_LLM_MODEL` / `LDEA_LLM_API_KEY`
- `LDEA_ROOT`（默认 `.ldea`）
- `LDEA_CWD` / `LDEA_MAX_TOOL_ROUNDS`

## 与赛题对齐（赛道二）

| 要求 | LDEA |
|------|------|
| 智能体（推理/规划/工具/记忆） | Agent loop + TOOL_SPECS + session ledger |
| 本地私有部署 | 仅调用本机/隧道 vLLM，不依赖云 API |
| AMD Radeon / ROCm | 实测 Qwen2.5-7B-Instruct @ ~26–29 tok/s（以真机预演为准，写入规格书 §6） |
| 可演示 | `ldea demo` 离线；`demo --live` 真 GPU |
| 可核验输出 | 报告五栏 + events.jsonl 可回放 |

## 竞赛交付文档

| 文档 | 路径 |
|------|------|
| 项目规格说明书（场景/架构/能力/部署/ROCm） | [docs/项目规格说明书.md](docs/项目规格说明书.md) |
| 演示视频分镜与口播 | [docs/demo-script.md](docs/demo-script.md) |
| 演示成片 | [docs/media/LDEA-Demo-AMD-ROCm.mp4](docs/media/LDEA-Demo-AMD-ROCm.mp4) |
| 路演 PPT（HTML + PDF） | [docs/pitch/](docs/pitch/) · [LDEA-pitch-editorial.pdf](docs/pitch/LDEA-pitch-editorial.pdf) |
| 提交清单 | [docs/交付清单.md](docs/交付清单.md) |
| 赛题原文摘要 | [赛事标准.txt](赛事标准.txt) |

## 提交打包（评委复现）

LDEA 依赖同级目录的证据核 **`AiRecap Plus`**（`package.json` → `"airecap-plus": "file:../AiRecap Plus"`）。**两个仓库必须一起交付**。

推荐目录布局：

```text
<submit-root>/
  Local Dev Evidence Agent/     # 本仓库
  AiRecap Plus/                 # 证据核（与 LDEA 同级）
```

打包（推荐脚本，输出到桌面）：

```powershell
# 在 LDEA 仓库根目录
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack-submit.ps1
# → %USERPROFILE%\Desktop\LDEA-AMD-DevMaster-submit.zip
# 自动排除：node_modules / .git / .ldea / .env / 私钥
```

评委从零构建：

```bash
cd "AiRecap Plus" && npm install && npm run build
cd "../Local Dev Evidence Agent" && npm install && npm run build && npm test
node dist/cli.js demo            # 离线，无需 GPU
# 有 ROCm vLLM 时：
# node dist/cli.js doctor && node dist/cli.js demo --live
```

**不要提交**：真实 `.env`、云主机 SSH 私钥、含生产密钥的日志。  
**可以提交**：`fixtures/` 内 demo 假密钥（`sk-demoonly…`）、规格书、视频、PPT HTML。

赛题四件套对照：

| 赛题要求 | 本项目落点 |
|----------|------------|
| 项目规格说明书 | `docs/项目规格说明书.md` |
| 完整源码 + README | 本仓 + `AiRecap Plus` + 本文 |
| 演示视频 3–5 min | `docs/media/LDEA-Demo-AMD-ROCm.mp4`（约 2:38） |
| PPT / 海报（二选一） | `docs/pitch/`（HTML 8 页 + `LDEA-pitch-editorial.pdf`） |

## 开发

```bash
npm run typecheck
npm test
npm run build
```

## License

Private competition entry / local use.
