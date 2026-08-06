# IndieGen Asset Studio —— 实操例程（含视频录制脚本）

> 用途：按「第一轨 · 多模态内容创作工具」要求，在 AMD Radeon GPU / ROCm 上
> 把整套工具跑一遍，并录制 3–5 分钟演示视频。
> 本文所有命令都在本机（gfx1100 · ROCm 7.1 · ComfyUI 0.30）实测通过。

---

## 0. 需要准备什么

| 项目 | 要求 |
| --- | --- |
| GPU | AMD Radeon（本文实测 gfx1100 / Navi 31，48 GiB 显存；8–16 GB 卡可通过显存卸载运行） |
| 软件 | Ubuntu 22.04+ · ROCm 7.x · Python 3.12 · Git |
| 磁盘 | 约 30 GB（模型）+ 项目代码 |
| 浏览器 | Chrome / Edge（3D 场景需要 WebGL） |

## 1. 克隆与安装

```bash
git clone git@github.com:MFWTW/create_3Dgame.git
cd create_3Dgame

# ① ComfyUI + AMD ROCm 自动检测安装（NVIDIA 会自动走 CUDA，无 GPU 走 CPU）
bash scripts/setup_comfyui.sh

# ② W1~W6 模型（SDXL / VAE / MiDaS / OpenPose 等，约 15 GB）
bash scripts/download_models.sh

# ③ W7 2D→3D：TripoSR 节点 + 权重（约 1.7 GB）
bash scripts/setup_3d.sh
bash scripts/download_3d_model.sh
```

### 验证 AMD/ROCm 就绪

```bash
./ComfyUI/.venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# 期望输出：2.11.0+rocm7.1 True

rocminfo | head -8        # 能看到 AMD GPU
rocm-smi --showuse --showmemuse   # 能读到 GPU 状态
```

## 2. 启动服务（两个终端）

```bash
# 终端 1：ComfyUI GPU 引擎（8188）
cd ComfyUI && HF_ENDPOINT=https://hf-mirror.com .venv/bin/python main.py \
    --listen 127.0.0.1 --port 8188 --disable-auto-launch

# 终端 2：Web 后端（8000）
bash server/run.sh
```

浏览器打开 **http://localhost:8000**。

## 3. Web 实操：一条提示词走完全链

给批次起同一个名字（例如 `wasteland_bar`），按顺序提交：

| 步骤 | 工作流 | 操作 | 输出 |
| --- | --- | --- | --- |
| 1 | W1 概念原画 | 填英文/中文提示词（中文会自动离线翻译）→ 提交 | 1024×1024 概念图 |
| 2 | W2 深度图 | 选择 W1 输出（服务器已有图片）→ 提交 | 灰度深度图 |
| 3 | W3 材质 | 选 W2 深度 → 提交 | 法线/高度/粗糙度/金属度 4 张贴图 |
| 4 | W4 音乐 | 填风格描述 → 提交 | 8 秒 MP3 循环 |
| 5 | W5 音效 | 选 glass_clink / murmur / ambient_bar → 提交 | MP3 触发音效 |
| 6 | W6 序列帧 | 上传角色设定图 + action=run → 提交 | 8 帧图集 PNG + JSON 配置 |
| 7 | W7 2D→3D | 选角色图 → 提交 | GLB + OBJ 3D 模型 |

完成后在任一任务详情点 **「进入 3D 场景」**：同一批次的资产会组装成
3D 酒吧，酒保自动「进店 → 吧台喝酒 → 举杯致意 → 巡桌小酌 → 擦吧台」，
背景音乐和玻璃杯音效自动播放，镜头自动缓慢旋转。

## 4. CLI 例程（录视频推荐，含真实输出）

以下命令与真实执行结果一致（本机实测）：

```bash
# ① 提交 W7：2D 角色图 → 3D 模型（约 5 秒完成）
curl -s -X POST http://127.0.0.1:8000/api/jobs \
  -F workflow=W7 \
  -F 'params={"geometry_resolution":256,"threshold":25,"chunk_size":8192}' \
  -F image_filename=10a0b6cad40f_p4_character.png \
  -F image_location=input \
  -F batch=wasteland_bar
# {"id":"4f05e40f0bf0","workflow":"W7","status":"running","prompt_id":"02c10ce0-..."}

# ② 轮询状态
watch -n1 'curl -s http://127.0.0.1:8000/api/jobs/4f05e40f0bf0 | jq -r .status'
# running → done

# ③ 查看产物
ls ComfyUI/output/wasteland_bar/W7_model_*
# W7_model_00001_model.glb   W7_model_00001_model.obj

# ④ 全链基准（W1~W6，自动用 rocm-smi 采样 GPU）
./ComfyUI/.venv/bin/python scripts/benchmark_amd.py --out deliverables/perf/benchmark.json
```

