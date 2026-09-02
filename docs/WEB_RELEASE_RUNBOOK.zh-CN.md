# Web 工作台发布与验收手册

本手册用于 UI 发布前的本地基线验证。它不替代最终云端模型验收；没有运行模型服务时，不能把“页面可访问”写成“RAG 已通过”。

## 1. 本地发布前检查

在仓库根目录执行：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\validate_specs.py --strict
Set-Location web
npm test
npm run build
Set-Location ..
.venv\Scripts\python.exe scripts\verify_web_release.py
```

最后一条命令只读取 `web/dist/`，为每个发布文件打印 SHA-256；将输出附在发布 PR 或部署记录中。不要把 `dist/`、Token、SSH 私钥、模型路径或云端 URL 提交到仓库。

## 2. 本地人工冒烟

启动 API：

```powershell
.venv\Scripts\python.exe scripts\start_api.py
```

另开终端启动工作台：

```powershell
Set-Location web
npm run dev
```

访问 Vite 显示的地址，完成：登录、创建项目、上传一份可解析资料和一个 CSV/XLSX 任务表、启动一次运行、查看任务证据与报告产物。管理员还应验证 System operations 可见，普通成员不可访问运维接口。

## 3. 部署顺序与回滚

1. 记录将要部署的 Git commit 和本地 `verify_web_release.py` 输出。
2. 先部署后端，再部署同一 commit 构建的 `web/dist/`；健康检查 `/health`、登录和项目列表必须可用。
3. 若 UI/API 契约异常，停止继续发布，将后端与 `web/dist/` 一并恢复到上一条已记录为通过的 commit；重新运行第 1 节的检查。
4. 不在浏览器、页面配置或截图中保存外部系统 Token、模型地址、磁盘路径或 SSH 凭据。

## 4. 最终云端门禁（最后执行）

云端模型服务恢复后，才执行以下真实验证：

```bash
python scripts/verify_end_to_end_rag_report_cloud.py
```

并额外保留三类证据：真实 RAG 报告及引用、并发队列下的任务完成情况、浏览器长时间运行后的登录与页面状态。GitHub/Jira 当前为受控流程 stub；在配置服务端凭据、最小权限和审计策略之前，不得声称已创建真实外部 Issue。
