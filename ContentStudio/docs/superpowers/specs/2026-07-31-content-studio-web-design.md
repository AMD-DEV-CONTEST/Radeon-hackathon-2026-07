# Content Studio Web 设计文档

- **日期:** 2026-07-31
- **状态:** 已通过口头评审，待用户书面确认
- **作者:** brainstorming 会话产出
- **关系:** 在既有桌面版 Content Studio（见 `2026-07-29-content-studio-design.md`）之上新增网页版，复用其 `core/`，不改动桌面版。

## 1. 目标与范围

给已有的 Content Studio 增加一个**网页版**：打开浏览器、上传图片 + 粘贴文字 → 一键用 AI 生成**微信公众号**长文与**小红书**笔记，并自动处理图片。**部署到服务器供多人使用**，但**免注册**：每人各自填自己的 LLM API Key（仅存浏览器，不落服务器）。

### 本次范围（MVP）

- 服务端渲染单页 + FastAPI 后端，包住既有 `core/`。
- 多人、免注册、各自填 Key（Key 仅存浏览器 `localStorage`，随每次请求带上，服务器临时用完即弃）。
- 生成公众号 + 小红书两套内容；图片按平台规格处理；页面内实时预览、复制、JSZip 纯前端打包下载。
- 服务器**全程无状态**：不落盘、不存任务、不留临时文件。
- Docker 一键部署。

### 非目标（YAGNI）

- 不做账号 / 登录 / 历史记录 / 用户内容持久化。
- 不做 OCR（图片提取文字）。桌面版有，网页 MVP 不引入（PaddleOCR 重，不适合多用户服务器）。
- 不做公众号官方 API 自动发布（与桌面版第二阶段同理，预留接口但不在本范围）。
- 不做限流 / 鉴权 / 反滥用（后续按需加）。
- 不删桌面版（`content_studio/main.py` 保留）。

## 2. 选定方案

在三个候选方案中选定 **方案 A：FastAPI + 服务端渲染页面 + 原生 JS，内存处理，服务器无状态**。

- **理由：** 正好匹配"打开网页、填图填字、一键出内容"的目标；零件最少；无状态最契合"多人 + 各自填 Key"的安全模型；`core/` 零改动复用。
- 备选方案 B（SPA：React/Vue）引入构建工具链，对当前范围过度设计，否决。
- 备选方案 C（任务队列 + 服务端文件存储 + SSE）服务器有状态、复杂度高，留给未来上 OCR / 大批量时再考虑。

## 3. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI + Uvicorn | async 友好长 LLM 调用；multipart 上传简单；与现有 `core/`(同步) 用 `to_thread` 并发 |
| 表单 | python-multipart | multipart/form-data 解析（图片 + 字段） |
| 模板 | Jinja2 | 服务端渲染单页，无前端构建步骤 |
| 前端 | 原生 HTML/CSS/JS + JSZip | 无构建；下载 zip 纯前端生成，保持服务器无状态 |
| 图片 | Pillow（复用） | 已有；封面/水印/压缩/拼接 |
| LLM | openai 兼容客户端（复用） | DeepSeek/GLM 等切换只改请求里的 provider/model |
| 部署 | Docker（python:3.12-slim） | 单容器、镜像小（不含 paddleocr） |
| 测试 | pytest + fastapi.testclient | 沿用现有 `tests/` 风格，只测纯逻辑与路由冒烟 |

新增依赖（与桌面依赖并存写入 `requirements.txt`）：`fastapi`、`uvicorn[standard]`、`python-multipart`、`jinja2`。前端库 **JSZip 采用 vendored**（把 `jszip.min.js` 放进 `content_studio/web/static/` 本地引用），不依赖 CDN，保证离线可用、无外链混用内容/跨域问题。

## 4. 架构与模块结构

```
content_studio/
├─ main.py            # 保留: 桌面 GUI 入口(不删)
├─ config.py          # 复用: ProviderConfig/ImageConfig + default_config()(provider 预设)
├─ core/              # ★ 完全复用,零改动
│  ├─ models.py         # LLMClient(provider)                 ← 复用
│  ├─ prompts.py                                            ← 复用
│  ├─ generator.py      # Generator.generate_wechat/xhs       ← 复用
│  ├─ image_pipeline.py # build_wechat_images/build_xhs_images ← 复用
│  ├─ exporter.py       # format_wechat/format_xhs 复用; export()(写盘)不用
│  └─ ocr.py            # MVP 不引入
└─ web/               # 新增
   ├─ __init__.py
   ├─ __main__.py      # python -m content_studio.web → uvicorn
   ├─ app.py           # FastAPI 工厂 + 挂载模板/静态
   ├─ routes.py        # GET / ; /api/providers ; /api/generate ; /api/health
   ├─ schemas.py       # pydantic 请求校验 / 响应模型
   ├─ services.py      # 编排: 解析表单→构建Provider/ImageConfig→并发跑→组装响应
   ├─ security.py      # 输入校验/大小限制/Key 脱敏/错误信息净化
   ├─ templates/index.html   # Jinja2 单页
   └─ static/{app.js,style.css}
```

