# LifePreview 中文复现说明

LifePreview 是参加 Track 1 的多模态内容创作工具，运行于 AMD Radeon `gfx1100` GPU 和 ROCm 7.2.1。用户在英文网页中搜索传记或书籍，读取资料，生成 AI 剧本，准备一张 FLUX 人物参考图，并提交约三秒的 MiniMax H3 视频任务。

> 截止时间前冻结的验收口径是 **GPU Runtime Proof（云端真实提交版）**：真实请求必须恰好一次到达 H3，并且 AMD GPU 已经开始执行。今天不把等待最终 MP4 作为阻断条件。预生成展示视频与当前生成任务严格分开，不能冒充当前任务结果。

英文主文档：[README.md](README.md)

## 比赛流程

1. 用户点击一次 **Start generation**，英文前端只发送一次 `POST /api/video-jobs`。
2. Search/Reader 搜索并读取对应书籍资料。
3. Research Worker 生成非空 AI 剧本并保存摘要。
4. 当前任务绑定一张提前通过正式 FLUX 后端生成的人物参考图，同时保存 request ID、提示词、seed、Workflow SHA 和图片 SHA。
5. H3 Compiler 构造 3.0 秒、73 帧、24fps、原生音频、无字幕的请求。
6. Submitter 只提交一次，并记录 prompt/queue ID、job ID、attempt、submission nonce、Workflow SHA 和时间戳。
7. ComfyUI 执行同一个 prompt，`rocm-smi`证明 AMD GPU 已开始工作。

## 白名单源码启动集

第一版源码不直接复制整个开发工作树，而是严格按照[submission-source-whitelist.txt](submission-source-whitelist.txt)组装。

保留七个运行单元：

- `consumer_web`：英文 React/Vite 前端；
- `shidu_api`：API、任务状态、单图阶段、H3 Submitter 和比赛 Worker；
- `shidu_provider_mcp`：Search/Reader Provider；
- `creative_hub`：PostgreSQL、研究/剧本、资产血缘和 H3 Compiler；
- `shared_contracts`：跨组件合同；
- `drama_factory`：FLUX 和 MiniMax H3/ComfyUI 运行适配；
- `atomic_runtime`、`deploy/amd`和`ops/amd`：能力注册、AMD部署和启动门禁。

明确排除：

- 模型权重、ComfyUI安装目录、生成视频、图片、缓存、日志、数据库和本地输出；
- API Key、Cookie、SSH私钥、真实`.env`、PostgreSQL密码和签名密钥；
- 旧视频分析、通用视频/短剧模板、长片、TTS、字幕、口型和无关生产加固测试；
- Agent内部交接文件和私人工作树。

## 环境

- Linux AMD Radeon云端，`gfx1100`级GPU，约48GiB显存；
- ROCm 7.2.1和兼容的PyTorch/ComfyUI；
- Python 3.12；
- Node.js 22与npm；
- PostgreSQL；
- GPU阶段的ComfyUI地址为`127.0.0.1:18188`。

仓库不包含模型权重。模型文件名、大小和SHA位于`source/deploy/amd/model-manifests/`，必须从合法来源另行获取并校验。

## 安装与启动

把白名单源码复制到`LifePreview/source`后执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
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

配置文件只能从公开模板复制，秘密写到仓库外的受限文件中：

```bash
cp source/deploy/amd/.env.example /persistent/douyin-amd/config/amd.env
chmod 600 /persistent/douyin-amd/config/amd.env

cd source/creative_hub
creative-hub-migrate
creative-orchestration-migrate

cd ../..
bash source/ops/amd/start-radeon-cloud.sh /persistent/douyin-amd/config/amd.env
```

该脚本启动Search/Reader、API、Research Worker、Vertical Slice Worker和网页，但会保持GPU/ComfyUI关闭，直到用户本人点击。

## 今日复现证据

点击前通过正式后端生成一张FLUX人物图，保存完整血缘，随后退出FLUX并通过内存/磁盘门禁。用户点击后保留以下证据：

- 浏览器只有一次`POST /api/video-jobs`；
- Search/Reader真实结果；
- AI剧本SHA；
- 预备人物图片SHA；
- H3 DTO和唯一提交记录；
- prompt/queue ID；
- ComfyUI当前任务；
- `rocm-smi`显存或GPU利用率变化。

今天不等待MP4完成，不要求视频CAS、签名URL、播放下载和ffprobe验收。这些属于赛后完整闭环。

## 预生成展示视频

部署页面可以单独显示 **Previously generated on AMD**：乔布斯两条、苏东坡一条、Frida Kahlo一条。MP4属于云端部署资产，不提交到Git；只在证据清单中记录SHA。

## 比赛提交

个人Fork官方仓库后，把`LifePreview`目录提交并向官方`main`发PR。标题：

```text
Track 1, <Luma登记的团队名或本人法定姓名>, LifePreview
```

正式材料、项目说明和PR描述必须使用英文；中文README仅作为辅助说明。
