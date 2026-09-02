1. 公网地址 api :

backend : 8080

内部架构 : Frontend
   |
   |
Cloudflare Tunnel
   |
   |
Go Poster API
   |
   |
ComfyUI API
   |
   |
AMD Radeon W7900 GPU
   |
   |
Z-Image Turbo
2. health check 
检查服务是否在线
request
GET ： /health

response :
{
  "status": "ok",
  "comfy": "connected",
  "tokenRequired": true,
  "bindings": {
    "prompt": {
      "nodeId": "57:27",
      "inputKey": "text"
    },
    "seed": {
      "nodeId": "57:3",
      "inputKey": "seed"
    }
  }
}

|字段|含义|
|-|-|
|status|Backend状态|
|comfy|ComfyUI GPU服务状态|
|prompt node|提示词节点|
|seed node|随机种子节点|
3. 创建生成任务
核心接口。
POST
/api/generate
完整：

POST 
Headers
必须：
Content-Type: application/json

X-Poster-Token: poster-dev-2026
Request Body
{
  "prompt": "A futuristic live concert poster, cinematic stage light, premium fashion editorial composition",
  "seed": 88
}

|字段|类型|必须|说明|
|-|-|-|-|
|prompt|string|✅|生成描述|
|seed|number|❌|随机种子|

4. response 

success :
{
  "jobId": "39581fad-fda9-46ca-9c30-fbfc03e7555e",
  "promptId": "39581fad-fda9-46ca-9c30-fbfc03e7555e",
  "status": "queued",
  "seed":88
}

save :
const jobId = response.jobId

查询状态

5。 查询生成状态
GET
/api/jobs/{jobId}
例如：
GET /api/jobs/39581fad-fda9-46ca-9c30-fbfc03e7555e
返回：
生成中：
{
 "jobId":"xxx",
 "status":"running"
}
完成：
{
 "jobId":"xxx",
 "status":"succeeded",
 "result":{
    "filename":"z-image-turbo_00015_.png",
    "type":"output"
 }
}
失败：
{
 "status":"failed",
 "error":"..."
}

6. 获取生成图片
GET
/api/jobs/{jobId}/result
例如：
GET
/api/jobs/39581fad-fda9-46ca-9c30-fbfc03e7555e/result
返回：
image/png
前端：
const imageUrl =
`${API_URL}/api/jobs/${jobId}/result`
然后：
<img src={imageUrl}/>

7. 7. 推荐前端流程
前端状态机：
用户输入海报需求

        |
        v

POST /api/generate

        |
        v

得到 jobId

        |
        v

loading动画

        |
        v

每2秒轮询

GET /api/jobs/{jobId}

        |
        |
   +----+----+
   |         |
running   succeeded

             |
             v

显示图片

固定一个环境变量
VITE_API_URL=https://xxx.trycloudflare.com

8. 当前限制
目前 MVP：
✅ 文生图
✅ Prompt控制
✅ Seed控制
✅ GPU生成
✅ 公网访问
✅ 前后端分离  
暂未实现：
用户上传人物图片
Logo上传
歌词输入
多图组合
视频/VJ生成
用户历史记录
登录系统

