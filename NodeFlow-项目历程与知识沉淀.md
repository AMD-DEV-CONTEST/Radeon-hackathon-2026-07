# NodeFlow 项目历程与知识沉淀

> 一份面向个人知识库的完整复盘文档。记录了 NodeFlow（AMD AI DevMaster 2026 Track 1 参赛项目）从零到交付的全过程，包括产品设计、技术实现、踩坑修复、AMD GPU 部署实战，以及可复用的工程方法论。

---

## 一、项目是什么

**NodeFlow** 是一个跑在 AMD Radeon GPU 上的 AI 图像生成工作站，核心主张是「无限画布手绘 + 扩散模型生图」，全程基于 ROCm 运行时，不依赖 NVIDIA CUDA。

一句话定位：**既避开 ComfyUI 的陡峭学习曲线，又比纯文生图输入框更有创作参与感——画布本身就是创作空间。**

### 核心能力

1. **无限画布创作**：用 Excalidraw 画布手绘草图，AI 将其重绘为成品画作（图生图）。
2. **Fast / Expert 双模式**：Fast 用 SDXL-Lightning 蒸馏模型几秒出图；Expert 用全量模型（FLUX.2-klein、NoobAI XL 等），参数全开放。
3. **多模型热切换**：SDXL / FLUX.2 / NoobAI / Animagine / Illustrious 一键切换，无需重启服务。
4. **LoRA 权重实时调节**：拆成「谁画」×「怎么画」两个维度，可混搭写实基底与动漫 LoRA。
5. **8 种风格预设**：Cyberpunk、Anime、Watercolor、Oil Painting、3D Render、Pixel Art、Concept Art、Minimalist。
6. **内置模型商店**：应用内直接浏览下载 HuggingFace / Civitai 的模型与 LoRA。
7. **视频生成**：集成 MiniMax H3，走本地 ComfyUI，支持文生视频与图生视频（把上游图当首帧）。

---

## 二、技术架构

```
Frontend (React 18 + Excalidraw Infinite Canvas)
   │  /api/*
   ▼
main.py (FastAPI Route Layer)
   ▼
engine.py (FluxEngine Facade → 委托给 ModelManager)
   ▼
model_manager.py (ModelManager 单例: load/switch/generate/LoRA)
   ▼
   ├── adapters/sdxl_adapter.py        (SDXL 家族: Lightning / Animagine / Illustrious / NoobAI)
   ├── adapters/flux2klein_adapter.py  (FLUX.2 Klein 家族: distilled / base)
   └── store_service.py                (模型商店: 聚合 HF + Civitai)
```

### 关键设计决策

- **Facade 模式**：`engine.py` 保留 `FluxEngine` 类名作为薄门面，全部委托给 `ModelManager`，旧代码无需改动即可工作。
- **ModelManager 单例**：统一处理模型加载/卸载/切换、文生图/图生图分发、LoRA 管理、GPU 状态查询。线程安全靠 `_generation_lock`（同一时刻只做一个生成）和 `_switch_lock`（防止并发切换）。切换失败自动回滚到上一个可用模型并恢复 LoRA 状态。
- **Adapter 模式**：`ADAPTER_REGISTRY` 把架构名映射到 `SDXLAdapter` / `Flux2KleinAdapter`，每个适配器暴露统一的 `load / generate_from_text / generate_from_image / load_lora / unload_lora` 接口。新增架构只需写一个新适配器。
- **配置中枢**：`config.py` 集中放 `MODEL_REGISTRY`、`STYLE_PRESETS`、`RATIO_MAPPINGS`（SDXL 64 对齐 / Flux 16 对齐）、`LICENSE_INFO`、`LORA_REGISTRY`，是各层引用的纯数据文件。

### 视频生成链路（MiniMax H3）

视频节点走的是**另一条独立链路**：前端浏览器直连本地 ComfyUI（默认 `http://localhost:8188`），而非 NodeFlow 后端。前端按官方 MiniMax H3 T2V 工作流拼出 API 格式图结构，提交到 ComfyUI 的 `/prompt` 接口，再轮询 `/history/{id}` 直到出片。

工作流节点：`UNETLoader + CLIPLoader + 双VAE(视频/音频) + MiniMaxH3ImageToVideo + BasicGuider + SamplerCustomAdvanced + 双VAEDecode + CreateVideo + SaveVideo`。加速 = 在 UNET 与 Guider 之间插入 `PatchSageAttentionKJ`（Sage Attention，约 2x 提速）。

---

## 三、开发历程时间线

这段项目从零开始，经历了「产品定型 → 前端画布 → 后端引擎 → bug 修复 → GPU 实例部署 → 参赛交付」几个阶段。核心脉络如下。

