# M50 · 本机 Agent https 残留回退（线上 ERR_SSL_PROTOCOL_ERROR 修复）

- **日期**：2026-08-06
- **背景**：用户在线上（botversex.feispace.me）看到大量 `GET https://localhost:8002/api/setup/health net::ERR_SSL_PROTOCOL_ERROR` 循环报错。控制台还有 `/api/v1/datasets 401`。
- **根因**：localStorage 里残留旧的 `botversex_local_agent_url=https://localhost:8002`（早期 setup 存的），而本机 Agent 是纯 HTTP——`agentFetch` 直接 fetch 存储的 https URL → 每次请求必 SSL 错误。Setup.tsx:42 也硬编码 https（但那是给装了自签证书的客户用的 href，保留正确）。
- **修复**：`agentFetch` 路由到本机 Agent 时，若 https://localhost|127.0.0.1 请求失败（SSL/网络错误），**回退到同 host 的 http 孪生重试一次，成功则 `setLocalAgentUrl(http)` 记住**——后续请求直接走 http，不再每次撞 SSL；真实客户装了自签 https 的 Agent 不受影响（只有失败才回退）。
- **关于 401**：`/api/v1/datasets 401` = 未登录时训练页拉数据被拒，属预期行为（页面应有登录提示）；不是本轮修复范围，但已向用户说明。
- **关键命令**：tsc（localAgent.ts）干净；协议冒烟 34/34（回归无影响）。
- **最终结果**：已提交。此修复随下一次 web 容器重建上线（当前线上 index-BV9a7gY5.js 是 8-5 后的某个构建，含旧逻辑）。
