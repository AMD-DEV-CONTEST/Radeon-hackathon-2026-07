# server/

后端服务（FastAPI，P2 已实现）。

## 功能

- 任务 API：`POST /api/jobs` 提交生成任务（W1 文本参数 / W2·W3 图片上传 / W4·W5 音频参数）
- 状态查询：`GET /api/jobs/{id}`（自动同步 ComfyUI 执行状态）
- 结果预览/下载：`GET /api/jobs/{id}/image`（代理 ComfyUI `/view`）
- 工作流列表：`GET /api/workflows`
- 任务记录：SQLite（`server/data/jobs.db`，不提交 git）
- 前端静态托管：`GET /`（web/index.html）

## 启动

```bash
bash server/run.sh          # 默认 8000 端口，COMFY_URL 指向 127.0.0.1:8188
```

## 依赖

```bash
pip install -r server/requirements.txt
```

> 下一阶段可扩展：WebSocket 实时进度、任务审批流（确认后再触发 W3/W4）、资产打包下载。
