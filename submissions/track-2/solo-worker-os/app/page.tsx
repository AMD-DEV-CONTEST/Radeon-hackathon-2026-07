'use client';

import Link from 'next/link';
import { getFeaturedScenarios } from '@/lib/demo/demo-scenarios';

// ─── Icons ──────────────────────────────────────────────────────────────────

function IconArrow() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M3 10a.75.75 0 0 1 .75-.75h10.638L10.23 5.29a.75.75 0 1 1 1.04-1.08l5.5 5.25a.75.75 0 0 1 0 1.08l-5.5 5.25a.75.75 0 1 1-1.04-1.08l4.158-3.96H3.75A.75.75 0 0 1 3 10Z" clipRule="evenodd" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
    </svg>
  );
}

function IconX() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
    </svg>
  );
}

function IconChat() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 0 1 .778-.332 48.294 48.294 0 0 0 5.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
    </svg>
  );
}

function IconDoc() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  );
}

function IconWallet() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a2.25 2.25 0 0 0-2.25-2.25H15a3 3 0 1 1-6 0H5.25A2.25 2.25 0 0 0 3 12m18 0v6a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 18v-6m18 0V9M3 12V9m18 0a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 9m18 0V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v3" />
    </svg>
  );
}

function IconChart() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
    </svg>
  );
}

function IconShield() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
    </svg>
  );
}

function IconSpark() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  HERO
// ═══════════════════════════════════════════════════════════════════════════

