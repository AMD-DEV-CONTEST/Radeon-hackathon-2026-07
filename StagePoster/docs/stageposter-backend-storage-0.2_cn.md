# 让后端拥有生命周期
```text
Frontend
   ↓
Go API
   ├── SQLite Metadata
   ├── Asset Storage
   ├── Job Queue
   ├── Workflow Registry
   ├── Poster Composer
   ↓
ComfyUI
   ↓
AMD W7900

```
ComfyUI 负责生成视觉素材。
Go 后端负责产品逻辑、任务、文件、版本、合成和接口。


```
POST /generate
  ↓
INSERT jobs(status=queued)
  ↓
提交 ComfyUI
  ↓
UPDATE jobs(comfy_prompt_id, status=running)
  ↓
后台 Worker 查询结果
  ↓
复制文件到 storage/jobs/{jobId}
  ↓
INSERT outputs
  ↓
UPDATE jobs(status=succeeded)
```

backend rerun 
···
查询 queued / running 任务
        ↓
重新向 ComfyUI 对账
        ↓
恢复状态
···

Job Reconciliation

新增接口
GET  /api/jobs
GET  /api/jobs/{jobId}/outputs
POST /api/jobs/{jobId}/cancel
POST /api/jobs/{jobId}/retry

任务列表
GET /api/jobs?status=succeeded&limit=20&cursor=xxx
{
  "items": [
    {
      "jobId": "job_xxx",
      "status": "succeeded",
      "prompt": "futuristic concert poster",
      "seed": 88,
      "createdAt": "2026-07-21T06:45:00Z",
      "thumbnailUrl": "/api/jobs/job_xxx/outputs/thumbnail"
    }
  ],
  "nextCursor": null
}


第二阶段：Asset Pipeline
持久化之后再做素材上传。
新接口
POST /api/assets
GET  /api/assets/{assetId}
前端先上传：
人物照片 → asset_person_01
Logo     → asset_logo_01
参考图   → asset_reference_01
生成接口升级为：
{
  "workflow": "poster-reference",
  "prompt": "cinematic live concert poster",
  "seed": 88,

  "assets": {
    "person": "asset_person_01",
    "logo": "asset_logo_01",
    "reference": "asset_reference_01"
  }
}
后端再把素材上传到 ComfyUI，并写入对应 LoadImage 节点。
这一步才需要你在 ComfyUI 页面增加输入图片节点，并重新导出 API Workflow。
第三阶段：Workflow Registry
不要让后端只认识一个 Workflow。
生成接口以后应该支持：
{
  "workflow": "poster-text",
  "version": "1.0.0",
  "prompt": "...",
  "seed": 88
}
后端维护一个绑定清单：
{
  "prompt": {
    "nodeId": "57:27",
    "inputKey": "text"
  },
  "seed": {
    "nodeId": "57:3",
    "inputKey": "seed"
  },
  "width": {
    "nodeId": "57:13",
    "inputKey": "width"
  },
  "height": {
    "nodeId": "57:13",
    "inputKey": "height"
  }
}
不建议长期依靠自动识别节点。自动识别适合第一次烟雾测试，正式系统应该显式绑定。
现有 Workflow 现在就能扩展的字段
你已经有：
Prompt：57:27 / text
Seed：57:3 / seed
Width：57:13 / width
Height：57:13 / height
因此不改 ComfyUI，现有接口就可以先加入：
{
  "prompt": "...",
  "seed": 88,
  "width": 1024,
  "height": 1536
}
这非常适合先支持：
1:1   社交媒体
4:5   Instagram 海报
2:3   标准宣传海报
9:16  抖音 / Reels
16:9  屏幕背景
不过后端需要限制尺寸，避免前端随手填个 16000 × 16000 把 GPU 烤成太阳饼。


# 下一阶段
生成任务
  ↓
写入 SQLite
  ↓
图片归档到 backend/storage
  ↓
重启 Go 后端
  ↓
任务记录和图片仍然可访问

