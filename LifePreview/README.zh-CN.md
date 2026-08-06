# LifePreview

LifePreview 是面向 Track 1 的多模态内容创作工具，已适配 AMD Radeon `gfx1100` GPU 与 ROCm 7.2.1。用户可以在英文网页中搜索传记或书籍、核对有来源依据的资料、生成简短的 AI 剧本、准备一张 FLUX 人物参考图，并提交一个 3 秒的 MiniMax H3 视频生成任务。

> 提交状态：本目录仍在组装为可复现的比赛快照。截止时间前冻结的验收口径是 **GPU Runtime Proof（GPU 运行证明）**：实时请求必须恰好一次到达 H3，并且 AMD GPU 必须开始执行该请求。截止验收不要求等待最终 MP4 生成完成。历史生成视频会独立展示，绝不会被描述为当前任务的生成结果。

English documentation: [README.md](README.md)

## 部署与验证状态

项目已在 NVIDIA 环境下完成部署。考虑到本次比赛云端服务器的内存与算力限制，部分演示数据和媒体素材已提前在本地生成。项目已在 AMD Radeon/ROCm 环境完成最小端到端闭环和针对性冒烟测试，用于确认核心服务能够启动、主要请求链路能够贯通，并且 GPU 执行路径能够工作。预生成输入和历史展示输出会与 AMD 实时执行证据分开标注。该验证范围并不表示所有数据、媒体资产或生产功能都已在比赛服务器上重新生成或完成全量验证。

## 提交材料

- [英文项目说明书](docs/LifePreview_Project_Profile_EN.pdf)：共 29 页，介绍产品背景、目标用户、原型与演示流程、端到端生成管线、AMD Radeon/ROCm 验证和当前成果。可编辑源文件见 [DOCX 版本](docs/LifePreview_Project_Profile_EN.docx)。
- [英文项目演示文稿](deck/LifePreview_Project_Deck_EN.pdf)：共 10 页，面向 Track 1 评审，介绍用户问题、产品模式、当前成果、核心创新、可复用的 AI 生成管线、AMD Radeon/ROCm 计算基础、产品化路线图和项目愿景。PDF 已保留演示文稿版式，可直接在 GitHub 中审阅。
- [当前演示视频](demo/LifePreview-demo-under-100MB.mp4)：4 分 47 秒、92.1 MB 的压缩 MP4。它属于展示材料，会与 AMD 实时运行证据分开标注。
- [AMD Radeon / ROCm 证据索引](evidence/AMD_ROCm_Evidence.md)：记录已报告的最小闭环和冒烟测试证据、其适用范围，以及提交前仍需补齐的最终实时运行证据。
- [制品校验和](evidence/SHA256SUMS.txt)：本目录内演示视频、项目说明书和演示文稿的 SHA-256 值。

## 许可证与第三方声明

LifePreview 自主开发的软件采用 [PolyForm Noncommercial License 1.0.0](LICENSE) 授权。第三方软件、模型权重和媒体素材仍分别受其自身条款约束，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。最终源码快照须保留依赖与模型的许可证记录。

## 比赛演示流程

1. 用户点击 **Start generation** 后，LifePreview 英文界面只发送一次 `POST /api/video-jobs`。
2. Search/Reader 定位用户选择的书籍并返回来源资料。
3. Research Worker 生成非空的 AI 剧本并记录其摘要。
4. 当前任务绑定一张已准备好的 FLUX 人物参考图，并记录 request ID、提示词、seed、工作流摘要和图片摘要。
5. H3 Compiler 构建请求：时长 3.0 秒、73 帧、24 fps、原生音频、无字幕。
6. Submitter 只发送一次 H3 请求，并记录 prompt/queue ID、job ID、attempt、submission nonce、工作流摘要和时间戳。
7. ComfyUI 开始执行同一个 prompt，`rocm-smi` 用于确认 AMD GPU 已进入工作状态。

## 可复现源码范围

首版源码包通过明确的白名单组装，不会直接复制整个开发工作树。白名单见 [submission-source-whitelist.txt](submission-source-whitelist.txt)。

包含的运行单元：

- `consumer_web`：英文 React/Vite 用户界面。
- `shidu_api`：公共 API、任务状态投影、提示词参考图阶段、H3 Submitter 和比赛 Worker。
- `shidu_provider_mcp`：无需密钥的 Search/Reader Provider 边界。
- `creative_hub`：PostgreSQL 记录、研究与剧本编排、资产血缘和 H3 Compiler。
- `shared_contracts`：不可变的跨组件契约。
- `drama_factory`：FLUX 参考图生成及 MiniMax H3/ComfyUI 运行时适配器。
- `atomic_runtime`：编排层使用的能力注册机制。
- `deploy/amd` 与 `ops/amd`：AMD Radeon 云端配置、预检、启动、状态检查和 GPU 门禁。