function HeroSection() {
  return (
    <section className="px-2 pt-10 pb-8 sm:pt-16 sm:pb-12">
      <div className="mx-auto max-w-3xl">
        {/* Social proof ABOVE headline */}
        <div className="mb-6 flex items-center gap-3">
          <div className="flex items-center gap-1">
            {[...Array(5)].map((_, i) => (
              <svg key={i} className="h-3.5 w-3.5 text-accent" viewBox="0 0 20 20" fill="currentColor">
                <path d="M10.868 2.884c-.321-.772-1.415-.772-1.736 0l-1.83 4.401-4.753.381c-.833.067-1.171 1.107-.536 1.651l3.62 3.102-1.106 4.637c-.194.813.691 1.456 1.405 1.02L10 15.591l4.069 2.485c.713.436 1.598-.207 1.404-1.02l-1.106-4.637 3.62-3.102c.635-.544.297-1.584-.536-1.65l-4.752-.382-1.831-4.4Z" />
              </svg>
            ))}
          </div>
          <span className="text-[13px] text-gray-500 dark:text-white/45">为独立工作者打造的对话式业务平台</span>
        </div>

        {/* Headline */}
        <h1 className="text-[34px] font-bold leading-[1.1] tracking-tight text-gray-900 sm:text-[48px] dark:text-white">
          管理你所有的客户、项目<br className="hidden sm:block" />和收款——全部在对话中完成
        </h1>

        {/* Subhead */}
        <p className="mt-5 max-w-xl text-[16px] leading-relaxed text-gray-600 dark:text-white/55">
          创建项目、生成合同、开具发票、记录收款——说一句话，AI 自动执行。
          不用填表，不用切换工具，数据自然沉淀。
        </p>

        {/* CTA */}
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <Link
            href="/chat"
            className="group inline-flex items-center gap-2 rounded-xl bg-gray-900 px-5 py-2.5 text-[14px] font-semibold text-white transition-all duration-200 hover:bg-gray-800 active:scale-[0.98] dark:bg-white dark:text-black dark:hover:bg-white/90"
          >
            免费开始使用
            <IconArrow />
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-xl border border-black/10 px-5 py-2.5 text-[14px] font-medium text-gray-600 transition-all duration-200 hover:border-black/20 hover:text-gray-900 dark:border-white/10 dark:text-white/60 dark:hover:border-white/20 dark:hover:text-white/90 active:scale-[0.98]"
          >
            查看仪表盘
          </Link>
        </div>
        <p className="mt-3 text-[13px] text-gray-400 dark:text-white/35">
          无需信用卡 · 5 秒上手 · 支持中英文
        </p>
      </div>

      <div className="mx-auto mt-12 max-w-4xl">
        <ProductPreview />
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  PRODUCT PREVIEW
// ═══════════════════════════════════════════════════════════════════════════

function ProductPreview() {
  return (
    <div className="overflow-hidden rounded-2xl border border-black/[0.08] bg-gray-50 shadow-2xl shadow-black/10 dark:border-white/[0.08] dark:bg-[#0a0a0c] dark:shadow-black/40">
      <div className="flex items-center gap-2 border-b border-black/[0.04] px-4 py-3 dark:border-white/[0.04]">
        <div className="flex gap-1.5">
          <div className="h-2.5 w-2.5 rounded-full bg-black/10 dark:bg-white/10" />
          <div className="h-2.5 w-2.5 rounded-full bg-black/10 dark:bg-white/10" />
          <div className="h-2.5 w-2.5 rounded-full bg-black/10 dark:bg-white/10" />
        </div>
        <div className="ml-3 flex items-center gap-2 text-[11px] font-medium text-gray-400 dark:text-white/30">
          <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
          </svg>
          Solo Worker OS
        </div>
      </div>

      <div className="grid grid-cols-1 gap-0 sm:grid-cols-2">
        {/* Left: Chat */}
        <div className="border-r border-black/[0.04] p-5 space-y-4 dark:border-white/[0.04]">
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-xl rounded-br-sm bg-accent/10 px-3.5 py-2.5 text-[13px] text-gray-800 dark:text-white/80">
              新客户周晨，企业官网改版，预算12000，截止8月20日
            </div>
          </div>
          <div className="flex gap-2.5">
            <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-accent/15 text-[11px] font-bold text-accent dark:text-amber-300">
              AI
            </div>
            <div className="flex-1 space-y-2">
              <p className="text-[13px] leading-relaxed text-gray-600 dark:text-white/60">
                已创建项目。客户 <span className="font-semibold text-gray-900 dark:text-white/80">周晨</span>，类型 <span className="font-semibold text-gray-900 dark:text-white/80">企业官网改版</span>，预算 <span className="font-mono text-accent dark:text-amber-300">¥12,000</span>，截止 <span className="font-mono text-gray-700 dark:text-white/70">2026-08-20</span>。
              </p>
              <div className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/15 bg-emerald-500/5 px-2.5 py-1.5 dark:border-emerald-400/15 dark:bg-emerald-400/5">
                <IconCheck />
                <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-300">项目已创建 · 仪表盘已更新</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Dashboard preview */}
        <div className="p-5 space-y-3 bg-black/[0.01] dark:bg-white/[0.01]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">概览</span>
            <span className="text-[10px] text-gray-300 dark:text-white/20">实时同步</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3 dark:border-white/[0.06] dark:bg-white/[0.02]">
              <p className="text-[10px] text-gray-400 dark:text-white/35">进行中</p>
              <p className="mt-0.5 text-[20px] font-bold tabular-nums text-accent dark:text-amber-300">4</p>
            </div>
            <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3 dark:border-white/[0.06] dark:bg-white/[0.02]">
              <p className="text-[10px] text-gray-400 dark:text-white/35">本月收入</p>
              <p className="mt-0.5 text-[20px] font-bold tabular-nums text-emerald-600 dark:text-emerald-300">¥8,000</p>
            </div>
          </div>
          <div className="rounded-lg border border-accent/10 bg-accent/[0.03] p-3 dark:border-amber-400/10 dark:bg-amber-400/[0.03]">
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-1.5 rounded-full bg-accent" />
              <span className="text-[11px] font-semibold text-gray-700 dark:text-white/70">项目已创建</span>
              <span className="ml-auto text-[10px] text-gray-300 dark:text-white/30">刚刚</span>
            </div>
            <p className="mt-1 text-[11px] text-gray-400 dark:text-white/40">企业官网改版 · 周晨</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  QUANTIFIED VALUE
// ═══════════════════════════════════════════════════════════════════════════

function QuantifiedValueSection() {
  const stats = [
    {
      value: '10+',
      unit: '小时/周',
      label: '节省在行政事务上的时间',
      sub: '不再手动整理项目信息、起草合同、追踪收款',
    },
    {
      value: '5',
      unit: '个工具',
      label: '合并为一个系统',
      sub: '替代 Excel + Word + 记账软件 + 微信备忘 + 日历',
    },
    {
      value: '0',
      unit: '张表单',
      label: '需要手动填写',
      sub: '全部通过自然语言对话完成录入和操作',
    },
  ];

  return (
    <section className="px-2 py-10">
      <div className="mx-auto max-w-4xl">
        <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-black/[0.06] sm:grid-cols-3 dark:border-white/[0.06]">
          {stats.map((s) => (
            <div key={s.label} className="bg-black/[0.02] p-6 dark:bg-white/[0.02]">
              <div className="flex items-baseline gap-1">
                <span className="text-[36px] font-bold tabular-nums text-gray-900 dark:text-white">{s.value}</span>
                <span className="text-[15px] font-semibold text-gray-500 dark:text-white/50">{s.unit}</span>
              </div>
              <p className="mt-2 text-[14px] font-semibold text-gray-800 dark:text-white/80">{s.label}</p>
              <p className="mt-1 text-[12px] leading-relaxed text-gray-400 dark:text-white/35">{s.sub}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  HOW IT WORKS
// ═══════════════════════════════════════════════════════════════════════════

const STEPS = [
  {
    num: '01',
    title: '说一句话，项目自动建档',
    desc: '「新客户周晨，企业官网改版，预算12000，截止8月20日」—— AI 自动提取客户、类型、预算、截止日期，一步完成建档。不用打开 Excel，不用填表单。',
    icon: IconChat,
    highlight: '从想法到建档，一句话的距离',
  },
  {
    num: '02',
    title: '对话生成合同和发票',
    desc: '基于项目信息自动生成服务合同、发票和催款邮件。合同模板可自定义，AI 从你的知识库中匹配条款。不用从空白文档开始写。',
    icon: IconDoc,
    highlight: '合同 · 发票 · 催款信，30 秒生成',
  },
  {
    num: '03',
    title: '收款状态自动追踪',
    desc: '记录每笔收款，自动更新项目状态（进行中 → 已交付 → 已开票 → 已收款）。仪表盘实时反映现金流，不用再翻聊天记录查谁付了没付。',
    icon: IconWallet,
    highlight: '从交付到收款，全流程可追溯',
  },
  {
    num: '04',
    title: '数据洞察自然产生',
    desc: '每次对话自动沉淀业务数据。一句话生成月度报告、收入统计、逾期分析。不用为了做报表而重新整理数据——数据是对话的副产品。',
    icon: IconChart,
    highlight: '对话即数据，报表一键生成',
  },
];

function HowItWorksSection() {
  return (
    <section className="px-2 py-14">
      <div className="mx-auto max-w-4xl">
        <div className="mb-10">
          <h2 className="text-[26px] font-bold tracking-tight text-gray-900 dark:text-white">从一句话到收款，全程对话完成</h2>
          <p className="mt-2 text-[15px] text-gray-500 dark:text-white/40">不再在表格、文档、记账软件之间来回切换</p>
        </div>

        <div className="space-y-3">
          {STEPS.map((step) => {
            const Icon = step.icon;
            return (
              <div
                key={step.num}
                className="flex gap-5 rounded-xl border border-black/[0.06] bg-black/[0.02] p-6 transition-colors duration-200 hover:border-black/[0.12] dark:border-white/[0.06] dark:bg-white/[0.02] dark:hover:border-white/[0.12]"
              >
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-black/10 text-accent dark:border-white/10 dark:text-amber-300">
                  <Icon />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <span className="text-[11px] font-bold tabular-nums text-gray-300 dark:text-white/25">{step.num}</span>
                    <h3 className="text-[16px] font-semibold text-gray-900 dark:text-white">{step.title}</h3>
                  </div>
                  <p className="mt-2 text-[14px] leading-relaxed text-gray-600 dark:text-white/50">{step.desc}</p>
                  <p className="mt-2.5 text-[13px] font-medium text-accent/70 dark:text-amber-300/70">{step.highlight}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  WHO IT'S FOR
// ═══════════════════════════════════════════════════════════════════════════

const AUDIENCES = [
  {
    title: '设计师',
    scenarios: '品牌设计 · UI/UX · 平面设计',
    useCase: '「为陈雨的品牌视觉项目生成合同」',
    outcome: '合同 30 秒生成，不用从模板改起',
  },
  {
    title: '开发者',
    scenarios: '独立开发 · 外包项目 · 技术咨询',
    useCase: '「新客户周晨，官网改版，预算12000」',
    outcome: '项目自动建档，不用手动整理需求',
  },
  {
    title: '顾问',
    scenarios: '管理咨询 · 营销策略 · 法律顾问',
    useCase: '「统计一下我这个月的收入情况」',
    outcome: '一句话生成报表，不用翻账本',
  },
  {
    title: '摄影师',
    scenarios: '婚礼摄影 · 商业摄影 · 活动跟拍',
    useCase: '「给张明写一封催款邮件」',
    outcome: '催款信自动匹配项目上下文',
  },
  {
    title: '内容创作者',
    scenarios: '文案 · 视频制作 · 自媒体运营',
    useCase: '「本周有什么要交的？」',
    outcome: '截止日期自动排优先级',
  },
  {
    title: '培训机构',
    scenarios: '独立讲师 · 工作坊 · 线上课程',
    useCase: '「把刘洋的项目标记为已交付」',
    outcome: '状态更新自动写入时间线',
  },
];

function AudienceSection() {
  return (
    <section className="px-2 py-14">
      <div className="mx-auto max-w-4xl">
        <div className="mb-10">
          <h2 className="text-[26px] font-bold tracking-tight text-gray-900 dark:text-white">为每一个有客户的人而生</h2>
          <p className="mt-2 text-[15px] text-gray-500 dark:text-white/40">无论你做什么，只要在服务客户，都能省下大量行政时间</p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {AUDIENCES.map((a) => (
            <div
              key={a.title}
              className="card-interactive rounded-xl border border-black/[0.06] p-5 dark:border-white/[0.06]"
            >
              <h3 className="text-[15px] font-semibold text-gray-900 dark:text-white/90">{a.title}</h3>
              <p className="mt-1 text-[12px] text-gray-400 dark:text-white/40">{a.scenarios}</p>
              <div className="mt-3 rounded-lg border border-black/[0.04] bg-gray-100 px-3 py-2 dark:border-white/[0.04] dark:bg-black/30">
                <p className="text-[12px] leading-relaxed text-gray-500 dark:text-white/45">
                  {a.useCase}
                </p>
              </div>
              <p className="mt-2 text-[12px] font-medium text-accent/60 dark:text-amber-300/60">{a.outcome}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  VS TRADITIONAL TOOLS
// ═══════════════════════════════════════════════════════════════════════════

function ComparisonSection() {
  const rows = [
    { aspect: '项目建档', traditional: '打开 Excel，手动输入字段', solo: '说一句话，AI 自动解析建档' },
    { aspect: '合同生成', traditional: '找模板，逐项修改，复制粘贴', solo: '基于项目信息自动生成' },
    { aspect: '收款追踪', traditional: '翻微信记录，手动对账', solo: '自动记录，仪表盘实时更新' },
    { aspect: '月度报表', traditional: '重新整理数据，花 1 小时', solo: '一句话生成，0 整理时间' },
    { aspect: '催款邮件', traditional: '从空白开始写，纠结措辞', solo: 'AI 根据项目上下文生成' },
    { aspect: '数据检索', traditional: '翻文件夹，搜索聊天记录', solo: '直接问 AI，秒级响应' },
  ];

  return (
    <section className="px-2 py-14">
      <div className="mx-auto max-w-4xl">
        <div className="mb-10">
          <h2 className="text-[26px] font-bold tracking-tight text-gray-900 dark:text-white">和传统工具的差距</h2>
          <p className="mt-2 text-[15px] text-gray-500 dark:text-white/40">同样的业务，不同的完成方式</p>
        </div>

        <div className="overflow-hidden rounded-xl border border-black/[0.06] dark:border-white/[0.06]">
          <div className="grid grid-cols-3 gap-px bg-black/[0.04] dark:bg-white/[0.04]">
            <div className="bg-white px-4 py-3 text-[12px] font-semibold uppercase tracking-wider text-gray-500 dark:bg-[#0e0e11] dark:text-white/40">
              业务场景
            </div>
            <div className="bg-white px-4 py-3 text-[12px] font-semibold uppercase tracking-wider text-gray-500 dark:bg-[#0e0e11] dark:text-white/40">
              传统工具
            </div>
            <div className="bg-white px-4 py-3 text-[12px] font-semibold uppercase tracking-wider text-accent dark:bg-[#0e0e11] dark:text-amber-300/70">
              Solo Worker OS
            </div>
          </div>
          {rows.map((row, i) => (
            <div key={row.aspect} className={`grid grid-cols-3 gap-px bg-black/[0.04] dark:bg-white/[0.04] ${i > 0 ? 'border-t border-black/[0.02] dark:border-white/[0.02]' : ''}`}>
              <div className="bg-white px-4 py-4 text-[13px] font-medium text-gray-700 dark:bg-[#0e0e11] dark:text-white/70">
                {row.aspect}
              </div>
              <div className="flex items-start gap-2 bg-white px-4 py-4 text-[13px] text-gray-400 dark:bg-[#0e0e11] dark:text-white/40">
                <span className="mt-0.5 flex-shrink-0 text-gray-300 dark:text-white/20"><IconX /></span>
                <span>{row.traditional}</span>
              </div>
              <div className="flex items-start gap-2 bg-white px-4 py-4 text-[13px] text-gray-700 dark:bg-[#0e0e11] dark:text-white/70">
                <span className="mt-0.5 flex-shrink-0 text-emerald-600 dark:text-emerald-400"><IconCheck /></span>
                <span>{row.solo}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  OBJECTION HANDLING
// ═══════════════════════════════════════════════════════════════════════════

function ObjectionSection() {
  const faqs = [
    {
      q: 'AI 真的能理解我的业务吗？',
      a: '系统内建项目、客户、合同、知识库等业务实体。AI 不是泛泛而谈的 ChatGPT——它基于你的真实业务数据给出可执行的方案。每次对话都在你的业务上下文中进行。',
      icon: IconSpark,
    },
    {
      q: '我的数据安全吗？',
      a: '数据存储在 Supabase（PostgreSQL）上，启用行级安全（RLS）。你的业务数据归你所有，不会用于训练模型。支持随时导出。',
      icon: IconShield,
    },
    {
      q: '上手难吗？需要学多久？',
      a: '如果你会打字，就会用。没有界面需要学习，没有表单需要填写——就像和助手聊天一样。说「新客户张三，logo设计，5000元」，系统自动完成剩下的。',
      icon: IconChat,
    },
    {
      q: '支持中文吗？',
      a: '完全支持中英文双语。界面、AI 对话、合同生成、发票模板全部支持中文。你甚至可以在对话中中英文混用。',
      icon: IconDoc,
    },
    {
      q: '比 Excel 好在哪？',
      a: 'Excel 需要你手动录入和维护数据。Solo Worker OS 的数据是对话的副产品——你每说一句话，数据就自动沉淀。不用为了记录而记录。',
      icon: IconChart,
    },
    {
      q: '以后会收费吗？',
      a: '基础功能永久免费（最多 5 个项目）。Pro 版 ¥49/月，无限项目 + 高级分析。Team 版 ¥149/月，支持团队协作。没有隐藏费用。',
      icon: IconWallet,
    },
  ];

  return (
    <section className="px-2 py-14">
      <div className="mx-auto max-w-4xl">
        <div className="mb-10">
          <h2 className="text-[26px] font-bold tracking-tight text-gray-900 dark:text-white">常见疑问</h2>
          <p className="mt-2 text-[15px] text-gray-500 dark:text-white/40">在决定之前，你可能想知道这些</p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {faqs.map((faq) => {
            const Icon = faq.icon;
            return (
              <div
                key={faq.q}
                className="rounded-xl border border-black/[0.06] bg-black/[0.02] p-5 dark:border-white/[0.06] dark:bg-white/[0.02]"
              >
                <div className="flex items-start gap-3">
                  <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-black/10 text-accent/70 dark:border-white/10 dark:text-amber-300/70">
                    <Icon />
                  </div>
                  <div>
                    <h3 className="text-[14px] font-semibold text-gray-900 dark:text-white/90">{faq.q}</h3>
                    <p className="mt-1.5 text-[13px] leading-relaxed text-gray-500 dark:text-white/45">{faq.a}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  SCENARIOS
// ═══════════════════════════════════════════════════════════════════════════

function ScenariosSection() {
  const scenarios = getFeaturedScenarios();

  return (
    <section className="px-2 py-14">
      <div className="mx-auto max-w-4xl">
        <div className="mb-8">
          <h2 className="text-[26px] font-bold tracking-tight text-gray-900 dark:text-white">现在就试试</h2>
          <p className="mt-2 text-[15px] text-gray-500 dark:text-white/40">点击任意场景，立即体验 AI 对话执行</p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {scenarios.map((scenario) => (
            <Link
              key={scenario.id}
              href={`/chat?prefill=${encodeURIComponent(scenario.prompt)}&demo=true`}
              className="card-interactive group block rounded-xl border border-black/[0.06] p-5 dark:border-white/[0.06]"
            >
              <h3 className="text-[14px] font-semibold text-gray-900 transition-colors group-hover:text-gray-600 dark:text-white/90 dark:group-hover:text-white">
                {scenario.title}
              </h3>
              <p className="mt-1 text-[12px] text-gray-400 dark:text-white/40">{scenario.subtitle}</p>
              <div className="mt-3 rounded-lg border border-black/[0.04] bg-gray-100 px-3 py-2 dark:border-white/[0.04] dark:bg-black/30">
                <p className="line-clamp-2 text-[12px] leading-relaxed text-gray-500 dark:text-white/45">
                  &ldquo;{scenario.prompt}&rdquo;
                </p>
              </div>
              <div className="mt-3 flex items-center gap-1 text-[12px] font-medium text-accent/60 transition-colors group-hover:text-accent dark:text-amber-300/60 dark:group-hover:text-amber-300">
                体验
                <IconArrow />
              </div>
            </Link>
          ))}
        </div>

        <div className="mt-6 text-center">
          <Link
            href="/demo"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-gray-400 transition-colors hover:text-gray-700 dark:text-white/40 dark:hover:text-white/70"
          >
            查看全部场景
            <IconArrow />
          </Link>
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  CTA
// ═══════════════════════════════════════════════════════════════════════════

function CTASection() {
  return (
    <section className="px-2 py-20">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-[30px] font-bold tracking-tight text-gray-900 sm:text-[36px] dark:text-white">
          把行政事务交给 AI<br />把时间还给你的手艺
        </h2>
        <p className="mx-auto mt-4 max-w-md text-[16px] leading-relaxed text-gray-500 dark:text-white/45">
          你擅长的是设计、开发、咨询——不是填表、对账、写催款信。
          让 AI 处理后者，你专注前者。
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link
            href="/chat"
            className="group inline-flex items-center gap-2 rounded-xl bg-gray-900 px-6 py-3 text-[15px] font-semibold text-white transition-all duration-200 hover:bg-gray-800 active:scale-[0.98] dark:bg-white dark:text-black dark:hover:bg-white/90"
          >
            免费开始使用
            <IconArrow />
          </Link>
        </div>
        <p className="mt-3 text-[13px] text-gray-400 dark:text-white/35">
          无需信用卡 · 5 秒上手 · 支持中英文
        </p>
      </div>
    </section>
  );
}

export default function HomePage() {
  return (
    <div className="pb-20">
      <HeroSection />
      <QuantifiedValueSection />
      <HowItWorksSection />
      <AudienceSection />
      <ComparisonSection />
      <ObjectionSection />
      <ScenariosSection />
      <CTASection />
    </div>
  );
}
