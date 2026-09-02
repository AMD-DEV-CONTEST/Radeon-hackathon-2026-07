# Spec: 定期清理服务 (Periodic Cleanup Service)

| 字段 | 值 |
|------|-----|
| **Spec ID** | `stable-cleanup-260722-0000` |
| **阶段** | Stage E |
| **状态** | ✅ implemented / verified |
| **创建日期** | 2026-07-22 |
| **对应路线图** | FULL_PRODUCT_ROADMAP.zh-CN.md — 阶段 E |

---

## 1. 概述

本 spec 覆盖阶段 E 的定期清理服务，自动清除过期资源，防止磁盘空间无限增长。

三类清理对象：
1. **过期烟雾测试项目** — `cleanup_smoke_project_days` 天后删除 `smoke-*` 项目
2. **过期临时上传** — `cleanup_temp_upload_days` 天后删除 `*.tmp` 文件
3. **旧向量索引** — `cleanup_old_index_days` 天后删除向量数据库索引目录

---

## 2. 用户故事

### US-1: 自动清理

**作为** 平台运维
**我想要** 系统自动清理过期的项目、临时文件和索引
**以便** 磁盘空间不会因测试和临时数据而耗尽

**验收标准：**
- 清理循环在 FastAPI lifespan 中作为后台 `asyncio.Task` 运行
- 可配置间隔（`cleanup_cron_interval_minutes`）
- 清理失败不影响主应用（异常被静默捕获）
- 可通过 `cleanup_enabled=False` 完全关闭

### US-2: 烟雾项目清理

**作为** 开发者
**我想要** 超过保留期的烟雾测试项目自动删除
**以便** 不需要手动清理测试产生的数据

**验收标准：**
- 只清理项目名以 `smoke-` 开头的目录
- 按项目目录的 mtime 判断年龄
- 同时删除对应的 output 目录
- 保留天数可配置

### US-3: 临时文件清理

**作为** 平台运维
**我想要** `*.tmp` 文件在过期后自动删除
**以便** 减少无用的磁盘占用

**验收标准：**
- 扫描 `project_root` 和 `output_root` 下的所有 `*.tmp` 文件
- 按文件 mtime 判断年龄
- 过期文件被 `unlink`

### US-4: 旧索引清理

**作为** 平台运维
**我想要** 过期的向量索引目录自动删除
**以便** 释放向量数据库的存储空间

**验收标准：**
- 扫描 `vector_db_root` 下的子目录
- 按目录 mtime 判断年龄
- 过期目录被 `rmtree` 删除

---

## 3. 数据模型

### CleanupReport

| 字段 | 类型 | 说明 |
|------|------|------|
| `projects_removed` | `int` | 清理的项目数 |
| `temp_files_removed` | `int` | 清理的临时文件数 |
| `indexes_removed` | `int` | 清理的索引目录数 |
| `errors` | `list[str]` | 错误列表 |

**计算属性：**
- `total` → 清理总数
- `success` → 是否无错误

---

## 4. 清理流程

```
app/main.py: _cleanup_loop()
  └── while cleanup_enabled:
      ├── sleep(cleanup_cron_interval_minutes * 60)
      └── run_cleanup(settings)  [try/except 静默]
          ├── _cleanup_expired_projects()
          │   └── for smoke-* dirs: age ≥ retention → rmtree
          ├── _cleanup_temp_uploads()
          │   └── for *.tmp files: age ≥ retention → unlink
          └── _cleanup_old_indexes()
              └── for index dirs: age ≥ retention → rmtree
```

年龄计算基于文件/目录的 `st_mtime`（修改时间）：
```python
age_days = (time.time() - st_mtime) / 86400.0
```

---

## 5. 配置

| 配置项 | 默认值 | 范围 | 说明 |
|--------|--------|------|------|
| `cleanup_enabled` | `True` | bool | 是否启用清理 |
| `cleanup_cron_interval_minutes` | `60` | 1-1440 | 清理间隔（分钟） |
| `cleanup_smoke_project_days` | `1` | 0-365 | 烟雾项目保留天数 |
| `cleanup_temp_upload_days` | `7` | 0-365 | 临时文件保留天数 |
| `cleanup_old_index_days` | `30` | 0-365 | 旧索引保留天数 |

---

## 6. 安全设计

- `shutil.rmtree` 使用 `ignore_errors=True`，Windows 权限问题不中断清理
- 清理循环的异常被 `try/except` 完全捕获，不会导致 FastAPI 崩溃
- 三个清理函数各自独立，任一失败不影响其他
- 值为 `0` 的保留天数表示跳过该类型清理（不执行）

---

## 7. 验收目标

- [x] 清理在 lifespan 后台任务中运行
- [x] 烟雾项目 `smoke-*` 过期后被清理
- [x] `*.tmp` 临时文件过期后被清理
- [x] 向量索引目录过期后被清理
- [x] 同时清理对应的 output 目录
- [x] 清理失败不影响应用运行
- [x] 可通过配置关闭清理
- [x] 可通过配置调整保留天数和间隔
- [x] 所有测试通过（test_stage_e_cleanup.py, 10 个用例）