### 阶段 1：需求与产品定位

项目起点是做一个「平衡开放性与低门槛」的 AI 生图工具。分析发现现有工具两极分化：ComfyUI 门槛高但可控性强，Liblib/即梦等平台门槛低但被模板锁定。NodeFlow 选择中间路线：**以无限画布为创作起点**，兼顾低门槛与高可控。

### 阶段 2：前端无限画布 + 节点系统

前端用 React 18 + Excalidraw 实现无限画布，上面叠加了节点式创作系统。节点支持右键与双击两种添加入口，用统一节点菜单管理（这是后来反复修复的重点之一）。

技术要点：为了让画布成为真正的创作空间，写了一套 `canvas-runtime.js` 处理节点渲染、连线拖拽、小地图（minimap）预览。

### 阶段 3：后端多模型引擎

后端用 FastAPI 实现，核心是 ModelManager 单例 + 适配器模式，支持多模型热切换与 LoRA。为了适配 AMD GPU，用 `hf_hub_download` + `from_single_file()` 加载 SDXL-Lightning（绕开子文件夹路径问题），并用 PyTorch ROCm wheels 跑推理。

### 阶段 4：bug 修复攻坚（miniMap 是重灾区）

这是整个项目调试耗时最长的部分。小地图（minimap）反复出现多个问题，逐一攻克：

- **视口框盖住整个小图**：当节点很少时，视口指示框铺满整个小地图。修复：实现 `getWorldBounds()`，保证画布有最小尺寸（视口 2.5 倍或 300px），让视口框呈现为正常的小方框。
- **菜单打开即关闭**：修复：加 350ms 的点击抑制窗口，用 `window.__nfSuppressClick` 时间戳解决。
- **连线拖拽失效**：统一了连接处理逻辑。
- **节点大小不随缩放变化 + 刷新率低**：更新世界边界计算，并优化刷新机制。
- **浏览器缓存旧脚本**：给 `index.html` 里的脚本 src 加版本号（`?v=n`），每次改动递增，强制浏览器加载新代码。

### 阶段 5：GPU 实例部署与 ComfyUI 集成

部署到 AMD Radeon GPU 实例（W7900 / ROCm）经历了大量环境问题，详见「部署踩坑实录」一节。

### 阶段 6：参赛交付

产出了完整交付物：源码仓库、12 页演示文稿（nodeflow-deck）、Demo 视频、参赛材料、ChatCut 制作指令。全部推送到 GitHub。

---

## 四、部署踩坑实录（AMD Radeon + ROCm）

这是全网几乎没有现成中文教程的部分，踩坑价值极高，全部是靠排查和试错解决的。

### 1. 环境变量与镜像

实例无法直连 `huggingface.co` 和 `github.com`，必须：

```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/persistent/hf_cache
export TRANSFORMERS_CACHE=/persistent/hf_cache
export DIFFUSERS_CACHE=/persistent/hf_cache
```

下载 GitHub release 文件时因自签名证书失败，需加 `--no-check-certificate`。

### 2. 持久化存储规划

`/workspace` 是临时盘，实例重置会清空。所有关键数据必须放 `/persistent`：

| 路径 | 用途 |
|------|------|
| `/persistent/venv` | Python 虚拟环境（避免重下 4GB+ 的 ROCm PyTorch） |
| `/persistent/hf_cache` | HuggingFace 模型缓存 |
| `/persistent/loras` | 下载的 LoRA 文件 |
| `/persistent/ComfyUI` | ComfyUI 本体 + 模型 |

### 3. torchaudio 的 CUDA 依赖坑

ComfyUI 导入 `torchaudio` 时报 `OSError: libcudart.so.13: cannot open shared object file`。根因是装的是 CUDA 版 torchaudio，而 AMD 环境没有 CUDA 库。解决：卸载 CUDA 版，装 ROCm 版：

```bash
pip install torchaudio==2.5.1+rocm6.2
```

### 4. huggingface-cli 弃用

`huggingface-cli download` 报"deprecated and no longer works"，改用 `hf download`：

```bash
hf download <repo> <file> --local-dir <dir>
```

### 5. ComfyUI 端口冲突

启动时报 `Port 8188 is already in use`，因为之前有个旧进程一直占着端口。排查命令：

```bash
ss -tlnp | grep 8188        # 看谁占用端口
ps aux | grep main.py       # 看所有相关进程
```

日志文件是 `nohup` 重定向的，要注意区分「启动失败退出的进程」日志和「真正在跑的进程」日志。

### 6. Sage Attention 加速节点缺失

