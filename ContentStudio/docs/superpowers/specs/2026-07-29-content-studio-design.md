# Content Studio 设计文档

- **日期:** 2026-07-29
- **状态:** 已通过口头评审，待用户书面确认
- **作者:** brainstorming 会话产出

## 1. 目标与范围

做一个 **Windows 桌面 GUI 程序**：用户投入「图片 + 文字」，**一键**用 AI 改写出：

1. **微信公众号**长文（标题 + 摘要 + 正文 HTML + 配图说明）
2. **小红书**笔记（标题 + 带 emoji 正文 + 话题标签 + 封面主标题）

同时**自动处理图片**（小红书 3:4 封面、大字标题、水印、多图拼接；公众号卡片封面 + 正文配图压缩）。

### 分阶段范围

- **第一阶段（MVP，本次实现）：** 输入 → AI 改写 → 图片处理 → 在 GUI 内预览 / 一键复制 / 导出图片。完整闭环、可独立运行。
- **第二阶段（后置，本次不实现）：** 公众号官方 API 自动发布（草稿 + 发布）。原因是该功能依赖**认证过的企业/组织主体公众号**，用户当前不确定其账号资质，作为可配置开关后置接入。小红书无开放发布 API，始终走手动复制。

> 第二阶段在设计中预留接口（`publish/wechat.py` + 配置开关），但本文档的验收范围限定在第一阶段。

## 2. 非目标（YAGNI）

- 不做小红书自动发布（无开放 API）。
- 不做浏览器/客户端模拟点击发布（不稳定、有封号风险）。
- 不做多账号矩阵管理。
- 不做内容排版编辑器（输出即为成品，复制即用）。
- 不做云端/多端同步（本地桌面程序）。

## 3. 选定方案

在三个候选方案中选定 **方案 A（分阶段 MVP）**，并借鉴方案 C 的模块化（核心逻辑独立成 `core/`，不依赖 GUI）。

- 理由：核心生成 + 图片处理价值最大、确定性最高，先跑通；公众号发布依赖外部资质，做成可配置开关后置，风险最低。

## 4. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| GUI | CustomTkinter | 轻量、现代外观、易打包；依赖比 PyQt 小 |
| LLM | OpenAI 兼容客户端 | DeepSeek / GLM / Kimi / 通义 均兼容，切换只改配置 |
| 图片 | Pillow + OpenCV | 项目已有；覆盖裁剪/水印/拼接/压缩 |
| OCR（可选） | PaddleOCR | 项目已有；用于把图片内文字并入素材 |
| 配置 | `~/.content_studio/config.json` | 桌面端最易用；GUI 设置面板写入 |
| 测试 | pytest | 只测 `core/` 纯逻辑 |

## 5. 架构与模块结构

```
content_studio/
├─ main.py                  # GUI 入口 (CustomTkinter)
├─ config.py                # 配置加载: API key/model/base_url、公众号凭证
├─ core/                    # 核心逻辑(独立、可测、不依赖 GUI)
│  ├─ models.py             # LLM 抽象层(OpenAI 兼容),按配置切换 provider
│  ├─ prompts.py            # 公众号 / 小红书 的 prompt 模板
│  ├─ generator.py          # 编排: 输入 → LLM → 结构化输出
│  ├─ image_pipeline.py     # 图片处理: 3:4 封面、水印、多图拼接、压缩
│  ├─ ocr.py                # (可选) PaddleOCR 提取图片文字
│  └─ exporter.py           # 打包产出: 文本块、处理后的图片、复制到剪贴板
├─ publish/
│  └─ wechat.py             # 公众号 API(第二阶段预留): token/上传图/草稿/发布
└─ gui/
   └─ app.py                # 主窗口 + 输入/输出/设置面板
```

**关键约束：**

- `core/` 完全独立，**不引用** GUI 或任何 UI 库，可单独 import 与测试。
- LLM 通过「OpenAI 兼容客户端」抽象，切换 provider 只改 `config.providers[*]` + `active_provider`，不改代码。
- 图片管线与文字管线是**两条并行管线**，公众号/小红书各自输出一套。
- `publish/` 是第二阶段，通过配置开关 `wechat.publish_enabled` 启用；第一阶段 GUI 中该入口灰掉。

## 6. 数据流与生成管线

### 输入（GUI 收集）

- 图片（1 张或多张本地路径，GUI 显示缩略图）
- 原始文字（文本框粘贴的素材）
- 开关：是否用 OCR 把图片里的文字也提取出来并入素材

### 生成管线（点「一键生成」触发）

```
[图片 + 文字]
      │
      ├─(可选) OCR 提取 ─→ 合并进素材文本
      ▼
  组装「素材包」= 用户文字 + OCR文字 + 图片清单
      │
      ├──────────────┬──────────────┐
      ▼              ▼              ▼
  公众号 prompt   小红书 prompt   图片管线
      │              │              │
      ▼              ▼              ▼
   LLM 调用       LLM 调用      Pillow/OpenCV
      │              │              │
      ▼              ▼              ▼
 结构化 JSON     结构化 JSON   处理后的图片
      └──────────────┴──────────────┘
                     │
                     ▼
                  exporter 打包 → GUI 预览 + 复制 + 导出
```

### LLM 结构化产出

