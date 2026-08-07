# NodeFlow 项目交接文档

> 最后更新: 2026-08-03
> 项目: AMD AI DevMaster Hackathon Track 1 参赛作品
> 状态: MVP 已部署上线, 待迭代优化

---

## 一、项目概况

### 1.1 这是什么

NodeFlow 是一个基于 AMD Radeon GPU 的 AI 图像生成工具,核心功能是让用户在无限画布上手绘草图或输入文字,然后用 Flux 模型生成风格化图片。项目参加 2026 AMD AI DevMaster Hackathon Track 1。

### 1.2 技术栈

| 层 | 技术 | 版本 | 许可证 |
|----|------|------|--------|
| 前端 | React + Excalidraw | React 18.3, Excalidraw 0.17 | MIT |
| 构建工具 | Vite | 5.4 | MIT |
| 后端 | FastAPI + Uvicorn | FastAPI 0.115 | MIT |
| AI 推理 | diffusers + PyTorch (ROCm) | diffusers 0.32, PyTorch 2.5.1+rocm6.2 | Apache 2.0 |
| 当前模型 | FLUX.1-schnell | - | Apache 2.0 |
| 目标模型 | FLUX.2-klein-4B | - | Apache 2.0 |
| GPU | AMD Radeon PRO W7900 | 48GB VRAM | - |
| 运行时 | ROCm 6.2 + Python 3.12 | - | - |

### 1.3 核心功能

- **图生图 (img2img)**: 用户在 Excalidraw 画布上手绘草图,选择风格预设后生成风格化图片
- **文生图 (text2img)**: 用户输入文字描述,选择风格预设后生成图片
- **8 种风格预设**: Cyberpunk, Anime, Watercolor, Oil Painting, 3D Render, Pixel Art, Concept Art, Minimalist
- **风格化强度调节**: img2img 模式下可调节 0.1-1.0 的 strength 参数

---

## 二、项目结构

```
/workspace/ai-canvas/
├── backend/
│   ├── engine.py          # Flux 推理引擎 (单例模式, t2i + i2i 共享权重)
│   ├── main.py            # FastAPI 入口 (API 路由 + 静态文件服务)
│   └── requirements.txt   # Python 依赖 (torch/torchvision 不含,需单独装 ROCm 版)
├── frontend/
│   ├── src/
│   │   ├── App.jsx        # 主组件 (画布 + 控制面板 + 结果展示)
│   │   └── main.jsx       # React 入口
│   ├── index.html         # HTML 模板
│   ├── package.json       # npm 依赖
│   └── vite.config.js     # Vite 配置 (base: './' 兼容子路径部署)
├── start.sh               # 一键部署脚本
├── setup.sh               # 环境检查脚本 (实例重置后用)
└── README.md              # 项目说明
```

### 2.1 持久化存储 (实例重置后不丢失)

```
/persistent/
├── hf_cache/              # HuggingFace 模型缓存 (~12GB for Flux schnell)
├── venv/                  # Python 虚拟环境 (含 PyTorch ROCm)
└── (其他需要持久化的数据)
```

> 关键: `/workspace` 是临时盘,实例重置后会被清空。所有重要数据必须放 `/persistent`。

---

## 三、当前部署状态

### 3.1 运行中的服务

- **后端**: `uvicorn main:app --host 0.0.0.0 --port 8000` (在 GPU 实例上)
- **前端**: 已通过 `npm run build` 构建为静态文件,由 FastAPI 在 `:8000` 端口直接服务
- **外部访问**: 通过平台原生 `rc-tunnel expose --port 8000` 暴露到公网

### 3.2 访问方式

```bash
# 在 GPU 实例 Terminal 里
rc-tunnel expose --port 8000
# 会输出一个公网 URL,直接在浏览器打开即可
```

### 3.3 环境变量 (必须配置)

```bash
# HuggingFace 镜像 (实例不能直连 huggingface.co)
export HF_ENDPOINT=https://hf-mirror.com

# HuggingFace Token (Flux schnell 是 gated repo)
export HF_TOKEN="${HF_TOKEN:-hf_YOUR_HF_TOKEN_HERE}"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

# 模型缓存路径 (放持久化存储)
export HF_HOME=/persistent/hf_cache
export TRANSFORMERS_CACHE=/persistent/hf_cache
export DIFFUSERS_CACHE=/persistent/hf_cache
```

