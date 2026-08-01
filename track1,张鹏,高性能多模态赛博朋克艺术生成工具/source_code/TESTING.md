# -*- coding: utf-8 -*-
# Aether Style AIGC Contest Testing Manual

## 1. Overview

AMD ROCm GPU 环境下 Aether Style 图生视频生成管线的标准测试流程，确保功能正确、性能达标、WebUI 可用。提交前所有项必须 100% 通过。

**测试范围**：
- 环境验证（ROCm / HIP / GPU，目标：gfx1100 RDNA3 W7900 48GB）
- Python 依赖校验
- 端到端测试 T1–T9（含 T8 万相视频、T9 Flux.1 文生图）
- Gradio WebUI 功能检查
- 性能基准（gfx1100 参考值）
- 故障排查 FAQ

---

## 2. Prerequisites

### 2.1 Hardware
- AMD GPU ≥ 8GB VRAM（竞赛目标 48GB：Flux 1216×832 + Wan2.1-T2V-14B 720P）
- 支持架构：gfx906/908/90a/940/941/942/1030/1100/1101/1102
- **竞赛参考机**：gfx1100 (RDNA3, 96 CU, 48GB VRAM, ROCk 6.16.13 → ROCm 6.2.x)

### 2.2 OS & ROCm
- Ubuntu 22.04 / 24.04 LTS，Kernel 5.15+
- ROCm 6.0.x – 7.0.x，`/opt/rocm` 软链接可用
- 用户加入 `render`、`video` 组

### 2.3 Software
- Python 3.9 – 3.12（推荐 3.10）
- pip ≥ 23.0，Git ≥ 2.30

> **注意**：项目通常挂载在 `/persistent/aether_style`，不要硬编码 `/workspace`。

---

## 3. Environment Verification

```bash
# GPU 与 VRAM
rocm-smi --showproductname --showhw --showmeminfo vram

# HIP 编译器
hipcc --version

# HIP 运行库
ldconfig -p | grep -i hip
ls -la /opt/rocm/lib/libamdhip64* 2>/dev/null || ls -la /opt/rocm/lib64/libamdhip64* 2>/dev/null

# rocminfo 关键信息
rocminfo | grep -E "Agent.*Name|Chip|Marketing|ComputeUnit|VRAM|HSA Runtime Version"
rocminfo | grep -c "Agent.*gfx"
```

**预期**：
- 至少 1 个 GPU agent；竞赛机应为 gfx1100，96 CU，≈48GB VRAM
- rocm-smi VRAM ≥ 49152 MB
- hipcc 输出版本号；libamdhip64.so 可解析

---

## 4. Python Environment

### 4.1 Strategy A（推荐，必须优先使用）— /opt/venv

**99% 情况不要自己建 venv**。竞赛镜像预装的 `/opt/venv` 已包含正确的 torch+HIP、gfx1100 目标、grpcio/protobuf 等底层依赖。

```bash
cd /persistent/aether_style
source /opt/venv/bin/activate
which python3   # 必须是 /opt/venv/bin/python3

# Pre-flight 检查：/opt/venv torch 是否可用
python3 - << 'PY'
import sys, torch
print("torch:", torch.__version__)
print("hip  :", getattr(torch.version, "hip", None))
print("cuda :", torch.cuda.is_available())
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print("dev  :", torch.cuda.get_device_name(0))
    print("arch :", getattr(p, "gcnArchName", None))
    print("vram :", round(p.total_memory/1024**3, 2), "GB")
else:
    sys.exit(2)  # exit=2 → /opt/venv 损坏，转 Strategy B
PY

# 安装 AIGC 应用依赖（必须用公共 PyPI，不要用 rocm 索引）
pip install --index-url https://pypi.org/simple/ -r requirements.txt

# 加固易被 pip resolver 搞乱的版本锁
# 【关键选择】diffusers/transformers 新版要求 huggingface_hub>=0.34，
#   而 gradio 4.44.x 内部 import 已被 HF 0.26 删除的 HfFolder 类。
#   方案一（推荐，新模型栈稳定）：保持 huggingface_hub>=0.34,<1.0（满足 diffusers/transformers），
#        由 app.py 顶部预埋 Appendix D 猴子补丁 stub HfFolder 兜底。
#   方案二（legacy，仅当补丁无效时）：huggingface_hub<0.26，但会与 diffusers>=0.39 冲突。
#   默认执行【方案一】。
pip install -U "protobuf>=6.31.1,<7.0" \
                "huggingface_hub>=0.34.0,<1.0" \
                "gradio==4.44.1" "gradio-client>=1.3.0,<1.4.0"

# 关键：验证三件套 + 通过补丁让 gradio 在高版本 hf_hub 下也能 import
python3 - << 'PY'
import sys, types
# 模拟 app.py 预埋的 Appendix D HfFolder 补丁（临时 import 时注入）
try:
    import huggingface_hub as _hf_hub; _hf_hub.HfFolder
except Exception:
    _stub = types.ModuleType('HfFolder_stub')
    _stub.get_token = staticmethod(lambda *a, **kw: None)
    _stub.save_token = staticmethod(lambda *a, **kw: None)
    _stub.delete_token = staticmethod(lambda *a, **kw: None)
    try: import huggingface_hub as _hf_hub
    except Exception: pass
    else: _hf_hub.HfFolder = _stub; sys.modules['huggingface_hub'].HfFolder = _stub
import gradio, gradio_client, google.protobuf, transformers, diffusers
print("gradio         :", gradio.__version__)
print("gradio_client  :", gradio_client.__version__)
print("huggingface_hub:", __import__('huggingface_hub').__version__)
print("protobuf       :", google.protobuf.__version__)
print("transformers   :", transformers.__version__)
print("diffusers      :", diffusers.__version__)
from huggingface_hub import HfFolder
print("HfFolder patch : OK at", HfFolder)
PY
# 所有版本号正常输出 + HfFolder patch OK = 加固完成

# 运行 env 模式确认绿
python3 test_flow.py --mode env
```

