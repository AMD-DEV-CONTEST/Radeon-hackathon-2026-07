# 3DGenerateFlow 演示视频脚本（紧凑版，3–5 分钟）

## 视频目标

- 展示 **Web UI 实际操作流程**。
- 展示后端在 **AMD Radeon GPU / ROCm** 上的真实运行。
- 展示最终输出：**清晰、稳定、多样化**的可打印 2.5D / 3D 模型。
- 体现“**一张照片 + 一句话 → 可打印全彩 3D / 2.5D 模型**”的完整创作闭环。

---

## 分镜 1：开场与痛点（25 秒）

**画面**：标题卡 → 普通照片（宠物、人物、产品）→ 3D 打印成品示意。

**旁白**：
> 想把自己的宠物、家人或产品照片变成可以 3D 打印的全彩手办或浮雕？传统流程需要多角度拍摄、手动建模、风格化、打印检查，门槛很高。3DGenerateFlow 让这件事变成：一张照片，一句话。

---

## 分镜 2：项目与平台介绍（30 秒）

**画面**：Web UI 主界面，展示向导模式 / Lazy Canvas 双模式、右上角 **AMD ROCm Ready** 徽章，同时展示 `/health/gpu` JSON。

**旁白**：
> 3DGenerateFlow 是一个基于 Web UI 的 AI 多模态内容创作工具。内置 3D Director Agent，上传照片并描述风格，系统就能自动编排从图生图、多视角合成、3D 生成到打印检查的完整流程。核心推理全部运行在 AMD Radeon GPU + ROCm 开源软件栈上。

---

## 分镜 3：2.5D 浮雕纪念币（60 秒）

**画面**：
1. 上传 `dog.jpg`。
2. 输入需求：“2.5D 浮雕纪念币，滑板狗”。
3. 点击 **AI 规划风格** → 选择 `relief_coin`。
4. 点击 **生成模型** → Lazy Canvas 六步流程高亮。
5. 结果展示：深度图、GLB 预览、打印报告（80×80×7 mm，30 cm³，watertight）。
6. 下载 `relief.stl`。

**旁白**：
> 先看 2.5D。上传滑板狗照片，Agent 自动选择圆形硬币浮雕并安排深度估计。后端在 ROCm 上运行 Stable Diffusion 风格化和 Depth Anything V2，随后生成带彩色贴图的 GLB 和可直接打印的 STL。最终模型 watertight，尺寸和体积都经过打印检查。

---

## 分镜 4：全彩 3D 人物（90 秒）

**画面**：
1. 上传 `bride.jpg`。
2. 输入需求：“写实 3D 新娘全身像”。
3. Agent 规划选择 `realistic_3d` + `fullcolor_3d`。
4. 点击 **生成模型**。
5. Lazy Canvas 展示多视角合成：front / right / back / left 四张图（停留 3–5 秒）。
6. 3D 生成 + 纹理烘焙 → 彩色 GLB 预览旋转。
7. 打印报告：目标高度 80 mm、watertight 状态。
8. 下载 `model.glb`。

**旁白**：
> 再看全彩 3D。上传新娘照片，Agent 调用 Zero123 在本地 AMD GPU 上合成四个视角，再输入 Hunyuan3D-2mv 生成模型。由于 Hunyuan3D-2 的纹理模块依赖 CUDA 扩展，在 ROCm 上无法直接编译，系统会自动 fallback：把参考图投影烘焙到 GLB，保证输出仍然是彩色 3D。模型按 80 mm 目标高度等比缩放并打印检查。

---

## 分镜 5：风格多样性（40 秒）

**画面**：快速切换风格目录结果：
- 卡通 3D、低多边形 3D、体素 3D、粘土 3D、素描 3D
- 透光浮雕、剪影浮雕、纪念币

**旁白**：
> 除了写实，还可以一键切换卡通、低多边形、体素、粘土、素描等 3D 风格，以及透光浮雕、剪影浮雕、纪念币等 2.5D 风格，满足个性化 3D 打印和视觉设计需求。

---

## 分镜 6：AMD GPU 运行表现（30 秒）

**画面**：
- `amd-smi static` / `rocm-smi` 一闪而过。
- `/health/gpu` JSON 高亮 `rocm_available: true`。
- 终端日志：`Generating multi-view images` → `Generating 3D mesh` → `Texture baking fallback` → `Scaling and computing print metrics`。
- 任务状态从 `pending` → `preprocessing` → `generating_multiview` → `generating_3d` → `postprocessing` → `completed`。

**旁白**：
> 风格迁移、多视角合成、3D 生成等关键推理全部在 AMD Radeon GPU 上本地完成。后端输出清晰、稳定，任务状态实时同步到前端，最终模型 watertight 且尺寸符合打印要求。

---

## 分镜 7：结尾（20 秒）

**画面**：Web UI 下载按钮 → GLB 模型旋转预览 → 项目 Logo + GitHub 仓库链接。

**旁白**：
> 3DGenerateFlow：一张照片，一句话，在 AMD Radeon GPU 上生成可打印的全彩 3D 或 2.5D 模型。项目已开源，欢迎体验。

---

## 技术备注

- **录制工具**：
  - 本地：OBS Studio / QuickTime / ScreenPal。
  - AMD 实例 headless：使用 `scripts/record_demo.sh`（Xvfb + fluxbox + ffmpeg）。
- **建议**：Web UI 和终端窗口同时录制，体现从命令行/GUI 到最终结果的完整流程。
- **首次运行**：提前下载模型到 `models/hf_cache`，避免录制时等待。
- **剪辑**：生成过程等待可剪掉，用进度条/状态跳转加速带过。

---

## 参考命令

```bash
# 启动后端
export USE_ROCM=true USE_HUNYUAN3D=true HIP_VISIBLE_DEVICES=0
cd services/api
source .venv/bin/activate
CELERY_TASK_ALWAYS_EAGER=true \
CELERY_RESULT_BACKEND=cache+memory:// \
CELERY_TASK_EAGER_PROPAGATES=true \
PYTHONPATH=../.. uvicorn main:app --host 0.0.0.0 --port 8000

# 启动前端
cd apps/web
npm run dev

# 健康检查
curl -s http://localhost:8000/health/gpu | python3 -m json.tool

# 自动录屏
cd /workspace/3DGenerateFlow
bash scripts/record_demo.sh
```
