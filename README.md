# 独立游戏 AI 资产全链路生成平台（基于 ComfyUI）

> 面向独立游戏开发者/小型工作室的多模态资产生成平台：
> 一套文本设定 → 概念原画 → 深度图 → 3D 材质 → 背景音乐 → 环境音效 → 序列帧图集。
> 以 ComfyUI 为工作流引擎，前端为可交互的流程网站；
> 每完成一个阶段就提交并推送到 GitHub（规范见「Git 与 GitHub 协作规范」）。

---

## 一、场景与目标

痛点：独立游戏团队在美术、音效、音乐上的外包成本占研发大头，
且多方外包极难保证风格统一。

### 1. 统一设定的多模态资产流

开发者输入一段文本设定（如“废土风格酒吧”），工具依次生成：

```text
文本设定（废土风格酒吧）
  │
  ├─ W1 概念原画（图像）
  │     └─（人工确认后）── W2 深度图 ── W3 3D 贴图材质
  │
  ├─ W4 背景音乐（带金属敲击声的暗黑氛围电子乐）
  └─ W5 NPC 环境音效（玻璃杯碰撞、含糊交谈声）
```

### 2. 序列帧生成

输入角色动作指令（如“跑步”“攻击”），工具基于角色设定图，
直接输出可用于游戏引擎的 2D 动作序列帧图集（PNG 图集 + JSON 配置）。

---

## 二、总体架构

```text
┌─────────────────────────────────────────────────────────┐
│  浏览器（前端网站）                                      │
│  - 设定输入 / 任务提交 / 结果预览 / 资产下载 / 进度       │
└──────────────┬──────────────────────────────────────────┘
               │ HTTP / WebSocket
┌──────────────▼──────────────────────────────────────────┐
│  Web 后端（FastAPI / Node.js）                          │
│  - 任务队列、SQLite 任务记录、权限/Token                │
│  - 调用 ComfyUI HTTP API（/prompt、/history、/view）    │
│  - WebSocket 转发执行进度                                 │
└──────────────┬──────────────────────────────────────────┘
               │ HTTP（本机或内网）
┌──────────────▼──────────────────────────────────────────┐
│  ComfyUI（GPU 工作流引擎）                              │
│  - workflows/*.json：W1~W6 各流程的 API 格式定义        │
│  - 模型：SDXL、MiDaS/Depth Anything、ControlNet、       │
│    音频生成节点等                                        │
│  - 输出：ComfyUI/output/（后同步到 assets/）            │
└─────────────────────────────────────────────────────────┘
```

两种「网站」形态，可按团队能力选择：

| 形态 | 说明 | 适用 |
| --- | --- | --- |
| A. 轻量版 | 直接用 ComfyUI 自带 WebUI + 工作流文件，开发者手动跑流程 | 单人 / 验证阶段 |
| B. 流程网站 | 自建前端 + 后端，把 W1~W6 封装成「填写设定 → 点按钮 → 看进度 → 下载资产」的完整产品 | 小团队 / 对外交付 |

本项目按形态 B 规划，但每阶段成果在形态 A 下也可用。

---

## 三、ComfyUI 工作流设计（W1~W6）

> ComfyUI 工作流有 UI 格式与 API 格式两种 JSON。网站后端必须使用 **API 格式**
> （Workflow → Export (API)），这样 `/prompt` 接口才能直接提交。
> 所有工作流文件统一放在 `workflows/` 目录，并在本表登记。

| 编号 | 名称 | 输入 | 输出 | 关键节点 / 模型 |
| --- | --- | --- | --- | --- |
| W1 | 概念原画 | 文本设定 | 高清概念图 | SDXL 基座 + 风格 LoRA + KSampler + 高清修复（Latent Upscale / Ultimate SD Upscale）；固定 seed 保证可复现 |
| W2 | 深度图 | W1 概念图 | 灰度深度图 | MiDaS（dpt_hybrid，controlnet_aux 预处理器）；可选升级 Depth Anything V2 |
| W3 | 3D 贴图材质 | W2 深度图 | normal / height / roughness / metalness 贴图集 | 自定义节点 PBRFromDepth：深度图→法线+高度+粗糙度+金属度（可调参数） |
| W4 | 背景音乐 | 音乐风格描述 | MP3（MusicGen small） | 自定义节点 MusicGenNode（transformers MusicGen），可调 prompt/时长/seed |
| W5 | 环境音效 | 音效类型 | MP3 循环/触发音效 | 自定义节点 ProceduralSFX：玻璃杯碰撞 / 含糊交谈 / 酒吧环境音（程序化合成） |
| W6 | 序列帧图集 | 角色设定图 + 动作指令 | PNG 图集 + JSON 配置（帧尺寸/网格/时长） | 自定义节点 ActionPose 生成动作骨架帧 → ControlNet OpenPose (SDXL) 逐帧 img2img → ImageGrid 拼图；JSON 由后端生成 |
| W7 | 2D 转 3D 角色模型 | 角色设定图 | GLB/OBJ 3D 模型 | ComfyUI-Flowty-TripoSR（TripoSR 单图重建）；安装：`scripts/setup_3d.sh` + `scripts/download_3d_model.sh` |

