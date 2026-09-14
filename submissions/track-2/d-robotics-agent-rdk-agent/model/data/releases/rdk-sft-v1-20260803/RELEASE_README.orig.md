# rdk-sft-v1-20260803 — 统一格式 SFT 发布目录

本目录是 `data/` 整理后的**统一训练数据入口**：所有对话样本均为同一种格式 `rdk_sft_sample.v1`（见 `schema/rdk_sft_sample.v1.schema.json`），全部 1755 条唯一样本逐条通过严格校验（顶层字段、消息形态、tool_call 与 tool 消息一一对应、`arguments` 为对象），task_id 全局零重复。机器可读清单见 `manifest.json`（含每个文件的行数、SHA-256、来源与变换方式）。

> **2026-08-03 提升事件**：原 needs-review 隔离区的 848 条样本已按所有者决定**全量提升**并入 `agentic/` 与 `combined/`。每条提升样本的 metadata 都带 `promoted_from_needs_review: true` 及原始 `failed_checks`、`quality_score` 标记；**回退方法**：过滤掉 `metadata.promoted_from_needs_review == true` 的行即还原为 327 条精选集。其中 428 条含证据类失败（无据推断/数字无出处/ssh 契约），训练配置可按 `failed_checks` 自行再筛。

## 目录结构

```text
rdk-sft-v1-20260803/
├── manifest.json                  # 机器可读清单（行数 / sha256 / 来源 / 变换）
├── schema/rdk_sft_sample.v1.schema.json
├── agentic/                       # 真实板端 Agentic，1175 条（946/116/113）
│                                  #   = 精选 327 + 提升 848（带 promoted 标记）
├── qa/                            # 无工具 QA，300 条（240/30/30）
├── combined/                      # 合并训练入口 = agentic + qa，1475 条（1186/146/143）
├── repair-synthetic/              # synthetic repair，280 条，独立存放
│   ├── stage2_train.jsonl (96)   ├── stage2_validation.jsonl (24)
│   ├── stage3_train.jsonl (128)  └── stage3_validation.jsonl (32)
└── needs-review/                  # 审计副本：848 条已提升，此处保留原件与质检明细
    ├── needs_review.jsonl                      # ⚠️ 已并入 agentic/，勿重复计数
    └── quality_scores.needs_review.jsonl       # 每条的质检得分与 failed_checks
```

## 怎么用

- **直接训练**：用 `combined/train.jsonl` + `combined/validation.jsonl`；或按需分别取 `agentic/`、`qa/`。
- **只要精选集**：过滤掉 `metadata.promoted_from_needs_review == true` 的行（还原为提升前的 627 条真实数据入口）。
- **要加 synthetic repair**：显式地把 `repair-synthetic/*_train.jsonl` 追加进训练配置。这些样本 `metadata.is_synthetic=true`，随时可过滤。
- **不要用**：`needs-review/`（审计副本，内容已在 `agentic/` 里）；源数据集里的 `rejected.jsonl`、`raw_trajectories.jsonl`（审计物）。

## 数据来源与变换

| 输出 | 来源（相对 data/） | 变换 |
| --- | --- | --- |
| `agentic/*` | v2 数据集 `{train,validation,test}.jsonl` + `needs_review.jsonl` | 精选部分逐字节原样；提升部分追加 6 个 metadata 标记键 |
| `qa/*` | `sft/magicbox-no-tool-qa-300-20260731-v1/{train,validation,test}.jsonl` | 逐字节原样 |
| `combined/*` | agentic + qa 按 split 拼接 | 仅拼接 |
| `repair-synthetic/stage2_*` | stage2-repair-v5 `repair_*.jsonl` | `schema_version` 归一化 |
| `repair-synthetic/stage3_*` | stage3-repair-v7 `repair_*.jsonl` | `schema_version` 归一化 |
| `needs-review/*` | v2 数据集 `needs_review.jsonl` / `quality_scores.jsonl`（过滤） | 审计副本，原样保留 |

提升样本的 metadata 新增键：`promoted_from_needs_review`、`original_quality_status`、`quality_score`、`failed_checks`、`promoted_at`、`promotion_basis`；消息、工具、outcome 逐字段未动（抽样断言验证）。repair 归一化同前：仅 `schema_version` + 3 个 provenance 标记。

## 边界声明

- `repair-synthetic/` 是 synthetic native Pi replay，**不是**真实板端轨迹，不进 `combined/`，是否入训由训练配置显式决定。
- 提升的 848 条未经人工逐条复核（质检 `failed_checks` 记录在案）；如训练/评估表现异常，优先按标记回退或按 `failed_checks` 分层筛选。
- validation/test 中分别含 84/80 条提升样本；如需"纯精选"评测集，请按标记过滤。
- stage3 repair 收录的是 v7（v6 同集已取代）。源数据集目录全部原位保留，样本 metadata 里的绝对路径 provenance 仍可解析。
