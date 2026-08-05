# 证据索引 · omima × AMD（可复核）

> 与 `../00-PACKAGE.md` 数字口径一致。  
> 原始长日志在 `DOCS/references/` 与 Gitea `omima-hackathon/logs/`；此处做**提交向导航**。

---

## 1. 模型与数据集（魔搭 ModelScope）

| 资产 | 类型 | 地址 | 证明什么 |
|------|------|------|----------|
| omima-1B | model | https://modelscope.cn/models/kooooon/omima-1B | 阵眼路由模型（记忆 + 路由 + 任务提炼） |
| omima-35B | model | https://modelscope.cn/models/kooooon/omima-35B | 军师岗位 LoRA adapter（Ornith-1.0-35B，r=64）@ MI300X 训练 |
| omima-9B | model | https://modelscope.cn/models/kooooon/omima-9B | Worker 岗位权重 + GGUF Q8 |
| omima-distilled | dataset | https://modelscope.cn/datasets/kooooon/omima-distilled | 首轮训练用 chatml + wiki |
| omima-training-data | dataset | https://modelscope.cn/datasets/kooooon/omima-training-data | combined + distill + knowledge 分片（后续供弹） |

CLI 核验示例（本机已用参赛令牌登录过；提交包不写令牌）：

```bash
modelscope download kooooon/omima-35B --local_dir ./omima-35B
# adapter_config.json · adapter_model.safetensors · README
```

---

## 2. 试验与施工日志（仓库路径）

| 主题 | 路径（Hackathon 工作区） | 关键结论 |
|------|--------------------------|----------|
| 选型 / FP8 / Phase 1–4 | `DOCS/references/12-试验日志-AMD-MI300X选型与微调.md` | tool-call 8/9；FP8 195 vs BF16 118 |
| 双模型测速 / 9B 架构 | `DOCS/references/` 与 Gitea logs `09-作战日志-2026-07-19-…` | 35B LoRA ~59 TPS；9B 裸 ~152 / LoRA ~75 |
| 35B LoRA 训练夜 | Gitea `logs/construction-log-2026-07-18.md` | 9B 57min；35B 1h11m；Loss 账 |
| Consultation / 置信度 | `DOCS/references/construction-log-2026-07-22.md` | 置信度 0.72；三层部署定稿 |
| Pocket Worker CPU | Gitea `logs/Pocket-Worker-verification-report-2026-07-19.md` | Q8 ~13 t/s tool-call |
| 模式与 40 分专章 | `DOCS/submission/amd-rocm-technical.md` | 编制叙事 + 主链 |

Gitea 镜像：`http://111.228.42.18/boss/omima-hackathon` · `logs/`

---

## 3. 指标定义（禁止混口径）

| 名称 | 定义 |
|------|------|
| C=3 聚合 TPS | vLLM 并发 3 路时的聚合吞吐（tok/s） |
| 短上下文服务 TPS | 服务端单次 completion 量级测速（256 tok 级） |
| tool-call 8/9 | 固定 9 题协议场景，A2 失败归因工具名非模型 |
| Loss | 训练日志 train/eval loss，非下游任务分 |

不得将 llama.cpp 聚合吞吐与 vLLM 数字写入同一格且不标注框架。

---

## 4. 软件栈与命令（可复现骨架）

```bash
# 环境
rocm-smi
# 军师 FP8 服务（示意）
python -m vllm.entrypoints.openai.api_server \
  --model /path/to/Qwen3.6-35B-A3B-FP8 \
  --trust-remote-code --port 8000
# 岗位 LoRA（示意）
python -m vllm.entrypoints.openai.api_server \
  --model /path/to/Ornith-1.0-35B \
  --enable-lora --lora-modules omima-35b=/path/to/adapter \
  --max-lora-rank 64 --port 8000
# 训练脚本
bash scripts/finetune_35b_lora.sh --fp8
```

脚本位置：Gitea `omima-hackathon/scripts/`；副本亦在 `DOCS/references/scripts/`。

---

## 5. 应用层与星网（功能分，非替代 GPU 分）

| 项 | 说明 |
|----|------|
| Gateway | 生产向 JD-ECS 等；health / agents / events 有实测记录于 planning evidence |
| Xagent | 桌面/无头星站 harness |
| omima-phone | 手机 client（控制面） |
| 成本账 | 56.3 亿 tokens / ¥444.55（缓存命中）— 应用价值，不计入 ROCm 吞吐 |

详见 `main-paper.md` §3。

---

## 6. 演示媒体（Demo Video）

| 媒体 | 用途 | 状态 |
|------|------|------|
| **`media/omima-vox-90s.mp4`** | **主演示 VOX 动能信息图**（无配音 / 无 BGM · 帧动画） | **已交付 · 2026-08-05** |
| `media/omima-vox-main.mp4` | 与 90s 同内容副本（赛方 3–5 min 位可选；本提交以 90s 路演密度说明足够） | 同拷贝 |

### 6.1 VOX 成片元数据

| 项 | 值 |
|----|-----|
| 文件 | `evidence/media/omima-vox-90s.mp4` |
| 时长 | **86.0 s**（目标带 85–95s） |
| 分辨率 | 1920×1080 · H.264 · 30 fps · 无音轨 |
| 形态 | 静音动能信息图：弹入 / 砸字 / 宫格级联 / 数字计数 / 扫光 / 硬切+短叠化 |
| 分镜依据 | `../demo-storyboard-vox.md`（90s 骨架 A→H 压缩 15 镜） |
| 数字口径 | FP8 ~195 / BF16 ~118 / **+65%** · tool-call **8/9** · 35B ~**59–65 TPS** · 9B GGUF ~**13 t/s** |
| 片尾 | omima · AMD AI DevMaster · ModelScope `kooooon/omima-35B` · `omima-9B` |
| 明确不做 | 口播 TTS、BGM、1kHz 测试音、空几何 zoompan |

镜表与分镜：`../demo-storyboard-vox.md`（§2 分镜表 · §8 制作规格）。

```
evidence/
  INDEX.md          ← 本文件
  media/
    omima-vox-90s.mp4     ← 主演示
    omima-vox-main.mp4    ← 同内容副本
```

---

## 7. 边界（与专章一致）

- 消费级 Ryzen AI / MAX 整机：模式落位，本赛未逐台实测成绩。  
- MTP / KV / AITER 消融：不写入已完成优化。  
- 万级全量二轮 LoRA：数据就绪 ≠ 权重已训完。  
- VOX 主片为信息图叙事；实机录屏方案已废弃（成片以 VOX 交付）。

*索引与 submission 专章同步维护*
