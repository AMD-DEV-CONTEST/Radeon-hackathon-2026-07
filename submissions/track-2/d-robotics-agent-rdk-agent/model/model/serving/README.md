> English version: [README.en.md](README.en.md)

# Tier 1 — 在 Radeon 上启动 SFT 服务并验证身份

评委路线:一条命令完成下载公开权重、校验制品身份、起服务并等待健康。约 20 分钟(不含下载)。

`qwen3_agentic_openai_server.py` 即正式评测所用的服务端**原件**(SHA-256 `95d5c139…`,与 `../deployment_manifest.orig.json` 及 A/B 评测的 expect 集绑定的是同一个哈希)。

## 1. 部署

```bash
bash deploy.sh
```

`deploy.sh` 依次完成:环境自检(Python ≥ 3.10、ROCm torch 能看到 GPU)→ 下载基座(`unsloth/Qwen3-32B-bnb-4bit@7f721e74`)与 adapter(ModelScope `ming01/Qwen3-32B-Agentic-SFT-r1-v3`)→ **fail-closed 身份校验:adapter SHA-256 必须等于 `4dcee691…f20bf`,不符则拒绝启动** → 安装锁定版依赖 → 起服务 → 轮询 `/health` 直到报告 `checkpoint-000119`。已满足的步骤自动跳过,可重复执行。

```bash
DRY_RUN=1 bash deploy.sh   # 只校验主机与制品,不启动任何服务
```

实测环境:AMD Radeon gfx1100(加载后约 19.3GB VRAM)、ROCm 7.2.1、Python 3.12、torch 2.9.1+rocm7.2.0。脚本不安装 ROCm 本身;若 torch 看不到 GPU,会打印确切的安装命令后退出。就绪输出:

```
{"status":"ok","model":"Qwen3-32B-Agentic-SFT-r1-v3","checkpoint":"checkpoint-000119"}
```

默认值不合适时可覆盖:`BASE_MODEL`、`ADAPTER`、`API_KEY_FILE`、`PORT`、`SKIP_DEPS=1`。若想手动逐步执行,`deploy.sh` 里每一步都是可直接复制的普通 shell 行。

## 2. 行为探针(可选,证明 adapter 生效)

```bash
python3 ../ab-probe/probe.py ./api_key probe-out.json
# 与 ../ab-probe/probe-sft-*.json 对照;若改起 base-only 服务(去掉 ADAPTER,serve.sh 会拒绝——
# 用 --model 直启不带 --adapter),输出应与 probe-base-*.json 一侧对齐
```

## Agent 接入接口

模型服务只暴露标准接口,不提供也不接管 `rdk-agent` 的配置:

- Base URL:`http://<radeon-host>:8000/v1`
- Endpoint:`POST /chat/completions`
- Model:`Qwen3-32B-Agentic-SFT-r1-v3`
- Authentication:`Authorization: Bearer <API_KEY>`

API Key 由 Radeon 主机上的 `API_KEY_FILE` 提供,真实 Key 不进入仓库。`rdk-agent` 的 provider、Base URL、模型名和 API Key 由使用者在 Agent 侧自行配置。