这些变量已写入 `~/.bashrc` 和 `start.sh` 中。

---

## 四、API 参考

| 端点 | 方法 | 说明 | 参数 |
|------|------|------|------|
| `/` | GET | 返回前端页面 | - |
| `/api/info` | GET | API 基础信息 | - |
| `/api/health` | GET | 健康检查 (含 GPU 状态) | - |
| `/api/styles` | GET | 获取风格列表 | - |
| `/api/generate/text2img` | POST | 文生图 | `prompt` (str), `style` (str), `width` (int), `height` (int) |
| `/api/generate/img2img` | POST | 图生图 | `file` (UploadFile), `style` (str), `strength` (float) |

返回格式统一为:
```json
{
  "status": "ok",
  "image": "data:image/png;base64,<base64编码的PNG>"
}
```

---

## 五、已知问题与用户反馈

### 5.1 模型质量问题 (高优先级)

**问题**: FLUX.1-schnell 生成的图片质量不佳,用户评价"太垃圾了"。

**原因分析**: Flux schnell 是 4 步蒸馏模型,主打速度而非质量。4 步推理下细节和构图都偏弱。

**解决方案**: 迁移到 FLUX.2-klein-4B (详见第七节)。

### 5.2 前端 UI/UX 问题 (高优先级)

**问题**: 部署到网站上后界面"特别丑"、"非常简陋",缺少即梦、Liblib 那种高级感和丝滑动效。

**具体表现**:
- 右侧面板的 "Simple Present" 等 Excalidraw 默认 UI 元素暴露过多,不够干净
- 缺少加载动画、过渡动效
- 整体视觉风格缺乏设计感,像是半成品
- 与即梦、Liblib 等成熟产品相比差距明显

**根本原因**: 当前前端几乎全部用内联 style 写的,没有独立的 CSS 文件,没有动画系统,没有设计系统。Excalidraw 的默认 UI 占据了大量视觉空间,喧宾夺主。

**解决方向**: 详见第八节。

### 5.3 前端 Bug

用户提到"前端有一些 bug"但未具体描述。需要在本地开发环境中系统排查。

### 5.4 Excalidraw 默认 UI 干扰

Excalidraw 自带的顶部菜单栏、左侧工具栏、底部属性面板在当前布局中暴露过多,尤其是右侧面板区域出现了 "Simple Present" 等 Excalidraw 原生 UI,与自定义控制面板产生视觉冲突。

---

## 六、开发经验与踩坑记录

### 6.1 AMD Radeon Cloud 平台相关

**实例重置是常态**: 平台维护、超时、手动重启都可能导致实例重置。`/workspace` 目录会被清空,只有 `/persistent` 保留。

**教训**:
- 代码必须推送到 Git 或备份到 `/persistent`
- Python venv 放 `/persistent/venv`,这样重置后不用重装 PyTorch (4GB+ 下载)
- HuggingFace 缓存放 `/persistent/hf_cache`,这样重置后不用重新下载 12GB 模型
- 环境变量写入 `~/.bashrc`,但 `~/.bashrc` 也在临时盘上,需要通过 `start.sh` 重新设置

**JupyterLab 代理不可靠**: 尝试过通过 JupyterLab 的 proxy 访问端口,但 404 频发,且重启 Jupyter 会导致实例崩溃。最终放弃,改用 `rc-tunnel`。

**rc-tunnel 是正解**: 平台原生工具,`rc-tunnel expose --port 8000` 一条命令搞定公网访问,稳定可靠。

### 6.2 PyTorch + ROCm 安装

