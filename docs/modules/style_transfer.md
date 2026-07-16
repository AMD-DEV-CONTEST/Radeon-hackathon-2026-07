# 模块设计:风格迁移 (style_transfer)

> **状态**: 🚧 占位 — D4 待实现
> **负责模块**: `src/models/style_transfer.py`
> **对应 ADR**: [0002-why-ip-adapter](../decisions/0002-why-ip-adapter.md)

---

## 1. 为什么这么设计

业务需求:用户上传一张内容图 + 一张风格图,产出"内容用风格的画"的图。

- **核心**:IP-Adapter for SDXL(见 ADR 0002)— 零训练,1-3 秒
- **关键参数**:`ip_adapter_scale` (0.0-1.0,风格强度)
- **管道**:`StableDiffusionXLPipeline` + `IPAdapter` 加载

## 2. 设计优点

- **零训练** — 上传参考图即可,不需要 DreamBooth
- **风格/内容解耦** — 不会把参考图的内容强塞到输出
- **可调强度** — `ip_adapter_scale` 从 0.2(微染)到 0.9(强风格)
- **复用 SDXL 权重** — 只需额外下载 IP-Adapter (~1.5GB)

## 3. 能做什么

- ✅ 内容图 + 风格图 → 1-4 张风格化图
- ✅ `ip_adapter_scale` 0.0-1.0
- ✅ 与文生图/图生图 pipeline 共享 base 权重
- ✅ 风格强度实时调(同一 prompt 多个 scale 出多张对比)

## 4. 做不到什么

- ❌ "学"特定概念(你养的猫、某明星)— 那是 DreamBooth 路线
- ❌ 像素风/低多边形等极端风格(IP-Adapter 训练数据偏向自然风格)
- ❌ 视频级一致性(那是视频风格化,v0.2+)
- ❌ 风格 + 结构双重精确控制(那要 IP-Adapter Plus + ControlNet,v0.2+)

## 5. 实施清单(D4)

- [ ] `src/models/style_transfer.py`(< 300 行,继承 BaseModel)
- [ ] `src/api/routes/style.py`(POST /api/style,接收两张图)
- [ ] `src/api/schemas.py` 加 `StyleRequest` / `StyleResponse`
- [ ] `src/ui/pages/style.py`(Gradio tab + 双图上传 + 强度 slider)
- [ ] `tests/unit/test_style_transfer.py`(mock IPAdapter)
- [ ] `notebooks/03_style_transfer.ipynb`(在 AMD Cloud 跑通)
- [ ] 更新本文档"设计细节"小节(完成后)

---

_占位 — D4 完成后填实_