### 各工作流的工程要点

1. **风格统一**：W1 固定风格 LoRA 与 seed；W2~W7 全部以角色设定图为条件输入，避免「多方外包风格漂移」的问题。
2. **逐步确认**：W1 → W3、W1 → W4/W5 之间设置人工确认节点（对应需求中「确认后生成 3D 贴图」）。
3. **可复现**：每个任务记录完整参数（prompt、seed、模型名、LoRA），输出 JSON 清单存档。
4. **序列帧一致性**：逐帧生成时用「角色设定图 + OpenPose 骨骼 + 固定 seed + 同一 LoRA」约束；帧间差异过大时改用 AnimateDiff 抽帧路线。
5. **音乐/音效兜底**：本地音频模型缺失时，后端封装外部 API（音乐、TTS），前端体验不变。

---

## 四、网站功能设计

### 页面

- **首页**：两条入口（多模态资产流 / 序列帧生成）
- **流程页**：左侧填设定，中间看步骤进度，右侧预览当前结果
- **资产库**：按项目归档的历史资产，支持下载与参数回看
- **任务列表**：队列状态（排队 / 执行中 / 失败 / 完成）

### 核心交互

1. 用户输入文本设定（可上传参考图）
2. 后端创建任务，调用 ComfyUI `/prompt` 提交对应工作流 JSON
3. 前端通过 WebSocket 实时显示 ComfyUI 执行进度
4. 每步完成后预览；用户点击「确认，进入下一步」才触发下游工作流
5. 最终资产打包下载；记录存 SQLite

### 后端 API（草案）

```text
POST /api/projects         创建项目
POST /api/jobs             提交生成任务（指定 workflow + 参数）
GET  /api/jobs/{id}        查询任务状态
GET  /api/jobs/{id}/result 获取生成结果（代理 /view）
POST /api/jobs/{id}/approve   确认当前步骤，触发下一步
GET  /api/assets            资产列表 / 下载
```

---

## 五、部署方案

### 推荐：docker-compose

```text
comfyui   （GPU 服务，映射 ComfyUI 模型目录）
web       （前端静态资源 + 后端 API）
nginx     （统一入口、HTTPS、静态缓存）
```

- ComfyUI 与网站可部署在同一台 GPU 服务器（AutoDL / 阿里云 P100/A10 起）
- 模型文件（safetensors/ckpt）只放服务器磁盘，**绝不进入 git**
- 局域网演示时可不开公网，直接访问 8188 端口

### 模型与第三方节点清单（部署时安装）

- 基础出图：SDXL 基座 + 风格 LoRA（模型清单见 `docs/models.md`）
- 深度：MiDaS（comfyui_controlnet_aux）；可选 Depth Anything V2
- 姿态：ControlNet OpenPose（P4 序列帧用）
- 音频：ComfyUI-MusicGen、AudioScheduler（P3）
- 工具：ComfyUI-Essentials（ImageGrid 等）

> 第三方节点与模型随 ComfyUI 版本迭代，具体版本以安装时官方仓库 README 为准。

---

## 六、目录结构

```text
.
├── README.md               # 本文档
├── .gitignore              # 排除模型、输出、环境等
├── docker-compose.yml      # P5 部署（待建）
├── scripts/
│   ├── setup_comfyui.sh    # ComfyUI 一键安装（克隆+依赖+自定义节点）
│   └── download_models.sh  # 模型下载（hf-mirror 国内镜像，断点续传）
├── docs/
│   └── models.md           # 模型清单（含后续阶段规划）
├── deploy/
│   ├── docker-compose.yml   # web + nginx 编排
│   ├── nginx.conf           # 反向代理 + HTTPS 示例
│   ├── web.Dockerfile
│   └── systemd/             # 宿主机开机自启单元
├── workflows/              # ComfyUI 工作流 JSON（API 格式）+ 说明
│   ├── W1_concept.json     # 概念原画
│   ├── W2_depth.json       # 深度图
│   ├── W3_material.json    # 3D 材质
│   ├── W4_music.json       # 背景音乐
│   ├── W5_sfx.json         # 环境音效
│   └── W6_sprite.json      # 序列帧图集
├── server/                 # 后端（FastAPI 草案，P2 起实现）
├── web/                    # 前端（P2 起实现）
├── assets/                 # 上传素材与生成结果（gitignore）
└── ComfyUI/                # 本地运行的 ComfyUI（gitignore，不提交）
```

