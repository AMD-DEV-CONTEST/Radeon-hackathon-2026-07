import { Suspense, type ReactNode } from 'react';
import Link from 'next/link';
import { createServerClient } from '@/lib/supabase-server';
import { formatMoney, timeAgo, todayISO, getGreeting } from '@/lib/utils';
import type { Project, AgentAction } from '@/lib/types';
import ProjectCard from '@/components/ProjectCard';
import DashboardRefresher from '@/components/DashboardRefresher';
import { getServerT, getServerLang } from '@/lib/i18n-server';
import { getCachedDashboardData, setCachedDashboardData } from '@/lib/dashboard-cache';

export const dynamic = 'force-dynamic';

// ─── tiny icons ──────────────────────────────────────────────────────────────
function IconBriefcase() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M20 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2ZM16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" />
    </svg>
  );
}
function IconClock() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="12" cy="12" r="9" />
      <path strokeLinecap="round" d="M12 7v5l3 3" />
    </svg>
  );
}
function IconBadgeCheck() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="m9 12 2 2 4-4m6 2a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
    </svg>
  );
}
function IconAlert() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
    </svg>
  );
}

const ACTION_ICONS: Record<string, ReactNode> = {
  project_created:     <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>,
  status_updated:      <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" /></svg>,
  contract_generated:  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" /></svg>,
  followup_generated:  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z" /></svg>,
  invoice_generated:   <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 0 0 2.25-2.25V6.75A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25v10.5A2.25 2.25 0 0 0 4.5 19.5Z" /></svg>,
  payment_recorded:    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z" /></svg>,
  deliverable_filed:   <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" /></svg>,
};

function summarizeAction(
  a: AgentAction,
  projectMap: Map<string, Project>,
  t: ReturnType<typeof getServerT>,
  lang: 'zh' | 'en',
): string {
  const proj = a.project_id ? projectMap.get(a.project_id) : null;
  const who = proj ? `${proj.project_type} · ${proj.client_name}` : 'a project';
  const statusLabels: Record<string, string> = {
    active: t.status.active,
    delivered: t.status.delivered,
    invoiced: t.status.invoiced,
    paid: t.status.paid,
  };
  switch (a.action_type) {
    case 'project_created':     return `${t.project.projectCreated}: ${who}`;
    case 'status_updated':      {
      const st = String((a.payload as { status?: string }).status ?? '');
      return `${t.project.statusUpdated}: ${who} → ${statusLabels[st] ?? st}`;
    }
    case 'contract_generated':  return `${t.project.contractGenerated}: ${who}`;
    case 'followup_generated':  return `${t.project.followupGenerated}: ${who}`;
    case 'invoice_generated':   return `${t.project.invoiceGenerated}: ${who}`;
    case 'payment_recorded':    return `${t.project.paymentRecorded}: ${who}`;
    case 'deliverable_filed':   return `${t.project.deliverableFiled}: ${who}`;
    default: return a.action_type;
  }
}

// ─── skeleton for the data section ───────────────────────────────────────────
function DataSkeleton() {
  return (
    <div className="space-y-8">
      {/* stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="glass rounded-2xl p-6 space-y-3 animate-pulse">
            <div className="h-3 w-24 rounded bg-gray-200 dark:bg-white/[0.06]" />
            <div className="h-9 w-20 rounded bg-gray-200 dark:bg-white/[0.06]" />
          </div>
        ))}
      </div>
      {/* quick actions */}
      <div className="flex flex-wrap gap-3">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-11 w-32 rounded-xl bg-gray-200 dark:bg-white/[0.05] animate-pulse" />
        ))}
      </div>
      {/* content */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="glass rounded-2xl p-6 space-y-3 animate-pulse">
              <div className="h-4 w-32 rounded bg-gray-200 dark:bg-white/[0.05]" />
              <div className="h-3 w-24 rounded bg-gray-200 dark:bg-white/[0.05]" />
              <div className="h-6 w-20 rounded bg-gray-200 dark:bg-white/[0.05] mt-5" />
            </div>
          ))}
        </div>
        <div className="glass rounded-2xl p-5 space-y-4 animate-pulse">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="flex gap-3">
              <div className="h-6 w-6 rounded-md bg-gray-200 dark:bg-white/[0.05] flex-shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-3 w-full rounded bg-gray-200 dark:bg-white/[0.05]" />
                <div className="h-2 w-16 rounded bg-gray-200 dark:bg-white/[0.05]" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── async data section (suspends) ───────────────────────────────────────────
