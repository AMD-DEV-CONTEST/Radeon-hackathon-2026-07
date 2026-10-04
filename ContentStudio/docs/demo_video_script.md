# Demo Video Script (3–5 Minutes) | 演示视频脚本

## Pre-Demo Preparation | 录制前准备

1. Ensure Content Studio is running | 确保 Content Studio 已启动
2. Pre-generate 1-2 articles in History | 历史记录里预存 1-2 篇文章（防现场慢）
3. Have JupyterLab open showing ComfyUI on AMD GPU | 打开 JupyterLab 展示 ComfyUI 在 AMD GPU 上运行

---

## Script

### [0:00–0:30] Introduction | 介绍

**Show:** Demo page (`/demo`)

**Narrate (CN):**
> 大家好，这是 Content Studio——一款基于 AMD Radeon GPU 和 ROCm 的 AI 多模态内容创作工具。它能把照片、主题和文字，一键转化成可发布的公众号文章和小红书笔记，配图还能自动风格化。

**Subtitle (EN):**
> Content Studio — an AI multimodal content creation tool built on AMD Radeon GPU with ROCm. It transforms photos, themes, and text into ready-to-publish articles with AI-styled images.

Point to architecture diagram:
**Narrate (CN):**
> 文本生成跑在 AMD GPU 上（Radeon Cloud 的 Qwen 模型），图像风格化跑在 ComfyUI + ROCm 6.2 上（AMD gfx1100 架构，48 GB 显存）。

**Subtitle (EN):**
> Text generation runs on AMD GPU (Qwen via Radeon Cloud). Image styling runs on ComfyUI with ROCm 6.2 on gfx1100 architecture, 48 GB VRAM.

---

### [0:30–1:00] GPU Proof | GPU 实证

**Show:** JupyterLab terminal with ComfyUI logs

**Narrate (CN):**
> 这是 ComfyUI 在 AMD Radeon GPU 实例上的运行日志——ROCm 版本 6.2，架构 gfx1100，49 GB 显存。模型是 DreamShaper 8，做风格迁移和文生图。

**Subtitle (EN):**
> ComfyUI running on AMD Radeon GPU instance — ROCm 6.2, gfx1100 architecture, 49 GB VRAM. Model: DreamShaper 8 for style transfer and text-to-image.

---

### [1:00–2:30] Live Generation | 实时生成

**Show:** Click "Start Now" → Main form

**Action:**
1. Upload 2-3 photos
2. Select style per photo (e.g., "Anime" for one, "None" for screenshot)
3. Type theme: "硬件老化测试：Burn-in Test 与 3DMark06"
4. Select template: "产品评测 / Product Review"
5. Select target: "公众号 / WeChat"
6. Click "一键生成 / Generate"

**Narrate (CN):**
> 我上传几张照片，每张单独选风格——这张选动漫风，这张截图选「无」（保留原图）。输入主题，选模板，选公众号，点一键生成。系统把照片发给 AMD GPU 上的视觉模型，看懂每张图的内容，然后生成文章、风格化图片，最后把图按内容放进文章里。

**Subtitle (EN):**
> Upload photos, assign per-photo styles, enter theme, select template, click Generate. The system sends photos to the vision model on AMD GPU, reads each image's content, generates the article, styles images, and places them logically.

Watch progress bar:
**Narrate (CN):**
> 可以看到进度——正在写文章，AMD GPU 上跑了大约 X 秒。

**Subtitle (EN):**
> Progress indicator — text generation took X seconds on AMD GPU.

---

### [2:30–3:30] Preview & Edit | 预览与编辑

**Show:** Preview page

**Narrate (CN):**
> 文章生成好了。注意看——3DMark 的截图被自动放到了讲 3DMark 的段落旁边，BurnIn 的截图放到了 BurnIn 段落旁边。视觉模型看懂了图里的内容，按逻辑摆放。

**Subtitle (EN):**
> Article ready. Notice: the 3DMark screenshot is placed beside the 3DMark section, BurnIn beside BurnIn — the vision model read the content and placed each image logically.

Demonstrate:
**Narrate (CN):**
> 正文可以直接编辑——改个字。图片可以拖动到任意位置。下方还有每张图的图注。计时显示文本 X 秒、出图 Y 秒，全在 AMD GPU 上。

**Subtitle (EN):**
> Body text is fully editable. Drag images to reposition. Captions below each photo. Timing: text Xs, images Ys — all on AMD GPU.

---

### [3:30–4:15] Publish | 发布

**Action:** Click "发到公众号草稿箱 / Publish to Draft Box"

**Narrate (CN):**
> 点一下「发到公众号草稿箱」，系统自动把文章和图片上传到微信服务器，直接进草稿箱，不用复制粘贴。

**Subtitle (EN):**
> One click — article with images uploaded to WeChat servers, enters draft box directly. No copy-paste needed.

Show media_id confirmation:
**Narrate (CN):**
> 发布成功，草稿已经进了公众号后台。

**Subtitle (EN):**
> Published successfully. Draft is now in the WeChat backend.

---

### [4:15–4:45] Additional Features | 更多功能

**Narrate (CN):**
> 不满意？点「重新生成」，同一输入再跑一次，每次结果不同。还能导出 HTML、打印 PDF。历史记录里所有文章都存着，随时回看。

**Subtitle (EN):**
> Not satisfied? Regenerate with one click. Export HTML, print PDF. History page saves all past articles.

Show quickly: Regenerate button → Export HTML → History page → Self-Check page

---

### [4:45–5:00] Closing | 结尾

**Narrate (CN):**
> Content Studio 展示了一个完整的 AMD GPU 多模态内容创作流水线——从 AI 写文（Qwen on AMD GPU），到视觉理解自动放图，到 ComfyUI 风格化出图（ROCm 6.2）。谢谢观看！

**Subtitle (EN):**
> Content Studio demonstrates a complete multimodal content creation pipeline on AMD Radeon GPU — from AI text generation (Qwen), to vision-based image understanding, to ComfyUI image styling (ROCm 6.2). Thank you.

---

## Tips | 录制提示

- If live generation is slow → show pre-generated article from History | 如果现场慢，展示历史记录里的成品
- If ComfyUI tunnel is down → photos use original style, still works | 如果 ComfyUI 断了，照片用原图，流程照跑
- Keep JupyterLab tab open as GPU proof throughout | 全程保持 JupyterLab 标签页打开作为 GPU 证明
- Use OBS Studio or Windows screen recorder (Win+G) | 用 OBS 或 Windows 自带录屏（Win+G）
- Record in 1080p, clear audio | 录 1080p，声音清楚
