# Content Studio · Web 版设计文档（AMD 赛道一）

- **日期:** 2026-07-30
- **状态:** 已通过口头评审，待用户书面确认
- **作者:** brainstorming 会话产出
- **关联:** `docs/superpowers/specs/2026-07-29-content-studio-design.md`（第一阶段桌面 MVP，已完成）

## 1. 背景与目标

把现有 **Windows 桌面 MVP**（投入「图片+文字」一键生成公众号长文/小红书笔记、导出本地文件）演进为 **Web 应用**，面向 2026 AMD AI DevMaster 黑客松**赛道一（多模态内容创作工具）**。

用户在网页输入「**主题 + 照片 + 文字**」并选一个**预设视觉风格**，一键：

1. 云端 LLM（OpenAI 兼容，如千问 Qwen）产出公众号长文（标题 + 摘要 + 正文 HTML + 图注 + 文生图提示词），文风随所选风格变化。
2. 本地 **AMD GPU 上的 ComfyUI** 对用户照片做**风格迁移**、按需**文生图**补配图。
3. 用现有 `image_pipeline` 做封面(2.35:1)/压缩/水印后处理。
4. **真调公众号官方 API 发到草稿箱**（用户已持有认证公众号 + AppID/AppSecret）。

### 已确认基线（brainstorming 结论）

| 维度 | 决定 |
|---|---|
| 部署 | **混合**：ComfyUI 本地 AMD GPU（出图）；文本走云端 OpenAI 兼容 API |
| ComfyUI 职责 | **两者都要**：照片风格迁移 + 文生图补配图 |
| 公众号资质 | 已有**认证公众号 + 凭证**，草稿箱 API 可真调 |
| 前端 | **FastAPI + Jinja2 服务端渲染** + 少量原生 JS |
| 平台范围 | **先只做公众号**；小红书时间允许再加 |
| 风格选择 | **预设风格菜单**（动漫/赛博朋克/复古/极简…） |
| 方案 | **方案 A（精简垂直切片）+ 选性增量** |

## 2. 范围

### MVP 验收标准（方案 A）

1. 网页可上传 1–N 张图、填主题/素材文字、从下拉选风格、点「一键生成」。
2. 文本经云端 LLM 出结构化结果 `title / summary / body_html / image_captions / image_prompts`，文风随所选风格变化。
3. ComfyUI（本地 GPU）对用户照片做风格迁移、按 `image_prompts` 文生图补配图；取回图后用 `image_pipeline` 做封面(2.35:1)+限宽 900+水印+JPEG。
4. 预览页展示标题/摘要/正文/图集，生成进度可见。
5. 点「发到草稿箱」→ 真调公众号 API → 公众号后台「草稿箱」出现新草稿，返回草稿 `media_id`。
6. 至少 **2 个风格**端到端可用（含对应 ComfyUI workflow）。
7. `core/`、`publish/`、`styles/` 单元测试通过（mock HTTP）。

### 非目标（YAGNI）

- 不做小红书（本次范围外；时间允许再说，且无发布 API）。
- 不做自动群发 `freepublish`（只到草稿箱，风险高）。
- 不做多账号管理。
- 不做用户登录/多用户（本地单用户工具）。
- 不做任务历史持久化（内存任务表即可，重启清空）。

### 可选增量（时间允许，**不进 MVP 验收**）

- SSE 实时进度（替代轮询）。
- 预览页简易编辑器（发布前改标题/正文/换图）。
- 单图重生成。
- 多图各自选风格。

## 3. 架构与模块结构

保留并复用 `core/`（**不删桌面 `gui/`**），新增 web 层、发布层、ComfyUI 客户端、风格注册表：

```
content_studio/
├─ main.py                # 保留: GUI 入口 (桌面版仍可跑, 不动)
├─ config.py              # 扩展: +ComfyConfig; 保留 ProviderConfig/ImageConfig/WeChatConfig
├─ core/
│  ├─ models.py           # 复用 (LLMClient, OpenAI 兼容, 文本走云端)
│  ├─ prompts.py          # 扩展: build_wechat_prompt(material, style) + 图像提示词指令
│  ├─ generator.py        # 扩展: generate_wechat(material, style) + 产出 image_prompts
│  ├─ image_pipeline.py   # 复用: ComfyUI 之后的封面裁剪/水印/压缩
│  ├─ ocr.py              # 复用 (可选)
│  ├─ comfy.py            # 新: ComfyUI HTTP 客户端 (排队/轮询/取图)
│  └─ exporter.py         # 弱化: web 版只组装内存结构, 不再写本地 txt
├─ publish/
│  └─ wechat.py           # 新: token / uploadimg / add_material / draft/add
├─ styles/
│  ├─ registry.py         # 新: StylePreset 注册表 (id → 名字/workflow/llm_tone/visual_keywords)
│  └─ workflows/          # 新: 每风格一份 ComfyUI API 格式 workflow JSON
│     ├─ anime.json
│     ├─ anime_t2i.json
│     ├─ cyberpunk.json
│     └─ cyberpunk_t2i.json
├─ web/
│  ├─ __init__.py
│  ├─ app.py              # 新: FastAPI 实例 + uvicorn 入口
│  ├─ routes.py           # 新: 路由
│  ├─ jobs.py             # 新: 内存任务表 + 进度状态
│  ├─ templates/          # 新: Jinja2 (index 表单 / preview 结果页 / settings)
│  └─ static/             # 新: 少量 css/js
├─ gui/                   # 保留不动
└─ tests/                 # 仓库根 tests/, 见 §8
```