**必须用 ROCm 专用 wheel**:
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.2
```
不能从 PyPI 直接装,否则没有 ROCm 支持。

**验证 GPU 可用性**:
```python
import torch
print(torch.cuda.is_available())  # True
print(torch.cuda.get_device_name(0))  # AMD Radeon Graphics
# 注意: 属性名是 total_memory 不是 total_mem
print(torch.cuda.get_device_properties(0).total_memory / 1e9)
```

### 6.3 HuggingFace 模型下载

**实例不能直连 huggingface.co**,必须配置镜像:
```bash
export HF_ENDPOINT=https://hf-mirror.com
```

**Flux schnell 是 gated repo**,需要 HuggingFace token:
```bash
export HF_TOKEN=hf_xxxxx
```

### 6.4 前端构建与部署

**Vite base 必须设为 './'**: 这样构建出的静态文件使用相对路径,兼容任何子路径部署。

**npm install 需要 --legacy-peer-deps**: Excalidraw 的 peer dependency 与 React 18 有冲突。

**FastAPI 挂载静态文件的顺序**: 必须在所有 API 路由定义之后才能 `app.mount("/assets", ...)`,否则会拦截 API 请求。

**前端构建后由 FastAPI 服务**: 不需要单独跑 Vite dev server,`npm run build` 后 FastAPI 直接服务 `dist/` 目录。

### 6.5 Flux 模型推理优化

**t2i + i2i 共享权重**: 用 `FluxImg2ImgPipeline.from_pipe(self._pipe_t2i)` 复用同一份权重,节省 ~12GB 显存。W7900 有 48GB VRAM 足够,但这是个好习惯。

**Flux schnell 参数**:
- `num_inference_steps=4` (schnell 专为少步优化,不建议改)
- `guidance_scale=0.0` (schnell 不需要 guidance)
- `torch_dtype=torch.bfloat16` (ROCm 支持,显存减半)

### 6.6 关于 Flux.1 vs Flux.1-schnell 的选择

当时选择 schnell 的理由:
- Apache 2.0 许可证 (dev 模型是非商业许可)
- 4 步极速推理,适合 demo 展示
- 不需要 CLIP text encoder 的复杂配置 (ComfyUI 中 Flux 需要双 CLIP)

但现在看来 schnell 的质量确实不够,特别是与 Flux.2 相比。

---

## 七、Flux.2 迁移计划 (高优先级)

### 7.1 目标模型

**FLUX.2-klein-4B** (Apache 2.0 许可证)

选择理由:
- 4B 参数量,比 schnell 更强的生成质量
- Apache 2.0 开源许可,符合比赛要求
- 约 13GB 显存占用 (BF16),W7900 的 48GB VRAM 绰绰有余
- diffusers 已原生支持 `Flux2KleinPipeline`

### 7.2 迁移步骤

**Step 1: 升级 diffusers**

```bash
# Flux2 需要较新版本的 diffusers
pip install --upgrade diffusers transformers
```

**Step 2: 修改 engine.py**

核心改动:
```python
# 旧
from diffusers import FluxPipeline, FluxImg2ImgPipeline
# 新
from diffusers import Flux2KleinPipeline  # 或对应类名

# 旧
self._pipe_t2i = FluxPipeline.from_pretrained(
    "black-forest-labs/FLUX.1-schnell", torch_dtype=dtype
).to(device)
# 新
self._pipe_t2i = Flux2KleinPipeline.from_pretrained(
    "black-forest-labs/FLUX.2-klein-4B", torch_dtype=dtype
).to(device)
```

> 注意: 需要确认 Flux2KleinPipeline 是否支持 from_pipe 做 img2img。如果不支持,可能需要单独加载 i2i pipeline 或用其他方式实现图生图。

**Step 3: 调整推理参数**

Flux.2-klein 的推荐参数与 schnell 不同:
- 步数可能需要更多 (参考官方文档,蒸馏版可能 4-8 步,完整版可能 20-50 步)
- guidance_scale 可能需要非零值
- 需要根据实际效果调试

**Step 4: 首次下载模型**

Flux.2-klein-4B 模型约 8-10GB,首次启动需要下载。确保 HF 缓存在 `/persistent/hf_cache`。

**Step 5: 测试验证**

```bash
# 测试文生图
curl -X POST http://localhost:8000/api/generate/text2img \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a futuristic city at sunset","style":"cyberpunk"}' \
  -o /tmp/test.json