### 4.2 Strategy B（仅当 Strategy A pre-flight exit=2 时）

```bash
cd /persistent/aether_style
python3 -m venv venv_amd
source venv_amd/bin/activate

# 根据 ROCk 版本选对应 torch 索引（竞赛机 ROCk 6.16 → rocm6.2）
# ROCk 6.0x → rocm6.0 | 6.8x → rocm6.1 | 6.16x → rocm6.2 | 7.x → rocm7.0
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

# 验证 HIP torch
python3 -c "import torch; print(torch.cuda.is_available(), torch.__version__)"
# 必须输出 True，否则重来

# 安装 AIGC 依赖 + 加固锁（与 Strategy A 相同：默认方案一 hf_hub 0.34+ + app.py HfFolder 补丁）
pip install --index-url https://pypi.org/simple/ -r requirements.txt
pip install -U "protobuf>=6.31.1,<7.0" \
                "huggingface_hub>=0.34.0,<1.0" \
                "gradio==4.44.1" "gradio-client>=1.3.0,<1.4.0"
```

> gfx1100 + 旧 PyTorch wheel 报 `hipErrorNoBinaryForGpu` 时：
> ```bash
> export HSA_OVERRIDE_GFX_VERSION=11.0.0
> ```

---

## 5. Automated Test Runner (test_flow.py)

### 5.1 用法

