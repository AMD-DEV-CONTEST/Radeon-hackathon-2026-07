# M51 · 「登录已过期」全局横幅（401 不再静默）

- **日期**：2026-08-06
- **背景**：用户线上反馈「好多东西都没法正常看见」，控制台有大量 `401`。根因：token 过期时 `authFetch` **静默登出**（logout + 抛 AuthRequiredError），页面悄悄降级到磁盘数据——用户不知道为什么少了功能。
- **完成了什么**：
  - `lib/auth.ts`：新增 auth-required 全局标记（`markAuthRequired` / `clearAuthRequired` / `isAuthRequired` / `onAuthRequired` 订阅），`authFetch` 撞 401 时打标记再登出。
  - `lib/authContext.tsx`：context 暴露 `authRequired` + `dismissAuthRequired`（订阅标记变化）。
  - `Layout.tsx`：全局横幅「登录已过期，部分数据与操作不可用」+「重新登录」（`/login?redirect=<当前页>`，Login 页已支持该参数）+「知道了」。
- **解决了什么**：401 从「静默降级」变「明确提示」，用户知道要重新登录且登录后回到原页面。
- **关键命令**：auth/authContext/Layout 三文件 tsc 严格检查干净。
- **最终结果**：已提交。随下一次 web 容器重建上线。
- **下一步**：v2 主线继续；部署重建仍等用户确认（M50/M51 都在等同一趟）。
