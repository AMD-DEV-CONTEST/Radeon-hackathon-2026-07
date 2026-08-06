import Link from 'next/link';
import { getServerT, getServerLang } from '@/lib/i18n-server';

export const dynamic = 'force-dynamic';

interface Plan {
  id: string;
  name: { zh: string; en: string };
  price: { amount: string; period: string };
  description: { zh: string; en: string };
  features: { zh: string; en: string }[];
  cta: { zh: string; en: string };
  highlighted: boolean;
  badge?: { zh: string; en: string };
}

const PLANS: Plan[] = [
  {
    id: 'free',
    name: { zh: '入门版', en: 'Starter' },
    price: { amount: '¥0', period: '/mo' },
    description: { zh: '适合刚开始接单的自由职业者', en: 'For freelancers just getting started' },
    features: [
      { zh: '最多 10 个项目', en: 'Up to 10 projects' },
      { zh: 'AI 对话助手', en: 'AI chat assistant' },
      { zh: '项目 & 客户管理', en: 'Project & client management' },
      { zh: '合同生成', en: 'Contract generation' },
      { zh: '基础数据看板', en: 'Basic dashboard' },
    ],
    cta: { zh: '免费开始', en: 'Start Free' },
    highlighted: false,
  },
  {
    id: 'pro',
    name: { zh: '专业版', en: 'Pro' },
    price: { amount: '¥49', period: '/mo' },
    description: { zh: '适合全职自由职业者和小团队', en: 'For full-time freelancers' },
    features: [
      { zh: '无限项目', en: 'Unlimited projects' },
      { zh: '发票生成 & 收款记录', en: 'Invoicing & payment tracking' },
      { zh: '月度业务报告', en: 'Monthly business reports' },
      { zh: '知识库 RAG', en: 'Knowledge base RAG' },
      { zh: '汇率 & 定价基准', en: 'Exchange rates & pricing benchmarks' },
      { zh: '优先邮件支持', en: 'Priority email support' },
    ],
    cta: { zh: '升级专业版', en: 'Upgrade to Pro' },
    highlighted: true,
    badge: { zh: '最受欢迎', en: 'Most Popular' },
  },
  {
    id: 'team',
    name: { zh: '团队版', en: 'Team' },
    price: { amount: '¥149', period: '/mo' },
    description: { zh: '适合协作团队和工作室', en: 'For collaborative teams & studios' },
    features: [
      { zh: '专业版全部功能', en: 'Everything in Pro' },
      { zh: '最多 5 个成员', en: 'Up to 5 members' },
      { zh: '团队协作 & 权限', en: 'Team collaboration & roles' },
      { zh: '共享项目看板', en: 'Shared project dashboard' },
      { zh: 'API 接入', en: 'API access' },
      { zh: '专属客服支持', en: 'Dedicated support' },
    ],
    cta: { zh: '联系我们', en: 'Contact Us' },
    highlighted: false,
  },
];

function CheckIcon() {
  return (
    <svg className="h-4 w-4 flex-shrink-0 text-amber-400" viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
    </svg>
  );
}

/**
 * Checkout is only offered when the whole loop can complete: a key to charge
 * with, a price to charge for, and a webhook secret so the payment actually
 * grants the plan. Missing any one of them means the button would take money
 * without delivering, so Pro falls back to the same contact flow as Team.
 */
const BILLING_ENABLED = Boolean(
  process.env.STRIPE_SECRET_KEY &&
  process.env.STRIPE_PRO_PRICE_ID &&
  process.env.STRIPE_WEBHOOK_SECRET,
);

