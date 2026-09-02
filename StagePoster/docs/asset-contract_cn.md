StagePoster Asset Contract v1.0

目标：定义素材上传、校验、存储、预处理和生命周期存储方式：服务器本地文件系统 + SQLite 元数据

1. 核心规则

素材只上传一次。

上传文件
  ↓
后端返回 asset_id
  ↓
生成请求引用 asset_id

前端不能在生成接口中提交：

Base64 图片

本地文件路径

服务器绝对路径

ComfyUI 输入路径

未经后端导入的外部 URL

2. 素材类型

类型

含义

格式

用途

artist_image

人物或乐队图片

PNG、JPEG、WebP

人物参考和身份控制

logo

活动、品牌、乐队 Logo

PNG、WebP、SVG

最终确定性合成

style_reference

风格参考图

PNG、JPEG、WebP

风格分析或图片条件

background_reference

背景或地点参考

PNG、JPEG、WebP

构图或背景条件

后续预留：

audio
video
mask
font
document

3. 上传协议

POST /api/v1/projects/{project_id}/assets

格式：

multipart/form-data

字段：

字段

必填

说明

file

是

单个文件

asset_type

是

素材类型

label

否

用户展示名称

rights_confirmed

是

必须为 true

client_asset_id

否

前端本地关联 ID

MVP 每次请求上传一个文件。

前端可以并行上传多个请求。

4. 文件限制

建议默认：

类型

最大大小

最小尺寸

最大尺寸

普通图片

20 MiB

256 × 256

12000 × 12000

SVG Logo

2 MiB

不适用

预处理时转换

必须执行：

根据文件内容识别 MIME。

不信任扩展名。

限制解码后的像素数量。

校验图片是否可解码。

应用 EXIF Orientation。

转为 sRGB。

处理或移除不必要元数据。

限制动画图片。

检查 SVG 脚本和外部引用。

防止压缩炸弹。

限制由 /capabilities 返回。

5. 素材状态机

uploaded
  ↓
validating
  ↓
processing
  ↓
ready

失败分支：

validating → rejected
processing → failed
ready → deleted

状态

含义

可用于生成

uploaded

已接收二进制

否

validating

正在校验

否

processing

正在标准化和生成预览

否

ready

可使用

是

rejected

文件不合法

否

failed

服务端处理失败

否

deleted

已删除

否

小图片可以在一个上传请求中同步处理完成并直接返回 ready。

6. SQLite 元数据

建议字段：

id
project_id
asset_type
status
label
original_filename
stored_filename
mime_type
size_bytes
width
height
checksum_sha256
storage_key
preview_storage_key
client_asset_id
rights_confirmed
rejection_code
created_at
updated_at
deleted_at

SQLite 不保存大文件 Blob。

SQLite 只保存文件元数据和存储引用。

7. 文件目录结构

outputs/
  projects/
    <project_id>/
      uploads/
        originals/
      processed/
        normalized/
        previews/
        masks/
      generated/
        <job_id>/
          intermediate/
          final/

规则：

路径使用后端生成的 ID。

原始文件名只作为元数据。

原始文件名不能直接作为磁盘路径。

拒绝路径穿越字符。

上传先写临时目录。

校验成功后原子移动到正式目录。

中断上传必须定期清理。

8. 各类型预处理

8.1 Artist Image

至少完成：

图片解码

方向修正

sRGB 转换

高质量标准化副本

前端预览图

尺寸和主体占比检查

后续可增加：

人物分割

背景移除

Face Detection

Identity Embedding

自动裁剪建议

Mask

原图必须保留，以便重新处理。

8.2 Logo

规则：

必须保留原始 Logo 形态。

不允许扩散模型重绘 Logo。

保留透明通道。

SVG 必须安全清洗。

SVG 可转换为安全高分辨率 PNG。

Logo 在最终排版阶段合成。

可生成浅色和深色预览。

8.3 Style Reference

至少完成：

标准化

预览图

尺寸记录

宽高比记录

后端决定它用于：

Image Conditioning

风格分析

Prompt 上下文

调色参考

8.4 Background Reference

至少完成：

标准化

预览

尺寸记录

宽高比检查

可能用于：

背景重绘

构图参考

场景参考

Control 输入

9. 素材绑定规则

角色

允许类型

数量

primary_artist

artist_image

MVP 必须 1 个

secondary_artist

artist_image

0 至 3

event_logo

logo

0 至 1

brand_logo

logo

0 至 3

style_reference

style_reference

0 至 3

background_reference

background_reference

0 至 1

texture_reference

style_reference

0 至 1

不兼容组合必须在进入 GPU 队列前失败。

10. 素材公开响应

可返回：

{
  "id": "asset_01K...",
  "project_id": "proj_01K...",
  "asset_type": "artist_image",
  "status": "ready",
  "label": "Lead singer",
  "mime_type": "image/png",
  "width": 2048,
  "height": 2048,
  "size_bytes": 4821931,
  "preview_url": "https://<host>/api/v1/assets/asset_01K.../preview",
  "created_at": "2026-07-20T12:01:00Z"
}

不能返回：

磁盘绝对路径

ComfyUI 路径

Storage Key

Stack Trace

服务端内部目录

11. 文件访问策略

MVP 由 Go 后端提供文件。

要求：

使用不透明 Asset ID。

校验访问权限。

正确设置 MIME。

防止目录遍历。

禁止目录列表。

Preview 可配置缓存。

最终输出可配置长期缓存。

后续可替换成对象存储签名 URL。

12. 重复文件检测

上传后计算 SHA-256。

同一 Project 内：

相同文件可复用磁盘内容。

不同语义角色可拥有不同 Asset 记录。

不自动跨 Project 合并素材。

13. 删除策略

MVP 推荐逻辑删除：

标记 Asset 为 deleted。

禁止新 Job 使用。

已存在 Job 的快照仍保留。

后台安全清理文件。

前端不能假设删除接口返回后，文件立即从磁盘消失。

14. SQLite 和文件系统一致性

SQLite 和文件系统无法共享一个原子事务。

推荐流程：

文件写入临时目录。

完成格式和内容校验。

生成标准化副本和预览。

文件移动到正式目录。

更新 SQLite 记录。

删除临时文件。

后端启动时检查：

数据库有记录但文件丢失

文件存在但数据库没有记录

超时临时文件

预览生成失败

未完成上传

黑客松阶段做一次启动检查即可。

15. 远程服务器模式

当前 GPU 服务器运行后端时：

Frontend
  ↓ 上传素材
StagePoster API
  ↓ 保存本地文件
SQLite 记录 Asset
  ↓ 创建 Job
ComfyUI 使用服务器本地素材
  ↓
返回 Output URL

素材不需要经过 GitHub。

前端不需要同步服务器目录。

16. 最低安全要求

限制文件大小

限制请求 Body

MIME 检测

图片解码校验

SVG 安全处理

文件名清洗

后端生成路径

CORS 白名单

上传速率限制

Project 素材数量限制

临时文件清理

不公开 ComfyUI

17. 验收标准

前端能独立上传每种素材。

每个素材获得稳定 Asset ID。

非法素材在生成前被拒绝。

内部路径永不泄漏。

Logo 被原样保留。

素材绑定可完整校验。

重启后素材仍可访问。

Mock 和 Comfy 使用同一上传 API。

Runtime Asset 不提交 GitHub。

