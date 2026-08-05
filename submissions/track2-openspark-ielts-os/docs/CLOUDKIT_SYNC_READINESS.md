# CloudKit 同步准备

当前应用的学习数据默认只保存在本机，并支持导出/导入备份。启用 CloudKit 前，不应把整个 LocalStorage 原样上传；应按实体同步并保留冲突规则。

## 需要同步的数据

| 实体 | 本机来源 | 主键 | 冲突规则 |
| --- | --- | --- | --- |
| 单词进度 | `wordProgress` | word | `updatedAt` 最新优先 |
| 错题与复习调度 | `wrongQuestions` | id | 合并复习次数，`nextReviewDate` 取更早日期 |
| 写作草稿/历史 | `writingDrafts` | taskId + versionId | 版本追加，不覆盖历史稿 |
| 学习事件 | `learningEvents` | id | 追加去重 |
| 口语会话文本 | `speakingSessions` | id | 追加去重；录音文件不自动同步 |
| 学习计划与反思 | plan/reflection keys | date | `updatedAt` 最新优先 |
| 稍后学习、资料路径进度 | item/path id | id | 状态合并，完成状态不可回退 |

## 不同步的数据

- 原始 PDF、视频、音频：继续保留在用户自己的 iCloud Drive，按需打开。
- 口语录音二进制：默认仅本机，避免占用 iCloud 空间；后续可单独开启录音备份。
- API Key、登录 Cookie、系统缓存。

## 启用前置条件

1. 用付费 Apple Developer 团队签名，而不是免费 7 天开发签名。
2. 在 Apple Developer 的 App ID `com.francischi.ieltsos` 启用 iCloud capability。
3. 创建并绑定 CloudKit container，例如 `iCloud.com.francischi.ieltsos`。
4. 在 Xcode 的 Signing & Capabilities 添加 iCloud / CloudKit，并重新生成 provisioning profile。
5. 先在 Development 环境做两台设备的冲突、离线编辑和删除恢复测试；通过后再部署 Production schema。

## 客户端策略

- 启动时拉取增量；本地写入后使用后台队列上传。
- 网络不可用时只写本地，恢复网络后重试。
- 每次同步保留本地恢复副本，失败时不清空学习记录。
- 设置页显示“最近同步时间 / 待上传数量 / 立即同步”，不显示伪造的“已同步”。

## 验收标准

- 同一账号两台设备的单词进度、错题、写作历史在 30 秒内收敛。
- 同时编辑同一草稿时保留两个版本，不丢文本。
- 删除 App 后恢复登录能取回同步数据。
- 飞行模式完成学习后，联网可补传且不产生重复学习事件。
