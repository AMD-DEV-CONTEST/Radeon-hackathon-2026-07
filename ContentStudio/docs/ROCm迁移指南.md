# ROCm 迁移指南（AMD Radeon GPU）

> 把 Content Studio · Web 版从「云端 LLM + DirectML 占位」迁移到「真正基于 AMD Radeon GPU + ROCm」的操作手册。
> 适用前提：一台 **Linux + AMD GPU** 的机器（ROCm 是 Linux 优先；Windows 原生只有 DirectML，不算 ROCm）。

## ⭐ 赛方官方路径：AMD Radeon Cloud（最省事，推荐先用这个）

赛方提供 **Radeon Cloud**（云端 AMD Radeon GPU），有两条路，都不用你本地有 AMD 卡：

### 路径 1 · 免费模型 API（文本跑在 AMD GPU，免实例、免额度）

开箱即用的 OpenAI 兼容端点，跑的就是 AMD Radeon GPU 上的 Qwen/DeepSeek。

1. 去 https://developer.amd.com.cn/radeon/modelapis （Token Factory）登录 → 在 Public Free Model APIs 选模型（如 `Qwen3.6-35B-A3B`）→ 复制你的 **API Key**。
2. 应用「设置」里选 provider = **radeon**，Base URL 已预填 `https://developer.amd.com.cn/radeon/api/v1`，模型填 `Qwen3.6-35B-A3B`（或 `DeepSeek-V4-Flash`），API Key 填上面那个 → 保存。

**就这样：你的文本生成就跑在 AMD Radeon GPU 上了，满足赛道「基于 AMD GPU」。**（`radeon` 是纯文本模型，不开「视觉」，配图靠手动拖放——见预览页。）

### 路径 2 · 自己的实例（跑 ComfyUI 出图 / 专属模型）

1. https://radeon-global.anruicloud.com/ → 登录 → Profile → Add Template（选容器镜像；如要 SSH 先在 Profile 加公钥、并在模板里开 SSH Access）→ Launch 启动实例。
2. 进入实例（Open Notebook → JupyterLab 终端，或 SSH）。这是 **Linux + ROCm** 环境。
3. **出图（ComfyUI）**：在实例里装 ROCm 版 PyTorch + ComfyUI（见下方 §3），启动后把应用「设置」里的 ComfyUI Base URL 改成实例给的地址。
4. **专属模型 API**：模板里设 Deploy Type = vLLM Model API，serve command 如 `vllm serve <model> --host 0.0.0.0 --port 8000`；启动后用实例给的 Base URL/Key 当 provider。
5. **用完务必回 Profile → Active Instance → Destroy Instance**（否则持续耗额度）。

> 路径 1 最快拿到「AMD GPU 文本」的赛道加分；路径 2 把 ComfyUI/专属模型也搬上 AMD GPU，凑齐「文本+图像都在 AMD GPU」的最强故事。

---

## 0. 为什么现在不用改代码

架构已经解耦：
- **文本**：`LLMClient`（`core/models.py`）是 **OpenAI 兼容客户端**。vLLM / Ollama / TGI 都暴露 OpenAI 兼容 API，只要把配置里的 `base_url` 从云端改成 `http://localhost:<port>/v1` 即可，`generator.py`/`pipeline.py` 一行不动。
- **图像**：`comfy.py` 通过 HTTP（默认 `http://127.0.0.1:8188`）连 ComfyUI。ComfyUI 在 Linux+ROCm 上启动后自动走 ROCm/HIP，客户端无感。

所以迁移 = **装 ROCm 栈 + 起本地推理服务 + 改 3 个配置项 + 换 4 个 workflow JSON**。不重写业务代码。

## 1. 前置：装 ROCm

按 AMD 官方文档装对应你发行版的 ROCm（建议 ROCm 6.1+）。装完验证：

```bash
rocm-smi                 # 能看到 GPU、显存
/opt/rocm/bin/rocminfo   # 有 agent 输出
```

> 注意：ROCm 对 RDNA3（RX 7000 系）支持最好；RDNA2（6000 系）大多可用但需设 `HSA_OVERRIDE_GFX_VERSION`（如 6000 系常见 `export HSA_OVERRIDE_GFX_VERSION=10.3.5`）。老卡（Polaris/Vega）支持有限。

## 2. 文本推理：本地起 ROCm 服务

### 方案 A（推荐）：Ollama —— 最简单，自动用 ROCm

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve                       # 默认 :11434，OpenAI 兼容在 /v1
ollama pull qwen2.5:7b-instruct    # 或 gemma2:2b / qwen2.5:14b（按显存选，见 §5）
```

### 方案 B：vLLM —— 吞吐更高（推理加速加分项）

用官方 ROCm 镜像最省事：
```bash
docker run --network host --device /dev/kfd --device /dev/dri \
  -v ollama:/root/.ollama rocm/vllm:latest \
  --model Qwen/Qwen2.5-7B-Instruct --port 8000