### 关键约束

- `core/` 与 `publish/`、`styles/` **不依赖任何 UI 库**，可单独 import 与测试。
- ComfyUI 与公众号都走 **HTTP**，可 mock、可测；ComfyUI 不可达时降级（见 §5）。
- 切换风格/模型只改配置与 workflow 文件，**不改代码**。
- 文本 LLM 仍走「OpenAI 兼容客户端」抽象，切换 provider 只改 `config.providers[*]` + `active_provider`。
- `main.py` 不动（GUI 入口保留）；Web 用 `python -m content_studio.web.app`。

## 4. 数据流（点「一键生成」触发，后台异步 job）

```
[主题 + 文字 + 照片 + 风格]
   │
   ├─(可选) OCR ─→ 合并进素材
   ▼
 LLM (云端, 一次结构化调用)
   └─→ 文章 title/summary/body_html/image_captions       (文风套用 style.llm_tone)
   └─→ image_prompts[]: 恰好 comfy.t2i_count 条画面描述 (套 style.visual_keywords)
   │
 ComfyUI (本地 AMD GPU)
   ├─→ 每张用户照片 → img2img/IP-Adapter (style.workflow_style) → 风格化图
   └─→ 每个 image_prompt → txt2img SDXL (style.workflow_t2i)   → 新配图
   ▼
 image_pipeline 后处理: 首图 → to_wechat_cover(2.35:1); 其余 → resize≤900 + 水印 + JPEG
   ▼
 组装成品 → 推进度到 job → 预览页
   │ (用户确认)
   ▼
 publish/wechat.py → 公众号草稿箱
```

### 设计取舍

- **风格三合一驱动**：一个 `StylePreset` 同时驱动 ① ComfyUI 出图风格 ② LLM 文风 ③ 文生图正向提示词。这是赛道「风格定制」评分点的关键。
- **ComfyUI 不可达即降级**：连不上/超时 → 退回「仅原图 + image_pipeline 处理」并告警，**不阻塞出文**。保证无 GPU 也能演示文本+发布闭环。
- **文/图管线解耦**：文本先出（含 `image_prompts`），图像随后消费；图像失败不影响文本与发布（用原图兜底）。

## 5. ComfyUI 集成（`core/comfy.py`）— 体现 GPU 价值的核心

- **连接**：`base_url`（默认 `http://127.0.0.1:8188`）。`POST /prompt` 提交 workflow graph → 轮询 `GET /history/{prompt_id}` → `GET /view?filename=...` 下载输出为 PIL。
- **workflow 模板**：每风格一份 **API 格式 JSON**（从 ComfyUI 网页「保存(API格式)」导出），含占位符 `{input_image}` / `{positive}` / `{seed}`；风格迁移用 img2img/IP-Adapter，文生图用 SDXL txt2img。
- **注入**：用户上传图先 `POST /upload/image` 拿服务器端 filename；prompt 填进对应节点；随机 seed。
- **接口**：
  - `upload_image(path) -> filename`
  - `run_workflow(graph: dict, timeout) -> list[PIL.Image]`（提交 + 轮询 + 取全部输出图）
  - `style_transfer(image_path, style: StylePreset) -> PIL.Image`
  - `text_to_image(prompt, style: StylePreset) -> PIL.Image`
- **降级**：ComfyUI 不可达/超时 → 抛可识别异常，调用方退回原图；单图失败跳过、不中断整批。
- **部署注记**（实现期处理，不影响设计）：Windows 上 ComfyUI 走 `--directml` 使用 AMD GPU；`comfy.py` 只认 HTTP，与部署方式解耦。

## 6. 公众号草稿箱（`publish/wechat.py`）— 头条功能