MiniMax H3 视频工作流默认插入 `PatchSageAttentionKJ`（来自 KJNodes 的 Sage Attention 加速），但该节点在实例上未注册，导致工作流校验失败、视频生成失败。排查：

```bash
# 检查节点类是否存在
curl -s http://localhost:8188/object_info/PatchSageAttentionKJ
```

修复：前端提交前先探测该节点是否可用，不可用则自动降级为不加速，避免整条工作流失效。

### 7. 公网访问与隧道

实例用 `rc-tunnel` 暴露公网地址。隧道状态异常时（`not_found: this Pod has no active tunnel`），重启隧道：

```bash
rc-tunnel stop
rc-tunnel expose --port 8000
```

---

## 五、可复用的工程方法论

这些是跨项目通用的经验，不只是针对 NodeFlow。

### 1. 前端「伪后端」分层设计

前端 mock-api 层把所有 API 封装成统一接口，`USE_REAL_API` 开关控制走真实后端还是 mock。好处：前端开发不依赖后端，本地无 GPU 时也能跑；部署时一键切换。所有 16 个端点都实现了 mock 与真实两套实现。

### 2. 浏览器缓存控制

改前端静态文件后，务必递增脚本 src 的版本号（`?v=n`），否则浏览器会加载旧代码，导致「改了没用」的假象。这是非常常见但容易被忽略的坑。

### 3. 依赖隔离与增量修复

ComfyUI 和 NodeFlow 后端共用 `/persistent/venv` 时，依赖版本冲突容易连锁报错。排查时遵循「先看完整报错链的根因，再动手」，例如何 on `libcudart` 的报错，根因其实是 torchaudio 装错了平台版本，而不是表面上缺 CUDA 库。

### 4. 失败降级优先于阻断

视频加速节点不可用时，选择「自动降级为不加速」而不是报错终止。这种「feature 优雅降级」的思路，让核心功能在任何环境下都能先用起来。

### 5. 一键部署脚本化

写了 `start.sh`（一键部署）和 `setup_comfyui.sh`（一键装 ComfyUI + 模型），把可复现的环境搭建固化成脚本，避免每次手动敲命令踩坑。

---

## 六、参赛交付物清单

| 交付物 | 说明 |
|--------|------|
| 项目源码仓库 | 前后端 + 部署脚本，推送到 GitHub |
| `NodeFlow-README.md` | 完整项目文档（含 Demo 视频链接） |
| `nodeflow-deck/` | 12 页演示文稿（HTML，靛蓝瓷主题） |
| `NodeFlow_Demo.mp4` | 最终 Demo 视频（3-5 分钟，1080p） |
| `demo-video-guide.md` | Demo 视频分镜脚本 |
| `ChatCut-demo-instructions.md` | 给 ChatCut 的视频制作指令 |
| `NodeFlow_UI_需求文档_TreeDesign.md` | UI 需求规格 |
| `参赛材料.md` | 参赛文档 |
| `push_to_github.sh` | 一键推送 GitHub 脚本 |

---

## 七、收获与反思

这段经历最大的收获不是某个具体功能，而是「在真实硬件上限期交付」的完整训练。

- **技术深度来自解决真实问题**：minimap 的 bug 反复出现，逼着我真正理解了视口坐标、世界边界、缩放映射这些底层几何，而不是会用 API 就完事。
- **AMD ROCm 生态没有想象中难**：`libcudart` 报错看起来很吓人，但本质只是平台版本装错了。ROCm wheels 装对后，PyTorch 代码几乎零改动就能跑通，说明 AMD 生态的工程化已经相当成熟。
- **部署是最大的隐形工作量**：写功能可能只占一半时间，另一半全耗在环境、依赖、端口、缓存、隧道这些"脏活"上。把环境搭建脚本化，是保护自己不被重复踩坑的关键。
- **降级设计让系统更健壮**：加速节点缺失时不阻断，而是降级——这种"核心功能永远可用"的哲学，在演示和交付场景尤其重要。
- **AI 协作的边界**：这款工具大量代码由 AI 辅助完成，但每一处 bug 的定位、每一个架构决策的判断，都需要人来做最终把关。AI 是放大器，不是替代品。

---

## 八、仓库地址

- GitHub：`https://github.com/Eason-made-it/Radeon-hackathon-2026-07`
- 项目文档：`NodeFlow-README.md`
- 部署脚本：`start.sh` / `setup_comfyui.sh`

---

*这篇文档沉淀了 NodeFlow 从创意到交付的完整过程，也凝结了 AMD ROCm 部署、前端画布、多模型引擎等可复用的硬核经验。*