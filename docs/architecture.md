# FrameForge 架构说明

## 1. 总体架构

FrameForge 采用三层架构：**Gradio Web UI** → **Python 编排层 (Orchestrator)** → **ComfyUI 推理后端 + 视频工具链**。

```
┌─────────────────────────────────────────────────────┐
│                   Gradio Web UI                      │
│  (时间轴 | 帧预览 | 画板涂抹 | 提示词 | 前后对比)      │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP API (Gradio 事件)
┌──────────────────────▼──────────────────────────────┐
│              FrameForge Orchestrator                  │
│                   (Python 后端)                      │
│                                                      │
│  ┌───────────┐  ┌───────────┐  ┌────────────────┐   │
│  │ 视频生成   │  │ 帧级编辑   │  │  编辑传播引擎   │   │
│  │ 模块      │  │ 模块      │  │  (光流传播)     │   │
│  └─────┬─────┘  └─────┬─────┘  └───────┬────────┘   │
│        │              │                │             │
│        ▼              ▼                ▼             │
│  ┌──────────────────────────────────────────────┐    │
│  │          ComfyUI 推理后端 (ROCm)              │    │
│  │  Wan2.1 | SDXL-Inpaint | ControlNet | SAM2   │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │              视频处理工具链                    │    │
│  │         FFmpeg (拆帧/合帧) + OpenCV           │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

## 2. 模块职责

### 2.1 `core/video_generator.py` — 视频生成模块
- 输入：提示词、参考图（可选）、时长、分辨率、种子
- 通过 `ComfyUIClient` 加载 `wan21_i2v.json` 工作流，填参后提交
- 监听 WebSocket 进度，完成后下载 MP4
- 调用 `utils.video_utils.split_video_to_frames` 拆为 PNG 帧序列
- 帧数自动对齐到 `4k+1`（Wan2.1 要求）

### 2.2 `core/frame_editor.py` — 帧级编辑模块
- 输入：帧路径、mask、编辑提示词、控制类型、重绘强度
- mask 经归一化 + 轻微膨胀后上传
- 按是否启用 ControlNet 选择 `sdxl_inpaint.json` 或 `sdxl_inpaint_controlnet.json`
- `controlnet_type` 切换预处理节点：canny→节点 20，depth→节点 21（运行时改连线）
- SDXL Inpainting 在 mask 区域内按新提示词生成，mask 外保持不变

### 2.3 `core/edit_propagator.py` — 编辑传播引擎（核心创新）
- 输入：编辑后关键帧、原始帧目录、关键帧索引、mask、传播范围
- 算法：
  1. RAFT 计算 edited→orig 前向光流 F，orig→edited 后向光流 B
  2. 用 F 把编辑帧 warp 到 orig 坐标系
  3. 前后向一致性检查：`|F(x) + B(x+F(x))| < threshold` 排除不可靠像素
  4. 组合 mask = 编辑 mask ∩ 可靠区域
  5. 高斯羽化混合 warp 结果与原帧
  6. SSIM 评估传播质量，低于阈值标记为低质量
- RAFT 使用 torchvision 内置 `raft_large`，惰性加载

### 2.4 `core/video_composer.py` — 视频合成模块
- 优先级合并帧序列：propagated > edited > original
- FFmpeg 合帧为 MP4，可选保留原音轨（先抽 AAC 再合并）

### 2.5 `backend/comfyui_client.py` — ComfyUI 客户端
- HTTP API：上传图像/mask、提交工作流、查询历史、下载输出
- WebSocket：实时进度监听（失败回退轮询）
- 工作流模板操作：加载、按节点 ID 改参数
- `requests` / `websocket` 惰性导入，纯工作流操作无需网络库

## 3. 数据流

```
用户输入(提示词+参考图)
  → [视频生成] Wan2.1 i2v → MP4
  → [拆帧] FFmpeg → PNG 序列
  → [预览] Gradio 时间轴 → 用户选关键帧
  → [选区] 画板涂抹 → mask
  → [重绘] SDXL Inpainting + ControlNet → 编辑帧
  → [传播] RAFT 光流 → warp + 羽化混合 → 相邻帧
  → [合帧] FFmpeg → 最终 MP4
  → [对比/导出]
```

## 4. 显存分配（48GB）

| 组件 | 显存 |
|------|------|
| Wan2.1 i2v (FP8) | ≈ 28GB |
| SDXL Inpainting | ≈ 8GB |
| ControlNet ×2 | ≈ 4GB |
| SAM2 | ≈ 2GB |
| 光流 + 其他 | ≈ 2GB |
| **合计** | **≈ 44GB（留 4GB 余量）** |

生成阶段仅加载 Wan2.1；编辑阶段切换到 SDXL + ControlNet + SAM2，48GB 优势在于编辑阶段可同时驻留所有组件。

## 5. 会话与目录

每个用户会话有独立子目录（`outputs/frames/{session_id}/` 等），避免多用户冲突：

```
outputs/
├── frames/{session_id}/      # 拆帧
├── edited/{session_id}/      # 编辑后帧
├── masks/{session_id}/       # mask
├── propagated/{session_id}/  # 传播结果
└── final/{session_id}.mp4    # 最终视频
```

## 6. 关键设计决策

- **ComfyUI 作为推理后端**：复用现成节点生态，避免重写模型加载/采样逻辑；FrameForge 只做编排
- **工作流模板 + 运行时改参**：模板存 JSON，代码按节点 ID 改 `inputs`，兼顾灵活与可读
- **RAFT 用 torchvision 内置**：免去独立安装，与 ROCm PyTorch 自动兼容
- **惰性导入网络库**：`requests`/`websocket` 仅在真正通信时导入，便于离线测试工作流逻辑
- **传播优先级**：`propagated > edited > original`，确保编辑与传播结果都能体现在最终视频
