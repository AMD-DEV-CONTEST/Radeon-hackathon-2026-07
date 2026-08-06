# 3DGenerateFlow 演示视频制作指南

> **目标**：制作一段 3–5 分钟、能在评审时清晰展示作品价值的演示视频。视频比重最高，请优先完成。

---

## 一、视频内容清单（按评审标准对应）

| 评审项 | 视频里必须出现的画面 | 建议时长 |
|---|---|---|
| **完整输入-处理-输出工作流** | 上传照片 → 输入需求 → Agent 规划 → 生成 → 下载模型 | 90–120 秒 |
| **创作场景创新性与趣味性** | 2.5D 浮雕 vs 全彩 3D 风格对比；宠物/人物/产品示例 | 45–60 秒 |
| **实际应用与社会价值** | 打印报告、watertight 检查、可直接 3D 打印的模型展示 | 30–45 秒 |
| **AMD GPU / ROCm 运行表现** | `/health/gpu`、终端日志、任务状态流转、GPU 占用 | 30–45 秒 |
| **收尾** | 项目地址、一句话总结 | 20–30 秒 |

**总时长控制在 3:30–4:30 最佳。**

---

## 二、推荐录制环境

### 2.1 在本地 Mac / Windows 录制

- **浏览器**：Chrome / Edge，打开 `http://<AMD实例IP>:5173/` 或本地前端 dev server。
- **录屏**：OBS Studio（推荐）、QuickTime Player、ScreenPal。
- **终端**：同时打开一个 SSH 窗口，显示后端日志和 `/health/gpu` 输出。
- **后期**：剪映 / CapCut / Premiere，剪掉模型生成等待过程，用加速片段展示流程。

### 2.2 在 AMD 实例 headless 环境录制（无显示器）

已提供脚本 `scripts/record_demo.sh`，它会：
1. 启动 Xvfb 虚拟显示（`:99`，1920×1080）。
2. 可选启动一个简单窗口管理器（Fluxbox）和浏览器/前端页面。
3. 用 `ffmpeg x11grab` 录制屏幕。
4. 停止后保存为 `demo_*.mp4`。

使用方式：
```bash
cd /workspace/3DGenerateFlow
bash scripts/record_demo.sh
# 脚本结束后输出 /tmp/3dgf_demo_YYYYMMDD_HHMMSS.mp4
```

如需手动录制，执行：
```bash
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
fluxbox &
# 启动你的浏览器或 frontend dev server
ffmpeg -f x11grab -r 30 -s 1920x1080 -i :99.0 -c:v libx264 -preset fast -pix_fmt yuv420p demo.mp4
```

---

## 三、分镜脚本（紧凑版，约 4 分钟）

完整旁白见 `docs/DEMO_SCRIPT.md`。这里给出录制时的**关键画面顺序**。

### 镜头 1：开场（0:00–0:20）
- 画面：标题卡 + 示例输入照片（宠物、人物、产品）。
- 旁白：一句话说明痛点和解决方案。

### 镜头 2：Web UI + GPU 就绪（0:20–0:45）
- 画面：Web UI 主界面，点击右上角 **AMD ROCm Ready** 徽章；同时展示 `/health/gpu` JSON。
- 旁白：强调本地 AMD GPU 运行、ROCm 就绪。

### 镜头 3：2.5D 浮雕纪念币（0:45–1:45）
- 画面：上传 `dog.jpg` → 输入 “2.5D relief coin” → 点击 Plan → 点击 Generate → 进度条 → 深度图 + 预览 + 下载 STL。
- 旁白：说明从照片到浮雕纪念币的完整流程，突出打印参数（尺寸 80×80×7 mm，体积 30 cm³，watertight）。
- **技巧**：生成过程可剪掉等待，用 2–3 秒加速蒙太奇带过。