明确排除：

- 模型权重、ComfyUI 安装目录、缓存、生成图片与视频、运行时数据库、日志和本地输出；
- API Key、Cookie、SSH 私钥、真实 `.env` 文件、PostgreSQL 密码、签名密钥及其他凭据；
- 旧版视频分析、通用视频或短剧模板、长片组装、TTS、字幕、口型同步和无关的生产加固测试；
- Agent 内部交接文件和私人开发工作树。

## 目标环境

- Linux AMD Radeon 云端实例，`gfx1100` 级 GPU，约 48 GiB 显存。
- ROCm 7.2.1，以及兼容 ROCm 的 PyTorch/ComfyUI 环境。
- Python 3.12，用于应用服务。
- Node.js 22 与 npm，用于 Web 应用。
- PostgreSQL，用于 Creative Hub 和任务状态。
- 启用 GPU 阶段后，ComfyUI 监听 `127.0.0.1:18188`。

仓库不包含模型权重。固定的文件名、大小和 SHA-256 值记录在 `source/deploy/amd/model-manifests/` 中。请从获得许可的分发渠道下载每个模型，并在使用前完成校验。

## 安装

将白名单源码复制到 `LifePreview/source` 后执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e source/atomic_runtime
python -m pip install -e source/shared_contracts
python -m pip install -e source/drama_factory
python -m pip install -e source/creative_hub
python -m pip install -e source/shidu_provider_mcp
python -m pip install -e source/shidu_api

cd source/consumer_web
npm ci
npm run build
```

复制公开配置模板，并把密钥写入仓库外的受限文件：

```bash
cp source/deploy/amd/.env.example /persistent/douyin-amd/config/amd.env
chmod 600 /persistent/douyin-amd/config/amd.env
```

不要将密钥值提交到 Git。公开模板通过文件引用使用 `/persistent/douyin-amd/secrets` 下的密钥。

## 数据库与 CPU 服务

先创建 `amd.env` 中引用的两个 PostgreSQL 数据库及其凭据，然后执行：

```bash
cd source/creative_hub
creative-hub-migrate
creative-orchestration-migrate

cd ../..
bash source/ops/amd/start-radeon-cloud.sh /persistent/douyin-amd/config/amd.env
```

启动脚本会执行预检，并启动 Search/Reader、API、Research Worker、Vertical Slice Worker 和 Web 应用；在用户操作前，ComfyUI/GPU 会保持关闭。

常用检查命令：

```bash
bash source/ops/amd/status-radeon-cloud.sh /persistent/douyin-amd/config/amd.env
curl -fsS http://127.0.0.1:18082/health/ready
curl -fsS http://127.0.0.1:14289/
```

## GPU 运行证明

在用户最终点击前：

1. 通过正式 FLUX 后端生成一张人物参考图。
2. 保存其 request ID、提示词、seed、工作流 SHA-256 和图片 SHA-256。
3. 停止 FLUX/ComfyUI，并确认显存和磁盘预检门禁通过。
4. 不得提前提交 H3 请求。

随后由用户点击一次 **Start generation**。证据应覆盖：浏览器唯一一次 POST、Search/Reader 结果、剧本摘要、预备图片摘要、H3 DTO、prompt/queue ID、ComfyUI 运行条目和 `rocm-smi` 活动。

```bash
bash source/ops/amd/gpu-go-no-go.sh /persistent/douyin-amd/config/amd.env
rocm-smi
```

## 聚焦验证

首版启动集只包含与比赛流程直接相关的测试：

```bash
python -m pytest \
  source/shared_contracts/tests/test_h3_contracts.py \
  source/drama_factory/tests/test_h3_compilation.py \
  source/creative_hub/tests/test_h3_workflow_compiler.py \
  source/shidu_api/tests/test_competition_prompt_reference.py \
  source/shidu_api/tests/test_competition_runtime_wiring.py \
  source/shidu_api/tests/test_competition_vertical_slice_worker.py -q

cd source/consumer_web
npm test -- --run
npm run test:amd-gateway
```

## 历史生成作品展示

部署后的演示页面可以提供独立的 **Previously generated on AMD** 画廊，包含两段 Steve Jobs 视频、一段苏东坡视频和一段 Frida Kahlo 视频。这些大体积 MP4 属于部署资产，不提交到 Git；其校验和应记录在证据清单中。

## 比赛提交

官方仓库为 [AMD-DEV-CONTEST/Radeon-hackathon-2026-07](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)。请从个人 Fork 提交 `LifePreview` 目录，并向官方 `main` 分支发起 Pull Request。

PR 标题格式：

```text
Track 1, <Luma 登记的团队名称或本人法定姓名>, LifePreview
```

所有正式提交材料和 Pull Request 描述必须使用英文；本中文 README 仅用于辅助阅读与复现。