```bash
cd /persistent/aether_style
source /opt/venv/bin/activate

# 帮助
python3 test_flow.py --help

# 模式 1：仅环境（<10s，不加载模型）
python3 test_flow.py --mode env

# 模式 2：冒烟测试 T1–T6 + T8 视频 fallback + T9 Flux/Wan 表面
python3 test_flow.py --mode smoke

# 模式 2b：轻量冒烟（跳过 Flux 24GB + Wan 28GB 下载/推理，仅 SD 快速路径 + T9 API 面）
#   首次在没缓存的测试机 / 慢网络 / CI 上跑，避免多 GB 下载把 suite 卡死时用。
python3 test_flow.py --mode smoke --no-heavy

# 生产启动（推荐）：run_light.sh 不在代码里写死弱模型，而是让引擎在"配置允许"下自动选最优：
#   文生图/图生图 → Flux.1-dev(若授权+有空间) > SDXL > SD v1.5
#   文生视频     → Wan2.1-14B(若磁盘余量够) > Wan2.1-1.3B > damo-vilab 1.7b
#   磁盘不足时自动跳过/降级，gated/配额满不崩溃，始终回退到可跑模型。
bash run_light.sh

# 图像模型选择（AETHER_SD_MODEL，影响 WebUI 文生图 / 图生图 + smoke 的 SD 路径）
#   默认 SDXL（~7GB, 非 gated, 比 v1.5 好一档）；小盘机若 SDXL 装不下会自动回退 SD v1.5：
export AETHER_SD_MODEL=sdxl            # 可选: sdxl (默认) / v1.5 / 任意 HF repo id 或本地路径
python3 app.py                         # 启动后图像生成走 SDXL（失败自动回退 SD v1.5，不会彻底失败）
# 注：SDXL 原生分辨率 1024；WebUI 文生图滑块默认已调为 512–1536 / 值 1024。

# 视频模型选择（仅 WebUI / 全量视频生成生效，smoke --no-heavy 不加载视频模型）
#   ★ 不设置 AETHER_WAN_MODEL 时，引擎按"磁盘余量"自动选最优：余量 ≥ ~33GB 用 14B，
#     否则自动降级 1.3B（~6GB），仍装不下再回退 damo-vilab 1.7b。这就是"配置允许下用最好模型"。
#   也可显式强制：
export AETHER_WAN_MODEL=1.3B          # 可选: 14B (默认, 自动) / 1.3B / 任意 HF repo id 或本地路径
python3 app.py                        # 启动后视频生成走对应 Wan2.1 变体
# 注：Wan 加载失败（权重不完整/缺分片/磁盘满）不再崩溃，会自动回退 legacy damo-vilab T2V；
#     回退也失败则 app.py 捕获并返回友好错误，不会让进程挂掉。

# Flux 模型选择（AETHER_FLUX_MODEL，仅 WebUI / 全量 Flux 推理生效）
#   默认 FLUX.1-schnell 是开源、非 gated 的（Apache-2.0，4 步，~24GB），无需任何授权即可直接下载；
#   已放弃 gated 的 FLUX.1-dev（需 HF 授权 token，会 403），仅当你已授权才显式切换：
export AETHER_FLUX_MODEL=schnell        # 默认即 schnell（开源）；可选: dev (gated, 需授权) / 任意 HF repo id 或本地路径
python3 app.py                           # 启动后用 schnell 跑 Flux 文生图（仍需 ~24GB 空间）
# 注：dev 加载遇 403/gated 时 app.py 不再崩溃，会打印清晰的授权指引并禁用 Flux Txt2Img。

# 模式 3：全量测试 T1–T9（含 Flux 推理、Wan 视频、T7 基准）
python3 test_flow.py --mode full --benchmark-steps 30

# 自定义输出目录（产物和报告分离）
python3 test_flow.py --mode full \
    --output-dir /tmp/aether_artifacts \
    --report-dir /persistent/aether_style/test_reports

# 只传 --output-dir：报告自动写入 $OUTPUT_DIR/test_reports/
python3 test_flow.py --mode full --benchmark-steps 50 \
    --output-dir /tmp/aether_grading_artifacts
```

**产物写入位置**：
- 图片/视频/GIF → `output_dir`（默认 `<repo_root>/outputs`）
- JSON 报告 → `report_dir/test_report_YYYYMMDD_HHMMSS.json`（默认 `<repo_root>/test_reports/`）
- 日志无独立文件，需要时用 `2>&1 | tee test_reports/run.log` 重定向

### 5.2 测试项定义 T1–T9

| ID | 名称 | 验证内容 |
|----|------|----------|
| T1 | 环境依赖 | Python≥3.8；torch+cuda OK；8 个核心库可 import；FluxPipeline/WanPipeline 可导入性；目录结构 |
| T2 | 引擎初始化（SD v1.5） | SD v1.5 管线实例化，device=CUDA，无 OOM |
| T3 | 基础图像操作 | Image.new、PNG 读写、resize、RGBA→RGB 往返 |
| T4 | Img2Img 快速推理 | SD v1.5 Img2Img 2 步 512×512；输出有效 RGB 且落盘 |
| T5 | Txt2Img 快速推理 | SD v1.5 Txt2Img 2 步 256×256；文件 > 0 |
| T6 | 边界用例 | 奇数尺寸、空 prompt、极端 strength、RGBA 输入均不抛异常 |
| T7 | 性能基准（SD Img2Img） | `--benchmark-steps` 控制步数；记录均耗时、每步耗时、VRAM 峰值 |
| T8 | 文生视频（Wan2.1 优先） | **首选 Wan2.1**：smoke=3步9帧320×240；full=20步33帧832×480。失败则 fallback damo-vilab。断言：MP4>10KB 且 ≥2 帧 |
| T9 | Flux.1 集成 | API 表面检查；懒加载时报 `RuntimeError("Flux.1 model is not loaded")`；已加载时 2 步 768×768 生成非空 PNG |

---

## 6. Pass / Fail Criteria

| Test | 通过标准 |
|------|----------|
| T1 | torch+cuda OK；8 核心库可 import；Flux/Wan Pipeline 可导入性记录；目录 OK |
| T2 | SD v1.5 引擎初始化成功；无 OOM |
| T3 | 像素 round-trip 一致；resize/转换无异常 |
| T4 | Img2Img 返回有效 RGB 图并落盘 |
| T5 | Txt2Img 返回有效 RGB 图并落盘 |
| T6 | 5 个边界子用例均无异常；输出文件存在 |
| T7 | 基准完成；耗时有限；VRAM 峰值已记录 |
| T8 | 视频 MP4 > 10KB 且 ≥2 帧；Wan2.1 或 fallback 路径均算通过 |
| T9 | Flux API 存在；懒加载抛正确 RuntimeError；已加载时 768px 推理非空 PNG |

