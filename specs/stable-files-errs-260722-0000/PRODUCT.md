# Spec: 文件上传加固 + 统一错误码 (File Upload Hardening & Unified Error Codes)

| 字段 | 值 |
|------|-----|
| **Spec ID** | `stable-files-errs-260722-0000` |
| **阶段** | Stage E |
| **状态** | ✅ implemented / verified |
| **创建日期** | 2026-07-22 |
| **对应路线图** | FULL_PRODUCT_ROADMAP.zh-CN.md — 阶段 E |

---

## 1. 概述

本 spec 覆盖阶段 E 中的两个质量保障能力：

1. **文件上传加固** — 对用户文件上传进行全面校验（扩展名、MIME、大小、病毒扫描占位）
2. **统一错误码** — 所有 API 端点使用统一的 `APP_ERROR_CODES` 字典返回结构化错误

---

## 2. 用户故事

### US-1: 文件上传校验

**作为** 平台管理员
**我想要** 上传文件时自动校验格式、大小和安全性
**以便** 防止恶意文件或过大文件导致系统问题

**验收标准：**
- 只允许 6 种扩展名：`.md`, `.txt`, `.pdf`, `.docx`, `.xlsx`, `.csv`
- 基于文件内容（magic bytes）检测 MIME 类型，再与白名单比对
- 文件大小不超过 `max_upload_size_mb`（默认 50MB）
- 空文件拒绝
- 文件名长度不超过 `max_upload_filename_length`（默认 255 字符）
- 病毒扫描占位（clamdscan 集成预留，当前默认 `skip`）
- Windows 上 `.csv` 被识别为 `application/vnd.ms-excel` 也接受

### US-2: 统一错误码

**作为** API 消费者
**我想要** 所有错误返回包含 `error_code`、`message`、`user_message` 的结构化响应
**以便** 前端可以统一处理并显示友好的中文提示

**验收标准：**
- `APP_ERROR_CODES` 字典覆盖所有已知错误场景
- 错误响应格式：`{"error_code": "E_XXX", "message": "技术描述", "user_message": "用户友好文案", "details": {}}`
- 包含但不限于：文件格式、大小、MIME、扫描、项目、运行、重试、取消等错误类型
- 未知错误码回退到 `INTERNAL_ERROR`

---

## 3. 数据模型

### FileValidationError

| 字段 | 类型 | 说明 |
|------|------|------|
| `filename` | `str` | 文件名 |
| `error_code` | `str` | 错误码 |
| `message` | `str` | 技术描述 |
| `user_message` | `str` | 用户友好消息 |

### UploadResult

| 字段 | 类型 | 说明 |
|------|------|------|
| `relative_path` | `str` | 保存后的相对路径 |
| `size_bytes` | `int` | 文件大小（字节） |
| `sha256` | `str \| None` | SHA-256 哈希 |
| `mime_detected` | `str \| None` | 检测到的 MIME |
| `extension_matched` | `bool` | 扩展名与 MIME 是否匹配 |
| `virus_scan_status` | `str` | 扫描状态 (skipped/clean/infected) |

### ErrorDetail

| 字段 | 类型 | 说明 |
|------|------|------|
| `error_code` | `str` | 错误码编号 |
| `message` | `str` | 技术描述 |
| `user_message` | `str` | 用户友好消息 |
| `details` | `dict` | 附加详情 |

### 文件常量

```python
ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".xlsx", ".csv"}

ALLOWED_MIME_TYPES = {
    "text/plain", "text/markdown", "text/x-markdown", "text/csv",
    "application/vnd.ms-excel", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

EXTENSION_TO_MIME = {
    ".md": ["text/markdown", "text/x-markdown", "text/plain"],
    ".txt": ["text/plain"],
    ".pdf": ["application/pdf"],
    ".docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    ".xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    ".csv": ["text/csv", "text/plain", "application/vnd.ms-excel"],  # Windows 兼容
}

MAX_UPLOAD_SIZE_MB_DEFAULT = 50
```

