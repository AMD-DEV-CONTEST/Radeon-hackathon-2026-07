# TEST_REPORT.md — 文件上传加固 + 统一错误码

| 字段 | 值 |
|------|-----|
| **Spec ID** | `stable-files-errs-260722-0000` |
| **测试日期** | 2026-07-22 |
| **测试结果** | ✅ **16/16 全部通过** |

---

## 测试套件: test_stage_e_files.py (10 tests)

```
tests/test_stage_e_files.py::test_validate_file_ok_txt PASSED
tests/test_stage_e_files.py::test_validate_file_ok_md PASSED
tests/test_stage_e_files.py::test_validate_file_ok_pdf PASSED
tests/test_stage_e_files.py::test_validate_file_empty PASSED
tests/test_stage_e_files.py::test_validate_file_too_large PASSED
tests/test_stage_e_files.py::test_validate_file_bad_extension PASSED
tests/test_stage_e_files.py::test_validate_file_mime_mismatch PASSED
tests/test_stage_e_files.py::test_validate_file_csv_windows PASSED
tests/test_stage_e_files.py::test_validate_file_name_too_long PASSED
tests/test_stage_e_files.py::test_save_project_upload_returns_upload_result PASSED
```

## 测试套件: test_stage_e_error_codes.py (6 tests)

```
tests/test_stage_e_error_codes.py::test_all_error_codes_present PASSED
tests/test_stage_e_error_codes.py::test_get_error_returns_error_detail PASSED
tests/test_stage_e_error_codes.py::test_error_has_user_message_zh PASSED
tests/test_stage_e_error_codes.py::test_get_error_unknown_fallback PASSED
tests/test_stage_e_error_codes.py::test_error_detail_fields PASSED
tests/test_stage_e_error_codes.py::test_error_codes_unique PASSED
```

---

## 验收对照

| 验收标准 | 状态 |
|----------|------|
| 6 种扩展名正确校验 | ✅ test_validate_file_ok_* |
| CSV Windows MIME 兼容 | ✅ test_validate_file_csv_windows |
| 空文件拒绝 | ✅ test_validate_file_empty |
| 超大文件拒绝 | ✅ test_validate_file_too_large |
| 非法扩展名拒绝 | ✅ test_validate_file_bad_extension |
| MIME 不匹配检测 | ✅ test_validate_file_mime_mismatch |
| 超长文件名拒绝 | ✅ test_validate_file_name_too_long |
| UploadResult 返回验证摘要 | ✅ test_save_project_upload_returns_upload_result |
| 所有错误码存在 | ✅ test_all_error_codes_present |
| 中文用户消息 | ✅ test_error_has_user_message_zh |
| 未知错误码回退 | ✅ test_get_error_unknown_fallback |
| 错误码不重复 | ✅ test_error_codes_unique |
