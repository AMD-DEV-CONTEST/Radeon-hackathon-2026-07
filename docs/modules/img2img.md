# 模块设计:图生图 (img2img)

> **状态**: 🚧 占位 — D3 待实现
> **负责模块**: `src/models/img2img.py`
> **对应 ADR**: [0001-why-sdxl](../decisions/0001-why-sdxl.md)

---

## 1. 为什么这么设计

业务需求:用户上传一张图 + prompt,产出基于原图结构的修改图。

- **底模**:SDXL img2img(同文生图,见 ADR 0001)
- **核心参数**:`strength` (0.0-1.0,改的力度)+ `image` + `prompt`
- **可选增强**:ControlNet(边缘/深度/姿势控制)— v0.1 走简单路线,ControlNet 留 v0.2

## 2. 设计优点

- **结构保留** — `strength=0.3-0.6` 时,原图布局基本保留,只改风格/细节
- **复用 pipeline** — `StableDiffusionXLImg2ImgPipeline` 加载同 SDXL 权重,无额外模型下载
- **可叠加风格** — 后续可加 IP-Adapter 做"风格 + 结构"双重控制

## 3. 能做什么

- ✅ 单图 + prompt → 1-4 张修改图
- ✅ `strength` 控制修改强度(0.1 微调, 0.8 大改)
- ✅ 任意尺寸输入(自动 resize 到 1024x1024)
- ✅ 与文生图共享 SDXL 权重(节省显存)
- ✅ 负向 prompt

## 4. 做不到什么

- ❌ 多图一致性(单图修改)
- ❌ 局部编辑(那是 inpainting 模块,v0.2+)
- ❌ 姿态/边缘控制(那要 ControlNet,v0.1 暂不集成)
- ❌ 保持人物身份(那是 IP-Adapter FaceID,v0.2+)

## 5. 实施清单(D3)

- [ ] `src/models/img2img.py`(< 300 行,继承 BaseModel)
- [ ] `src/api/routes/img2img.py`(POST /api/img2img,接收 multipart)
- [ ] `src/api/schemas.py` 加 `Img2ImgRequest` / `Img2ImgResponse`
- [ ] `src/ui/pages/img2img.py`(Gradio tab + 图片上传)
- [ ] `tests/unit/test_img2img.py`(mock pipeline + 验证 strength 处理)
- [ ] `notebooks/02_img2img.ipynb`(在 AMD Cloud 跑通)
- [ ] 更新本文档"设计细节"小节(完成后)

---

_占位 — D3 完成后填实_