# 检查结果
python3 -c "import json; d=json.load(open('/tmp/test.json')); print(d.get('status'), len(d.get('image','')))"
```

### 7.3 风险与注意事项

- Flux2 可能需要更高版本的 transformers/diffusers,可能与现有依赖冲突
- Flux2KleinPipeline 的 API 接口可能与 FluxPipeline 不同,需要查阅 diffusers 文档
- img2img 实现方式可能变化,需要确认 Flux.2 是否有对应的 Img2Img pipeline
- 首次下载需要走 HF 镜像 (hf-mirror.com)

### 7.4 参考资源

- HuggingFace diffusers Flux2 文档: https://huggingface.co/docs/diffusers/api/pipelines/flux2
- FLUX.2-klein-4B 模型页: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- Flux.2-klein-4B 在 AMD GPU 上已有成功案例 (AMD Instinct MI60),W7900 应无问题

---

## 八、前端 UI/UX 优化计划 (高优先级)

### 8.1 问题诊断

当前前端的核心问题:
1. **没有设计系统**: 所有样式都是内联 style,没有统一的色彩、字体、间距规范
2. **Excalidraw UI 喧宾夺主**: 默认的顶部菜单、左侧工具栏、属性面板暴露太多,与自定义 UI 冲突
3. **零动效**: 没有过渡动画、加载动画、悬停效果,感觉"死板"
4. **视觉层次混乱**: 左侧深色顶栏 + 右侧浅色面板,风格不统一
5. **缺少现代感**: 没有毛玻璃、渐变、阴影等现代 UI 元素

### 8.2 优化方向

**A. 隐藏/定制 Excalidraw UI**
- 使用 `UIOptions` 隐藏不需要的菜单项
- 考虑用 Excalidraw 的 `props.UIOptions.canvasActions` 精确控制显示项
- 或考虑自定义 Excalidraw 主题,使其与整体设计融合

**B. 建立设计系统**
- 创建独立的 CSS 文件 (或 CSS-in-JS 方案)
- 定义统一的色彩变量 (--primary, --bg, --surface, --border 等)
- 统一间距、圆角、阴影规范

**C. 添加动效**
- 生成按钮: 加载状态用骨架屏或脉冲动画
- 图片生成完成: 淡入 + 缩放过渡
- 面板切换: 滑动过渡
- 风格卡片: 悬停时微缩放 + 阴影变化
- 参考即梦/Liblib 的交互质感

**D. 视觉升级**
- 统一暗色主题 (与画布区域一致)
- 右侧面板用半透明毛玻璃效果
- 风格预设用图标/缩略图代替纯文字按钮
- 生成结果区域增加放大预览功能

### 8.3 本地开发工作流 (回答用户问题)

> "我们修 bug 是不是要先线下，也就是先在本地把它修好？"

**是的,推荐本地开发流程**:

1. **本地拉代码**: 在本地电脑 clone 项目代码 (不含模型和 venv)
2. **本地装依赖**: `npm install --legacy-peer-deps` (前端) + `pip install` (后端,不需要 ROCm 版 torch,用 CPU 版即可调试)
3. **本地跑前端 dev server**: `npm run dev` (Vite 热更新,改完即看)
4. **后端可以连远程**: 前端的 `vite.config.js` 已配置 proxy,将 `/api` 转发到 `localhost:8000`。本地开发时可以把 target 改成远程 GPU 实例的地址,这样本地改前端、远程跑模型
5. **测试通过后构建**: `npm run build`
6. **推送到 GPU 实例**: 把 `dist/` 目录或源码同步到 GPU 实例
7. **GPU 实例上重新构建**: `npm run build` 然后 FastAPI 自动服务新的静态文件

**关键配置**: `vite.config.js` 中的 proxy 配置:
```javascript
proxy: {
  '/api': {
    target: 'http://localhost:8000',  // 本地开发时改成远程 GPU 地址
    changeOrigin: true,
  },
}
```

---

## 九、比赛提交规划

### 9.1 项目定位

NodeFlow 的核心卖点:
- **AMD Radeon GPU 原生推理**: 不依赖 NVIDIA CUDA,展示 ROCm 生态
- **画布交互式 AI 创作**: 不是简单的文生图框,而是手绘草图 + AI 风格化的工作流
- **简化设计**: 相比 ComfyUI 的复杂节点编辑器,提供更低门槛的创作体验

### 9.2 可以在提交材料中强调的设计决策

1. **选择 Flux schnell 而非 Flux dev**: Apache 2.0 许可证,适合商业化和比赛展示;4 步极速推理,适合实时 demo
2. **t2i + i2i 共享权重**: 通过 `from_pipe` 复用,节省显存,展示工程优化能力
3. **Excalidraw 画布**: 提供无限画布 + 手绘交互,区别于传统的上传图片式 img2img
4. **FastAPI 一体化部署**: 前后端统一服务,简化部署,适合 hackathon 快速演示

### 9.3 后续功能路线图

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | Flux.2 迁移 | 提升生成质量 |
| P0 | 前端 UI 重做 | 提升视觉质感和交互体验 |
| P1 | 画布上直接叠加生成结果 | 在 Excalidraw 画布上放置生成的图片,而非只在右侧面板 |
| P1 | 历史记录 | 保存生成历史,支持回溯和对比 |
| P2 | LoRA 支持 | 允许加载自定义 LoRA 做风格定制 |
| P2 | 多模型切换 | 在 UI 上切换不同模型 |
| P3 | 节点式工作流 | 从简单画布进化为节点编辑器 (类似 ComfyUI 但更易用) |

---

## 十、快速恢复指南 (实例重置后)

如果 GPU 实例被重置,按以下步骤恢复:

```bash
# 1. 激活持久化的 venv
source /persistent/venv/bin/activate

