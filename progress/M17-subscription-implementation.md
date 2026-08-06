# M17 — 三档订阅实现记录

日期: 2026-05-12

## 已落地

### API
- [`apps/api/app/data/plans.yaml`](../apps/api/app/data/plans.yaml) — free / pro / creator 配额真源
- [`apps/api/app/services/entitlement_service.py`](../apps/api/app/services/entitlement_service.py) — 统一门禁与用量计数
- User 字段：`subscription_tier`, `tier_expires_at`, `stripe_customer_id`
- 表：`usage_counters`, `skill_listings`, `subscription_records`
- 迁移：`python -m app.migrations.m17_subscription`
- `/api/v1/auth/me` 返回 entitlements
- `/api/v1/auth/plans` 公开套餐目录
- 训练/Skill run 创建前配额检查；训练列表按用户过滤（admin 看全部）
- `/api/v1/billing/webhook/stripe`（stub）、`/api/v1/billing/admin/set-tier`
- `/api/v1/marketplace/*` 上架与批量任务 stub

### Web
- `useEntitlements` 数据来自 `/me`
- [`UpgradeModal`](../apps/web/src/components/billing/UpgradeModal.tsx)
- Workflow 调色板按 tier 过滤；Pro 节点 `camera_denoise`, `trajectory_optimize`
- Navbar 显示套餐名

### Realtime
- `X-Inference-Priority` 头与 status 中的 `queue_tier`

## 验收

```bash
bash scripts/botclaw-acceptance-gate.sh
cd apps/api && python -m app.migrations.m17_subscription
```

免费用户 `POST /api/v1/trainings` + `train_backend=qualia` → 402 `tier_required_pro`。

Admin 用户 `POST /api/v1/billing/admin/set-tier` body `{"tier":"pro","days":30}` 后限额放开。
