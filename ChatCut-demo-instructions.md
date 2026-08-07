# ChatCut Demo 视频需求说明

> 用途：AMD AI DevMaster Hackathon 2026 Track 1 参赛作品 Demo 视频
> 目标：用 ChatCut 制作 3–5 分钟的演示视频，展示 NodeFlow 在 AMD Radeon GPU 上真实运行

---

## 一、一句话概述

NodeFlow 是一个纯本地、无 CUDA 依赖的 AI 图像工作站，跑在 AMD Radeon GPU（ROCm 运行时）上，提供「无限画布手绘 + 扩散模型生图」，支持文生图、图生图（草图转画）、多模型热切换、LoRA 调节、Fast/Expert 双模式。

Demo 视频要证明：**它能真实、流畅、高质量地在 AMD Radeon GPU 上跑全套 AI 生图流程**。

---

## 二、给 ChatCut 的核心任务

请你制作一段 **3–5 分钟的演示视频**，并满足以下评分关键点（这是评委重点看的）：

1. **必须是真实操作**，不是幻灯片 —— 真实点击、真实生成的过程
2. **必须展示 AMD Radeon GPU** —— 画面里出现 GPU 名称、ROCm 运行时、VRAM 占用
3. **必须展示真实性能** —— 从输入到出图，保留真实耗时（不要快进、不要剪辑掉等待时间）
4. **必须展示出图质量** —— 清晰、稳定、风格多样

---

## 三、技术规格

| 项目 | 要求 |
|------|------|
| 时长 | 3–5 分钟（建议 3.5–4 分钟） |
| 分辨率 | 1080p（1920×1080）横屏 |
| 帧率 | 30fps |
| 格式 | MP4（H.264） |
| 音频 | 清晰英文配音（或中文 + 英文字幕） |
| 文件大小 | 500MB 以内 |

---

## 四、分镜脚本（按此结构制作）

### 第1幕 · 开场（0:00–0:20）
- 画面：NodeFlow 界面载入，显示标题/Logo
- 字幕叠加："NodeFlow — Infinite Canvas AI Stylization Workstation"
- 字幕叠加："Running on AMD Radeon PRO W7900 · ROCm Native"
- 旁白：介绍这是跑在 AMD Radeon GPU 上、不依赖 NVIDIA CUDA 的 AI 生图工作站

### 第2幕 · GPU 证明（0:20–0:35）
- 画面：打开 `/api/health` 页面，或终端执行 `rocm-smi` + `torch.cuda.get_device_name`
- 旁白：整个推理管线跑在 AMD Radeon PRO W7900（48GB VRAM）上，使用 ROCm 运行时和 PyTorch ROCm wheels
- 动作：展示 JSON 响应或终端输出，确认 GPU 型号

### 第3幕 · 草图转画（0:35–1:30）
- 画面：回到画布，手动画一个简单草图（人物/树/建筑），选「Sketch → Art」模式
- 选风格 **Watercolor**，强度拉到 0.8，点 Generate
- 展示加载状态（按钮显示 "Generating..."），等待 3–5 秒出结果，结果出现在结果面板
- 关键：**保留真实等待时间**，不要剪辑 —— 评委要看真实性能
- 旁白：画布导出 PNG 发给后端，扩散模型几秒内把草图变成水彩画

### 第4幕 · 风格切换（1:30–2:15）
- 画面：同一张草图，切风格到 **Cyberpunk** → 生成 → 展示
- 再切 **3D Render** → 生成 → 展示
- 三张结果并排对比
- 旁白：同一张草图、三种完全不同的风格，都在这块 AMD GPU 上生成

### 第5幕 · 文生图（2:15–2:50）
- 画面：切到「Text → Art」模式
- 输入提示词："a serene mountain lake at dawn with mist rising from the water"
- 选风格 **Oil Painting**，点 Generate，展示结果
- 旁白：支持文生图，后端自动补充专业提示词前缀

### 第6幕 · Fast vs Expert 双模式对比（2:50–3:30）
- 画面：Fast 模式生成 ~2-3 秒；切 Expert 模式同提示词生成 ~12-20 秒
- 展示画质差异（Expert 更好）
- 旁白：Fast 用 SDXL-Lightning 蒸馏模型（约2秒）；Expert 用全量模型（28-50步），更慢但质量更高、参数完全可控

### 第7幕 · 多模型 + LoRA（3:30–4:10）
- 画面：打开模型面板，从 SDXL-Lightning 切到 NoobAI XL
- 打开 LoRA 面板，拖动权重滑杆，用新模型 + LoRA 生成
- 旁白：模型可热切换无需重启；LoRA 权重实时可调，可混合写实基底与动漫 LoRA 出混合风格

### 第8幕 · 结尾（4:10–4:30）
- 画面：回到主界面
- 字幕叠加："NodeFlow" / "AMD Radeon PRO W7900 · 48GB VRAM · ROCm 7.x · PyTorch 2.x" / 参赛信息
- 旁白：证明完整 AI 生图工具可完全跑在 AMD Radeon + ROCm 上，无需 CUDA。Thank you.

---

## 五、后期制作要求

- **字幕**：若中文配音，必须加英文字幕（评分要求）；干净无衬线字体（Arial/Helvetica），底部居中带深色底条
- **文字叠加**：用于 GPU 名称、模型名、耗时、风格名；每屏至少停留 2 秒；白色文字带轻微阴影
- **剪辑**：保持简单硬切或 0.3s 淡入淡出，不要过度剪辑；**不要快进加载过程**
- **背景音乐**：可选，音量极低（旁白的 10-15%），纯器乐、无歌词、科技/氛围感

---

## 六、提交前检查清单

- [ ] 时长 3–5 分钟
- [ ] 画面上出现 AMD Radeon GPU 名称（W7900）
- [ ] 展示 ROCm / PyTorch 信息
- [ ] 演示了 Sketch-to-Art（图生图）
- [ ] 演示了 Text-to-Art（文生图）
- [ ] 展示真实生成耗时（未剪辑掉）
- [ ] 同一草图展示多种风格
- [ ] 展示 Fast vs Expert 模式差异
- [ ] 展示模型切换
- [ ] 配音清晰、英文（或有英文字幕）
- [ ] 1080p 分辨率、MP4 格式、500MB 以内