**整体通过阈值：9/9 = 100%**。T8/T9 接受 fallback 路径保持旧环境绿色，但**竞赛答辩演示必须展示原生 Wan2.1 + Flux 推理**。

---

## 7. Performance Benchmarks

### 7.1 实时监控

```bash
# Terminal A：GPU 监控（保持打开）
watch -n 1 rocm-smi --showuse --showmeminfo vram

# Terminal B：运行基准
cd /persistent/aether_style && source /opt/venv/bin/activate
python3 test_flow.py --mode full --benchmark-steps 30 --output-dir /tmp/aether_bench
```

### 7.2 参考指标（gfx1100 RDNA3 W7900 48GB，ROCk 6.16 → ROCm 6.2）

| 负载（默认参数） | GPU% | VRAM (GB) | 每步耗时 (s/step) |
|------------------|------|-----------|-------------------|
| SD v1.5 Txt2Img 512×512, 30 steps | >90 | 3–5 | 0.30–0.70 |
| Flux.1 Dev, 28 steps, bf16 offload | >88 | 20–32 | 1.20–2.50 |
| Wan2.1-T2V-14B 480P (832×480), 30 steps, 49f | >92 | 32–42 | 1.50–3.20 |
| **Wan2.1-T2V-14B 720P (1280×720), 30 steps, 81f（答辩档）** | >90 | 38–47 | 3.20–6.00 |

> GPU% 持续 <50% → 查 FAQ #12 / #15（HSA override / pipeline 落 CPU）。

---

## 8. WebUI (app.py) Validation Checklist

### 8.1 启动

```bash
cd /persistent/aether_style && source /opt/venv/bin/activate
# export HSA_OVERRIDE_GFX_VERSION=11.0.0   # 旧 torch + gfx1100 时
python3 app.py --host 0.0.0.0 --port 7860 --no-ssl
```

浏览器打开 `http://<host>:7860`（Chromium 系）。

### 8.2 检查项

#### 基础（1–17，至少通过 16/17）

1. 页面 20s 内完成首屏加载（Wan/Flux 懒加载，首屏快）
2. 顶部「Environment Status」手风琴可展开；显示 Python/torch/cuda=True/GPU 名/VRAM/Flux 状态/Wan 状态
3. 环境状态面板内部无中文乱码或问号
4. Tab 2 (Img2Img SD fallback) 预设按钮可填入 prompt，无 JS 错误
5. Img2Img 上传 512×512 JPEG；缩略图显示正常
6. Steps=30、Strength=0.75、Guidance=7.5、Seed=42 可设置
7. Img2Img 30-step 生成完成；outputs 产物 ≥200KB
8. Tab 3 (Txt2Img SD)「Cyberpunk」预设 + Steps=30 Seed=1234 生成成功
9. 生成时状态框显示英文 Running/Step X/Y/Done，无中文乱码
10. 硬刷新 (Ctrl+Shift+R) 后 UI 状态正常，按钮可用
11. Share 按钮能出 gradio.live 链接（失败则用 FAQ #10/#11 隧道）
12. 生成期间 rocm-smi GPU% >90%
13. 底部 Tips 提及 Flux.1 / Wan2.1 / diffusers≥0.32 / modelscope

#### Tab 1 — Flux.1（18–28，需 11/11）

18. Tab 1 标签：`? Flux.1 文生图（最高画质·推荐）`
19. 分辨率下拉 ≥6 项（含 1024×1024 1:1、1216×832 3:2、832×1216 2:3，均 8-aligned）
20. 高级提示词模板下拉 ≥5 条英文模板（chiaroscuro / shallow DOF 等）
21. Steps 默认 28、Guidance 3.5；标注「Flux 不支持负向提示词」
22. 「Flux 模型管理」折叠区：路径输入框 + Reload 按钮 + 状态框
23. 点预设模板可填入英文电影级 prompt
24. **Flux 已缓存**：Steps=4 size=768×768 Seed=42 → 输出 ≥500KB、尺寸 ≥768px
25. **Flux 未加载**：Generate 提示 `Flux.1 model is not loaded`，无崩溃
26. Reload Flux（空路径）显示可读状态，非 500
27. 完整演示：1024×1024 28 steps guidance 3.5 → 35–70s，VRAM 20–32GB
28. 产物 PNG ≥2.5MB，画面内容匹配描述

