'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  DEMO_DOMAINS,
  DEMO_SCENARIOS,
  getScenariosByDomain,
  type DemoDomain,
} from '@/lib/demo/demo-scenarios';

// ─── Domain icons ────────────────────────────────────────────────────────────

function IconProject() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25Z" />
    </svg>
  );
}
function IconKnowledge() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
    </svg>
  );
}
function IconAnalytics() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
    </svg>
  );
}
function IconWriting() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125" />
    </svg>
  );
}
function IconSchedule() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0V11.25A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" />
    </svg>
  );
}
function IconArrow() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M3 10a.75.75 0 0 1 .75-.75h10.638L10.23 5.29a.75.75 0 1 1 1.04-1.08l5.5 5.25a.75.75 0 0 1 0 1.08l-5.5 5.25a.75.75 0 1 1-1.04-1.08l4.158-3.96H3.75A.75.75 0 0 1 3 10Z" clipRule="evenodd" />
    </svg>
  );
}

const DOMAIN_ICONS: Record<DemoDomain, () => JSX.Element> = {
  project_management: IconProject,
  knowledge_search: IconKnowledge,
  data_analysis: IconAnalytics,
  writing_assistant: IconWriting,
  schedule_tasks: IconSchedule,
};

// ═══════════════════════════════════════════════════════════════════════════
//  MAIN
// ═══════════════════════════════════════════════════════════════════════════

export default function DemoPage() {
  const [activeDomain, setActiveDomain] = useState<DemoDomain | null>(null);
  const filteredScenarios = activeDomain ? getScenariosByDomain(activeDomain) : DEMO_SCENARIOS;

  return (
    <div className="px-6 py-10 sm:px-12">
      <div className="mx-auto max-w-4xl">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-[24px] font-bold tracking-tight text-gray-900 dark:text-white">全部场景</h1>
          <p className="mt-1 text-[14px] text-gray-500 dark:text-white/40">点击卡片即可体验，AI 自动理解意图并执行</p>
        </div>

        {/* Domain filter */}
        <div className="mb-6 flex flex-wrap gap-2">
          <button
            onClick={() => setActiveDomain(null)}
            className={`rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-all duration-200 ${
              activeDomain === null
                ? 'border-gray-200 dark:border-white/15 bg-gray-50 dark:bg-white/[0.08] text-gray-900 dark:text-white'
                : 'border-gray-200 dark:border-white/[0.06] text-gray-500 dark:text-white/40 hover:text-gray-700 dark:hover:text-white/70'
            }`}
          >
            全部
            <span className="ml-1.5 text-[10px] opacity-50">{DEMO_SCENARIOS.length}</span>
          </button>
          {DEMO_DOMAINS.map((domain) => {
            const count = getScenariosByDomain(domain.id).length;
            const isActive = activeDomain === domain.id;
            const Icon = DOMAIN_ICONS[domain.id];
            return (
              <button
                key={domain.id}
                onClick={() => setActiveDomain(domain.id)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-all duration-200 ${
                  isActive
                    ? 'border-amber-400/20 bg-amber-400/5 text-amber-300'
                    : 'border-gray-200 dark:border-white/[0.06] text-gray-500 dark:text-white/40 hover:text-gray-700 dark:hover:text-white/70'
                }`}
              >
                <Icon />
                {domain.label}
                <span className="text-[10px] opacity-50">{count}</span>
              </button>
            );
          })}
        </div>

        {/* Domain descriptions */}
        {activeDomain && (
          <div className="mb-6 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] p-4">
            <p className="text-[13px] leading-relaxed text-gray-500 dark:text-white/50">
              {DEMO_DOMAINS.find((d) => d.id === activeDomain)?.description}
            </p>
          </div>
        )}

        {/* Scenario cards — NO technical details */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredScenarios.map((scenario) => (
            <Link
              key={scenario.id}
              href={`/chat?prefill=${encodeURIComponent(scenario.prompt)}&demo=true`}
              className="card-interactive group block rounded-xl border border-gray-200 dark:border-white/[0.06] p-5"
            >
              <h3 className="text-[14px] font-semibold text-gray-900 dark:text-white/90 transition-colors group-hover:text-gray-900 dark:group-hover:text-white">
                {scenario.title}
              </h3>
              <p className="mt-1 text-[12px] text-gray-500 dark:text-white/40">{scenario.subtitle}</p>
              <div className="mt-3 rounded-lg border border-gray-200 dark:border-white/[0.04] bg-black/30 px-3 py-2">
                <p className="line-clamp-2 text-[12px] leading-relaxed text-gray-500 dark:text-white/45">
                  &ldquo;{scenario.prompt}&rdquo;
                </p>
              </div>
              <div className="mt-3 flex items-center gap-1 text-[12px] font-medium text-amber-300/60 transition-colors group-hover:text-amber-300">
                体验
                <IconArrow />
              </div>
            </Link>
          ))}
        </div>

        {/* Back to home */}
        <div className="mt-10 text-center">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-gray-500 dark:text-white/40 transition-colors hover:text-gray-700 dark:hover:text-white/70"
          >
            返回首页
            <IconArrow />
          </Link>
        </div>
      </div>
    </div>
  );
}