# AMD Radeon Studio — 架构总览

## 1. 分层架构(自顶向下)

```
┌─────────────────────────────────────────────────────────────┐
│                       客户端 (Browser)                       │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP
┌──────────────────────────▼──────────────────────────────────┐
│  Gradio UI (src/ui/)                                         │
│  · pages/{text2image, img2img, style_transfer}              │
│  · components/{sidebar, header, model_picker, gallery}      │
│  · app.py — LibLibAI 风格布局(白底 + 左侧深色栏)            │
└──────────────────────────┬──────────────────────────────────┘
                           │ Python call
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI (src/api/)        ◀── 也可独立部署纯 API 服务       │
│  · routes/{text2image, img2img, style}                      │
│  · schemas.py (Pydantic v2)                                 │
│  · app.py — DI via Depends(模型实例单例)                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ BaseModel interface
┌──────────────────────────▼──────────────────────────────────┐
│  Models (src/models/)  — Strategy Pattern                   │
│  ┌──────────────────┬──────────────────┬──────────────────┐  │
│  │ Text2ImageSDXL   │ Img2ImgSDXL      │ StyleTransfer    │  │
│  │                  │ + ControlNet     │ IPAdapter        │  │
│  └──────────────────┴──────────────────┴──────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │ PipelineFactory.create_model(key)
┌──────────────────────────▼──────────────────────────────────┐
│  Core (src/core/) — 抽象层,无业务                             │
│  · BaseModel (abstract) + GenerationRequest / Result        │
│  · DeviceManager (ROCm / CUDA / CPU 自动检测)                │
│  · PipelineFactory (@register_model 装饰器)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ diffusers / transformers
┌──────────────────────────▼──────────────────────────────────┐
│  PyTorch (ROCm / CUDA 后端)                                 │
│  · SDXL · IP-Adapter · ControlNet                           │
│  · HF Hub + safetensors                                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  AMD Radeon GPU (Radeon Cloud · Linux + ROCm 6.1+)          │
│  · MI300X (192GB) / RX 7900 XTX (24GB) / PRO W7900 (48GB)   │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 数据流(以"风格迁移"为例)

```
[用户] 上传风格图 + 输入 prompt
   ↓
[Gradio] style_transfer page
   ↓ 构造 GenerationRequest(prompt, style_image=...)
   ↓
[FastAPI] /api/style 端点
   ↓ Pydantic 验证 + 调 service.generate(req)
   ↓
[Model] StyleTransferIPAdapter.generate(req)
   ↓ IP-Adapter pipeline(prompt, ip_adapter_image=style_image, ...)
   ↓ 推理 30 步
   ↓
[GPU]  SDXL UNet + IP-Adapter Cross-Attention
   ↓
[PIL]  list[Image.Image]
   ↓
[IO]   保存到 outputs/<uuid>.png
   ↓ base64 编码返回 Gradio
   ↓
[用户] 看到结果图 + 下载
```

---

## 3. 关键设计原则

| 原则 | 落地方式 |
|---|---|
| **依赖单向** | `ui → api → models → core`,绝不反向 |
| **业务/基础设施分离** | `core/` 不依赖具体模型;`models/` 不依赖 `ui`/`api` |
| **策略 + 工厂** | 加新模型 = 写一个 `BaseModel` 子类 + `@register_model`,不改其他 |
| **类型驱动** | `GenerationRequest` / `Pydantic schemas` 是唯一契约,IDE 提示贯穿全栈 |
| **资源管理** | `BaseModel.load()` / `unload()` 显式生命周期,避免 GPU 显存泄漏 |
| **可测性** | `core/` 完全无 I/O,可纯单元测;`models/` 用 `unittest.mock` 测逻辑 |

---

## 4. 文件职责速查(谁不能做什么)

| 文件 | 职责 | 禁止 |
|---|---|---|
| `core/device.py` | 设备检测 | 写具体模型 |
| `core/base_model.py` | 模型抽象 + 数据契约 | 写具体 pipeline |
| `core/pipeline_factory.py` | 模型注册/创建 | 写 IO / 业务 |
| `models/*.py` | 具体模型实现 | 改 `core/` |
| `api/routes/*.py` | HTTP 端点 | 直接调 `diffusers`(走 model) |
| `api/schemas.py` | 请求/响应类型 | 写业务 |
| `ui/pages/*.py` | Gradio 页面 | 直接 `import src.models.*`(走 api) |
| `ui/components/*.py` | 可复用组件 | 写页面逻辑 |
| `utils/*.py` | 工具函数 | import 业务模块 |

---

## 5. 部署拓扑

```
┌────────────────┐    HTTPS    ┌────────────────────────┐
│  浏览器(用户)  │ ──────────► │  AMD Cloud Instance    │
│  (任意设备)    │  ◄────────  │  (Linux + ROCm)        │
└────────────────┘             │  ┌──────────────────┐  │
                               │  │ Gradio (7860)    │  │
                               │  │   └─ FastAPI 内嵌│  │
                               │  └──────────────────┘  │
                               │  ┌──────────────────┐  │
                               │  │ AMD Radeon GPU   │  │
                               │  │ (ROCm + PyTorch) │  │
                               │  └──────────────────┘  │
                               └────────────────────────┘
```

> 比赛交付时,演示视频直接录 AMD Cloud 实例的 Gradio 界面,展示从输入到出图的全流程 + 实时 GPU 占用。

---

_Last updated: 2026-07-16 · D1_