#### Tab 4 — Wan2.1 文生视频（29–40，需 12/12）

29. Tab 4 标签：`? 文生视频（阿里万相 Wan2.1·默认）`
30. 顶部 Markdown 提及 Apache 2.0 / VBench #1 / umT5 中文 / **720P 档 = 81帧 30步 Guidance5.0**
31. 中文提示词模板 ≥5 条（都市雨夜/女孩跟拍/全息鲸/机械义手/隧道狂飙）
32. 分辨率下拉：480P(832×480) / 576P(1024×576) / 720P(1280×720)（均 16 倍数）
33. 时长/帧数下拉：2s-33f / 3s-49f / 4s-65f / 5s-81f（均 N = k×8-1）
34. Steps 默认 30 (10–60)、Guidance 默认 5.0 (1–15)、FPS 默认 16 (8–24)
35. Seed 控件（默认 42）
36. 「Wan2.1 模型管理」折叠区：HF/local 路径 + Reload + 状态
37. **Wan 未缓存（smoke）**：480P 2s Steps=4 Seed=42 中模板 → 状态显示引擎类型；fallback 也需 MP4>10KB
38. **Wan 已缓存（答辩档）**：720P 5s-81f Steps=30 Guidance=5.0 Seed=42 → ~4–8 min，VRAM 38–47GB，MP4 ≥12MB 81帧 16fps 可在画廊播放
39. Reload Wan 指向缓存目录 → 状态 `pipeline ready`，重载 <5s
40. 底部 Tips 含 `diffusers >= 0.32 (WanPipeline)` 和 `modelscope (国内镜像可选)`

**最低通过：36/40**。

---

## 9. Troubleshooting FAQ

