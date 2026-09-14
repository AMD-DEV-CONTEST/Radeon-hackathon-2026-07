# 服务端模型身份证明(model/)

这一节回答闭环中最关键的一个问题:**线上推理服务加载的,到底是不是训练出来的那份 adapter?**

## 身份链

```text
训练侧(冻结)                          服务侧(运行时)
checkpoint-000119/manifest.json   ==   deployment_manifest.orig.json
  adapter_model.safetensors              adapter_model_sha256
  268,555,264 字节                       4dcee691…f20bf   ← 两侧同一哈希
  sha256 4dcee691…f20bf                  + 主机指纹(hostname/boot_id/GPU unique id)
                                         + 服务端脚本与启动脚本的 SHA-256
```

`served-model-manifest.json` 把这条链和行为学证据合并成单一文件,是本节的主件。

## 行为学证明(diff proof)

同一套 6 个探针、temperature=0、同一个请求模型名,分别打向 base-only 服务与 base+adapter 服务(捕获文件在 `ab-probe/`):

| 探针 | 结果 | 含义 |
|---|---|---|
| identity / math / tool_call | 逐字一致 | LoRA 未破坏通用能力与结构化 tool-call |
| tool_continuation / rdk_domain / exit0_semantics | 明显不同 | adapter 权重确实参与了生成 |

复现方法:在训练机上 `python3 ab-probe/probe.py <api_key_file> out.json`,分别在两种服务形态下各跑一次,对比输出(tool_calls 对比须剔除随机 call id)。

## 必须知道的时间线与坑

2026-08-04 16:59 UTC,SFT 部署创建并通过全部部署闸门;**17:54 UTC 服务被切回 base-only,且 base 服务以 `--accepted-model-alias` 接受 SFT 模型名**——此后请求 SFT 名的会话实际由裸 base 应答(响应 `model` 字段如实返回 base 名,`/health` 报告 `adapter_loaded:false`)。2026-08-05 03:41 UTC 恢复 SFT 服务。

教训已写入 `served-model-manifest.json` 的 `known_footgun`:服务返回的 `model` 字段与 `/health` 才表示当时实际加载的形态。`rdk-agent` 的 provider、Base URL、模型名和 API Key 由使用者在 Agent 侧自行配置,本模型包不接管 Agent 配置。

## adapter 实物与公开下载

adapter 不入 Git。校验清单见 `SHA256SUMS`。

**公开下载**:[ModelScope · ming01/Qwen3-32B-Agentic-SFT-r1-v3](https://modelscope.ai/models/ming01/Qwen3-32B-Agentic-SFT-r1-v3/files)(模型)
**配套数据集**:[ModelScope · ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files)(脱敏 train+validation;historically held-out Test 已在本仓库评测后公开用于复现)

评委验证只需三步:

```bash
# 1. 下载(ModelScope CLI 或页面直接下载)
modelscope download ming01/Qwen3-32B-Agentic-SFT-r1-v3 adapter_model.safetensors --local_dir .
# 2. 校验——必须逐字节等于训练冻结清单里的哈希
sha256sum adapter_model.safetensors
# 期望:4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf  (268,555,264 字节)
# 3. 对照冻结来源:examples/qwen3-32b-training/evidence/checkpoint-000119/manifest.json
```

权重哈希的四个存在位置:ModelScope 公开仓库(2026-08-05 已用匿名 API 复核为 Public)、训练机 checkpoint 原件、本地备份 `amd-rl/model-artifacts/checkpoint-000119/`、训练冻结 manifest 记录。四处 `adapter_model.safetensors` 均为 268,555,264 字节且 SHA-256 逐字节一致。公开 `adapter_config.json` 为可移植分发做了两处规范化:`base_model_name_or_path` 从原训练机绝对路径改为 `unsloth/Qwen3-32B-bnb-4bit`,`revision` 从 `null` 固定为 `7f721e74a6a8cc9ee352f7e49303a2c1705f9083`,并增加末尾换行;权重内容未改变。

## 边界声明

本节证明的是**部署身份**(加载了哪份权重)与**行为差异**(adapter 生效),不证明**质量提升**——SFT 是否比 base 更强,由评测时 historically held out、评测后公开用于复现的 Test 与 Base/SFT A/B 回答,那是 benchmark 一节的职责。
