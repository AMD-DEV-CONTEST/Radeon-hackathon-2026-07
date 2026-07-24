# GIF 录制指南

## 目录

1. [录制工具推荐](#录制工具推荐)
2. [录制内容规划](#录制内容规划)
3. [录制步骤](#录制步骤)
4. [GIF 优化](#gif-优化)
5. [添加到 README](#添加到-readme)

---

## 录制工具推荐

### Windows

| 工具 | 特点 | 推荐度 |
|------|------|--------|
| [ScreenToGif](https://www.screentogif.com/) | 免费、轻量、易用 | ⭐⭐⭐⭐⭐ |
| [LICEcap](https://www.cockos.com/licecap/) | 免费、开源、跨平台 | ⭐⭐⭐⭐ |

### macOS

| 工具 | 特点 | 推荐度 |
|------|------|--------|
| [GIPHY Capture](https://giphy.com/apps/giphycapture) | 免费、简单 | ⭐⭐⭐⭐ |
| [Kap](https://getkap.co/) | 免费、开源 | ⭐⭐⭐⭐⭐ |

### 在线工具

| 工具 | 链接 | 特点 |
|------|------|------|
| [ezgif.com](https://ezgif.com/) | 在线编辑 | 免费、无需安装 |

---

## 录制内容规划

### 建议录制顺序（30-60秒）

```
0:00-0:05  项目标题页面
0:05-0:10  打开终端，启动服务
0:10-0:15  打开浏览器，访问 Web UI
0:15-0:25  上传采购订单，展示处理结果
0:25-0:35  上传送货单，展示三单校验
0:35-0:45  展示异常检测（不匹配的单据）
0:45-0:50  展示对话查询功能
0:50-0:55  展示 GPU 信息（rocm-smi）
0:55-1:00  结束画面
```

### 录制分辨率

- **推荐**: 1280x720 (720p)
- **帧率**: 15-30 fps
- **格式**: GIF

---

## 录制步骤

### 步骤 1: 准备环境

```bash
# 启动 vLLM 服务
python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-3.1-8B-Instruct \
    --dtype half \
    --port 8000 &

# 启动 Web UI
python -m src.agent
```

### 步骤 2: 打开录制工具

1. 打开 ScreenToGif（或其他工具）
2. 设置录制区域为浏览器窗口
3. 设置帧率为 15 fps

### 步骤 3: 开始录制

1. 点击"录制"按钮
2. 按照规划的顺序操作
3. 每个操作停留 2-3 秒
4. 完成后点击"停止"

### 步骤 4: 编辑 GIF

1. 删除不必要的帧
2. 调整播放速度
3. 添加文字说明（可选）
4. 裁剪到合适大小

### 步骤 5: 保存 GIF

- **文件名**: `demo.gif`
- **位置**: `assets/demo.gif`
- **大小**: < 5MB（GitHub 限制）

---

## GIF 优化

### 使用命令行优化

```bash
# 安装 gifsicle（可选）
# Windows: scoop install gifsicle
# Mac: brew install gifsicle

# 优化 GIF
gifsicle -O3 --colors 128 input.gif -o output.gif
```

### 在线优化

访问 https://ezgif.com/optimize 上传并优化 GIF。

### 优化建议

1. **颜色数**: 限制在 128 色以内
2. **帧率**: 15 fps 足够
3. **尺寸**: 640x360 或 800x450
4. **时长**: 30-60 秒最佳

---

## 添加到 README

### 修改 README.md

在 README 的"演示"部分取消注释并更新：

```markdown
## 🎬 演示

![Supply Chain DocAgent Demo](assets/demo.gif)

**在线演示**: [http://localhost:7860](http://localhost:7860) (本地运行)

**演示视频**: [YouTube](#) (待录制)
```

### 创建 assets 目录

```bash
mkdir -p assets
# 将 demo.gif 复制到 assets/ 目录
cp demo.gif assets/
```

---

## 快速录制脚本

如果您想使用 Python 自动化录制，可以使用以下脚本：

```python
"""
屏幕录制脚本 - 使用 pyautogui
"""

import pyautogui
import imageio
import time
from datetime import datetime

# 配置
RECORD_SECONDS = 60  # 录制时长（秒）
FPS = 15  # 帧率
OUTPUT_FILE = "demo.gif"

# 开始录制
print(f"开始录制，将在 {RECORD_SECONDS} 秒后停止...")
print("请准备好演示...")

frames = []
start_time = time.time()

while time.time() - start_time < RECORD_SECONDS:
    # 截取屏幕
    screenshot = pyautogui.screenshot()
    frames.append(screenshot)
    
    # 控制帧率
    time.sleep(1 / FPS)

# 保存为 GIF
print("正在保存 GIF...")
imageio.mimsave(OUTPUT_FILE, frames, fps=FPS)

print(f"录制完成！文件保存为: {OUTPUT_FILE}")
```

### 安装依赖

```bash
pip install pyautogui imageio Pillow
```

### 运行脚本

```bash
python scripts/record_demo.py
```

---

## 注意事项

1. **关闭无关窗口** - 录制时只保留需要的窗口
2. **鼠标移动** - 保持鼠标在可见区域
3. **避免打字** - 打字速度太快会导致 GIF 过大
4. **预演** - 录制前先练习几遍
5. **测试** - 录制后检查 GIF 是否清晰

---

## 提交 GIF 到 GitHub

```bash
# 添加 GIF
git add assets/demo.gif

# 提交
git commit -m "Add demo GIF to README"

# 推送
git push origin submission
```

---

## 示例 GIF 结构

```
Radeon-hackathon-2026-07/
├── assets/
│   └── demo.gif          # 演示 GIF
├── README.md             # 引用 GIF
└── ...
```