# 2. 设置环境变量
export HF_ENDPOINT=https://hf-mirror.com
export HF_TOKEN="${HF_TOKEN:-hf_YOUR_HF_TOKEN_HERE}"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
export HF_HOME=/persistent/hf_cache
export TRANSFORMERS_CACHE=/persistent/hf_cache
export DIFFUSERS_CACHE=/persistent/hf_cache

# 3. 检查代码是否还在
ls /workspace/ai-canvas/backend/main.py
# 如果不在,需要从 Git 或备份恢复代码

# 4. 安装后端依赖 (torch 已在 venv 里,这步很快)
cd /workspace/ai-canvas/backend
pip install -r requirements.txt

# 5. 构建前端
cd /workspace/ai-canvas/frontend
npm install --legacy-peer-deps
npm run build

# 6. 启动后端 (会自动加载模型 + 服务前端)
cd /workspace/ai-canvas/backend
uvicorn main:app --host 0.0.0.0 --port 8000 &

# 7. 暴露到公网
rc-tunnel expose --port 8000
```

或者直接运行:
```bash
cd /workspace/ai-canvas
bash start.sh
```

---

## 十一、关键文件说明

### backend/engine.py

Flux 推理引擎,单例模式。核心设计:
- `FluxEngine` 是单例,全局只加载一次模型
- `_pipe_t2i` 是文生图管线,`_pipe_i2i` 通过 `from_pipe` 复用权重
- `STYLE_PRESETS` 字典定义了 8 种风格,每种对应一段 prompt 前缀
- `generate_from_text()` 和 `generate_from_image()` 是两个核心方法
- 迁移 Flux.2 时主要改这个文件

### backend/main.py

FastAPI 应用,提供 RESTful API。核心设计:
- 启动时通过 `@app.on_event("startup")` 预加载模型
- `/api/generate/text2img` 接收 JSON,`/api/generate/img2img` 接收 multipart/form-data
- 图片以 `data:image/png;base64,...` 格式返回
- 前端构建后由 FastAPI 在根路由 `/` 服务,`/assets` 挂载静态文件

### frontend/src/App.jsx

React 主组件,目前约 350 行。核心设计:
- 左侧 Excalidraw 画布 (img2img 模式) 或文本输入框 (text2img 模式)
- 右侧控制面板: 风格选择 + 强度滑块 + 生成按钮 + 结果展示
- `exportCanvasAsPNG()` 将 Excalidraw 画布导出为 PNG blob
- `BACKEND_URL = ''` 使用相对路径,前后端同源
- 这个文件是 UI 优化的主要对象

### start.sh

一键部署脚本,自动完成: 环境检查 -> venv 激活 -> 依赖安装 -> 后端启动 -> 前端构建 -> 外部访问提示。

---

## 十二、HuggingFace Token

```
hf_YOUR_HF_TOKEN_HERE
```

这个 token 用于下载 Flux 模型 (gated repo)。已配置在 `start.sh` 和 `~/.bashrc` 中。如果失效需要去 HuggingFace 重新生成。

---

## 十三、新 Session 快速上手

如果你是接手这个项目的新 AI 助手,请按以下顺序了解项目:

1. 读这份文档,了解项目概况和当前状态
2. 读 `backend/engine.py` 了解推理引擎
3. 读 `backend/main.py` 了解 API 设计
4. 读 `frontend/src/App.jsx` 了解前端实现
5. 读 `start.sh` 了解部署流程
6. 检查 GPU 实例是否在运行,服务是否正常
7. 当前最高优先级任务: Flux.2 迁移 + 前端 UI 重做

用户偏好:
- 用中文交流
- 技术术语可以用英文
- 希望有高级感、丝滑动效的 UI (参考即梦、Liblib)
- 重视比赛提交质量
- 修 bug 先在本地修好再部署
