# ComfyUI 工作流准备说明

## AMD FLUX.2-dev 人物身份参考图（Phase 3）

AMD H3 Ref2VA 的人物身份参考图使用固定能力 `flux2-dev-fp8mixed.v1`，不得替换为
FLUX.2 Klein、`latest` 或通配版本。模型权威根为
`/persistent/douyin-amd/models/flux2-dev/flux2-dev-fp8mixed-v1`，ComfyUI 固定发布为
`/persistent/douyin-amd/comfyui/0.30.0-6f7cd7fc`（commit
`6f7cd7fceaaf60d2669b554936394a7412c6fde5`）。许可证快照为
`FLUX Non-Commercial License`。

三个 API 模板及其原始文件 SHA-256 由
`config/flux2_dev_fp8mixed_amd_capability.json` 唯一指定：

| 能力角色 | API 模板 | SHA-256 |
|---|---|---|
| `text_to_image` | `keyframe_flux2_t2i_api.json` | `6029c0b8d2fe9133b354f01b2d693fa83622ebc1135b4638ab3f884065589618` |
| `single_reference_edit` | `keyframe_flux2_edit_api.json` | `60a8681d63ce3c01f43047b2bb137bfc327041e271e3b38d3fa974abeb012b87` |
| `dual_reference_edit` | `keyframe_flux2_edit_dual_api.json` | `20a045a89f663a5e2bcd24d1abb27bbe054fecfc3488230e981493493a2dc536` |

编译器只接受能力文件中的三个文件名，并固定使用 512×768、Euler、20 steps、
guidance 4.0；参考图缩放固定为 1.0 megapixel。模板保留受控占位符，提交 ComfyUI
前必须由 `drama.flux2_reference.workflows.compile_flux2_workflow` 完整替换。人物三视图
分别生成且种子/提示词摘要独立；每个视图最多重试一次，全部单视图 GLM QC 和跨视图
GLM QC 通过后才能冻结 `CharacterReferenceSetV1`。

流水线通过 **占位符注入** 调用 ComfyUI：模板里把动态值写成 `{{KEY}}`，运行时由对应 Agent 替换。
换工作流/换模型只需替换这里的 JSON 并保持占位符命名，无需改 Python 代码。

> **架构说明（迁移期）**：AMD H3 Ref2VA 人物身份参考图使用上面的本地
> FLUX.2-dev 能力；下文 CogView/SDXL/Wan 说明仅描述尚未迁移的旧流水线，不能作为
> AMD H3 身份参考图的模型或工作流权威来源。

> **本机环境（已对齐）**：2× RTX 4090 48GB；ComfyUI Desktop 路径 `F:\Users\A\AppData\Local\Programs\ComfyUI`。本目录下的工作流文件名已与**实际下载的模型**逐一对齐（见下方“已安装模型清单”）。**图生视频默认走 lightx2v 4 步加速**（用户已下载对应 LoRA），需要更高画质时按下文“全质量切换”一键改回。
>
> **两种 JSON 格式**：
> - `*_api.json`（本目录根下）= **API 格式**，流水线提交给 ComfyUI `/prompt` 用，含 `{{占位符}}`，**不要在 GUI 里直接 Open**（GUI 打开的是下面的 UI 格式）。
> - `gui/*.json` = **UI/workflow 格式**，给人在 **ComfyUI Desktop** 里 `Workflow ▸ Open` 打开/编辑用，已填入真实模型名、可直接跑（见“GUI 可视化工作流”）。

## 已安装模型清单（ground truth，工作流文件名以此为准）

放在 ComfyUI 的 `models/<子目录>/` 下：

