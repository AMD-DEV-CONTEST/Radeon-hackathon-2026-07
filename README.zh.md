# Candy Sticker Generator · 糖果番剧 Q 版贴纸生成器

> English version: [README.md](README.md)

> 基于 **AMD Radeon + ROCm** 全链路（训练 + 推理 + 后处理 + 服务）的一个简单的二次元 Q 版贴纸生成项目。
> 一句话：输入一张参考图或一个表情关键词 → 输出带白边、去底、可印刷/可直发的成套贴纸。

---

## 1. 项目定位

这是一个**完整软件项目**，不是单一脚本。它把「风格 LoRA 训练 → 贴纸底图生成 → 去底/白边/拼版/导出 → 多模态图生文闭环 → WebUI 服务 → GPU 基准证明」串成一条可在 AMD ROCm 上跑通的创作管线。

亮点：**训练与推理全部在 AMD Radeon（ROCm）上完成**，并自带 GPU 占用证据，契合「AMD 适配」。

---

## 2. 整体架构（分层）

```
┌─────────────────────────────────────────────────────────────┐
│                        用户入口                              │
│   WebUI (src/webui/gradio_app.py)   ·   命令行 (scripts/)    │
└───────────────┬───────────────────────────┬─────────────────┘
                │                           │
        ┌───────▼────────┐          ┌───────▼────────┐
        │  多模态闭环     │          │   贴纸生成管线  │
        │ src/multimodal │          │ src/generation │
        │ img2prompt.py  │          │ sticker_pipeline│
        └───────┬────────┘          └───────┬────────┘
                │ 图→文→图提示词增强              │
                └─────────────┬───────────────┘
                              ▼
                    ┌─────────────────────┐
                    │  SDXL + 自训 LoRA   │  ← src/lora (在 ROCm 上训练)
                    │  (stkstyle 风格)    │     animagine-xl-4.0 基座
                    └─────────┬───────────┘
                              ▼
        ┌─────────────────────────────────────────────┐
        │            后处理 (src/generation)           │
        │  matting(去白底) → border(EDT白边) →        │
        │  sheet(拼版) → export(ZIP/微信/TG/印刷)     │
        └─────────────────────┬───────────────────────┘
                              ▼
                    demo_output/ (8 表情成品)
                              ▼
              src/bench/gpu_benchmark.py  (ROCm 占用证据)
```

---

## 3. 目录结构

```
candy-sticker-generator/
├── README.md                  # 英文版总览与架构（默认）
├── README.zh.md               # 本文件：中文版总览与架构
├── ARCHITECTURE.md            # 模块职责、数据流、ROCm 适配细节
├── BUILD_GUIDE.md             # 复现指南：重建 GPU 证据 / PDF / PPT
├── MODELS.md                  # 模型清单与下载命令（Animagine / Qwen-VL / LoRA）
├── requirements.txt           # Python 依赖（pip 包，不含模型权重）
├── src/                       # ★ 全部源码（按职责分包）
│   ├── generation/            # 核心生成与后处理
│   │   ├── sticker_pipeline.py        # SDXL+LoRA 出图主线
│   │   ├── matte_floodfill_batch.py   # floodfill 去白底
│   │   ├── add_sticker_whiteborder.py # EDT 外扩白边
│   │   ├── build_sheet.py             # 贴纸拼版布局
│   │   └── make_sheet_export.py       # 导出 ZIP / 微信 / TG / 印刷稿
│   ├── multimodal/            # 多模态图生文闭环
│   │   └── img2prompt.py             # Qwen2.5-VL：图→提示词→反推增强
│   ├── webui/                 # 服务层
│   │   └── gradio_app.py             # Gradio WebUI（三模式 + LoRA + 印刷稿）
│   ├── bench/                 # 基准与证据
│   │   └── gpu_benchmark.py          # rocm-smi 占用 / 出图耗时
│   └── lora/                  # ★ LoRA 训练子模块（在 ROCm 上自训）
│       ├── train_stkstyle_lora.py    # PEFT/Diffusers 训练脚本
│       ├── README.md                 # 训练配方与复现
│       ├── train.log                 # 真实训练日志（2000 步 / 4230s）
│       ├── training_data/images/     # 33 对训练图 + caption
│       └── models/stkstyle_lora_diffusers/  # 训好的权重 (185MB, Git LFS)
├── scripts/                   # CLI 入口 / 运维
│   ├── run_one.py  run_8expr.py      # 单张 / 8 表情批量出图
│   ├── convert_lora.py  gen_lora_data.py
│   ├── compare_lora.py  lora_loadtest.py
│   └── setup.sh  restart_webui.sh  start_tunnel_*.sh
├── demo_output/               # 8 张表情成品贴纸 + 拼版图（演示用）
├── tools/                     # 交付物与 GPU 证据生成
│   ├── build_pdf.py  build_pptx.py       # Profile PDF / 10 页 PPT
│   └── gen_gpu_evidence.py  render_gpu_charts.py   # 实例采样 → 本地渲染证据图
└── submission/                # 官方提交包（英文）
    ├── README.md  README.zh.md
    └── docs/
        ├── Project_Profile.md/.pdf       # 官方 5 要素
        ├── presentation.pptx             # 10 页路演
        └── evidence_gpu/                 # ROCm 功耗/显存时序图 ×4 + gpu_evidence.json + device_info.txt
```

