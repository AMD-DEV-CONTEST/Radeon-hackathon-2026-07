# 模块设计:文生图 (text2image)

> **状态**: 🚧 占位 — D2 待实现
> **负责模块**: `src/models/text2image.py`
> **对应 ADR**: [0001-why-sdxl](../decisions/0001-why-sdxl.md)

---

## 1. 为什么这么设计

业务需求:用户输入一段 prompt,产出 1-4 张符合 prompt 的图片。

- **底模**:SDXL base(见 ADR 0001)— ROCm 兼容稳,生态全
- **接口**:`BaseModel` 抽象 + `@register_model("text2image")`
- **管道**:diffusers `StableDiffusionXLPipeline`,FP16

## 2. 设计优点

- **零侵入扩展** — 加 SD-Turbo 快速模式 = 新写一个类,不动现有
- **显存友好** — 默认 FP16;显存紧张时 `enable_model_cpu_offload()`
- **类型安全** — `GenerationRequest` 约束输入,IDE 提示贯穿
- **可测** — load/generate 都有 mock 点

## 3. 能做什么

- ✅ 单 prompt → 1-4 张图
- ✅ 负向 prompt(negative_prompt)
- ✅ 尺寸 512x512 ~ 1024x1024
- ✅ 步数 1-50(默认 30)
- ✅ guidance scale 0-20(默认 7.5)
- ✅ seed 锁定(可复现)
- ✅ 显存占用实时打印(在 result.extra 里)

## 4. 做不到什么

- ❌ 多图参考 / 角色一致性(那是 v0.2 InstantStory 路线)
- ❌ 中文 prompt 原生支持(SDXL token 限制,需翻译或用 mPrompt)
- ❌ 实时预览(必须等整张图生成完)
- ❌ 视频输出(那是图生视频模块)
- ❌ 显存 < 6GB 直接跑 SDXL(需降级 SD-Turbo)

## 5. 实施清单(D2)

- [ ] `src/models/text2image.py`(< 300 行,继承 BaseModel)
- [ ] `src/api/routes/text2image.py`(POST /api/text2image)
- [ ] `src/api/schemas.py` 加 `Text2ImageRequest` / `Text2ImageResponse`
- [ ] `src/ui/pages/text2image.py`(Gradio tab)
- [ ] `tests/unit/test_text2image.py`(mock pipeline 测逻辑)
- [ ] `notebooks/01_text2image.ipynb`(在 AMD Cloud 跑通)
- [ ] 更新本文档"设计细节"小节(完成后)

---

_占位 — D2 完成后填实_