---

## 七、开发路线图（每阶段一次 GitHub 提交）

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| P0 | 仓库初始化 + 本文档 | GitHub 可见完整方案 |
| P1 | 本地 ComfyUI 安装，跑通 W1、W2 | 文本→概念图→深度图可用 |
| P2 ✅ | 后端 API + 前端页面（任务提交/进度/预览） | 网页能提交 W1/W2 任务并取回结果 |
| P3 ✅ | W3 材质 + W4 音乐 + W5 音效接入 | 三类资产可从网页生成下载 |
| P4 ✅ | W6 序列帧图集 | 跑步/攻击动作图集 + JSON 可下载 |
| P5 ✅ | 部署上线 + 文档完善 | 部署文件就绪（docker-compose/nginx/systemd），公网可访问 |

---

## 八、Git 与 GitHub 协作规范

### 1. 每完成一部分就提交

```bash
git add -A
git commit -m "P2: 完成后端任务队列与前端预览"
git push origin main
```

### 2. 关于「覆盖原有的」

- 普通 `git push` 就会把**最新文件内容**更新到 GitHub（默认分支），历史提交仍然保留，这是推荐做法；
- 如果你确实要让远程仓库完全等于本地（比如重做历史、清掉旧提交），才需要强制推送：

  ```bash
  git push --force origin main
  ```

  ⚠️ 强制推送会丢弃远程已有的提交，**只在单人维护时使用**；多人协作时不要用。
- 建议：用「阶段提交 + 普通推送」代替「覆盖」，每次 P0~P5 完成一个里程碑，GitHub 上自然就是最新版，还能回滚。

### 3. 提交规则

- 大模型文件（`*.safetensors`、`*.ckpt`、`*.pth`）**禁止提交**，由 `.gitignore` 排除；
- 工作流 JSON 每次修改后都提交，方便回滚与协作；
- commit message 用「阶段 + 做了什么」的格式，如 `P3: 接入音乐与音效工作流`。

### 4. 首次上传到 GitHub

```bash
# 在 GitHub 网页新建空仓库（不要勾选 README 初始化），然后：
git remote add origin git@github.com:<你的用户名>/<仓库名>.git
git branch -M main
git push -u origin main
```

### 5. 可选：GitHub Pages 展示

如果希望网站首页/方案说明可以被公开访问，可以把 `web/` 的静态部分发布到 GitHub Pages，后端与 ComfyUI 仍部署在 GPU 服务器。

---

## 九、快速开始（P1 起）

```bash
# 1. 安装 ComfyUI（自动创建虚拟环境、安装依赖与自定义节点）
bash scripts/setup_comfyui.sh

# 2. 下载 P1 模型（SDXL 基座 + VAE + MiDaS，约 7.3GB）
bash scripts/download_models.sh

# 3. 启动 ComfyUI
cd ComfyUI && .venv/bin/python main.py --listen 0.0.0.0 --port 8188

# 4. 浏览器打开 http://localhost:8188，导入 workflows/W1_concept.json 开始验证
```

> 各阶段详细操作会在对应阶段补充到本文档。

> P1 环境说明：安装脚本自动检测 GPU（NVIDIA→CUDA / AMD→ROCm / 无 GPU→CPU），并固定
> torch/torchvision/torchaudio 的配套版本（2.11.0），避免 ABI 不兼容导致启动失败。

### P2：启动网页（当前进度）

```bash
# 1. 确保 ComfyUI 已在 8188 端口运行
# 2. 启动后端（首次需先 pip install -r server/requirements.txt）
bash server/run.sh

# 3. 浏览器打开 http://localhost:8000
#    W1：填设定文本 → 提交 → 预览/下载概念原画
#    W2：上传概念图 → 生成深度图
```

### P3：音乐/音效/材质（当前进度）

