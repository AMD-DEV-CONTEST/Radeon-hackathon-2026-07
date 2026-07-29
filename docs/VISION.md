# 图文解析（本地 OCR）

PrivateLocalAgent 支持上传图片并在本地完成文字识别，**不上传公网**。

## 用法

1. 底部点开 **图文解析** 模式（或任意模式）
2. 点 **上传图片**（png / jpg / webp / bmp）
3. 上传后会自动触发解析；也可手动说：`解析刚上传的图片` / `这张图里写了什么？`

## 引擎优先级

1. `rapidocr-onnxruntime`（推荐，`pip install rapidocr-onnxruntime Pillow`）
2. `pytesseract`（需系统安装 Tesseract）
3. 仅元数据 / 可选 BLIP 描述（`TRANSFORMERS_VISION=1`）

## 工具

```json
{"tool":"parse_image","args":{"name":"photo.png"}}
```

不传 `name` 时自动解析上传目录中最新图片。

## 代码

- `src/vision/image_parse.py`
- 工具：`ToolRegistry.parse_image`
- 模式：`vision` / UI「图文解析」