1. **access_token**：`grant_type=client_credential`，缓存并在过期前 5 分钟刷新。
2. **正文配图**：`POST /cgi-bin/media/uploadimg`（multipart）→ 返回 URL → 嵌进 `body_html` 的 `<img src>`（此 URL 仅限图文正文内使用）。
3. **封面缩略图**：`POST /cgi-bin/material/add_material?type=image` → `media_id` → 作为 `thumb_media_id`。
4. **建草稿**：`POST /cgi-bin/draft/add`，`articles=[{title, author, digest=摘要, content=带 img 的 html, thumb_media_id, content_source_url, need_open_comment:0, only_fans_can_comment:0}]` → 返回草稿 `media_id`。
5. **错误**：`40001` token 失效 → 刷新重试一次；`45xxx` 权限错误 → 明确提示（已认证不会触发）；网络错误重试 2–3 次。

### 接口

- `WeChatPublisher(app_id, app_secret, http=...)`
- `get_access_token() -> str`（带缓存）
- `upload_body_image(path) -> str`（返回文章内可用 URL）
- `upload_cover_material(path) -> str`（返回 `media_id`）
- `create_draft(article: dict) -> str`（返回草稿 `media_id`）
- `publish_article(title, digest, body_html, cover_path, body_image_paths) -> str`（编排上面四步，返回草稿 id）

## 7. 风格预设注册表（`styles/registry.py`）

```python
@dataclass
class StylePreset:
    id: str               # "anime"
    name: str             # "动漫风"
    workflow_style: str   # "workflows/anime.json"      风格迁移
    workflow_t2i: str     # "workflows/anime_t2i.json"   文生图
    llm_tone: str         # "活泼、二次元感、多用感叹"    喂给 LLM 定文风
    visual_keywords: str  # "anime style, vibrant, cel shading"  拼进 t2i 正向提示
```

- 内置至少 2 个预设（动漫、赛博朋克）。MVP 验收要求 ≥2。
- workflow JSON 文件随仓库附带占位模板，真实模型/LoRA 由用户在实现期替换。

## 8. Web 层

### 路由

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 表单页：主题/文字/上传图/风格下拉/OCR 开关/设置入口 |
| POST | `/generate` | 建后台 job，返回 `job_id` |
| GET | `/job/{id}` | JSON 进度 + 中间产物（前端 ~1.5s 轮询） |
| GET | `/job/{id}/preview` | 预览页：标题/摘要/正文/图集 +「发到草稿箱」 |
| POST | `/job/{id}/publish` | 调 `publish/wechat`，返回草稿 `media_id` + 后台链接 |
| GET/POST | `/settings` | provider key / ComfyUI base_url / 公众号凭证 |

### 任务与进度

- 内存 `jobs: dict[id, {stage, progress, result, error}]`，单进程内有效。
- 前端轮询 `/job/{id}`；增量项可换 SSE。

## 9. 配置

沿用 `~/.content_studio/config.json`，扩展 `comfy` 段：

```python
@dataclass
class ComfyConfig:
    base_url: str = "http://127.0.0.1:8188"
    enabled: bool = True
    style_transfer: bool = True
    t2i_count: int = 1      # 文生图补几张
    timeout: int = 180
```

保留现有 `providers` / `active_provider`（文本 LLM）、`image`、`ocr_enabled`、`wechat`（app_id/app_secret）。

新增依赖：`fastapi`、`uvicorn`、`jinja2`、`python-multipart`（`httpx`、`requests`、`Pillow`、`openai` 已有）。

## 10. 错误处理

- **LLM 失败**（网络/鉴权/限流）：沿用现有重试 + JSON 修复式重发 + 纯文本降级。
- **ComfyUI 不可达/超时**：退回「仅原图 + image_pipeline 处理」并告警，不阻塞出文。
- **单图生成/上传失败**：跳过 + 告警，不中断整批。
- **公众号 token 失效（40001）**：刷新一次重试；权限错误（45xxx）明确报错。
- **配置缺失**：首次运行引导到 `/settings`，不直接报错。

## 11. 测试

`pytest`，测纯逻辑 + mock HTTP（不碰 ComfyUI 真机/公众号真调）：

- `tests/test_comfy.py`：mock `/prompt` `/history` `/view`，验证 workflow 注入、取图、降级。
- `tests/test_publish_wechat.py`：mock requests，验证 token 缓存/刷新、`uploadimg → add_material → draft/add` 全流程、错误码处理。
- `tests/test_styles.py`：预设注册表加载、字段完整。
- `tests/test_generator.py`：扩展 `style` 参数与 `image_prompts` 产出（在现有基础上增补）。
- `tests/test_web_routes.py`：FastAPI `TestClient`，验证 `/generate` 建 job、`/job/{id}` 返回进度、`/publish` 调用（mock publish 层）。

ComfyUI 真实 GPU 与公众号真调 = 手动验收，不进单测。

## 12. 演示脚本（建议，非阻塞）

为评委准备一段「无 GPU 也能跑」的降级演示路径，以及一段「带 GPU 风格迁移」的完整演示路径，体现赛道四方向（轻量化部署 / 推理加速 / 风格定制 / 画质优化）。