| 子目录 | 文件名 | 用于 |
|---|---|---|
| `diffusion_models/` | `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | Wan2.2 I2V 高噪专家 |
| `diffusion_models/` | `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | Wan2.2 I2V 低噪专家 |
| `text_encoders/` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | Wan2.2 文本编码（CLIPLoader type=wan） |
| `vae/` | `wan_2.1_vae.safetensors` | Wan2.2 VAE |
| `loras/` | `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` | lightx2v 4 步加速（高噪） |
| `loras/` | `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | lightx2v 4 步加速（低噪） |
| `checkpoints/` | `sd_xl_base_1.0.safetensors` | 关键帧 SDXL 底模 |
| `ipadapter/` | `ip-adapter-plus-face_sdxl_vit-h.safetensors` | 关键帧角色一致性（IPAdapter PLUS FACE） |
| `clip_vision/` | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | IPAdapter 的 ViT-H 图像编码器 |

> IPAdapter 的两个文件名经核对 `cubiq/ComfyUI_IPAdapter_plus` 源码：`PLUS FACE (portraits)` 预设按正则 `plus.face.sdxl.vit.h` 匹配 ipadapter 文件、按默认 ViT-H 正则 `ViT.H.14.*s32B.b79K` 匹配 clip_vision 文件——上面两个文件名**都能被自动解析**，无需手填。IPAdapter 模型放 `models/ipadapter/`（loader 扫描该目录；旧版 `sdxl_models/` 布局也兼容）。

## 占位符约定

| 文件 | 用途 | 必须保留的占位符 |
|---|---|---|
| `keyframe_flux_api.json` | 镜头关键帧 / 场景基准图（无参考图，自包含 T2I；对应 `pipeline.yaml` 的 `workflows.keyframe`） | `{{POS_PROMPT}}` `{{NEG_PROMPT}}` `{{SEED}}` `{{WIDTH}}` `{{HEIGHT}}` `{{CKPT}}` |
| `keyframe_instantid_api.json` | 关键帧·角色一致性（**InstantID 强锁脸，默认**；对应 `workflows.keyframe_instantid`） | 上面 6 个 + `{{REF_IMAGE}}` `{{INSTANTID_WEIGHT}}` |
| `keyframe_sdxl_ipadapter_api.json` | 关键帧·角色一致性（IPAdapter 退化路径；对应 `workflows.keyframe_ref`） | 上面 6 个 + `{{REF_IMAGE}}` `{{IP_WEIGHT}}` `{{IP_END}}` |
| `keyframe_scene_img2img_api.json` | 关键帧·无人物镜头从场景图 img2img 锁背景（对应 `workflows.keyframe_scene_ref`） | `{{POS_PROMPT}}` `{{NEG_PROMPT}}` `{{SEED}}` `{{WIDTH}}` `{{HEIGHT}}` `{{CKPT}}` `{{CONTROL_IMAGE}}` `{{DENOISE}}` |
| `character_ref_qwen_api.json` | ~~人物多视图参考图~~ **已停用**（参考图改由云端 CogView 生成；文件保留仅供历史参考，pipeline.yaml 不再引用） | — |
| `i2v_wan22_api.json` | Wan2.2 图生视频 | `{{REF_IMAGE}}` `{{POS_PROMPT}}` `{{NEG_PROMPT}}` `{{FRAMES}}` `{{FPS}}` `{{SEED}}` `{{WIDTH}}` `{{HEIGHT}}` |
| `infinitetalk_api.json` | 对口型 | `{{REF_IMAGE}}` `{{AUDIO}}` `{{POS_PROMPT}}` `{{SEED}}` |

数值类占位符在 JSON 里要写成字符串形式（如 `”seed”: “{{SEED}}”`），注入时会自动转回数字。

## 导出步骤

1. 在 ComfyUI 里搭好工作流，确认能正常出图/出片（**最省事**：直接 `Workflow ▸ Open` 打开 `gui/` 里对应的 UI 文件，它已填好真实模型名，改改提示词/起始帧就能跑）。
2. 设置中开启 **开发者模式(Dev Mode)**。
3. 菜单 **Save (API Format)** 导出 `*_api.json`。
4. 把导出的内容替换对应文件，把需要动态控制的输入值改成上表的 `{{占位符}}`。
5. 对照样例：`keyframe_flux_api.json` 是最小 SDXL 文生图；`gui/keyframe_sdxl_ipadapter.json` 和 `gui/i2v_wan22_lightx2v.json` 是带真实模型名的可视化参考图。

## 状态

- `keyframe_flux_api.json` —— ✅ 自包含 SDXL 文生图（无参考图，场景图/无人物镜头用它；pipeline.yaml `workflows.keyframe`）。
- `keyframe_sdxl_ipadapter_api.json` —— ✅ SDXL + IPAdapter 角色一致性（**已是默认行为**：有人物参考图的镜头由 `KeyframeGenerator` 自动选用；pipeline.yaml `workflows.keyframe_ref`）。
- `character_ref_qwen_api.json` —— ⛔ **已停用**。人物参考图与场景参考图改由云端 CogView-4 生成（`config/models.yaml` + `config/pipeline.yaml`）；此文件保留在仓库仅供历史参考，pipeline.yaml 不再引用，**本地无需下载 FLUX 模型**。`pipeline.yaml` 里原来的 `workflows.scene_ref` key 同样已停用（注释掉），也不再使用。
- `i2v_wan22_api.json` —— ✅ Wan2.2 14B I2V（官方原生模板结构：双 high/low-noise UNet + 两段 KSamplerAdvanced）。**默认 lightx2v 4 步加速**：两个 UNet 各接一个 `LoraLoaderModelOnly` 加载对应的 lightx2v LoRA，总步数 4（高噪 2 + 低噪 2）、cfg 1.0、sampler euler、scheduler simple、shift 5.0。全质量切换见下文。
- `infinitetalk_api.json` —— ✅ InfiniteTalk 对口型（kijai WanVideoWrapper 节点链，可选）。

> 这些是面向 **ComfyUI 核心 + 下列自定义节点** 的参考图；ComfyUI 各版本之间 node 的 `class_type`／输入字段名会变动——**若某工作流加载失败，请在你本机 ComfyUI 里打开对应的官方/示例模板，用 Save (API Format) 重新导出覆盖，并保持相同的 `{{占位符}}` 命名**即可。
>
> 干跑模式（`--dry-run`）不需要真实工作流，会写占位产物跑通流程。

## 每个工作流的依赖（模型文件 + 自定义节点）

| 工作流 | 关键节点 | 必需模型文件（放到 ComfyUI `models/<子目录>`） | 必需自定义节点 |
|---|---|---|---|
| `keyframe_flux_api.json` | CheckpointLoaderSimple → KSampler → SaveImage | `checkpoints/sd_xl_base_1.0.safetensors`（可换任意 SDXL ckpt） | 无（纯核心） |
| `keyframe_instantid_api.json` | + InstantIDModelLoader + InstantIDFaceAnalysis(CPU) + ControlNetLoader + ApplyInstantID → KSampler(cfg5) | 上面的 SDXL ckpt；`instantid/ip-adapter.bin`；`controlnet/instantid/diffusion_pytorch_model.safetensors`（路径用反斜杠）；`insightface/models/antelopev2/` 5 onnx | **ComfyUI_InstantID** + insightface/onnxruntime |
| `keyframe_sdxl_ipadapter_api.json` | + LoadImage → IPAdapterUnifiedLoader(`PLUS FACE (portraits)`) → IPAdapter | 上面的 SDXL ckpt；`ipadapter/ip-adapter-plus-face_sdxl_vit-h.safetensors`；`clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`（Unified Loader 按文件名正则自动匹配，已核对源码） | **ComfyUI_IPAdapter_plus**（cubiq） |
| `keyframe_scene_img2img_api.json` | CheckpointLoaderSimple → LoadImage → VAEEncode → KSampler(denoise) → SaveImage | 上面的 SDXL ckpt（**无需额外模型**） | 无（纯核心） |
| `character_ref_qwen_api.json` | ~~UNETLoader(flux) + DualCLIPLoader → FluxGuidance → KSampler → SaveImage~~ | **已停用** — 无需下载 FLUX 模型（`flux1-dev.safetensors` / `t5xxl_fp16.safetensors` / `clip_l.safetensors` / `ae.safetensors`）；参考图现由云端 CogView-4 生成 | — |
| `i2v_wan22_api.json` | 2×UNETLoader(high/low) → 2×LoraLoaderModelOnly(lightx2v) → 2×ModelSamplingSD3 + CLIPLoader(`wan`) + VAELoader → WanImageToVideo → 2×KSamplerAdvanced → VAEDecode → VHS_VideoCombine(mp4) | `diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` + `..._low_noise_...safetensors`；`loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` + `..._low_noise...`；`text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`；`vae/wan_2.1_vae.safetensors` | **ComfyUI-VideoHelperSuite**（VHS_VideoCombine） |
| `infinitetalk_api.json` | WanVideoModelLoader + MultiTalkModelLoader + WanVideoVAELoader + WanVideoTextEncodeCached + (LoadAudio→DownloadAndLoadWav2VecModel→MultiTalkWav2VecEmbeds) + WanVideoImageToVideoMultiTalk → WanVideoSampler → WanVideoDecode → VHS_VideoCombine | Wan2.1 14B I2V 480p 权重（fp8/gguf，如 `wan2.1-i2v-14b-480p-Q8_0.gguf`）；InfiniteTalk 权重（如 `Wan2_1-InfiniteTalk_Single_Q8.gguf`）；`Wan2_1_VAE_bf16.safetensors`；`umt5-xxl-enc-bf16.safetensors`；wav2vec（`TencentGameMate/chinese-wav2vec2-base`，首次自动下载） | **ComfyUI-WanVideoWrapper**（kijai）+ **ComfyUI-VideoHelperSuite** + **ComfyUI-KJNodes**（ImageResizeKJv2） |

> 模型文件名以各工作流 JSON 顶部的 `_comment` 为准；换权重时改 loader 节点里的文件名即可，无需动占位符。
> 显存：本机 **48GB** 单卡 Wan2.2 14B I2V 跑 480p（如 480×832）很轻松，**720p（720×1280）也完全可行**（改 `config/pipeline.yaml` 的 `video.gen_width/gen_height`）；两张卡各绑一个 ComfyUI 实例（8188 / 8189）并行翻倍产能。

## 图生视频：lightx2v 4 步加速（默认）与全质量切换

`i2v_wan22_api.json` **默认走 lightx2v 4 步加速**（用户已下载两个 lightx2v LoRA，量产吞吐优先）。两套参数如下：

| 模式 | 步数（高/低） | cfg | sampler | scheduler | ModelSamplingSD3 shift | LoRA |
|---|---|---|---|---|---|---|
| **lightx2v 4 步（默认）** | 4（2 + 2） | 1.0 | euler | simple | 5.0 | 两个 `LoraLoaderModelOnly` 各加载对应 lightx2v LoRA，strength 1.0 |
| **全质量（更慢更精）** | 20（10 + 10） | 3.5 | euler | simple | 8.0 | **绕过/删除**两个 `LoraLoaderModelOnly` |

> lightx2v 参数来源：lightx2v 官方模型卡讨论（4 步 = 高噪 2 + 低噪 2、cfg 1.0、euler + simple、shift 5）。

**一键切到全质量**（API 文件 `i2v_wan22_api.json`）：
1. 删除节点 `51`、`52`（两个 `LoraLoaderModelOnly`），把 `41.model` 改回 `["37",0]`、`42.model` 改回 `["38",0]`（直接从 UNETLoader 取）。
2. 两个 `KSamplerAdvanced`（`47`/`48`）的 `steps` 改 `20`，把切分点改到 10（`47.end_at_step=10`、`48.start_at_step=10`），`cfg` 改 `3.5`。
3. 可选：两个 `ModelSamplingSD3` 的 `shift` 改 `8.0`。

GUI 文件 `gui/i2v_wan22_lightx2v.json` 里更简单：选中两个 LoRA 节点按 **Ctrl+B** 旁路，再按上面改 KSampler 步数/cfg 即可。

## 关键帧一致性（自动按镜头选择，默认开启）

`KeyframeGenerator`（`src/drama/agents/keyframe_generator.py`）按镜头元数据在**四个**工作流间自动路由，优先级 **InstantID > IPAdapter > 场景 img2img > 纯文生图**：

| 镜头条件 | 选用工作流 | 机制 |
|---|---|---|
| 有人物 且 `keyframe.use_instantid=true`（**默认**） | `keyframe_instantid_api.json` | **InstantID** 强锁脸（InsightFace 提身份 + ControlNet 注入，远强于 IPAdapter） |
| 有人物 且未开 InstantID | `keyframe_sdxl_ipadapter_api.json` | SDXL + IPAdapter PLUS FACE 注入正脸 |
| 无人物 且 `keyframe.use_scene_ref=true`（**默认**） | `keyframe_scene_img2img_api.json` | 从场景参考图 img2img 锁背景（**免额外模型**） |
| 其余 | `keyframe_flux_api.json` | SDXL 纯文生图 |

对应 `config/pipeline.yaml`：

```yaml
keyframe:
  use_instantid: true        # 有人物镜头默认走 InstantID 强锁脸
  instantid_weight: 0.8
  use_scene_ref: true        # 无人物镜头默认从场景图 img2img
  scene_ref_denoise: 0.6
  ip_weight: 0.9             # InstantID 关闭时的 IPAdapter 退化路径
  ip_end: 0.8
