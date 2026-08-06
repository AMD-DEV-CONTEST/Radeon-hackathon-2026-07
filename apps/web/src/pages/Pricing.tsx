import { useEffect, useState } from 'react'
import {
  Check,
  X,
  Sparkles,
  Zap,
  Crown,
  Loader2,
  HardDrive,
  Cpu,
  Cloud,
  Layers,
  Gamepad2,
  ShieldCheck,
  Store,
  MessageCircle,
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { useAuth } from '../lib/authContext'
import {
  fetchPlansCatalog,
  type PlanLimits,
  type PlansCatalog,
  type SubscriptionTier,
} from '../lib/entitlements'
import { CONTACT } from '../config/contact'

interface TierCard {
  tier: SubscriptionTier
  name: string
  price: string
  priceSub: string
  badge?: string
  icon: React.ReactNode
  accent: string
  limits: PlanLimits | null
}

function fmtStorage(bytes: number): string {
  if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(0)} TB`
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(0)} GB`
  return `${(bytes / 1e6).toFixed(0)} MB`
}

function fmtLimit(n: number): string {
  return n < 0 ? '无限' : String(n)
}

export function Pricing() {
  const { user } = useAuth()
  const currentTier = (user?.subscription_tier ?? user?.entitlements?.tier ?? 'free') as SubscriptionTier

  const [catalog, setCatalog] = useState<PlansCatalog | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchPlansCatalog()
      .then(setCatalog)
      .catch((e) => setErr((e as Error).message))
  }, [])

  const limitsMap: Record<string, PlanLimits | null> = {}
  if (catalog) {
    for (const p of catalog.plans) limitsMap[p.tier] = p.limits
  }

  const pricing = catalog?.pricing ?? {
    pro_usd_monthly: 9,
    pro_cny_monthly: 68,
    creator_cny_monthly: 128,
  }

  const cards: TierCard[] = [
    {
      tier: 'free',
      name: '免费版',
      price: '¥0',
      priceSub: '永久免费',
      icon: <Zap className="h-6 w-6" />,
      accent: 'from-emerald-500/20 to-teal-500/20',
      limits: limitsMap.free ?? null,
    },
    {
      tier: 'pro',
      name: '个人会员',
      price: `¥${pricing.pro_cny_monthly}`,
      priceSub: `/ 月（≈$${pricing.pro_usd_monthly}/mo）`,
      badge: '推荐',
      icon: <Sparkles className="h-6 w-6" />,
      accent: 'from-blue-500/20 to-indigo-500/20',
      limits: limitsMap.pro ?? null,
    },
    {
      tier: 'creator',
      name: '高级创作者版',
      price: `¥${pricing.creator_cny_monthly}`,
      priceSub: '/ 月',
      icon: <Crown className="h-6 w-6" />,
      accent: 'from-amber-500/20 to-orange-500/20',
      limits: limitsMap.creator ?? null,
    },
  ]

  type FeatureRow = {
    label: string
    icon: React.ReactNode
    values: [string | boolean, string | boolean, string | boolean]
  }

  const featureRows: FeatureRow[] = catalog
    ? [
        {
          label: '数据集存储',
          icon: <HardDrive className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? fmtStorage(c.limits.storage_bytes) : '—')) as [string, string, string],
        },
        {
          label: '本地训练 / 月',
          icon: <Cpu className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? fmtLimit(c.limits.training_local_monthly) : '—')) as [string, string, string],
        },
        {
          label: 'Qualia 云训练 / 月',
          icon: <Cloud className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? fmtLimit(c.limits.training_qualia_monthly) : '—')) as [string, string, string],
        },
        {
          label: 'Qualia 最大时长',
          icon: <Cloud className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? (c.limits.qualia_max_hours > 0 ? `${c.limits.qualia_max_hours}h` : '—') : '—')) as [string, string, string],
        },
        {
          label: '并发训练上限',
          icon: <Layers className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? String(c.limits.training_concurrent_max) : '—')) as [string, string, string],
        },
        {
          label: 'Skill 调用 / 月',
          icon: <Gamepad2 className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? fmtLimit(c.limits.skill_runs_monthly) : '—')) as [string, string, string],
        },
        {
          label: '推理优先级',
          icon: <Zap className="h-4 w-4" />,
          values: cards.map((c) => {
            if (!c.limits) return '—'
            const p = c.limits.inference_priority
            return p === 0 ? '普通' : p <= 10 ? '优先' : '最高'
          }) as [string, string, string],
        },
        {
          label: '工作流节点数',
          icon: <Layers className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? String(c.limits.workflow_nodes.length) : '—')) as [string, string, string],
        },
        {
          label: '动作动词数',
          icon: <Gamepad2 className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? String(c.limits.verbs.length) : '—')) as [string, string, string],
        },
        {
          label: '上架付费 Skill',
          icon: <Store className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? c.limits.can_publish_paid_skills : false)) as [boolean, boolean, boolean],
        },
        {
          label: '商用授权',
          icon: <ShieldCheck className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? c.limits.commercial_license : false)) as [boolean, boolean, boolean],
        },
        {
          label: '批量任务',
          icon: <Cpu className="h-4 w-4" />,
          values: cards.map((c) => (c.limits ? c.limits.batch_jobs : false)) as [boolean, boolean, boolean],
        },
      ]
    : []

  return (
    <div className="container mx-auto px-4 py-8 space-y-10">
      {/* Header */}
      <div className="text-center space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">选择您的套餐</h1>
        <p className="text-muted-foreground max-w-lg mx-auto">
          从免费版起步，随时升级解锁更大存储、Qualia 云训练、高级工作流节点和创作者商业化能力。
        </p>
      </div>

      {err && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300 text-center">
          无法加载套餐信息：{err}
        </div>
      )}

      {!catalog && !err && (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-12">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载套餐中…
        </div>
      )}

      {/* Pricing Cards */}
      {catalog && (
        <div className="grid gap-6 md:grid-cols-3 max-w-5xl mx-auto">
          {cards.map((card) => {
            const isCurrent = card.tier === currentTier
            const isPopular = card.tier === 'pro'
            return (
              <div
                key={card.tier}
                className={`relative flex flex-col rounded-2xl border bg-card p-6 transition-shadow hover:shadow-lg ${
                  isPopular
                    ? 'border-primary shadow-md shadow-primary/10 ring-1 ring-primary/20'
                    : 'border-border'
                }`}
              >
                {isPopular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-primary px-4 py-1 text-xs font-semibold text-primary-foreground">
                    {card.badge}
                  </div>
                )}

                {/* Gradient accent strip */}
                <div className={`absolute top-0 left-0 right-0 h-1 rounded-t-2xl bg-gradient-to-r ${card.accent}`} />

                <div className="flex items-center gap-3 mb-4 mt-2">
                  <div className={`flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br ${card.accent}`}>
                    {card.icon}
                  </div>
                  <div>
                    <div className="font-semibold text-lg">{card.name}</div>
                  </div>
                </div>

                <div className="mb-6">
                  <span className="text-4xl font-extrabold tracking-tight">{card.price}</span>
                  <span className="text-sm text-muted-foreground ml-1">{card.priceSub}</span>
                </div>

                {/* Quick highlights */}
                {card.limits && (
                  <ul className="space-y-2.5 mb-6 text-sm flex-1">
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                      <span>{fmtStorage(card.limits.storage_bytes)} 数据集存储</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                      <span>{fmtLimit(card.limits.training_local_monthly)} 本地训练 / 月</span>
                    </li>
                    <li className="flex items-center gap-2">
                      {card.limits.training_qualia_monthly > 0 ? (
                        <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                      ) : (
                        <X className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                      )}
                      <span className={card.limits.training_qualia_monthly === 0 ? 'text-muted-foreground' : ''}>
                        {card.limits.training_qualia_monthly > 0
                          ? `${card.limits.training_qualia_monthly} 次 Qualia 云训练 / 月`
                          : 'Qualia 云训练'}
                      </span>
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                      <span>{fmtLimit(card.limits.skill_runs_monthly)} Skill 调用 / 月</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                      <span>{card.limits.workflow_nodes.length} 种工作流节点</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                      <span>{card.limits.verbs.length} 个动作动词</span>
                    </li>
                    {card.limits.can_publish_paid_skills && (
                      <li className="flex items-center gap-2">
                        <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                        <span>上架付费 Skill / 商用授权</span>
                      </li>
                    )}
                  </ul>
                )}

                <div className="mt-auto">
                  {isCurrent ? (
                    <Button variant="outline" className="w-full" disabled>
                      当前套餐
                    </Button>
                  ) : (
                    <Button
                      variant={isPopular ? 'default' : 'outline'}
                      className="w-full gap-2"
                      onClick={() => {
                        const tg = `https://t.me/${CONTACT.telegram.replace('@', '')}`
                        window.open(tg, '_blank', 'noopener')
                      }}
                    >
                      <MessageCircle className="h-4 w-4" />
                      申请内测 / 联系我们
                    </Button>
                  )}
                  <p className="text-[10px] text-center text-muted-foreground mt-2">
                    {card.tier === 'free' ? '无需信用卡' : '内测期通过管理员开通，正式支付通道开发中'}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Feature comparison table */}
      {catalog && featureRows.length > 0 && (
        <div className="max-w-5xl mx-auto">
          <h2 className="text-xl font-semibold text-center mb-6">功能对比</h2>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/30">
                  <th className="text-left py-3 px-4 font-medium text-muted-foreground w-[240px]">
                    功能
                  </th>
                  {cards.map((c) => (
                    <th key={c.tier} className="text-center py-3 px-4 font-semibold">
                      {c.name}
                      {c.tier === currentTier && (
                        <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-primary/15 text-primary font-medium">
                          当前
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {featureRows.map((row, i) => (
                  <tr
                    key={row.label}
                    className={i % 2 === 0 ? 'bg-transparent' : 'bg-muted/15'}
                  >
                    <td className="py-3 px-4 flex items-center gap-2 text-muted-foreground">
                      {row.icon}
                      {row.label}
                    </td>
                    {row.values.map((val, j) => (
                      <td key={j} className="text-center py-3 px-4">
                        {typeof val === 'boolean' ? (
                          val ? (
                            <Check className="h-4 w-4 text-emerald-500 mx-auto" />
                          ) : (
                            <X className="h-4 w-4 text-muted-foreground/40 mx-auto" />
                          )
                        ) : (
                          <span className="font-medium">{val}</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Contact strip */}
      <div className="max-w-2xl mx-auto text-center space-y-3 pb-8">
        <div className="flex flex-wrap items-center justify-center gap-2">
          <a
            href={`https://t.me/${CONTACT.telegram.replace('@', '')}`}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full border border-border bg-card px-3 py-1.5 text-xs hover:bg-muted transition-colors"
          >
            Telegram {CONTACT.telegram}
          </a>
          <span className="rounded-full border border-border bg-card px-3 py-1.5 text-xs">
            微信 {CONTACT.wechat}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          内测期间可通过管理员 API <code className="font-mono text-[10px]">POST /api/v1/billing/admin/set-tier</code> 手动升级。
        </p>
      </div>
    </div>
  )
}
