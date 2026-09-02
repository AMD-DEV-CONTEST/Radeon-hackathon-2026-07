# TECH.md — 定期清理服务

- Level: S2
- Status: verified

## 1. 架构决策

### 1.1 清理在 FastAPI lifespan 中运行

```python
# app/main.py
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    for directory in runtime_settings.required_directories():
        directory.mkdir(parents=True, exist_ok=True)
    cleanup_task = asyncio.create_task(_cleanup_loop(runtime_settings))
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
```

选择 FastAPI lifespan 而非独立 cron 服务的原因：
- 简化部署，无需额外进程
- 与应用共享 settings 配置
- 应用关闭时自动取消清理任务

### 1.2 mtime 年龄计算

```python
def _age_days(path: Path) -> float:
    try:
        stat = path.stat()
        return (time.time() - stat.st_mtime) / 86400.0
    except OSError:
        return 0.0
```

使用 `st_mtime`（修改时间）而非 `st_ctime`（创建时间）作为年龄基准，
因为文件拷贝时 ctime 会重置但 mtime 保留原始值。

### 1.3 CleanupReport 聚合

`CleanupReport` 是纯数据类（使用 `__slots__` 节省内存），聚合并返回清理摘要：

```python
report = CleanupReport()
# → report.projects_removed, .temp_files_removed, .indexes_removed, .errors
```

### 1.4 安全删除 _remove_tree_safe

```python
def _remove_tree_safe(path, report, label):
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)  # Windows 兼容
        elif path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
    except Exception as exc:
        report.errors.append(f"{label} {path}: {exc}")
```

`ignore_errors=True` 确保 Windows 权限问题不抛出异常。

---

## 2. 文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/services/cleanup.py` | 新增 | CleanupReport + _cleanup_expired_projects + _cleanup_temp_uploads + _cleanup_old_indexes + run_cleanup |
| `app/main.py` | 修改 | 新增 _cleanup_loop 后台任务；lifespan 中启动/取消 |
| `app/config.py` | 修改 | 新增 cleanup_enabled, cleanup_cron_interval_minutes, cleanup_smoke_project_days, cleanup_temp_upload_days, cleanup_old_index_days |
| `tests/test_stage_e_cleanup.py` | 新增 | 10 个测试用例 |

---

## 3. 关键实现细节

### 3.1 清理循环

```
while cleanup_enabled:
    sleep(interval)
    try: run_cleanup()
    except: pass  # 绝不崩溃
```

### 3.2 烟雾项目匹配

```python
if not project_dir.name.startswith("smoke-"):
    continue
```

只匹配以 `smoke-` 开头的目录名。

### 3.3 同时清理 output 目录

```python
output_dir = settings.output_root / project_dir.name
if output_dir.exists():
    _remove_tree_safe(output_dir, report, f"output/{project_dir.name}")
```

### 3.4 临时文件扫描

```python
for root_dir in (settings.project_root, settings.output_root):
    for tmp in root_dir.rglob("*.tmp"):
        if _age_days(tmp) >= retention:
            tmp.unlink(missing_ok=True)
```

使用 `rglob("*.tmp")` 递归扫描所有子目录。

---

## 4. 测试覆盖

### test_stage_e_cleanup.py (10 tests)

| 测试 | 说明 |
|------|------|
| `test_cleanup_report_defaults` | CleanupReport 初始值全为 0 |
| `test_cleanup_report_total` | total 计算正确 |
| `test_cleanup_report_success` | 无错误时 success=True |
| `test_cleanup_report_with_errors` | 有错误时 success=False |
| `test_age_days` | 年龄计算正确 |
| `test_age_days_nonexistent` | 不存在的路径返回 0 |
| `test_cleanup_expired_projects` | 过期 smoke 项目被清理 |
| `test_cleanup_temp_uploads` | 过期 .tmp 文件被清理 |
| `test_cleanup_old_indexes` | 过期索引目录被清理 |
| `test_run_cleanup_handles_errors` | 清理异常不抛出 |