**关键约束：**

- `core/` **零改动**，不引用任何 web 库；保持桌面版可继续独立运行与单测。
- `web/` 是 `core/` 的薄壳：只负责请求解析、并发编排、响应组装。
- 服务器**无状态**：请求之间不共享任何数据；图片全程内存，不落盘。
- 桌面版入口 `content_studio/main.py` 保留，与网页版互不影响。

## 5. 数据流

```
浏览器                       FastAPI                        core/
──────                       ──────                         ────
选 provider+粘 Key+文字        POST /api/generate             build_material()
+拖图 (Key 在 localStorage,   (multipart: provider,api_key,   Generator.generate_wechat ─┐
 每次随请求带)                 model,text,options,files[])    Generator.generate_xhs    ─┤并发
                             校验类型/大小/数量→               image_pipeline.build_*    ─┘(to_thread)
                             构建 ProviderConfig/ImageConfig  LLMClient(provider)
                             并发执行(threadpool)
                             图→PIL→JPEG→base64
                             返回 JSON ◄────────────────
渲染预览(公众号正文HTML live    JSON{wechat,xhs,images{...},skipped,warnings}
 渲染; 小红书图文;缩略图)
复制 / JSZip 纯前端打包下载      (服务器全程无状态,不落盘)
```

- 点"一键生成"触发 `POST /api/generate`。端点 `async def`，用 `asyncio.to_thread` 并发跑「公众号 LLM + 小红书 LLM + 图片管线」。openai 同步客户端跑在线程池里，不阻塞事件循环。
- 图片管线与文字管线是两条并行管线（沿用桌面版设计），公众号/小红书各自输出一套。

## 6. API 设计

### GET /
渲染 `index.html` 单页。

### GET /api/health → 200 `{"status":"ok"}`
容器健康检查用。

### GET /api/providers → `[{name, base_url, default_model}, ...]`
来自 `default_config().providers`，给前端 provider 下拉框。**不含任何 API Key。**

### POST /api/generate
**请求（multipart/form-data）：**

| 字段 | 类型 | 约束 |
|---|---|---|
| `provider` | str | 必须在预设列表 |
| `api_key` | str | 非空；仅本次请求内存使用 |
| `model` | str | 非空 |
| `text` | str | 素材文字，可为空 |
| `watermark_text` | str | 可选，默认 `@我的账号` |
| `crop_strategy` | str | `crop` \| `pad`，默认 `crop` |
| `collage` | bool | 默认 false |
| `jpeg_quality` | int | 50–95，默认 85 |
| `images` | File[] | 0–9 张；每张 ≤10MB；png/jpg/jpeg/webp/bmp |

**响应 200：**
```json
{
  "wechat":  {"title","summary","body_html","image_captions":[],"fell_back":false},
  "xhs":     {"title","body","hashtags":[],"cover_text":"","fell_back":false},
  "images":  {"wechat":[{"name":"img_1.jpg","data_url":"data:image/jpeg;base64,..."}],
              "xhs":  [{"name":"img_1.jpg","data_url":"..."}]},
  "skipped_images": 0,
  "warnings": []
}
```

**状态码：**
- `200`：至少一个平台成功（失败平台在响应内置空 + `warnings` 说明）。
- `422`：校验失败（图数/大小/类型/provider/Key），返回明确中文提示。
- `502`：两个平台 LLM 均失败，返回可读且脱敏的错误。

## 7. 安全（API Key 不持久化、不外泄）

- Key 只存在浏览器 `localStorage`；每次请求随 multipart 字段带上；服务器用它即时构造 `ProviderConfig`，调用完随请求对象回收。**绝不写盘、绝不写配置文件。**
- **绝不记日志**：访问日志只记路径 / 状态码 / 耗时；`api_key` 字段在任何情况下不被记录。
- 报错信息**原样脱敏**：不回显 Key、不回显完整请求体；`security.py` 负责净化错误文案。
- 响应体里**不包含** Key；`/api/providers` 只暴露 `name/base_url/default_model`。
- 全程同源（服务器自托管页面）→ **无需 CORS**，天然规避浏览器直连 LLM 的 CORS 与 Key 暴露风险。

## 8. 图片处理（内存、无落盘）

