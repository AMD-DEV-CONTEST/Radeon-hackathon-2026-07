# 架构详解（ARCHITECTURE）

本文档说明 `candy-sticker-generator` 各模块的职责、依赖关系与数据流，以及在 AMD ROCm 上的适配要点。

---

## 1. 分层模型

项目自上而下分为 5 层，每层只依赖其下层的产物，互不耦合：

| 层 | 目录 | 职责 | 关键产物 |
|---|---|---|---|
| 训练层 | `src/lora/` | 在 ROCm 上自训 `stkstyle` 风格 LoRA | `models/stkstyle_lora_diffusers/` |
| 生成层 | `src/generation/` | SDXL+LoRA 出图 + 去底/白边/拼版/导出 | 单张贴纸 PNG + 套装 |
| 多模态层 | `src/multimodal/` | 参考图 → 提示词反推，增强生成可控性 | 文本提示词 |
| 服务层 | `src/webui/` | Gradio 交互界面，串起上述所有能力 | Web 服务 |

命令行入口 `scripts/` 与运维脚本 `setup.sh` 等横向贯穿各层。

---

## 2. 模块职责

### 2.1 训练层 `src/lora/`
- `train_stkstyle_lora.py`：基于 `animagine-xl-4.0` 基座，用 PEFT/LoRA 微调。配置：**rank=32, alpha=16, lr=1e-4, 2000 步，仅训 UNet（冻结文本编码器），触发词 `stkstyle`**。
- `training_data/images/`：33 对（图 + `.txt` caption）训练样本。
- `models/stkstyle_lora_diffusers/`：Diffusers 格式权重（`pytorch_lora_weights.safetensors`，185MB）。
- `train.log`：真实训练日志，可在 ROCm 上 4230s（约 70 分钟）训完，是「训练也在 AMD 上」的铁证。

### 2.2 生成层 `src/generation/`
- `sticker_pipeline.py`：出图主线。加载 SDXL 基座 + `stkstyle` LoRA，按表情/风格提示词生成贴纸底图。
- `matte_floodfill_batch.py`：从近白背景 floodfill 去底，得到透明 PNG。
- `add_sticker_whiteborder.py`：用距离变换（EDT）外扩生成干净白边。
- `build_sheet.py`：把多张贴纸拼成一张排版图（如 2×4）。
- `make_sheet_export.py`：一键导出 **ZIP**（processed / sheets / wechat / tg / print 多规格），其中 `print/` 为 300dpi + 出血位的印刷稿。

### 2.3 多模态层 `src/multimodal/`
- `img2prompt.py`：用 Qwen2.5-VL 把参考图转成结构化提示词，再回灌生成管线，形成「图 → 文 → 图」闭环，降低出图对人工写 prompt 的依赖。

### 2.4 服务层 `src/webui/`
- `gradio_app.py`：单体 WebUI，是所有底层能力的统一入口。提供**三种输入模式**：
  - `文字` — 直接写角色概念，走 SDXL + LoRA 出图；
  - `参考图` — 上传参考图，先由 Qwen2.5-VL 反推提示词（图 → 文 → 图）再出图；
  - `草图` — 同上，但针对线稿/草图做细化。

  另集成 LoRA 权重开关与强度调节、后处理各阶段状态回显、拼页预览与多规格 ZIP 下载。

---

## 3. 数据流

```
[训练层]  training_data ──train──▶ stkstyle_lora_diffusers
                                        │
[多模态]  ref.png ──img2prompt──▶ prompt.txt
                                        │
[生成层]  prompt + LoRA ──sticker_pipeline──▶ 底图
                                        │
                     matte(去底) → border(白边) → sheet(拼版)
                                        │
                                  make_sheet_export
                                        │
                                  demo_output/ (8 表情)
                                        │
[服务层]  gradio_app.py 统一调度以上全部
```

---

## 4. AMD ROCm 适配要点

- **训练与推理同硬件**：LoRA 训练在 ROCm 完成（非云端），推理与 WebUI 也在同一张 Radeon 上运行。
- **依赖隔离**：使用 `requirements.txt` 锁定 Diffusers / Transformers / PEFT / Gradio 版本；从国内镜像 + `HF_HUB_DISABLE_XET=1` 规避 Xet CDN 401。
- **显存控制**：SDXL + LoRA 推理实测峰值约 **10,409 MB（~10.2 GB）**，Qwen2.5-VL 图生文约 **8,373 MB（~8.2 GB）**；
  48 GB 卡可并行多任务；训练仅训 UNet，显存友好。
- **实证留痕**：`submission/docs/evidence_gpu/` 含三类 ROCm 负载（SDXL 出图 / Qwen-VL 图生文 / LoRA 训练）的
  功耗与显存时序图、原始 JSON 采样与设备快照（Navi 31 / gfx1100 / ROCm 7.2），供评审核验。

---

## 5. 扩展方向

- 多角色：训练第二个角色 LoRA（如恶魔/蓝毛），复用 `src/lora/` 配方即可。
- Live 动图：曾用 LTX-Video I2V 试做表情动效，受限于旧版 checkpoint 结构漂移已暂缓（不影响主流程评分）。
- API 服务：在 `src/webui/gradio_app.py` 之外可封装 FastAPI，对外提供贴纸生成接口。

