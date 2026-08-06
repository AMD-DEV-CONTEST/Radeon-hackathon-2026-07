# C0-B stage-b（fail-closed / 动态 run 目录）

## 证据目录

- 每次正式采集必须设置 `PRIVATEPLATE_RUN_ID`（或由 `run-all.sh` 生成 `privateplate-<profile>-<utc>`）。
- 产物写入：`benchmarks/c0/stage-b/${PRIVATEPLATE_RUN_ID}/`
- **保护只读**：`privateplate-v2`、`privateplate-v2.attempt1-arg-fail`（历史 7B 证据）
- 源码完整性校验会 **忽略** 所有 `benchmarks/c0/stage-b/privateplate-*` 证据树，避免动态目录导致 git dirty 误杀。

## 账号渠道

- 新正式采集固定使用 `PRIVATEPLATE_ACCOUNT_CHANNEL=GLOBAL`，入口为 `https://radeon-global.anruicloud.com/`。
- `00-verify-account.mjs` 会在模型下载前核对渠道和入口；混用中国区网址会直接停止。
- `PRIVATEPLATE_STORAGE_MODE` 必须明确写 `PERSISTENT_PVC` 或 `EPHEMERAL`；`PRIVATEPLATE_MODEL_DIRECTORY` 固定为 `none`，不混入 OpenClaw、ComfyUI 或 DevZone。
- 历史中国区 JSONL、会话文件和截图保持原样，只作为 `LEGACY_PARTIAL` 证据，不会被迁移或重写。

## 模型 profile（强制）

| Profile | Model | Revision | Parser |
|---------|-------|----------|--------|
| `gemma4-12b-qat-w4a16-ct`（主候选，别名 `gemma4`） | `google/gemma-4-12B-it-qat-w4a16-ct` | `1d2c2d7f…` | gemma4 + reasoning gemma4，quant `compressed-tensors` |
| `qwen14`（对照） | `Qwen/Qwen2.5-14B-Instruct` | `cf98f3b3…` | hermes |

无默认 7B，无 auto-fallback。配置见 `model-profiles.json` + `runtime-pin.json`。Gemma 禁止混用 hermes；Qwen 禁止混用 gemma4 parser。

## 可执行安装路径（R0-5）

版本 pin **不够**；正式路径必须可安装、可校验、可收尾：

| 文件 | 作用 |
|------|------|
| `install-plan.json` | 官方来源、安装步骤、parser 策略、fail-closed 规则 |
| `00-install-runtime.sh` | 实例上按 pin 安装/对齐（支持 `--dry-run`） |
| `00-install-node22.sh` | Node ≥22.13 |
| `00-verify-runtime.mjs` | 模型下载前核对 pin；不符即停 |
| `00-stop-vllm.sh` | 成功/失败/中断都停止模型服务 |
| `layered-product-diag.mjs` | 当前九工具产品路径诊断采集 |
| `write-failure-summary.mjs` | 统一失败/完成摘要 |
| `write-evidence-inventory.mjs` | 整轮文件清单 + SHA-256 |
| `verify-install-plan.mjs` | **本地离线**静态检查（不连 Radeon） |

固定组合：Python 3.12、ROCm 7.2.3、vLLM `0.25.1+rocm723`（wheel URL 钉死）、Torch `2.11.0`（官方 ROCm 7.2 index）+ HIP `7.2*`、transformers `5.14.1`、compressed-tensors `0.17.0`。

本地 dry-run（不装包、不开实例）：

```bash
bash scripts/c0/stage-b/00-install-runtime.sh --dry-run
node scripts/c0/stage-b/verify-install-plan.mjs
```

## 当前提交口径

历史五工具 regression / holdout / hidden suite / Public Golden 采集器已从本提交包退役。
当前九工具产品证据以 `layered-product-diag.mjs` 与已封存的诊断树为准：

`benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/`

`run-all.sh` 仍负责安装、runtime pin、基线、会话元数据、失败摘要与证据清单；不再调用已删除的五工具 / Public Golden 采集脚本。

## 本地预检

```bash
node scripts/c0/stage-b/validate-model-profile.mjs
node scripts/c0/stage-b/verify-install-plan.mjs
bash scripts/c0/stage-b/00-install-runtime.sh --dry-run
npm run test:c0-integrity-current
npm run check
```

## 实例

当前正式诊断证据见 `benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/`；
Radeon 部署与优化说明见 `docs/submission/AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md`。

本文不构成开实例授权。每次正式运行都需要项目所有者当次明确确认。