- 上传字节 → `PIL.Image.open(BytesIO).convert("RGB")`；逐张加载，**坏图跳过并计数**（沿用桌面版容错），不中断整批。
- 复用 `image_pipeline.build_wechat_images` / `build_xhs_images`：含公众号 2.35:1 卡片封面、正文图限宽压缩；小红书 3:4 封面、大字标题叠加、水印、可选 collage 拼图。
- 处理后每张 → 内存 `BytesIO` 存 JPEG（按 `jpeg_quality`）→ base64 data URL，随 JSON 一次性返回。
- **不写磁盘、不留临时文件、不存任务状态。**
- 体积控制：单图 ≤10MB 上传限制 + JPEG 压缩 + 正文图限宽 900px，保证响应体可接受（base64 ~33% 膨胀靠压缩抵消）。

## 9. 前端 UX（单页，原生 JS）

- **顶部**：标题 + 折叠"设置"（provider 下拉 → 粘 API Key → 填模型名 + 图片选项：水印文字、裁剪/留白、collage、JPEG 质量）。设置存 `localStorage`，下次自动回填。
- **左栏**：拖拽 / 点选上传图片（缩略图预览 + 单张删除，最多 9 张）+ 素材文字框。
- **右栏**：两个 tab——公众号 / 小红书。
  - 公众号：标题、摘要；正文 `body_html` **用 `<iframe srcdoc>` 实时渲染**（隔离样式，所见即所得）；图注列表；处理后封面 / 配图缩略图。
  - 小红书：标题、带 emoji 正文、话题标签；3:4 封面图（含大字标题）+ 图集缩略图。
- **操作栏**：一键生成（生成中禁用 + 加载态）、复制标题 / 正文、打包下载 zip（JSZip 纯前端，按 `wechat/`、`xiaohongshu/` 分目录打包图片与文本）。
- **状态条**：就绪 / 生成中 / 完成（含跳过坏图数）/ 出错。
- 前端 JS 不做单元测试，靠手动验收。

## 10. 错误处理（对齐桌面版策略）

- **校验失败**（图数>9 / 单图>10MB / 类型不符 / provider 缺失 / Key 空）→ `422`，明确中文提示。
- **单平台 LLM 失败**（鉴权 / 限流 / 超时，`LLMClient` 已自带指数退避重试）：**保留成功平台**，失败平台在响应内置空并在 `warnings` 说明"可重试"；**整体不报 500**。
- **两个平台都失败** → `502`，返回可读错误（脱敏）。
- **JSON 解析失败**：`generator` 自带"修复式重发一次 → 仍失败则 `fell_back=true` 降级为原文"，前端展示降级提示。
- **坏图**：跳过 + `skipped_images` 计数 + `warnings` 提示。

## 11. 部署（Docker，Linux 服务器）

- `Dockerfile`：`python:3.12-slim`；装 web 用依赖（`fastapi`、`uvicorn[standard]`、`python-multipart`、`pillow`、`openai`、`jinja2`）；**不含 paddleocr**，镜像保持小。
- `CMD uvicorn content_studio.web.app:app --host 0.0.0.0 --port 8000`。
- `docker-compose.yml`：单服务 + 端口映射 + 可选 `mem_limit`。
- 健康检查走 `/api/health`。
- 新增依赖写进 `requirements.txt`（与桌面依赖并存，可加注释分组）。

## 12. 测试（pytest，沿用现有风格）

- `tests/test_web_services.py`：mock `LLMClient`，断言编排并发跑两平台 + 图片管线、坏图跳过计数、响应结构正确、**Key 不出现在响应里**。
- `tests/test_web_security.py`：超图数 / 超大 / 坏类型 / 空 Key → 报错；返回的 base64 是合法 data URL。
- 路由冒烟（`fastapi.testclient`）：`/`、`/api/providers`、`/api/health` 返回 200；`/api/generate` 校验失败路径返回 422。
- 前端 JS 不单测。

## 13. 验收标准

1. `docker compose up` 后浏览器打开，无需注册即可用。
2. 选 provider + 填 Key + 粘文字 + 上传 1–9 图 → 一键生成 → 公众号正文实时预览 + 小红书图文 + 两套处理后图。
3. 一键复制文本；JSZip 打包下载 zip（含两套图与文本，按平台分目录）。
4. Key 全程只在浏览器 + 单次请求内存，不在服务器落盘 / 记日志。
5. 单平台失败时另一平台仍可用并提示可重试；坏图跳过并计数。
6. `core/` 既有测试全绿；新增 web 测试通过。

## 14. 后续（非本次范围）

- OCR（图片提取文字）：若要加，需在服务器常驻一个 PaddleOCR 单例并规划内存 / 冷启动。
- 公众号官方 API 自动发布：与桌面版第二阶段同理，依赖认证主体 + AppID/AppSecret，预留接口。
- 限流 / 鉴权 / 反滥用：按运营需要再加。
