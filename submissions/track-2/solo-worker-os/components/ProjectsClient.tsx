'use client';

import { useState, useMemo, useCallback } from 'react';
import Link from 'next/link';
import { formatMoney, daysRemaining } from '@/lib/utils';
import type { Project, ProjectStatus } from '@/lib/types';
import StatusBadge from '@/components/StatusBadge';
import ProjectCard from '@/components/ProjectCard';
import { useLang } from '@/components/LanguageProvider';
import { translations } from '@/lib/i18n';

export default function ProjectsClient({ projects: initialProjects }: { projects: Project[] }) {
  const { lang } = useLang();
  const t = translations[lang];
  const [projects, setProjects] = useState(initialProjects);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | ProjectStatus>('all');
  const [updating, setUpdating] = useState<Set<string>>(new Set());
  const [updateError, setUpdateError] = useState<string | null>(null);

  const updateStatus = useCallback(async (projectId: string, status: ProjectStatus) => {
    setUpdating((prev) => new Set(prev).add(projectId));
    setUpdateError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      if (res.ok) {
        setProjects((prev) =>
          prev.map((p) => (p.id === projectId ? { ...p, status } : p))
        );
      } else {
        const err = await res.json().catch(() => ({}));
        setUpdateError(err.error || (lang === 'zh' ? '更新失败，请重试' : 'Update failed — please retry'));
      }
    } catch {
      setUpdateError(lang === 'zh' ? '网络错误，请重试' : 'Network error — please retry');
    }
    setUpdating((prev) => {
      const next = new Set(prev);
      next.delete(projectId);
      return next;
    });
  }, [lang]);

  const STATUS_TABS: { key: 'all' | ProjectStatus; label: string }[] = [
    { key: 'all',       label: t.projects.filterAll },
    { key: 'active',    label: t.status.active },
    { key: 'delivered', label: t.status.delivered },
    { key: 'invoiced',  label: t.status.invoiced },
    { key: 'paid',      label: t.status.paid },
  ];

  const TABLE_HEADERS = [
    t.projects.client,
    t.projects.type,
    t.projects.budget,
    t.projects.status,
    t.projects.deadline,
    t.projects.daysLeft,
    t.projects.actions,
  ];

  const filtered = useMemo(() => {
    let list = projects;
    if (statusFilter !== 'all') list = list.filter((p) => p.status === statusFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (p) =>
          p.client_name.toLowerCase().includes(q) ||
          p.project_type.toLowerCase().includes(q)
      );
    }
    return list;
  }, [projects, statusFilter, search]);

  const sorted = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return [...filtered].sort((a, b) => {
      const aOverdue = a.status !== 'paid' && a.deadline < today;
      const bOverdue = b.status !== 'paid' && b.deadline < today;
      if (aOverdue !== bOverdue) return aOverdue ? -1 : 1;
      return a.deadline.localeCompare(b.deadline);
    });
  }, [filtered]);

  function dayStr(days: number, overdue: boolean) {
    if (overdue) return lang === 'zh' ? `逾期${Math.abs(days)}天` : `${Math.abs(days)}d overdue`;
    if (days === 0) return lang === 'zh' ? '今日截止' : 'due today';
    return lang === 'zh' ? `剩余${days}天` : `${days}d left`;
  }

  return (
    <div className="space-y-5">
      {/* Search + filter */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <svg className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 dark:text-white/30" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t.projects.searchPlaceholder}
            className="glass w-full rounded-xl py-2.5 pl-9 pr-4 text-[14px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/30 focus:border-amber-300 dark:focus:border-amber-400/20 focus:outline-none transition-colors"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:text-white/30 dark:hover:text-white/60"
            >
              ×
            </button>
          )}
        </div>

        <div className="flex items-center gap-1 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] p-1">
          {STATUS_TABS.map((tab) => {
            const count = tab.key === 'all' ? projects.length : projects.filter((p) => p.status === tab.key).length;
            const active = statusFilter === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setStatusFilter(tab.key)}
                className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-all duration-300 ease-expo ${
                  active
                    ? 'bg-gray-200/70 dark:bg-white/[0.08] text-gray-900 dark:text-white shadow-[inset_0_1px_0_rgba(0,0,0,0.04)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
                    : 'text-gray-500 dark:text-white/40 hover:bg-gray-100 dark:hover:bg-white/5 hover:text-gray-700 dark:hover:text-white/70'
                }`}
              >
                {tab.label}
                {count > 0 && (
                  <span className={`ml-1.5 text-[10px] ${active ? 'text-gray-500 dark:text-white/50' : 'text-gray-400 dark:text-white/25'}`}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="glass flex flex-col items-center justify-center rounded-2xl px-8 py-20 text-center">
          {search || statusFilter !== 'all' ? (
            <>
              <p className="text-[15px] font-semibold text-gray-700 dark:text-white/70">{t.projects.noResults}</p>
              <p className="mt-1 text-[13px] text-gray-500 dark:text-white/35">{t.projects.noResultsDesc}</p>
              <button
                type="button"
                onClick={() => { setSearch(''); setStatusFilter('all'); }}
                className="mt-5 inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.03] px-4 py-2 text-[13px] font-semibold text-gray-500 dark:text-white/50 transition-all hover:bg-gray-100 dark:hover:bg-white/[0.06]"
              >
                {t.projects.clearFilters}
              </button>
            </>
          ) : (
            <>
              <p className="text-[15px] font-semibold text-gray-700 dark:text-white/70">{t.projects.noProjects}</p>
              <p className="mt-1 text-[13px] text-gray-500 dark:text-white/35">{t.projects.noProjectsDesc}</p>
              <Link href="/chat" className="mt-5 inline-flex items-center gap-1.5 rounded-lg border border-amber-200 dark:border-amber-400/20 bg-amber-50 dark:bg-amber-400/5 px-4 py-2 text-[13px] font-semibold text-amber-700 dark:text-amber-300 transition-all hover:bg-amber-100 dark:hover:bg-amber-400/10">
                {t.projects.goChat} →
              </Link>
            </>
          )}
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="glass hidden overflow-hidden rounded-2xl sm:block">
            <table className="min-w-full divide-y divide-gray-100 dark:divide-white/[0.04]">
              <thead className="bg-gray-50 dark:bg-white/[0.02]">
                <tr>
                  {TABLE_HEADERS.map((h) => (
                    <th key={h} className="px-5 py-3.5 text-left text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/35">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-white/[0.04]">
                {sorted.map((p) => {
                  const days = daysRemaining(p.deadline);
                  const overdue = days < 0 && p.status !== 'paid';
                  const isDone = p.status === 'paid';
                  return (
                    <tr key={p.id} className="transition-colors hover:bg-gray-50 dark:hover:bg-white/[0.03]">
                      <td className="px-5 py-3.5">
                        <Link href={`/project/${p.id}`} className="text-[14px] font-semibold text-gray-800 dark:text-white/90 transition-colors hover:text-amber-600 dark:hover:text-amber-300">
                          {p.client_name}
                        </Link>
                      </td>
                      <td className="px-5 py-3.5 text-[14px] text-gray-500 dark:text-white/50">{p.project_type}</td>
                      <td className="px-5 py-3.5 font-mono text-[14px] text-gray-700 dark:text-white/70 tabular-nums">{formatMoney(Number(p.budget), p.currency)}</td>
                      <td className="px-5 py-3.5"><StatusBadge status={p.status} lang={lang} /></td>
                      <td className="px-5 py-3.5 font-mono text-[13px] text-gray-500 dark:text-white/50">{p.deadline}</td>
                      <td className="px-5 py-3.5">
                        <span className={`text-[13px] font-bold ${isDone ? 'text-emerald-500 dark:text-emerald-400/60' : overdue ? 'text-red-500 dark:text-red-400' : days <= 3 ? 'text-amber-600 dark:text-amber-300' : 'text-gray-400 dark:text-white/35'}`}>
                          {isDone ? (
                            <svg className="inline h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                          ) : dayStr(days, overdue)}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-1.5">
                          {p.status === 'active' && (
                            <button
                              type="button"
                              onClick={() => updateStatus(p.id, 'delivered')}
                              disabled={updating.has(p.id)}
                              title={t.projects.markDelivered}
                              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-gray-500 dark:text-white/40 transition-all hover:bg-violet-100 dark:hover:bg-violet-400/10 hover:text-violet-600 dark:hover:text-violet-300 disabled:opacity-30"
                            >
                              {t.projects.markDelivered}
                            </button>
                          )}
                          {p.status === 'delivered' && (
                            <button
                              type="button"
                              onClick={() => updateStatus(p.id, 'invoiced')}
                              disabled={updating.has(p.id)}
                              title={t.projects.markInvoiced}
                              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-gray-500 dark:text-white/40 transition-all hover:bg-sky-100 dark:hover:bg-sky-400/10 hover:text-sky-600 dark:hover:text-sky-300 disabled:opacity-30"
                            >
                              {t.projects.markInvoiced}
                            </button>
                          )}
                          {p.status === 'invoiced' && (
                            <button
                              type="button"
                              onClick={() => updateStatus(p.id, 'paid')}
                              disabled={updating.has(p.id)}
                              title={t.projects.markPaid}
                              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-gray-500 dark:text-white/40 transition-all hover:bg-emerald-100 dark:hover:bg-emerald-400/10 hover:text-emerald-600 dark:hover:text-emerald-300 disabled:opacity-30"
                            >
                              {t.projects.markPaid}
                            </button>
                          )}
                          <Link
                            href={`/chat?prefill=${encodeURIComponent(lang === 'zh' ? `告诉我关于${p.client_name}的${p.project_type}项目` : `Tell me about the ${p.project_type} project for ${p.client_name}`)}`}
                            title={t.projects.chatAbout}
                            className="rounded-lg px-2 py-1 text-[11px] font-semibold text-amber-600/60 dark:text-amber-300/60 transition-all hover:bg-amber-100 dark:hover:bg-amber-400/10 hover:text-amber-700 dark:hover:text-amber-300"
                          >
                            AI
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="grid grid-cols-1 gap-3 sm:hidden">
            {sorted.map((p) => <ProjectCard key={p.id} project={p} lang={lang} />)}
          </div>
        </>
      )}

      {updateError && (
        <div className="flex items-center justify-between rounded-xl border border-red-300 dark:border-red-400/20 bg-red-50 dark:bg-red-400/5 px-4 py-2.5">
          <span className="text-[13px] text-red-600 dark:text-red-300/80">{updateError}</span>
          <button
            type="button"
            onClick={() => setUpdateError(null)}
            className="text-[12px] text-red-500 dark:text-red-300/50 hover:text-red-700 dark:hover:text-red-300"
          >
            ×
          </button>
        </div>
      )}

      <p className="text-right text-[12px] text-gray-400 dark:text-white/25">
        {sorted.length} / {projects.length} {t.projects.ofProjects}
      </p>
    </div>
  );
}