> **单一事实来源**：正式文档与 GPU 证据只存放在 `submission/docs/` 一处，
> 项目根不保留副本，避免两处内容不一致。

---

## 4. 快速开始

### 4.1 训练风格 LoRA（ROCm）
```bash
cd src/lora
python train_stkstyle_lora.py        # animagine-xl-4.0 基座, rank32, 2000 步
# 产物 → models/stkstyle_lora_diffusers/
```
详见 `src/lora/README.md`。

### 4.2 启动 WebUI（推荐演示方式）

> **⚠️ 环境激活**：本项目依赖装在 venv 中，启动前请先激活虚拟环境：

```bash
# 方式 1：激活 venv（推荐，之后可直接用 python / pip）
source /opt/venv/bin/activate
pip install -r requirements.txt
python src/webui/gradio_app.py --port 7860

# 方式 2：直接用 venv 的 Python（无需激活）
/opt/venv/bin/pip install -r requirements.txt
/opt/venv/bin/python src/webui/gradio_app.py --port 7860
```

> 🌐 浏览器打开 http://localhost:7860
> 
> ⚠️ 模型权重**不随 requirements 安装**：请先按根目录 `MODELS.md` 下载 Animagine 基座与 Qwen2.5-VL 到 `models/`（国内可设 `HF_ENDPOINT=https://hf-mirror.com`）。自训 `stkstyle` LoRA 已随仓库内置。
> 
> 💡 如需公网访问，可加 `--share` 参数获取 Gradio 临时公网链接。

### 4.3 命令行批量出图
```bash
python scripts/run_8expr.py          # 生成 8 表情成套贴纸
```

### 4.4 多模态提示词增强
```bash
python src/multimodal/img2prompt.py --image ref.png
```

---

## 5. 技术栈

| 层 | 技术 |
|---|---|
| 基座模型 | SDXL (animagine-xl-4.0) + 自训 `stkstyle` LoRA |
| 训练框架 | Diffusers + PEFT (LoRA)，ROCm 7.x |
| 后处理 | NumPy / Pillow / SciPy（floodfill 去底 + EDT 白边） |
| 多模态 | Qwen2.5-VL（图生文提示词反推） |
| 服务 | Gradio |
| 硬件 | AMD Radeon（ROCm），48GB 显存 |

---

## 6. 评分点映射

- **AMD ROCm 适配**：训练 + 推理 + 基准全在 ROCm 上，附 `submission/docs/evidence_gpu/` 实证。
- **完整工作流**：从训练到出图到导出到服务，端到端可复现。
- **实际应用价值**：导出含微信/TG/印刷稿多规格，直接可用。
- **多样性**：多表情（8 种）+ 自训风格 LoRA，可扩展多角色。

详见 `ARCHITECTURE.md` 与 `submission/docs/Project_Profile.pdf`。