> 竞赛机 u-7839 关键参数：ROCk 6.16.13（ROCm 6.2）、GPU gfx1100 W7900 48GB、项目在 `/persistent/aether_style`。

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | `rocm-smi: command not found` | ROCm 未装或 PATH 缺 `/opt/rocm/bin` | `export PATH=/opt/rocm/bin:$PATH; export LD_LIBRARY_PATH=/opt/rocm/lib:/opt/rocm/lib64:$LD_LIBRARY_PATH`；用户加入 render/video 组后重新登录 |
| 2 | 激活 venv 后 `import torch` 报 ModuleNotFound | 错激活了空 venv 或切了 shell | `deactivate && source /opt/venv/bin/activate && which python3`，确认输出 `/opt/venv/bin/python3` |
| 3 | `torch.cuda.is_available()=False` | 装了 CPU-only torch，或 HIP 库不在 LD | 用 Strategy A（/opt/venv）；Strategy B 重新走 ROCm 索引装 torch；`ldd $(python3 -c "import torch;print(torch._C.__file__)")` 确认无 `not found` 项 |
| 4 | `pip install -r requirements.txt` 报 diffusers / sentencepiece / av 无匹配分发 | pip.conf 或 CLI 把 --index-url 锁成 ROCm 索引（只有 torch 家族） | 显式 `pip install --index-url https://pypi.org/simple/ -r requirements.txt` |
| 5 | Flux / Wan 720P 加载或推理时 HIP OOM | 分辨率/帧数太高或并行进程吃 VRAM | Wan 720P 81f 峰值 42–46GB；关其他 GPU 进程（rocm-smi --showpids）；确认 engine.py 已启用 `enable_model_cpu_offload + enable_vae_slicing + enable_attention_slicing("auto")`；临时降档或重启节点 |
| 6 | Wan/Flux 首载卡住 >10 分钟 | HF 下载被 egress 防火墙拦截或路由慢 | `export HF_ENDPOINT=https://hf-mirror.com`；`pip install -U modelscope>=1.18.0`；保持 `~/.cache/huggingface/hub` 跨重启不丢 |
| 7 | Flux/Wan 输出全黑/噪图 | bf16/fp16 下溢 NaN，或 VAE half bug，或模型缓存损坏 | 把 VAE 转 fp32：`pipe.vae.to(torch.float32)`；删除缓存目录（`~/.cache/huggingface/hub/models--Wan-AI--*`、`models--black-forest-labs--*`）后通过 HF_ENDPOINT 重下 |
| 8 | ASGI worker 报 `TypeError: argument of type 'bool' is not iterable` + gradio_client schema 异常 | Gradio 4.44 客户端/服务端 OpenAPI schema 不匹配 | (a) 见附录 A 猴子补丁；(b) 加固：`pip install -U gradio==4.44.1 "gradio-client>=1.3.0,<1.4.0"`；(c) app.py 启动参数加 `show_api=False, debug=False` |
| 9 | 告警 `NUMA balancing enabled, performance may be slower` | 双路 AMD EPYC 主机 NUMA 平衡策略引入跨 Node 页迁移开销 | `echo 0 | sudo tee /proc/sys/kernel/numa_balancing`；持久化加 `kernel.numa_balancing=0` 到 `/etc/sysctl.d/99-numa.conf` 并 `sysctl -p`（Flux/Wan 提速 5–15%） |
| 10 | Share 按钮报 `Missing file: frpc_linux_amd64_v0.2` | Gradio 自带 frp 二进制下载被拦截 | 运行附录 B 的 `install_frpc.sh` 一键安装；或手动 scp 二进制到 `venv/site-packages/gradio/frpc/`；或改用附录 C cloudflared 隧道（无需 frp） |
| 11 | Share URL 已生成但浏览器 unreachable/超时 | 校园/云防火墙拦了 gradio.live 隧道入向 TCP 7000-7999 | 用附录 C **cloudflared 零注册隧道**（首选）或 ngrok；两者都仅走 443 出向，普遍放行 |
| 12 | 视频生成报 `does not appear to have a file named ... diffusion_pytorch_model-0000X-of-0001Y.safetensors` | Wan 权重是**半成品下载**（分片缺失），且旧代码 `from_pretrained` 未捕获异常 → 进程崩溃，连 legacy 回退都跑不到 | (a) 先删半成品释放配额：`rm -rf /persistent/aether_style/models/Wan2.1-T2V-14B-Diffusers`；(b) 小盘机改用 1.3B：`export AETHER_WAN_MODEL=1.3B` 再启动 `app.py`；(c) 已修复：Wan 加载失败不再崩溃，自动回退 legacy damo-vilab T2V，回退也失败则 app.py 返回友好错误 |
| 13 | Flux 报 `Access to model black-forest-labs/FLUX.1-dev is restricted ... 403` | `FLUX.1-dev` 是 **gated 模型**，需 HF 账号申请授权 + `huggingface-cli login`，否则下载被拒；与磁盘/版本无关 | (a) 去 https://huggingface.co/black-forest-labs/FLUX.1-dev 点 Request access，再用已授权 token `huggingface-cli login`；(b) 想跳过授权：改用非 gated 的 `export AETHER_FLUX_MODEL=schnell` 再启动 `app.py`；(c) 或把已授权权重放到本地目录，`export AETHER_FLUX_MODEL=/abs/path/to/FLUX.1-dev`；(d) 小盘机 24GB 装不下 Flux，dev/schnell 都会因配额满失败——这种机器 Flux 应禁用，SD+Wan1.3B 仍可用 |
| 12 | WebUI 推理慢；rocm-smi GPU% <50% 占多数 | pipeline 落 CPU、attention slicing 过度、device 字符串错误、gfx1100 缺 HSA override | 先跑 T1；`pipe.device.type=='cpu'` 就修 FAQ #3；调整 attention slicing；rocm-smi --showpids 看 python3 有非零 GPU%；stderr 有 `hipErrorNoBinaryForGpu` 就 FAQ #15 |
| 13 | protobuf 冲突：`grpcio-reflection 1.78.0 requires protobuf>=6.31.1,<7` 但装了 5.29.6 | diffusers/transformers 旧松绑到 `>=3.20,<6` 与镜像内 grpcio-reflection 1.78 冲突 | 加固：`pip install -U "protobuf>=6.31.1,<7.0"`；校验：`python3 -c "import google.protobuf, grpc_reflection, grpc_tools, transformers; print('protobuf:', google.protobuf.__version__, '→ ok')"`（sentencepiece + umT5/T5 在 6.33.x 下 OK） |
| 14 | Wan 推理报 TypeError：`flow_shift` 或 `export_to_video output_path/video_path` 关键字不认 | diffusers 0.30 vs 0.32+ API 漂移（flow_shift→shift→scheduler.config；导出参数名/返回类型变） | engine.py 已用**签名探测 wrapper** 兜住两个问题：flow_shift 会检查 `inspect.signature(WanPipeline.__call__)` 必要时写 `pipeline.scheduler.config['shift'|'flow_shift']`；导出有 `_safe_export_to_video/gif` 4 级 fallback。**拉取 2026-07-29 之后的 engine.py**，不要手改 kwargs |
| 15 | **仅 gfx1100**：任何推理起 `hipErrorNoBinaryForGpu` 或 VRAM 显示 <1GB | 装的 PyTorch ROCm wheel 太旧（fatbin 不含 gfx1100），如 Strategy B 选了 rocm6.0 | (1) Strategy B：重装 torch 走 ROCm 6.2 索引（含 gfx1100 fatbin）；(2) 快速 work around：`export HSA_OVERRIDE_GFX_VERSION=11.0.0`（写进 ~/.bashrc 持久化）；(3) 验证：`python3 -c "import torch; print(torch.cuda.get_device_properties(0).gcnArchName)"` 输出 `gfx1100:...` |
| 16 | `import gradio` 报 `ImportError: cannot import name 'HfFolder' from 'huggingface_hub'`（**或**加固时报反向冲突：diffusers 0.39/transformers 4.57 需要 hf_hub>=0.34） | 死锁根因：huggingface_hub 0.26+ 删除了 HfFolder，但 gradio 4.14–4.44 硬引用了它；同时 **diffusers>=0.39 / transformers>=4.57 要求 hf_hub>=0.34**，两方版本区间无交集。§4 默认【方案一】推荐做法是 hf_hub 0.34–1.0 + app.py 顶部预埋 Appendix D HfFolder 补丁（让 gradio 能 import）。老做法（方案二、仅在确认用旧版 diffusers<0.39 时可用：加固 `huggingface_hub<0.26`） | 【方案一 · 推荐 · 默认】保持高版本 hf_hub（满足新模型栈），由补丁兜底：(1) 加固 `pip install -U "huggingface_hub>=0.34.0,<1.0" gradio==4.44.1 "gradio-client>=1.3.0,<1.4.0`；(2) 确认 app.py 顶部已嵌入 **Appendix D 的 HfFolder stub 补丁（2026-07-30 起已预埋，无需手加）；(3) 验证：`python3 -c "import huggingface_hub, gradio, diffusers; print('hf:', huggingface_hub.__version__); from huggingface_hub import HfFolder; print('OK')"`。**方案二 · legacy（只在 diffusers<0.39 且不升级时用）：降级所有组件不推荐会触发反向冲突，不推荐。**如果方案一仍报错，回退到 §4.1 末尾写好的补丁段内的内联补丁脚本直接做临时 import 注入即可。 |