### 镜头 4：全彩 3D 人物（1:45–3:00）
- 画面：上传 `bride.jpg` → 输入 “realistic 3D full-body” → Agent 选择 multi-view → 展示 front / right / back / left 四张图 → 生成 GLB → 预览旋转 → 下载。
- 旁白：强调多视角一致性、Hunyuan3D-2mv 在 AMD GPU 上运行、纹理 fallback 保证彩色输出。
- **技巧**：多视角四宫格停留 3–5 秒，这是核心亮点。

### 镜头 5：风格多样性（3:00–3:40）
- 画面：快速切换风格目录：cartoon, low-poly, voxel, clay, sketch, lithophane, silhouette, realistic。
- 旁白：一句话总结可支持的 2.5D / 3D 风格。

### 镜头 6：AMD GPU 运行表现（3:40–4:10）
- 画面：终端日志显示 `Generating multi-view images` → `Generating 3D mesh` → `Texture baking fallback` → `Scaling and computing print metrics`；任务状态流转；`rocm-smi` / `amd-smi` 一闪而过。
- 旁白：强调关键推理全部在 AMD GPU 本地完成，输出清晰稳定。

### 镜头 7：结尾（4:10–4:30）
- 画面：下载模型 → 在 Three.js / Blender / 3D 打印切片软件中展示旋转模型 → 项目 Logo + GitHub 链接。
- 旁白：一句话总结 + 邀请体验。

---

## 四、后期剪辑建议

1. **剪掉等待**：模型生成可能耗时 1–5 分钟，保留“点击生成”和“生成完成”两个镜头，中间用进度条/状态跳转加速。
2. **添加字幕**：关键术语（ROCm、Hunyuan3D-2mv、watertight、Zero123）用中文或中英双语字幕标注。
3. **背景音乐**：选择轻快、科技感、无版权音乐（YouTube Audio Library / 剪映曲库）。音量低于旁白。
4. **输出格式**：
   - 分辨率：1920×1080
   - 帧率：30 fps
   - 编码：H.264 / AAC
   - 文件大小：建议 < 500 MB，方便上传和提交
5. **导出文件名**：`3DGenerateFlow_Demo_1080p.mp4`

---

## 五、预录检查清单

- [ ] 模型已预先下载到 `models/hf_cache`，避免录制时联网等待。
- [ ] 后端已启动并通过 `/health/gpu` 测试。
- [ ] 已跑通 2.5D 浮雕和全彩 3D 至少各一次，结果文件存在。
- [ ] 前端 GLB 预览能正常显示彩色模型。
- [ ] 浏览器缩放设为 100%，字体清晰可读。
- [ ] 终端窗口和浏览器窗口同时可见，方便展示命令行到 GUI 的完整流程。
- [ ] 录制分辨率固定为 1920×1080。
- [ ] 最终导出前检查音量、字幕、Logo、GitHub 链接。

---

## 六、快速命令参考

```bash
# 1. 启动后端
export USE_ROCM=true USE_HUNYUAN3D=true HIP_VISIBLE_DEVICES=0
cd services/api
source .venv/bin/activate
CELERY_TASK_ALWAYS_EAGER=true \
CELERY_RESULT_BACKEND=cache+memory:// \
CELERY_TASK_EAGER_PROPAGATES=true \
PYTHONPATH=../.. uvicorn main:app --host 0.0.0.0 --port 8000

# 2. 启动前端
cd apps/web
npm run dev

# 3. 健康检查
curl -s http://localhost:8000/health/gpu | python3 -m json.tool

# 4. 自动录屏（headless 环境）
cd /workspace/3DGenerateFlow
bash scripts/record_demo.sh
```

---

## 七、视频提交位置

- 建议上传到：项目 Release / 网盘 / Bilibili / YouTube（如比赛允许）。
- 在 README 和项目简介 PDF 中放置视频链接/二维码。
- 同时保留一份本地 MP4 备份，命名为 `3DGenerateFlow_Demo_1080p.mp4`。