- W3 材质、W4 音乐、W5 音效已接入网页（`http://localhost:8000`）
- MusicGen small 模型已下载到 `ComfyUI/models/musicgen/`（重新部署用 `scripts/download_musicgen.sh`）
- 自定义节点源码在 `nodes/indie_studio_nodes/`（PBRFromDepth / MusicGenNode / ProceduralSFX）

### P4：序列帧图集（当前进度）

- W6 已接入网页：上传角色设定图 → 选动作（run/attack）→ 生成 8 帧图集 + JSON 配置
- ControlNet OpenPose SDXL 模型已下载（`ComfyUI/models/controlnet/OpenPoseXL2.safetensors`）
- JSON 配置接口：`GET /api/jobs/{id}/sprite-config`（帧尺寸/网格/每帧时长）

## 十、部署上线（P5）

### 公网访问需要域名吗？

**不需要。** 服务器有公网 IP 就能访问：`http://公网IP:8000`（直连）或
`http://公网IP`（经 nginx 80 端口）。域名只是可选优化（好记 + HTTPS）；
注意国内服务器绑域名做网站需要 ICP 备案，纯 IP 访问不涉及。

### 方式一：宿主机一键部署（推荐，GPU 直通最省事）

```bash
bash scripts/deploy_host.sh
# 需要开机自启时（改好路径后）：
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now comfyui indiegen-web
```

### 方式二：Docker（web + nginx；ComfyUI 仍在宿主机直通 GPU）

```bash
cd deploy
docker compose up -d --build
```

### 防火墙

```bash
sudo ufw allow 80/tcp        # 推荐：只暴露 nginx 这一个端口
# sudo ufw allow 8000/tcp    # 若想直接暴露网页端口
# 8188（ComfyUI）保持仅本机访问，不要对公网开放
```

### 安全建议

- 只暴露 80/443；ComfyUI 的 8188 端口保持仅本机
- 公网可直接访问时，开启 nginx 基本认证：
  `htpasswd -c deploy/htpasswd admin`，然后取消 `deploy/nginx.conf` 中
  `auth_basic` 两行注释（密码文件不入 git）
- 后续版本可加任务额度/API Token

### 域名 + HTTPS（可选升级）

1. 在域名服务商添加 A 记录 → 服务器公网 IP
2. `sudo certbot --nginx -d your-domain.com`（自动配证书）
3. 放开 `deploy/nginx.conf` 中 443 server 注释并填写证书路径
4. 重启 nginx：`docker compose restart nginx` 或 `sudo systemctl reload nginx`

## 十一、批次与文件命名

- 提交任务时可填「批次名称」（如：废土酒吧）；留空则自动按时间命名
- 同一批次的输出自动归档到 `ComfyUI/output/<批次名>/`，文件名按工作流可读命名：
  `W1_concept`（概念原画）、`W2_depth`（深度图）、`W3_normal/height/roughness/metalness`（材质）、
  `W4_music`（音乐）、`W5_sfx`（音效）、`W6_frame/W6_atlas`（序列帧）
- 任务列表与详情页显示批次；接口支持 `GET /api/jobs?batch=<批次名>` 按批次筛选
- 网页「选择服务器已有图片」的输出目录下拉框也会按批次子文件夹分组显示

## 十二、3D 场景组装（环境预览）

把同一批次的零散资产组装成一个可交互的 3D 环境，角色自动演出（无需手动操控）：

- **环境照片 → 3D 场景**：概念原画作为场景主体，W2 深度图把整幅照片置换出真实
  几何（酒架/吧台随镜头产生立体视差），W3 四张贴图 → PBR 材质
- **2D 人物 → 3D 角色**：W7（TripoSR）把角色设定图转成真正的 3D 模型（GLB），
  未生成模型时用内置低模酒保演示
- **自动演出**：角色自动「走进酒吧 → 吧台喝酒 → 巡桌小酌 → 回吧台听音乐」，
  举杯时触发玻璃杯音效；W4 音乐循环播放，W5 音效随机触发
- 交互：点击开启声音，镜头自动缓慢旋转，也可拖拽旋转 / 滚轮缩放

用法：

1. 用同一个「批次名称」生成一批资产（建议包含 W1~W6，角色转 3D 用 W7）
2. 在任务详情点「进入 3D 场景」，或直接访问
   `/scene.html?batch=<批次名>`（如 `/scene.html?batch=废土酒吧环境`）

技术：Three.js（本地 vendor，无外网依赖），场景配置接口 `GET /api/scene?batch=<批次名>`。
