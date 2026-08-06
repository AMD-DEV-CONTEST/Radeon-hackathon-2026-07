# BotverseX 内测就绪度 & 过夜推进记录

> 2026-06-16 — 给用户明天看的诚实评估

## 一句话结论

**可以小范围邀请「有机械臂、愿意装 Local Agent」的人玩**；  
**还不适合**「很多人随便点开就懂、全流程零门槛跑通」的公开 launch。

你姐姐看不懂，**不是她的问题**——首页之前是英文工程话术，没讲清「这是啥、第一步干啥」。已在 `/robots` 加中文 **FirstRunBanner**（部署后可见）。

---

## 真实链路 vs 假链路

| 环节 | 状态 | 说明 |
|------|------|------|
| 浏览 / 注册 | ✅ 真 | 内测默认 Pro，无支付 |
| Setup + Local Agent | ✅ 真 | 需本机安装，门槛高 |
| SO-101 四步向导 | ✅ 真 | 连接→遥操作→录制→训练推理 |
| Reachy 虚拟模式 | ✅ 真 | 无硬件可演示 |
| 云端 catalog API | ✅ 真 | `/api/robots` 等 |
| **云端 realtime 服务** | ⚠️ 脆弱 | Docker 版未编完；靠 runc+socat 临时桥接，**重启后可能挂** |
| 本地训练 (MLP) | ✅ 真 | 需登录 + Local Agent + 本机数据 |
| Qualia 云训练 | ⚠️ 半真 | 需服务器配 `QUALIA_API_TOKEN` |
| Workflow 部分节点 | ❌ 占位 | ApiPendingNode，别宣传 |
| AI Hub / Marketplace / 支付 | ❌ 隐藏或未完成 | 内测勿提 |

**你要的闭环「操作→采集→训练→部署→推理」：**

- **有 SO-101 + Local Agent 的用户**：代码路径是通的，SO-101 向导就是为此设计。  
- **只有浏览器、无硬件**：只能浏览 + Reachy 虚拟模式，**不能**完成真录制/真训练。  
- **只有网站、无本机 Agent**：链路在「Setup」处断掉——这是架构如此，不是 bug。

---

## 运维最大风险（今晚已再次遇到）

1. **realtime 进程不在 Docker 里** → 服务器重启后 `/api/robots` 可能 502。  
2. **应对**：`scripts/ensure-realtime.sh`（已加）+ 长期应完成 `docker compose build realtime` 或 cron `@reboot`。  
3. **磁盘 81%** → 扩阿里云盘到 80–100G。

---

## 今晚已做

- [x] `/robots` 中文首屏说明（FirstRunBanner）— **已部署线上**
- [x] 标题/按钮中文化（「选择你的机器人」「进入向导」）
- [x] `scripts/smoke-prod.sh` — 一键测线上
- [x] `scripts/ensure-realtime.sh` — 优先 Docker，fallback runc+socat
- [x] Web 镜像 rebuild 并上线
- [x] 磁盘已扩至 ~158G（22% 使用）
- [x] Docker realtime 镜像构建完成（2.77GB）并已 `up -d`
- [x] 旧 socat systemd bridge 已 disable，改用 Docker `8002:8002`
- [x] `/api/robots` 恢复 **200**
- [x] `@reboot ensure-realtime.sh` 已写入 crontab
- [ ] 本地跑一遍 smoke-prod（服务器上已跑，见下方）

### Smoke 结果（2026-06-16 04:06）

```
home 200 | robots api 200 | setup health 200 | api health 200 | plans 200 | register 200 | js bundle 200
```

---

## 明天建议你怎么推

### 给姐姐这类「完全不懂」的人

发三句话 + 一个链接：

1. **这是帮机械臂录动作、训练技能的网站**（不是卖机器人）。  
2. **没机械臂**：打开 Reachy 虚拟模式看看就行。  
3. **有机械臂**：按 Setup 装一个小程序，然后点 SO-101「进入向导」。

链接：https://botversex.feispace.me/robots

### 给真正能玩的人（5–10 人内测）

- 必须有 SO-101 或 Reachy  
- 愿意用终端装 Local Agent  
- 你微信远程帮第一次 Setup  

成功标准：至少 **1 人**录到 dataset + 跑完一次本地训练或推理。

### 暂时别宣传

- AI Hub、Workflow 高级节点、Marketplace、付费

---

## 下一步工程优先级（建议）

1. **P0** — realtime 进 Docker + `@reboot` 健康检查（消灭 502）  
2. **P0** — 部署 FirstRunBanner 到线上  
3. **P1** — SO-101 向导 Step1 加「30 秒视频/GIF」  
4. **P1** — 阿里云盘扩容  
5. **P2** — Qualia token 配到 prod（云训练）

---

## 对你问题的直接回答

> 是不是准备让很多人来玩？

**准备让「一小批对的人」玩**，不是让很多人无脑涌入。  
潜力在「真机数据闭环」，但 friction（Local Agent、证书、串口）决定了受众必须是愿意折腾的早期用户。

> 链路要真跑通？

**SO-101 向导那条链是真实代码**，不是静态演示；  
**云端 infra 还不够稳**，需要先把 realtime 服务固化，再放大邀请人数。

晚安，明天你看完这份 + 打开 `/robots` 看新 banner 即可。