---

## 4. 文件验证流程

`app/services/files.py::validate_file()` 按顺序执行 6 步校验：

| 步骤 | 检查 | 失败错误码 |
|------|------|-----------|
| 1 | 文件名长度 ≤ max_upload_filename_length | `FILE_NAME_TOO_LONG` |
| 2 | 文件大小 > 0 | `FILE_EMPTY` |
| 3 | 文件大小 ≤ max_upload_size_bytes | `FILE_TOO_LARGE` |
| 4 | 扩展名 ∈ ALLOWED_EXTENSIONS | `FILE_EXTENSION_NOT_ALLOWED` |
| 5 | MIME 检测：内容 magic bytes 判定的类型 ∉ ALLOWED_MIME_TYPES | `UNSUPPORTED_FILE_TYPE` |
| 6 | 病毒扫描（如启用） | `FILE_VIRUS_DETECTED` |

### save_project_upload 返回值变更

```python
# 之前: 返回 str (相对路径)
# 之后: 返回 (str, UploadResult)
def save_project_upload(settings: Settings, project_id: str, filename: str, content: bytes) -> tuple[str, UploadResult]:
```

---

## 5. 配置

| 配置项 | 默认值 | 范围 | 说明 |
|--------|--------|------|------|
| `max_upload_size_mb` | `50` | 1-1024 | 最大上传文件大小 |
| `max_upload_filename_length` | `255` | 32-1024 | 最大文件名长度 |
| `virus_scan_enabled` | `False` | bool | 是否启用病毒扫描 |
| `virus_scan_command` | `["clamdscan", "--fdpass"]` | list | 扫描命令 |

---

## 6. 错误码一览

| 错误码 | 技术描述 | 用户消息 |
|--------|----------|----------|
| `FILE_NAME_TOO_LONG` | 文件名超长 | 文件名过长，请缩短后重试 |
| `FILE_EMPTY` | 空文件 | 文件内容为空，请检查后重试 |
| `FILE_TOO_LARGE` | 文件过大 | 文件大小超出限制 |
| `FILE_EXTENSION_NOT_ALLOWED` | 不支持的扩展名 | 不支持的文件格式，请检查文件类型 |
| `UNSUPPORTED_FILE_TYPE` | MIME 类型不在白名单 | 文件类型不支持，请检查文件内容 |
| `FILE_VIRUS_DETECTED` | 检测到病毒 | 文件安全扫描未通过 |
| `PROJECT_NOT_FOUND` | 项目不存在 | 指定的项目不存在 |
| `RUN_NOT_FOUND` | 运行不存在 | 运行记录不存在 |
| `RUN_ALREADY_CANCELLED` | 已取消 | 运行已经取消 |
| `RUN_CANCEL_TOO_LATE` | 取消太晚 | 运行已完成，无法取消 |
| `RUN_WRONG_STATUS` | 状态错误 | 当前运行状态不允许此操作 |
| `RETRY_LIMIT_EXCEEDED` | 超出重试次数 | 已超过最大重试次数 |

---

## 7. 验收目标

- [x] 6 种允许的扩展名正确校验
- [x] Windows CSV (`application/vnd.ms-excel`) 被接受
- [x] 空文件被拒绝 (FILE_EMPTY)
- [x] 超大文件被拒绝 (FILE_TOO_LARGE)
- [x] 非法扩展名被拒绝 (FILE_EXTENSION_NOT_ALLOWED)
- [x] MIME 不匹配被检测 (UNSUPPORTED_FILE_TYPE)
- [x] UploadResult 正确返回验证摘要
- [x] APP_ERROR_CODES 覆盖所有错误场景
- [x] get_error() 返回中文用户消息
- [x] 所有测试通过（test_stage_e_files.py + test_stage_e_error_codes.py, 16 个用例）