```
或本地装：按 vLLM ROCm 文献装 ROCm 版 PyTorch 后 `pip install vllm`。

### 改配置（两种方案都一样）

在网页 `/settings` 页填，或直接编辑 `~/.content_studio/config.json`：

```json
"providers": [
  {
    "name": "local-rocm",
    "base_url": "http://localhost:11434/v1",   // Ollama
    // "base_url": "http://localhost:8000/v1", // vLLM
    "api_key": "not-needed",                    // 本地服务随便填
    "model": "qwen2.5:7b-instruct"              // 与上面 pull 的一致
  }
],
"active_provider": "local-rocm"
```

## 3. 图像推理：ComfyUI 走 ROCm（最快：用一键脚本）

把仓库里的 `scripts/setup_comfyui_rocm.sh` 传到 Radeon Cloud 实例（或实例终端里 `git clone` 本仓库后就有），然后在实例终端跑：

```bash
bash setup_comfyui_rocm.sh
```

脚本自动：装 ROCm 版 PyTorch → 克隆并装 ComfyUI → 下一个起步模型（DreamShaper 8）→ 启动 ComfyUI（`0.0.0.0:8188`）。

**让本机应用连上实例的 ComfyUI（SSH 隧道，最稳）**——在 **Windows 本地**开个终端，把实例的 8188 映射到本机：
```
ssh -L 8188:localhost:8188 <user>@<host> -p <port>
```
`<user>/<host>/<port>` 在实例详情的 SSH access 里。映射成功后，应用「设置→ComfyUI Base URL」**保持 `http://127.0.0.1:8188`** 即可——流量经隧道直达实例的 ComfyUI（AMD GPU）。应用「设置」里确认 ComfyUI 已启用。

验证 GPU 在跑：实例上另开终端 `rocm-smi` 看 `GPU-UTIL` 不为 0。

## 4. workflow JSON（已预置可用，一般不用动）

`content_studio/styles/workflows/*.json` 已经是**可用的 img2img 工作流**（LoadImage→VAEEncode→KSampler→VAEDecode→SaveImage，模型 `dreamshaper8.safetensors`——就是 §3 脚本下载的那个；保留了 `{positive}`/`{input_image}`/`{seed}` 占位给代码注入）。**只要跑了 §3 的脚本，选风格就能直接出图，无需手动导出。**

想换模型/加 LoRA/改风格强度时再自行改：在 ComfyUI 网页（`http://127.0.0.1:8188`）搭好工作流 → 「设置 → 保存(API 格式)」导出 → 覆盖对应 `*.json`，**务必保留** `{positive}`、`{input_image}`（LoadImage）、`{seed}`（KSampler）这三个占位字符串。

## 5. 显存 / 模型选型

| 你的卡 | 显存 | 文本推荐 | SDXL 出图 |
|---|---|---|---|
| RX 7600 / 7600 XT | 8–16GB | Gemma-2-2B 或 Qwen2.5-1.5B（INT4） | 需 `--lowvram` |
| RX 7700 XT / 7800 XT / 7900 GRE | 12–16GB | Qwen2.5-7B（AWQ INT4 ≈5GB） | OK |
| RX 7900 XT / XTX | 20–24GB | Qwen2.5-14B（AWQ INT4 ≈9GB） | 宽裕 |

量化 = 轻量化部署评分点：优先用 AWQ/GPTQ INT4 版本（如 `Qwen2.5-7B-Instruct-AWQ`），显存减半、速度更快。

## 6. 赛道四评分点对照（迁移后）

| 评分项 | 怎么体现 |
|---|---|
| **推理加速** | 演示时 `rocm-smi` 看 GPU 利用率；vLLM 连续批处理 tokens/s；对比「云端 API 往返」vs「本地 ROCm 推理」延迟。 |
| **轻量化部署** | 单机一体（FastAPI + 本地推理 + ComfyUI 全在一台 GPU 机）；INT4 量化把大模型塞进消费级显存。 |
| **风格定制** | 已有：风格预设三合一（ComfyUI 出图 + LLM 文风 + 文生图提示词）。 |
| **画质优化** | 已有：`image_pipeline`（2.35:1 封面、限宽 900、水印、JPEG 压缩）+ ComfyUI 风格迁移。 |

## 7. 验收清单（迁移完成时逐条过）

- [ ] `rocm-smi` 能看到 GPU。
- [ ] `/settings` 的 active provider 是 `local-rocm`，base_url 指向 localhost。
- [ ] 生成一篇文章：文本来自本地 GPU（可断外网验证——断网仍能生成说明没走云端）。
- [ ] ComfyUI 任务跑时 `rocm-smi` 显示 GPU 占用。
- [ ] 4 个 workflow JSON 已替换为真实导出，`{positive}`/`{input_image}`/`{seed}` 占位保留。
- [ ] 风格迁移 + 文生图都能出图。
- [ ] 「发到草稿箱」仍能把成品发到公众号草稿箱。

## 8. 回退

迁移出问题时，把 `active_provider` 改回云端 provider（如 `deepseek`）即可瞬间回退到云端文本；ComfyUI 连不上会自动降级为原图（见 `pipeline.py` 的 ComfyError 分支），不阻塞出文。