### 本机实测性能（供视频展示）

| 工作流 | 配置 | GPU 执行 | 墙钟 | GPU 峰值 | 显存峰值 | 功率峰值 |
| --- | --- | --- | --- | --- | --- | --- |
| W1 概念 | SDXL 1024² · 25 步 | 14.6 s | 15.3 s | 100 % | 9.6 GB | 270 W |
| W2 深度 | MiDaS 512 | 1.1 s | 7.7 s | 93 % | 12.2 GB | 115 W |
| W3 材质 | 4 张贴图 | 1.0 s | 1.6 s | 50 % | 12.2 GB | 57 W |
| W4 音乐 | MusicGen-small 8 s | 9.6 s | 10.7 s | 100 % | 12.6 GB | 124 W |
| W5 音效 | 玻璃杯 4 s | 0.04 s | 1.5 s | 0 % | 12.4 GB | 63 W |
| W6 序列帧 | 8 帧 · 20 步 | 20.9 s | 21.3 s | 100 % | 21.7 GB | 271 W |
| W7 2D→3D | TripoSR 256³ | — | 5.2 s | — | — | — |

全链 W1–W6 合计 GPU 执行约 **57 秒**。数据保存在
`deliverables/perf/benchmark.json`（含 rocm-smi 逐秒采样）。

## 5. 视频录制建议（3–5 分钟）

| 时间 | 内容 | 要点 |
| --- | --- | --- |
| 0:00–0:20 | 开场：标题 + 一句话定位 | “One text setting → game-ready multimodal assets, locally on AMD Radeon / ROCm” |
| 0:20–1:00 | 项目背景与架构 | 痛点（外包贵/风格漂移）、架构图（网页→FastAPI→ComfyUI） |
| 1:00–2:40 | Web 实操 W1→W7 | 依次提交概念/深度/材质/音乐/音效/序列帧/3D，展示下载与预览 |
| 2:40–3:30 | CLI + ROCm 实证 | 上面第 4 节的 curl、轮询、benchmark 脚本、rocm-smi 实时读数 |
| 3:30–4:20 | 3D 场景展示 | 进入 3D 场景，展示自动演出 + 生成音乐/音效 |
| 4:20–5:00 | 收尾 | 交付物清单（PDF/PPT/源码/基准数据）+ 项目价值 |

录制技巧：

- 用 OBS 同时录「网页窗口 + 终端」，清晰展示从命令行/界面到最终结果；
- 关键数字（5.2 s / 57 s / VRAM 21.7 GB）可加字幕强调；
- 视频画面稳定即可，不需要剪辑特效；音轨可以直接用 W4 生成的背景音乐。

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| ComfyUI 启动报 `Qwen2Tokenizer` | 升级 transformers：`pip install "transformers>=4.50.3"`（setup_3d.sh 已自动处理） |
| W7 保存网格报 `ptp` 错误 | 升级 trimesh：`pip install "trimesh>=4.5"`（setup_3d.sh 已自动处理） |
| HF 下载慢 | 脚本默认走 hf-mirror.com；海外可 `HF=https://huggingface.co` |
| 端口 8000 被占用 | 先停旧进程再 `bash server/run.sh` |
| WebGL 不可用 | scene.html 自动降级 2D 兼容模式，不影响演示 |

## 7. 交付物清单

| 交付物 | 位置 |
| --- | --- |
| 项目简介 PDF（英文） | `deliverables/Project_Profile_EN.pdf` |
| 补充 PPT（英文） | `deliverables/Supplementary_Deck_EN.pptx` |
| 演示视频（由提交者按本例程录制） | 3–5 分钟，MP4 |
| 完整源代码 + README | 仓库根目录（`README_EN.md` 含环境配置/启动指南/依赖） |
| 性能基准数据 | `deliverables/perf/benchmark.json` + `.log` |
| 交付物生成脚本 | `deliverables/tools/` |

---

Track: **Multimodal Content Creation Tools** · All submission materials in English.