---

## 10. Appendices

### Appendix A — gradio_client schema 猴子补丁

**贴在 `app.py` 最顶部，`import gradio as gr` 之前**：

```python
import sys, os

def _patch_gradio_client_schema():
    try:
        from gradio_client import utils as _gc_utils
        _orig = _gc_utils.get_schema_type_string
        def _safe(t, *a, **kw):
            try:
                return _orig(t, *a, **kw)
            except Exception:
                if isinstance(t, bool): return "boolean"
                if t is None or t == type(None): return "null"
                return "string"
        _gc_utils.get_schema_type_string = _safe
    except Exception:
        pass

_patch_gradio_client_schema()
```

### Appendix B — frpc 一键安装脚本

存为 `install_frpc.sh` 然后 `bash install_frpc.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
FRPC_FN="frpc_linux_amd64_v0.2"
TARGET_DIR=""
for c in \
  "$(python3 -c 'import gradio,os;print(os.path.dirname(gradio.__file__))')/frpc" \
  "/opt/venv/lib/python3.10/site-packages/gradio/frpc" \
  "$HOME/.local/share/gradio/frpc"; do
  if [ -d "$(dirname "$c")" ]; then
    mkdir -p "$c" 2>/dev/null || true
    TARGET_DIR="$c"; break
  fi
done
[ -z "$TARGET_DIR" ] && { echo "ERROR: cannot locate gradio frpc dir"; exit 1; }
TARGET="${TARGET_DIR}/${FRPC_FN}"
[ -x "$TARGET" ] && { echo "frpc already installed at $TARGET"; exit 0; }
echo "Installing $FRPC_FN into $TARGET_DIR ..."
URLS=(
  "https://cdn-lfs-us-1.huggingface.co/repos/9a/5e/9a5ee1e7/frpc_0.5.1_linux_amd64/${FRPC_FN}"
  "https://raw.githubusercontent.com/gradio-app/gradio/main/gradio/frpc/${FRPC_FN}"
  "https://ghfast.top/https://github.com/gradio-app/gradio/raw/main/gradio/frpc/${FRPC_FN}"
)
OK=0
for U in "${URLS[@]}"; do
  echo "Trying: $U"
  if curl -fsSL --max-time 60 -o "${TARGET}.tmp" "$U"; then
    mv "${TARGET}.tmp" "${TARGET}"; chmod +x "${TARGET}"; OK=1
    echo "Install OK via mirror"; break
  fi
  rm -f "${TARGET}.tmp"
done
[ "$OK" -ne 1 ] && {
  echo "ALL MIRRORS FAILED. Manual: scp $FRPC_FN from reachable host then:"
  echo "  scp ./$FRPC_FN user@host:$TARGET && ssh user@host chmod +x $TARGET"
  exit 2
}
sha256sum "$TARGET"
"$TARGET" --version 2>&1 | head -1 || true
```