async function DashboardData({ t, lang }: { t: ReturnType<typeof getServerT>; lang: ReturnType<typeof getServerLang> }) {
  const today = todayISO();
  
  // Try to get cached data first
  const cached = getCachedDashboardData();
  
  let projectList: Project[];
  let actionList: AgentAction[];
  let paymentList: Array<{ amount: number; currency: string; received_date: string; project_id: string }>;
  let deliverableList: Array<{ id: string; project_id: string; title: string; type: string; status: string; url: string | null; created_at: string }>;
  
  if (cached) {
    // Use cached data
    projectList = cached.projects as Project[];
    actionList = cached.actions as AgentAction[];
    paymentList = cached.payments;
    deliverableList = cached.deliverables;
  } else {
    // Fetch from database
    const supabase = createServerClient();
    const [{ data: projects }, { data: actions }, { data: payments }, { data: deliverables }] = await Promise.all([
      supabase.from('projects').select('*').order('created_at', { ascending: false }).limit(50),
      supabase.from('agent_actions').select('*').order('created_at', { ascending: false }).limit(8),
      supabase.from('payments').select('*').order('received_date', { ascending: false }).limit(50),
      supabase.from('deliverables').select('*').order('created_at', { ascending: false }).limit(5),
    ]);

    projectList = (projects as Project[]) ?? [];
    actionList = (actions as AgentAction[]) ?? [];
    paymentList = (payments as Array<{ amount: number; currency: string; received_date: string; project_id: string }>) ?? [];
    deliverableList = (deliverables as Array<{ id: string; project_id: string; title: string; type: string; status: string; url: string | null; created_at: string }>) ?? [];
    
    // Update cache
    setCachedDashboardData({
      projects: projectList,
      actions: actionList,
      payments: paymentList,
      deliverables: deliverableList,
    });
  }
  
  const projectMap = new Map(projectList.map((p) => [p.id, p]));

  const activeCount = projectList.filter((p) => p.status === 'active').length;
  const overdueCount = projectList.filter((p) => p.status !== 'paid' && p.deadline < today).length;
  const recentProjects = projectList.slice(0, 4);

  const invoiced = projectList.filter((p) => p.status === 'invoiced');
  const pendingByCurrency = new Map<string, number>();
  for (const p of invoiced) pendingByCurrency.set(p.currency, (pendingByCurrency.get(p.currency) ?? 0) + Number(p.budget));
  const pendingLabel = pendingByCurrency.size === 0
    ? '—'
    : [...pendingByCurrency.entries()].map(([cur, amt]) => formatMoney(amt, cur)).join(' · ');

  // Real earned revenue from payments table (more accurate than project status)
  const earnedByCurrency = new Map<string, number>();
  for (const p of paymentList) earnedByCurrency.set(p.currency, (earnedByCurrency.get(p.currency) ?? 0) + Number(p.amount));
  // Fallback: if no payments in the payments table, compute from paid projects.
  // Single-pass O(n) — replaces the previous O(n²) multi-filter approach.
  const earnedLabel = earnedByCurrency.size === 0
    ? (() => {
        const paidByCurrency = new Map<string, number>();
        for (const p of projectList) {
          if (p.status === 'paid') {
            paidByCurrency.set(p.currency, (paidByCurrency.get(p.currency) ?? 0) + Number(p.budget));
          }
        }
        return paidByCurrency.size === 0
          ? '—'
          : [...paidByCurrency.entries()].map(([cur, amt]) => formatMoney(amt, cur)).join(' · ');
      })()
    : [...earnedByCurrency.entries()].map(([cur, amt]) => formatMoney(amt, cur)).join(' · ');

  // This month's revenue
  const thisMonth = new Date().toISOString().slice(0, 7);
  const monthRevenue = paymentList.filter((p) => p.received_date.startsWith(thisMonth));
  const monthRevenueByCurrency = new Map<string, number>();
  for (const p of monthRevenue) monthRevenueByCurrency.set(p.currency, (monthRevenueByCurrency.get(p.currency) ?? 0) + Number(p.amount));
  const monthRevenueLabel = monthRevenueByCurrency.size === 0
    ? '—'
    : [...monthRevenueByCurrency.entries()].map(([cur, amt]) => formatMoney(amt, cur)).join(' · ');

  // ─── 统一配色方案 ──────────────────────────────────────────────────────────
  // 所有统计卡片使用统一的灰色系 + 金色数值
  // 只有「需要关注」的 overdue > 0 时才显示警告色
  const STATS = [
    {
      label:  t.dashboard.activeProjects,
      value:  String(activeCount),
      icon:   <IconBriefcase />,
      href:   '/projects',
    },
    {
      label:  t.dashboard.pendingPayments,
      value:  pendingLabel,
      icon:   <IconClock />,
      href:   '/projects',
    },
    {
      label:  t.dashboard.totalEarned,
      value:  earnedLabel,
      icon:   <IconBadgeCheck />,
      href:   '/projects',
    },
    {
      label:  t.dashboard.overdueFollowups,
      value:  String(overdueCount),
      icon:   <IconAlert />,
      isAlert: overdueCount > 0,
      href:   '/projects',
    },
  ];

  const QUICK_ACTIONS = [
    { label: t.dashboard.quickActions.newClient,   href: `/chat?prefill=${encodeURIComponent(t.dashboard.quickActions.newClientPrefill)}` },
    { label: t.dashboard.quickActions.chase,       href: `/chat?prefill=${encodeURIComponent(t.dashboard.quickActions.chasePrefill)}` },
    { label: t.dashboard.recordPayment, href: `/chat?prefill=${encodeURIComponent(lang === 'zh' ? '张明的款收到了，记录一下' : 'I just received a payment from my most recent client')}` },
    { label: t.dashboard.quickActions.weekly,      href: `/chat?prefill=${encodeURIComponent(t.dashboard.quickActions.weeklyPrefill)}` },
    { label: t.dashboard.quickActions.overdue,     href: '/projects' },
  ];

  return (
    <div className="space-y-8">
      {/* Stats — 统一灰色卡片 + 金色数值 */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {STATS.map((c, i) => (
          <Link
            key={c.label}
            href={c.href}
            className={`tactile group relative overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-white/[0.03] p-6 transition-all duration-200 hover:border-gray-300 dark:hover:border-white/[0.12] stagger-${i + 1} animate-fade-up`}
          >
            <div className="relative">
              <div className={`mb-4 inline-flex items-center justify-center rounded-xl p-2.5 ${c.isAlert ? 'bg-red-50 dark:bg-red-500/10 text-red-500 dark:text-red-400' : 'bg-gray-100 dark:bg-white/[0.06] text-gray-500 dark:text-white/50'}`}>{c.icon}</div>
              <p className="text-[12px] font-semibold uppercase tracking-widest text-gray-400 dark:text-white/40">{c.label}</p>
              <p className={`mt-2 font-mono text-2xl font-bold tabular-nums ${c.isAlert ? 'text-red-500 dark:text-red-400' : 'text-gray-900 dark:text-white'} sm:text-3xl`}>{c.value}</p>
            </div>
          </Link>
        ))}
      </div>

      {/* Monthly revenue banner — 简洁灰色 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] px-6 py-5">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-100 dark:bg-white/[0.06] text-gray-500 dark:text-white/50">
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z" />
            </svg>
          </div>
          <div>
            <p className="text-[12px] font-semibold uppercase tracking-widest text-gray-400 dark:text-white/40">{t.dashboard.thisMonth}</p>
            <p className="mt-1 font-mono text-xl font-bold tabular-nums text-gray-900 dark:text-white">{monthRevenueLabel}</p>
          </div>
        </div>
        <Link
          href={`/chat?prefill=${encodeURIComponent(lang === 'zh' ? '导出这个月的月报' : 'Export my monthly report')}`}
          className="tactile inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-white dark:bg-white/[0.04] px-4 py-2.5 text-[13px] font-semibold text-gray-600 dark:text-white/70 transition-colors hover:border-gray-300 dark:hover:border-white/[0.15] hover:text-gray-900 dark:hover:text-white"
        >
          {t.dashboard.getReport}
          <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M3 10a.75.75 0 0 1 .75-.75h10.638L10.23 5.29a.75.75 0 1 1 1.04-1.08l5.5 5.25a.75.75 0 0 1 0 1.08l-5.5 5.25a.75.75 0 1 1-1.04-1.08l4.158-3.96H3.75A.75.75 0 0 1 3 10Z" clipRule="evenodd" /></svg>
        </Link>
      </div>

      {/* Quick actions — 统一灰色按钮 */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Primary manual action — 金色强调 */}
        <Link
          href={`/chat?prefill=${encodeURIComponent(lang === 'zh' ? '新客户 — 让我告诉你详情' : 'I have a new client — let me give you the details')}`}
          className="tactile inline-flex items-center gap-2 rounded-xl bg-amber-500 dark:bg-amber-400 px-5 py-3 text-[14px] font-bold text-black transition-all duration-200 hover:bg-amber-400 dark:hover:bg-amber-300"
        >
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
          {t.dashboard.newProject}
        </Link>
        {/* AI shortcuts — 灰色 */}
        {QUICK_ACTIONS.map((a) => (
          <Link
            key={a.href}
            href={a.href}
            className="tactile-strong inline-flex items-center rounded-xl border border-gray-200 dark:border-white/[0.08] bg-white dark:bg-white/[0.03] px-4 py-2.5 text-[13px] font-semibold text-gray-600 dark:text-white/60 transition-all duration-200 hover:border-gray-300 dark:hover:border-white/[0.15] hover:text-gray-900 dark:hover:text-white"
          >
            {a.label}
          </Link>
        ))}
      </div>

      {/* Main content — 去除网格间隙导致的断裂感 */}
      <div className="flex flex-col gap-8 xl:flex-row">
        {/* Recent projects — 弹性宽度填充 */}
        <section className="flex-1 min-w-0">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-[16px] font-bold text-gray-900 dark:text-white">{t.dashboard.recentProjects}</h2>
            <Link href="/projects" className="group flex items-center gap-1.5 text-[13px] font-semibold text-gray-500 dark:text-white/50 transition-colors hover:text-gray-700 dark:hover:text-white/80">
              {t.dashboard.viewAll}
              <svg className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 10a.75.75 0 0 1 .75-.75h10.638L10.23 5.29a.75.75 0 1 1 1.04-1.08l5.5 5.25a.75.75 0 0 1 0 1.08l-5.5 5.25a.75.75 0 1 1-1.04-1.08l4.158-3.96H3.75A.75.75 0 0 1 3 10Z" clipRule="evenodd" />
              </svg>
            </Link>
          </div>

          {recentProjects.length === 0 ? (
            <div className="glass rounded-2xl overflow-hidden">
              {/* Hero */}
              <div className="relative px-8 py-12 text-center">
                <div className="relative">
                  <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] text-gray-500 dark:text-white/50">
                    <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z" />
                    </svg>
                  </div>
                  <h3 className="text-[18px] font-bold tracking-tight text-gray-900 dark:text-white">{t.dashboard.onboardTitle}</h3>
                  <p className="mt-3 text-[14px] text-gray-500 dark:text-white/50 max-w-sm mx-auto">{t.dashboard.onboardDesc}</p>
                </div>
              </div>
              {/* Steps */}
              <div className="grid grid-cols-1 gap-px bg-gray-200 dark:bg-white/[0.06] sm:grid-cols-3">
                {[
                  { n: '1', title: t.dashboard.onboardStep1, desc: t.dashboard.onboardStep1Desc },
                  { n: '2', title: t.dashboard.onboardStep2, desc: t.dashboard.onboardStep2Desc },
                  { n: '3', title: t.dashboard.onboardStep3, desc: t.dashboard.onboardStep3Desc },
                ].map((s) => (
                  <div key={s.n} className="flex items-start gap-4 bg-white dark:bg-white/[0.02] px-6 py-6">
                    <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100 dark:bg-white/[0.06] text-[14px] font-bold text-gray-600 dark:text-white/70">{s.n}</span>
                    <div>
                      <p className="text-[14px] font-bold text-gray-800 dark:text-white/80">{s.title}</p>
                      <p className="mt-1 text-[13px] text-gray-500 dark:text-white/40">{s.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
              {/* CTA */}
              <div className="border-t border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.01] px-8 py-8">
                <p className="mb-2 text-[12px] font-semibold uppercase tracking-widest text-gray-400 dark:text-white/35">{t.dashboard.onboardTry}</p>
                <p className="mb-5 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-5 py-3 font-mono text-[14px] text-gray-600 dark:text-white/60">
                  {t.dashboard.onboardExample}
                </p>
                <Link
                  href="/chat"
                  className="inline-flex items-center gap-2 rounded-xl bg-amber-500 dark:bg-amber-400 px-6 py-3 text-[14px] font-bold text-black transition-all duration-200 hover:bg-amber-400 dark:hover:bg-amber-300"
                >
                  {t.dashboard.onboardCta}
                </Link>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-2">
              {recentProjects.map((p, i) => (
                <div key={p.id} className={`stagger-${i + 1} animate-fade-up`}>
                  <ProjectCard project={p} lang={lang} />
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Right sidebar — 固定宽度 */}
        <aside className="w-full xl:w-[360px] flex-shrink-0 space-y-8">
          {/* Activity feed */}
          <section>
            <h2 className="mb-5 text-[16px] font-bold text-gray-900 dark:text-white">{t.dashboard.recentActivity}</h2>
            <div className="glass rounded-2xl p-4">
              {actionList.length === 0 ? (
                <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
                  <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04]">
                    <span className="h-2.5 w-2.5 rounded-full bg-gray-300 dark:bg-white/25" />
                  </div>
                  <p className="text-[14px] text-gray-500 dark:text-white/45">{t.dashboard.noActivity}</p>
                </div>
              ) : (
                <ol className="space-y-0">
                  {actionList.map((a, i) => (
                    <li key={a.id} className="relative flex items-start gap-3.5 rounded-xl px-4 py-3 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.04]">
                      {i < actionList.length - 1 && (
                        <span className="absolute left-[24px] top-[40px] h-[calc(100%-12px)] w-px bg-gray-200 dark:bg-white/[0.06]" />
                      )}
                      <span className="relative z-10 mt-1 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-gray-100 dark:bg-white/[0.06] text-[12px] text-gray-500 dark:text-white/50">
                        {ACTION_ICONS[a.action_type] ?? '·'}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[14px] font-medium leading-snug text-gray-700 dark:text-white/75">{summarizeAction(a, projectMap, t, lang)}</p>
                        <div className="mt-1.5 flex items-center gap-2">
                          <span className="inline-flex items-center rounded border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-gray-500 dark:text-white/45">AI</span>
                          <p className="font-mono text-[12px] text-gray-400 dark:text-white/35">{timeAgo(a.created_at, lang)}</p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>

          {/* Deliverables — 交付物沉淀 */}
          {deliverableList.length > 0 && (
            <section>
              <h2 className="mb-5 text-[16px] font-bold text-gray-900 dark:text-white">{t.dashboard.deliverables}</h2>
              <div className="glass rounded-2xl p-4 space-y-2">
                {deliverableList.map((d) => {
                  const proj = projectMap.get(d.project_id);
                  const typeLabels: Record<string, string> = { final_delivery: '终稿', draft: '草稿', source_file: '源文件', documentation: '文档', other: '其他' };
                  return (
                    <div key={d.id} className="flex items-center gap-3.5 rounded-xl px-4 py-3 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.04]">
                      <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-gray-100 dark:bg-white/[0.06] text-[12px] text-gray-500 dark:text-white/50">
                        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" /></svg>
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[14px] font-medium text-gray-700 dark:text-white/75">{d.title}</p>
                        <p className="truncate text-[12px] text-gray-500 dark:text-white/40">{proj ? `${proj.project_type} · ${proj.client_name}` : d.project_id}</p>
                      </div>
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="rounded border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-2 py-0.5 text-gray-500 dark:text-white/45">{typeLabels[d.type] ?? d.type}</span>
                        <span className="font-medium text-gray-600 dark:text-white/55">{d.status}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

// ─── page shell (sync — renders immediately) ──────────────────────────────────
export default function DashboardPage() {
  const t = getServerT();
  const lang = getServerLang();
  const greeting = getGreeting(lang);

  return (
    <div className="space-y-8 animate-fade-up">
      <DashboardRefresher />
      {/* Header — no DB needed, renders instantly */}
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-gray-900 dark:text-white sm:text-[28px]">
            {greeting}
          </h1>
          <p className="mt-2 text-[14px] text-gray-500 dark:text-white/45">{t.dashboard.subtitle}</p>
        </div>
        <Link
          href="/chat"
          className="group inline-flex items-center gap-2.5 rounded-xl bg-amber-500 dark:bg-amber-400 px-6 py-3 text-[14px] font-bold text-black transition-all duration-200 hover:bg-amber-400 dark:hover:bg-amber-300"
        >
          <svg className="h-5 w-5 transition-transform duration-300 group-hover:rotate-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z" />
          </svg>
          {t.dashboard.newConversation}
        </Link>
      </div>

      {/* Data section — Supabase fetches here, skeleton shows while loading */}
      <Suspense fallback={<DataSkeleton />}>
        <DashboardData t={t} lang={lang} />
      </Suspense>
    </div>
  );
}