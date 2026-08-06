# 演示视频 · 操作流程与脚本（中文版）

项目：青汐灵隙 · 角色工坊（Qingxi Rift Character Workshop）
赛事：AMD AI DevMaster 黑客松 · 赛道一
建议时长：3:30–5:00。**视频/字幕用英文提交**；本中文文档供你本人对照操作用，**提示词保持英文**。

---

## 0. 录制前准备

| 项 | 准备 |
|----|------|
| 机器 | Radeon Cloud 实例（Navi31 / RX 7900 XTX 24GB），ROCm torch 就绪 |
| 代码 | `feature/character-workshop` 分支，拉到最新提交 |
| 模型 | `bash scripts/download_models.sh`（Qwen2.5-7B + SDXL 动漫模型） |
| 依赖 | `bash scripts/install_app_deps.sh` 跑通 |
| 录屏 | OBS 或系统录屏，1920×1080 全屏 |
| 语音 | 可选口播，或只用英文字幕 |
| 字体 | 不需要（卡片全英文） |

**录制前先热机**（把 7B + SDXL 载入内存，避免录制时等加载、更稳定）：

```bash
cd /persistent/qingxi-character-workshop/character-workshop
export MOCK=0
python3 - <<'PY'
from src.orchestrator import generate_card_job
r = generate_card_job("A Void traveler carrying a paper lantern", affinity_pref="Void", mock=False)
print("warmup", r.state)
PY
```

---

## 1. 录制顺序（时间盒）

| # | 段落 | 时长 | 画面内容 |
|---|------|------|----------|
| 1 | 片头 | 0:00–0:10 | 应用名、标语、"Powered by AMD Radeon + ROCm" |
| 2 | 硬件证明 | 0:10–0:35 | `rocm-smi`、device 检测、torch HIP |
| 3 | 启动应用 | 0:35–0:55 | `python3 app.py`，浏览器打开工作台 |
| 4 | 用例 1 · 完整出卡 | 0:55–2:20 | 用提示词池生成完整角色卡 |
| 5 | 用例 2 · 修订 | 2:20–3:00 | 一行修订说明，重绘 |
| 6 | 用例 3 · 参考图 | 3:00–3:40 | 上传草图 → 出卡受参考图影响 |
| 7 | 用例 4 · 多样性 | 3:40–4:30 | 3 条不同六系短提示词，快速混剪 |
| 8 | 收尾 | 4:30–5:00 | 一句话架构 + 致谢 |

---

## 2. 分段脚本

### 段落 2 · 硬件证明（0:10–0:35）

终端执行：

```bash
rocm-smi
python3 - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("hip", getattr(torch.version, "hip", None))
print("gpu", torch.cuda.get_device_name(0))
PY
```

口播/字幕："所有推理都在 AMD Radeon GPU 上通过 ROCm 软件栈本地运行。"

### 段落 3 · 启动应用（0:35–0:55）

```bash
export MOCK=0
export PORT=7860
python3 app.py
```

浏览器打开代理/tunnel 地址。指出：左栏输入、右栏结果、顶部 device 徽章显示 ROCm。

### 段落 4 · 用例 1：完整角色卡（0:55–2:20）

粘贴提示词，六系选 Void，点 **Generate Character Card**。
展示进度（Planning → Painting → Composing），再展示卡片。
下载并打开 card.png。讲解：原创设定 JSON + 动漫立绘 + 六维雷达 + 灵域。

### 段落 5 · 用例 2：修订（2:20–3:00）

卡片生成后不刷新页面，输入修订说明，点 **Apply Revision**。
展示外观/提示词变化、卡片重绘。

### 段落 6 · 用例 3：参考图（3:00–3:40）

上传一张简单草图（或自拍），描述角色，生成。
讲解：输出跟随参考图的姿势/发型，但保持原创动漫风格。

### 段落 7 · 用例 4：多样性混剪（3:40–4:30）

用提示词池里的 3 条短提示词快速生成，剪辑切换结果。
强调：不同六系 → 不同视觉关键词、雷达形状、设定文案。

### 段落 8 · 收尾（4:30–5:00）

一句话："文本（可加参考图）生成原创角色卡——全程本地 AMD Radeon。"

---

## 3. 提示词池（演示自选）

**主演示提示词（用例 1）：**

```
A quiet Void traveler in teal robes carrying a paper lantern
```

**修订说明（用例 2）：**

```
change to short golden hair
make the robe dark blue with silver trim
give them a soft smile
```

**参考图配套描述（用例 3）：**

```
A Form street performer whose jacket reshapes like clay
A Mind counselor who draws soothing runes with her fingertips
```

**多样性混剪（用例 4）——每个六系一条：**

```
A white-haired Life healer who keeps a pot of living moss
A silver-haired Mind rune master with pale blue eyes
A Matter heavy-armor fighter with a mineral crystal shield
A Form street performer whose jacket reshapes like clay
A Time clock keeper with a stopped pocket watch
A Void drone pilot who folds signal dead zones into shortcuts
```

**日常/生活化（可选加分）：**

```
A night-market candy-sugar artist who sometimes lets sugar strands float for three seconds
A primary-school music teacher who steadies a restless class by humming
A retired firefighter with a Matter shield and mineral-patterned burn scars
```

注意：
- 提示词必须原创（不出现第三方 IP 名称）。
- 3:30 演示选 3 条；5:00 演示选 5–6 条。

---

## 4. 后期检查清单

- [ ] 片头含应用名 + AMD Radeon + ROCm 字样
- [ ] 输入/输出画面无第三方 IP
- [ ] 英文字幕与口播一致
- [ ] 浏览器地址栏（proxy/tunnel）避免入镜（防暴露凭据）
- [ ] 最终导出 3–5 分钟、1080p、MP4

---

## 5. 录制中出错的现场应对

| 失败 | 镜头前怎么处理 |
|------|----------------|
| LLM JSON 报错 | 展示错误信息 + 说明"3 次尝试重试"设计，再点一次 |
| 出图 OOM | 说明降分辨率处理，重启应用 |
| 网络/API | 不存在——全本地，无需展示 |

**备用**：`outputs/` 里预存 1–2 张成功卡片图，若录制时实跑失败可切过去救场。