每个平台各一次 LLM 调用，强制 JSON 输出：

```json
{
  "wechat":      { "title": "...", "summary": "...", "body_html": "...", "image_captions": ["..."] },
  "xiaohongshu": { "title": "...", "body": "...(带emoji)", "hashtags": ["#xx"], "cover_text": "封面主标题" }
}
```

### 设计取舍

- **每平台单独调一次 LLM**（而非合并一次）：prompt 独立、风格更纯、可单独「重新生成」。代价是多一次调用，质量优先。
- 图片管线与文字管线**并行**，互不阻塞。
- 输出统一进 `exporter`：文本块带「复制」按钮、处理后图片存到输出目录并在 GUI 预览。

## 7. 图片处理规格（`image_pipeline.py`）

### 原子操作

| 操作 | 作用 |
|---|---|
| `to_cover_3_4(img)` | 智能裁成 3:4 竖图（1242×1656），默认居中裁剪填满，可配置改为留白填充 |
| `add_title_overlay(img, text)` | 小红书封面加主标题（大字 + 阴影/底色），用 LLM 给的 `cover_text` |
| `add_watermark(img, text/logo)` | 角落加半透明水印（账号名），位置/透明度可配 |
| `stitch_grid(imgs, cols)` | 多图拼成网格 collage（如 2 列） |
| `to_wechat_cover(img)` | 裁成公众号卡片封面 2.35:1（900×383） |
| `resize_for_article(img, max_w=900)` | 公众号正文配图：限宽 900px + JPEG 压缩 |

### 按平台组合

- **小红书图集**：第 1 张 → `to_cover_3_4` → `add_title_overlay`（用 `cover_text`）→ `add_watermark`；其余图 → `to_cover_3_4` → `add_watermark`（保持一致竖图）。勾选 collage 时用 `stitch_grid` 出一张拼图封面。
- **公众号图集**：第 1 张 → `to_wechat_cover`（2.35:1 卡片封面）；其余 → `resize_for_article`（压缩）。（第二阶段再上传到公众号）

### 平台规范依据

- 小红书推荐 3:4（竖图信息流最吃香），最多 9 图，封面带大字标题点击率高。
- 公众号正文图最大显示宽 ~900px，文章卡片封面 2.35:1。

### 配置项

水印文字/位置/透明度、裁剪策略（裁剪 vs 留白）、JPEG 质量、是否启用 collage。

## 8. 配置

持久化到 `~/.content_studio/config.json`，GUI「设置」面板写入：

```json
{
  "providers": [
    {"name": "deepseek", "base_url": "https://api.deepseek.com/v1", "api_key": "sk-...", "model": "deepseek-chat"},
    {"name": "glm",      "base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key": "...", "model": "glm-4"}
  ],
  "active_provider": "deepseek",
  "image": {"watermark_text": "@我的账号", "crop_strategy": "crop", "jpeg_quality": 85, "collage": false},
  "ocr_enabled": false,
  "wechat": {"app_id": "", "app_secret": "", "publish_enabled": false}
}
```

- 切换模型 = 改 `active_provider`，代码不变。
- 首次启动检测到配置缺失 → 弹设置面板引导填写，不直接报错。

## 9. 错误处理

- **LLM 失败**（网络/鉴权/限流）：指数退避重试 2~3 次 → 仍失败则在 GUI 明确报错；单平台成功另一平台失败时，**保留成功的**，失败的平台标红可「重试」。
- **JSON 解析失败**：先「修复式重发」一次（prompt 要求修 JSON）→ 仍失败则降级为纯文本输出。
- **图片问题**（格式不支持/损坏/过小）：**跳过该图并告警**，不中断整批。
- **OCR 初始化失败**：优雅关闭 OCR 功能并提示，不影响主流程。
- **配置缺失**：首次运行引导填写，不直接报错。

## 10. 测试

`pytest`，只测纯逻辑 `core/`，不碰 GUI：

- `image_pipeline`：样本图断言尺寸/水印存在/裁剪比例。
- `models`：mock HTTP，验证请求结构 + provider 切换。
- `generator`：mock LLM，验证 prompt 组装、JSON 解析、降级路径。
- 集成：固定 fixture（图 + 文），mock LLM 跑通端到端。

GUI 不做单元测试，靠手动验收。

## 11. 第一阶段验收标准

1. 能拖入/选择 1~9 张图片，粘贴文字。
2. 点「一键生成」后，并行产出公众号长文 + 小红书笔记（结构化字段齐全）。
3. 图片按平台规格处理：小红书 3:4 封面带大字标题 + 水印；公众号 2.35:1 封面 + 压缩正文图。
4. GUI 内可预览、一键复制各文本块、导出处理后图片到目录。
5. 可在设置里切换 LLM provider 并生效。
6. 单平台失败时另一平台仍可用，可重试失败平台。
7. `core/` 单元测试通过。

## 12. 第二阶段（后续，非本次范围）

- `publish/wechat.py`：access_token 管理 → 上传图片（uploadimg/add_material）→ 创建草稿（new draft）→ 发布（freepublish）。
- 启用条件：用户确认持有**认证公众号** + AppID/AppSecret，配置 `wechat.publish_enabled = true`。
- GUI 入口在第一阶段为灰置，第二阶段解锁。
