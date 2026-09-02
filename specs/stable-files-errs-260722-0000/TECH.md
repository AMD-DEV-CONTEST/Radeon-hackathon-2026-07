# TECH.md — 文件上传加固 + 统一错误码

- Level: S2
- Status: verified

## 1. 架构决策

### 1.1 validate_file() 顺序校验

6 步校验按从轻到重的顺序执行，一旦失败立即返回错误，避免不必要的 I/O：

```python
# app/services/files.py
def validate_file(settings: Settings, filename: str, content: bytes) -> FileValidationError | None:
    # 1. 文件名长度
    if len(filename) > settings.max_upload_filename_length:
        return get_error("E_FILE_NAME_TOO_LONG", ...)
    # 2. 空文件
    if not content:
        return get_error("E_FILE_EMPTY", ...)
    # 3. 文件大小
    if len(content) > settings.max_upload_size_bytes:
        return get_error("E_FILE_TOO_LARGE", ...)
    # 4. 扩展名
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return get_error("E_FILE_EXTENSION_DENIED", ...)
    # 5. MIME 检测
    detected_mime, _ = mimetypes.guess_type(filename)
    expected_mimes = EXTENSION_TO_MIME.get(suffix, [])
    if detected_mime and detected_mime not in expected_mimes:
        return get_error("E_FILE_MIME_MISMATCH", ...)
    # 6. 病毒扫描
    if settings.virus_scan_enabled:
        # TODO: integration placeholder
        result = run_scan(settings, content)
        if result.infected:
            return get_error("E_FILE_VIRUS_DETECTED", ...)
    return None
```

### 1.2 Windows CSV 兼容

Windows 上 `mimetypes.guess_type("data.csv")` 返回 `("application/vnd.ms-excel", None)`。
处理方式：
- `EXTENSION_TO_MIME[".csv"]` 包含 `"application/vnd.ms-excel"`
- `ALLOWED_MIME_TYPES` 同样包含该类型

### 1.3 save_project_upload 返回变更

```python
# 旧签名
def save_project_upload(...) -> str

# 新签名
def save_project_upload(...) -> tuple[str, UploadResult]
```

`UploadResult` 包含完整的验证摘要，调用方可通过该对象获取 `sha256`、`mime_detected`、`virus_scan_status` 等信息。

### 1.4 错误码字典结构

```python
# app/observability/error_codes.py
APP_ERROR_CODES: dict[str, dict[str, str]] = {
    "FILE_NAME_TOO_LONG": {
        "message": "File name exceeds maximum allowed length",
        "user_message": "文件名过长，请缩短后重试",
    },
    "FILE_EMPTY": {
        "message": "File content is empty",
        "user_message": "文件内容为空，请检查后重试",
    },
    "FILE_TOO_LARGE": {
        "message": "File size exceeds limit of {max_size} bytes",
        "user_message": "文件大小超出限制，最大支持 {max_size} 字节",
    },
    "FILE_EXTENSION_NOT_ALLOWED": {
        "message": "File extension {extension} is not in the allowed list",
        "user_message": "不支持的文件格式，允许的格式包括: {allowed}",
    },
    "UNSUPPORTED_FILE_TYPE": {
        "message": "Detected MIME type {mime} is not in the allowed list",
        "user_message": "文件类型不支持，请检查文件内容",
    },
    ...
}

def get_error(error_code: str, **details: str) -> dict[str, str]:
    entry = APP_ERROR_CODES.get(
        error_code,
        APP_ERROR_CODES["INTERNAL_ERROR"],
    )
    return {
        "error_code": error_code,
        "message": entry["message"].format(**details) if details else entry["message"],
        "user_message": entry["user_message"],
    }
```

未知错误码回退到 `INTERNAL_ERROR`。

---

## 2. 文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/schemas/models.py` | 修改 | 新增 ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES, EXTENSION_TO_MIME, FileValidationError, UploadResult, MAX_UPLOAD_SIZE_MB_DEFAULT |
| `app/schemas/__init__.py` | 修改 | 导出 FileValidationError, UploadResult, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES |
| `app/services/files.py` | 修改 | 新增 validate_file()；save_project_upload 返回值变更为 (str, UploadResult) |
| `app/observability/error_codes.py` | 新增 | APP_ERROR_CODES 字典 + get_error() 函数 |
| `app/config.py` | 修改 | 新增 max_upload_size_mb, max_upload_filename_length, virus_scan_enabled, virus_scan_command |
| `tests/test_stage_e_files.py` | 新增 | 10 个测试用例 |
| `tests/test_stage_e_error_codes.py` | 新增 | 6 个测试用例 |

---

## 3. 关键实现细节

### 3.1 MIME 映射表设计

使用 `dict[str, list[str]]` 而非 `dict[str, str]`，因为同一扩展名可能有多个合法 MIME 类型：
- `.md` → `text/markdown`, `text/x-markdown`, `text/plain`
- `.csv` → `text/csv`, `text/plain`, `application/vnd.ms-excel`

### 3.2 病毒扫描占位

病毒扫描默认 `enabled=False`，扫描状态始终为 `"skipped"`。
启用后，通过 `subprocess.run(virus_scan_command, ...)` 调用外部扫描器（如 clamdscan）。

### 3.3 错误响应格式

FastAPI 端点使用统一 dict 格式返回错误：

```json
{
  "error_code": "FILE_EMPTY",
  "message": "Uploaded file 'report.xlsx' is empty (0 bytes)",
  "user_message": "文件内容为空，请检查后重试"
}
```

---

## 4. 测试覆盖

### test_stage_e_files.py (10 tests)

| 测试 | 说明 |
|------|------|
| `test_validate_file_ok_txt` | 合法 .txt 文件通过 |
| `test_validate_file_ok_md` | 合法 .md 文件通过 |
| `test_validate_file_ok_pdf` | 合法 .pdf 文件通过 |
| `test_validate_file_empty` | 空文件返回 FILE_EMPTY |
| `test_validate_file_too_large` | 超限返回 FILE_TOO_LARGE |
| `test_validate_file_bad_extension` | 非法扩展名返回 FILE_EXTENSION_NOT_ALLOWED |
| `test_validate_file_mime_mismatch` | MIME 不匹配返回 UNSUPPORTED_FILE_TYPE |
| `test_validate_file_csv_windows` | Windows CSV (application/vnd.ms-excel) 通过 |
| `test_validate_file_name_too_long` | 超长文件名返回 FILE_NAME_TOO_LONG |
| `test_save_project_upload_returns_upload_result` | 返回 (str, UploadResult) 元组 |

### test_stage_e_error_codes.py (6 tests)

| 测试 | 说明 |
|------|------|
| `test_all_error_codes_present` | 所有必要的错误码存在 |
| `test_get_error_returns_error_detail` | get_error 返回 dict |
| `test_error_has_user_message_zh` | 错误包含中文用户消息 |
| `test_get_error_unknown_fallback` | 未知错误码回退到 INTERNAL_ERROR |
| `test_error_detail_fields` | ErrorDetail 所有字段正确 |
| `test_error_codes_unique` | 所有错误码不重复 |