export default function PricingPage() {
  const t = getServerT();
  const lang = getServerLang();

  const contactHref = (message: string) =>
    '/chat?prefill=' + encodeURIComponent(message);

  function ctaFor(plan: Plan): { href: string; label: string } {
    if (plan.id === 'free') {
      return { href: '/dashboard', label: plan.cta[lang] };
    }

    if (plan.id === 'team' || !BILLING_ENABLED) {
      return {
        href: contactHref(
          lang === 'zh'
            ? `我想了解${plan.name.zh}方案`
            : `I want to learn about the ${plan.name.en} plan`,
        ),
        label:
          plan.id === 'team'
            ? plan.cta[lang]
            : lang === 'zh'
              ? '预约开通'
              : 'Request access',
      };
    }

    return { href: `/api/stripe/checkout?plan=${plan.id}`, label: plan.cta[lang] };
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-16 sm:py-24">
      {/* Header */}
      <div className="text-center">
        <h1 className="text-[28px] font-bold tracking-tight text-gray-900 dark:text-white sm:text-[32px]">
          {lang === 'zh' ? '选择适合你的方案' : 'Choose your plan'}
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-[14px] text-gray-500 dark:text-white/40">
          {lang === 'zh'
            ? '从免费开始，随业务成长随时升级。所有方案均包含 AI 对话核心能力。'
            : 'Start free, upgrade as you grow. All plans include the core AI conversation engine.'}
        </p>
      </div>

      {/* Plans */}
      <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-3">
        {PLANS.map((plan) => (
          <div
            key={plan.id}
            className={`relative flex flex-col rounded-2xl border p-6 transition-all duration-200 ${
              plan.highlighted
                ? 'border-amber-400/30 bg-amber-400/[0.02]'
                : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02]'
            }`}
          >
            {plan.badge && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <span className="inline-flex items-center rounded-full bg-amber-400 px-3 py-1 text-[11px] font-bold text-black">
                  {plan.badge[lang]}
                </span>
              </div>
            )}

            {/* Plan name */}
            <h3 className="text-[18px] font-bold text-gray-900 dark:text-white/90">{plan.name[lang]}</h3>
            <p className="mt-1 text-[13px] text-gray-500 dark:text-white/35">{plan.description[lang]}</p>

            {/* Price */}
            <div className="mt-5 flex items-baseline gap-1">
              <span className="font-mono text-[36px] font-extrabold text-gray-900 dark:text-white">{plan.price.amount}</span>
              <span className="text-[14px] text-gray-400 dark:text-white/30">{plan.price.period}</span>
            </div>

            {/* Features */}
            <ul className="mt-6 flex-1 space-y-3">
              {plan.features.map((f, i) => (
                <li key={i} className="flex items-start gap-2.5">
                  <CheckIcon />
                  <span className="text-[13px] text-gray-600 dark:text-white/55">{f[lang]}</span>
                </li>
              ))}
            </ul>

            {/* CTA */}
            <Link
              href={ctaFor(plan).href}
              className={`mt-6 block w-full rounded-xl py-3 text-center text-[14px] font-bold transition-all duration-200 ${
                plan.highlighted
                  ? 'bg-amber-400 text-black hover:bg-amber-300'
                  : 'border border-gray-200 dark:border-white/[0.1] bg-gray-50 dark:bg-white/[0.04] text-gray-700 dark:text-white/70 hover:bg-gray-100 dark:hover:bg-white/[0.08] hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {ctaFor(plan).label}
            </Link>
          </div>
        ))}
      </div>

      {/* Trust row, shown only when billing is actually live.
          "Cancel anytime" is backed by /api/stripe/portal. There is deliberately
          no refund claim here — no refund path is implemented, and a promise
          nobody can honour costs more trust than it buys. */}
      {BILLING_ENABLED ? (
      <div className="mt-16 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-[12px] text-gray-400 dark:text-white/30">
        <span className="flex items-center gap-1.5">
          <svg className="h-3.5 w-3.5 text-emerald-400/60" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 1a4.5 4.5 0 0 0-4.5 4.5V9H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-.5V5.5A4.5 4.5 0 0 0 10 1Zm3 8V5.5a3 3 0 1 0-6 0V9h6Z" clipRule="evenodd" /></svg>
          {lang === 'zh' ? 'Stripe 安全支付' : 'Secure payment via Stripe'}
        </span>
        <Link href="/api/stripe/portal" className="flex items-center gap-1.5 hover:text-gray-600 dark:hover:text-white/60">
          <svg className="h-3.5 w-3.5 text-emerald-400/60" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z" clipRule="evenodd" /></svg>
          {lang === 'zh' ? '随时取消（管理订阅）' : 'Cancel anytime (manage subscription)'}
        </Link>
      </div>
      ) : null}
    </div>
  );
}