### Appendix C — cloudflared / ngrok 公网隧道

**C.1 cloudflared（零注册、零账号，优先）**

```bash
curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared
cloudflared tunnel --url http://127.0.0.1:7860 --no-autoupdate
# 读取 INF 行里的 https://RANDOM.trycloudflare.com，浏览器打开即可
```

**C.2 ngrok（需免费账号+authtoken，备选）**

```bash
curl -fsSL -o /tmp/ngrok.zip https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.zip
unzip -o /tmp/ngrok.zip -d /usr/local/bin/ && chmod +x /usr/local/bin/ngrok
ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN_HERE
ngrok http 7860 --log stdout
# Forwarding 行输出 https://RANDOM.ngrok-free.app
```

### Appendix D — HfFolder 猴子补丁（huggingface_hub ≥0.26 应急）

**贴在 app.py 最顶部，所有 import 之前**：

```python
import sys, types
try:
    import huggingface_hub as _hf_hub; _hf_hub.HfFolder  # probe
except Exception:
    _stub = types.ModuleType('HfFolder_stub')
    _stub.get_token = staticmethod(lambda *a, **kw: None)
    _stub.save_token = staticmethod(lambda *a, **kw: None)
    _stub.delete_token = staticmethod(lambda *a, **kw: None)
    try: import huggingface_hub as _hf_hub
    except Exception: pass
    else: _hf_hub.HfFolder = _stub; sys.modules['huggingface_hub'].HfFolder = _stub
```

### Appendix E — 评分 Rubric 映射（总 100 分，5 类各 20%）

提交前执行：
```bash
python3 test_flow.py --mode full --benchmark-steps 50 \
    --output-dir /tmp/aether_grading_artifacts
```
把整个 `/tmp/aether_grading_artifacts/` 打包即可。

| 类别 | 权重 | 评分点 | 需收集的产物 |
|------|------|--------|--------------|
| 环境 Environment | 20 | ROCm 验证；torch.cuda=True；gfx1100+ROCk6.16 记录；T1 全过；sentencepiece 装妥；WanPipeline+FluxPipeline 导入报告 | `test_report_<TS>.json` 顶层元数据 + T1.details；rocm-smi --showproductname --showmeminfo vram 截图；`python3 -c "import torch,diffusers; print(torch.cuda.is_available(), getattr(torch.cuda.get_device_properties(0),'gcnArchName',None), diffusers.__version__)"` 输出 |
| 功能 Functional | 20 | T2 引擎 init；T3 图像 ops；T4 img2img；T5 txt2img；T6 边界；**T8 视频 MP4 >10KB；T9 Flux API+条件推理** | test_report.json tests 数组全 pass=true；T4/T5/**T9 Flux** 样例 PNG；**T8 Wan 或 fallback 样例 MP4** |
| 性能 Performance | 20 | T7 基准完成；per-step 记录；VRAM 峰值；可选 Flux 1024×1024 28-step + Wan 480P 49f 计时；期间 GPU%>90% | test_report.json T7 + benchmark 字段；T7、Flux 全量、Wan 480P 全量三次 rocm-smi 监控截图（或合成一张） |
| UI | 20 | 基础 16/17；**Flux Tab 11/11**；**Wan Tab 12/12**；环境手风琴同时显示 Flux+Wan loaded 行；Tips 提 diffusers≥0.32 | 展开后的环境手风琴整页截图（Flux+Wan 都可见）；Flux Tab 1024×1024 28-step 结果截图；Wan Tab 720P 81f 30-step 画廊播放截图；Tab 4 Tips 中 diffusers≥0.32 / modelscope 行截图 |
| 展示 Presentation | 20 | README 清晰提 Flux+Wan；仓库整洁（别把 50GB 权重 commit！）；TESTING.md 与 T1–T9 同步；脚本可执行；submission.zip 解包干净；无硬编码密钥；engine.py/app.py/test_flow.py/requirements.txt 一致 | README.md；tree 清单；TESTING.md 副本；test_flow.py --help 输出；submission.zip sha256 manifest；1–2 句说明为什么选 Flux+Wan 代替原 SD v1.5 + damo-vilab baseline（贴合竞赛审美/文字理解评分点即可） |