workflows:
  keyframe: keyframe_flux_api.json                    # 无人物 + 未开场景锚
  keyframe_ref: keyframe_sdxl_ipadapter_api.json      # 有人物（IPAdapter 退化）
  keyframe_scene_ref: keyframe_scene_img2img_api.json # 无人物 + 场景锚
  keyframe_instantid: keyframe_instantid_api.json     # 有人物（默认，InstantID）
```

无需手动切换；流水线按镜头是否含人物参考图、是否开关自动路由。**InstantID 把同人率从纯 IPAdapter 的 ~50% 提升到 ≈92%**（实测）。

### InstantID 模型与坑（必读）

`keyframe_instantid_api.json` 需自定义节点 **`ComfyUI_InstantID`** + `insightface`/`onnxruntime`（已装），以及用户下载的模型：

| 路径 | 文件 | 大小 |
|---|---|---|
| `models/instantid/` | `ip-adapter.bin` | ~1.7 GB |
| `models/controlnet/instantid/` | `diffusion_pytorch_model.safetensors` | ~2.5 GB |
| `models/insightface/models/antelopev2/` | 5 个 onnx（1k3d68/2d106det/genderage/glintr100/scrfd_10g_bnkps） | — |

占位符：`{{CKPT}} {{REF_IMAGE}}（干净正脸，如 gpt_anchors/<char>/front.png）{{POS_PROMPT}} {{NEG_PROMPT}} {{SEED}} {{WIDTH}} {{HEIGHT}} {{INSTANTID_WEIGHT}}`。

> ⚠️ ControlNet 子目录路径必须用 **Windows 反斜杠**：`"instantid\\diffusion_pytorch_model.safetensors"`（正斜杠 → "value not in list" HTTP 400）。下/装完模型后**重启 ComfyUI**，用 `GET /object_info/InstantIDModelLoader` 验证节点已加载。

## GUI 可视化工作流（`gui/`，给人在 ComfyUI Desktop 里打开/编辑）

`gui/` 子目录里是 **UI / workflow 格式**（含 `nodes[]` / `links[]` / `groups` / 坐标 / `version` 字段，legacy `version: 0.4` 数组连线格式，ComfyUI Desktop 兼容性最好）。**已填入用户真实模型文件名（非占位符），加载即可跑**：

| 文件 | 内容 |
|---|---|
| `gui/keyframe_sdxl_ipadapter.json` | SDXL + IPAdapter PLUS FACE 关键帧（角色一致性）。参考脸默认 `reference_face.png`，在 LoadImage 节点换成你的脸图。 |
| `gui/i2v_wan22_lightx2v.json` | Wan2.2 14B I2V 双 high/low-noise 专家 + lightx2v 4 步 LoRA（默认加速档）。起始帧默认 `start_frame.png`，在 LoadImage 节点换图。 |

**怎么打开**：ComfyUI Desktop 顶部菜单 **Workflow ▸ Open**（或直接把 json 拖进画布），选对应文件即可。

**编辑后回写 API 文件**：在 ComfyUI **设置里开启 Dev Mode**，改完用 **Save (API Format)** 导出，覆盖本目录根下对应的 `*_api.json`，并把需要流水线动态控制的输入值改回 `{{占位符}}`（占位符清单见本文开头表格）。这样流水线用的 API 文件就与你在 GUI 里调好的图保持一致。

> 诚实说明：`gui/*.json` 是**按官方 Wan2.2 I2V 模板拓扑 + lightx2v LoRA 手写并做了结构校验**（所有连线 id/slot 自洽、JSON 合法）的参考图；ComfyUI 各版本之间 node 字段/widget 顺序可能漂移，**若某文件加载后报红或 widget 错位，请在本机用对应官方模板重新搭一遍并 Save 覆盖**——拓扑和模型名照本文即可。

## ComfyUI-Manager 需安装的自定义节点

> **关键帧三件套懒人下载**：`tools/download_comfy_models.ps1` 会自动从 HuggingFace 下载 SDXL base、IPAdapter Plus Face、CLIP-ViT-H 这三个模型到正确的子目录（Wan2.2 系列 + lightx2v LoRA 已提前下好，该脚本只补这三个）。用法：`powershell -ExecutionPolicy Bypass -File tools\download_comfy_models.ps1`。

用 **ComfyUI-Manager**（Manager ▸ Custom Nodes Manager）安装：

| 自定义节点 | 提供的关键节点 | 哪个工作流要 |
|---|---|---|
| **ComfyUI-VideoHelperSuite**（Kosinkadink） | `VHS_VideoCombine`（合成 mp4） | `i2v_wan22_api.json` / `gui/i2v_wan22_lightx2v.json`（必需） |
| **ComfyUI_InstantID** | `InstantIDModelLoader` / `InstantIDFaceAnalysis` / `ApplyInstantID` | `keyframe_instantid_api.json`（**默认人物路径**，必需；+ insightface/onnxruntime） |
| **ComfyUI_IPAdapter_plus**（cubiq） | `IPAdapterUnifiedLoader` / `IPAdapter` | `keyframe_sdxl_ipadapter_api.json` / `gui/keyframe_sdxl_ipadapter.json`（IPAdapter 退化路径） |
| **ComfyUI-WanVideoWrapper**（kijai） + **ComfyUI-KJNodes** | `WanVideo*` / `MultiTalk*` / `ImageResizeKJv2` | `infinitetalk_api.json`（仅做对口型时需要，可选） |

> 关键帧若用纯 SDXL 文生图 / 场景 img2img（`keyframe_flux_api.json` / `keyframe_scene_img2img_api.json`）则**无需任何自定义节点**（纯核心）。

## 推荐工作流/模型

- 关键帧一致性：**SDXL + IPAdapter（PLUS FACE）**（ComfyUI 本地）；人物/场景参考图由云端 **CogView-4** 生成（见 `config/models.yaml`）。
- 图生视频：**Wan2.2 14B I2V**（官方模板 `video_wan2_2_14B_i2v`）；**默认 lightx2v 4 步加速**，全质量切换见上文；48GB 单卡 480p 轻松、720p 可行。
- 对口型：**InfiniteTalk**（MeiGen-AI）+ WanVideoWrapper（kijai）——**可选**，其模型（Wan2.1 14B I2V 权重 / InfiniteTalk 权重 / wav2vec 等）**目前未下载**；`infinitetalk_api.json` 保持原样，待需要对口型时再装 WanVideoWrapper + KJNodes 并下载对应权重。
