import type { ReactNode } from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { createServerClient } from '@/lib/supabase-server';
import { formatMoney, daysRemaining, timeAgo } from '@/lib/utils';
import type { Project, AgentAction } from '@/lib/types';
import StatusBadge from '@/components/StatusBadge';
import Markdown from '@/components/Markdown';
import CopyButton from '@/components/CopyButton';
import FollowUpGenerator from '@/components/FollowUpGenerator';
import ProjectStatusButtons from '@/components/ProjectStatusButtons';
import ProjectEditFields from '@/components/ProjectEditFields';
import WorkflowTracker from '@/components/WorkflowTracker';
import { getServerT, getServerLang } from '@/lib/i18n-server';

export const dynamic = 'force-dynamic';

export default async function ProjectDetailPage({ params }: { params: { id: string } }) {
  const t = getServerT();
  const lang = getServerLang();
  const supabase = createServerClient();
  const { data: project } = await supabase.from('projects').select('*').eq('id', params.id).single();
  if (!project) notFound();
  const { data: actions } = await supabase.from('agent_actions').select('*').eq('project_id', params.id).order('created_at', { ascending: false });
  const actionList = (actions as AgentAction[]) ?? [];
  const p = project as Project;
  const days = daysRemaining(p.deadline);
  const overdue = days < 0 && p.status !== 'paid';
  const contractAction = actionList.find((a) => a.action_type === 'contract_generated');
  const contractText = contractAction ? String((contractAction.payload as { contract?: string }).contract ?? '') : '';

  const ACTION_LABELS: Record<string, string> = {
    project_created: t.project.projectCreated,
    status_updated: t.project.statusUpdated,
    contract_generated: t.project.contractGenerated,
    followup_generated: t.project.followupGenerated,
  };

  const ACTION_ICONS: Record<string, ReactNode> = {
    project_created: <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>,
    status_updated: <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" /></svg>,
    contract_generated: <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" /></svg>,
    followup_generated: <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z" /></svg>,
    invoice_generated: <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 0 0 2.25-2.25V6.75A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25v10.5A2.25 2.25 0 0 0 4.5 19.5Z" /></svg>,
    payment_recorded: <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z" /></svg>,
  };

  const chatPrefill = encodeURIComponent(
    lang === 'zh'
      ? `告诉我关于 ${p.client_name} 的 ${p.project_type} 项目详情。`
      : `Tell me about the ${p.project_type} project for ${p.client_name}.`
  );

  const contractPrefill = encodeURIComponent(
    lang === 'zh'
      ? `为 ${p.client_name} 的 ${p.project_type} 项目生成合同`
      : `Generate a contract for ${p.client_name}'s ${p.project_type} project`
  );

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Back + chat link */}
      <div className="flex items-center justify-between">
        <Link href="/projects" className="inline-flex items-center gap-1.5 text-[13px] font-medium text-gray-500 dark:text-white/40 transition-colors hover:text-gray-800 dark:hover:text-white/80">
          <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M12.7 4.3a1 1 0 0 1 0 1.4L8.4 10l4.3 4.3a1 1 0 0 1-1.4 1.4l-5-5a1 1 0 0 1 0-1.4l5-5a1 1 0 0 1 1.4 0Z" clipRule="evenodd" />
          </svg>
          {t.project.backToProjects}
        </Link>
        <Link
          href={`/chat?prefill=${chatPrefill}`}
          className="inline-flex items-center gap-1.5 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3.5 py-1.5 text-[13px] font-semibold text-amber-300 transition-all hover:bg-amber-400/10"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z" />
          </svg>
          {t.project.openInChat}
        </Link>
      </div>

      {/* Project header card — editable fields */}
      <div className="glass relative overflow-hidden rounded-2xl p-6">
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-amber-400/5 blur-3xl" />
        <div className="relative">
          <ProjectEditFields
            projectId={p.id}
            initial={{
              client_name: p.client_name,
              project_type: p.project_type,
              budget: p.budget,
              currency: p.currency,
              deadline: p.deadline,
            }}
            labels={{
              budget: t.project.budget,
              deadline: t.project.deadline,
              clientName: lang === 'zh' ? '客户名' : 'Client',
              projectType: lang === 'zh' ? '项目类型' : 'Project type',
              currency: t.project.budget,
              save: lang === 'zh' ? '保存' : 'Save',
              cancel: lang === 'zh' ? '取消' : 'Cancel',
              edit: lang === 'zh' ? '点击编辑' : 'Click to edit',
              daysLeft: t.project.daysLeft,
              overdue: t.project.overdue,
              dueToday: t.project.dueToday,
              created: t.project.created,
            }}
            createdAt={p.created_at.slice(0, 10)}
            statusSlot={
              <>
                <StatusBadge status={p.status} label={t.status[p.status]} />
                <ProjectStatusButtons projectId={p.id} currentStatus={p.status} />
              </>
            }
          />
        </div>
      </div>

      {/* Workflow tracker */}
      <WorkflowTracker projectId={p.id} />

      {/* Follow-up generator */}
      <FollowUpGenerator projectId={p.id} clientName={p.client_name} />

      {/* Contract */}
      <div className="glass rounded-2xl p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[15px] font-bold text-gray-800 dark:text-white/80">{t.project.contract}</h2>
          {contractText && (
            <div className="flex items-center gap-2">
              <a
                href={`/api/export/contract/${p.id}`}
                download
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.03] px-3 py-1.5 text-[12px] font-semibold text-gray-500 dark:text-white/50 transition-all hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-800 dark:hover:text-white/80"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 3a.75.75 0 0 1 .75.75v7.69l2.47-2.47a.75.75 0 1 1 1.06 1.06l-3.75 3.75a.75.75 0 0 1-1.06 0L5.72 9.97a.75.75 0 1 1 1.06-1.06l2.47 2.47V3.75A.75.75 0 0 1 10 3ZM3.75 15a.75.75 0 0 0 0 1.5h12.5a.75.75 0 0 0 0-1.5H3.75Z" clipRule="evenodd" />
                </svg>
                {t.project.downloadContract}
              </a>
              <CopyButton text={contractText} label={t.project.copyContract} />
            </div>
          )}
        </div>
        {contractText ? (
          <div className="rounded-xl border border-gray-200 dark:border-white/[0.04] bg-gray-50 dark:bg-white/[0.02] p-5">
            <Markdown content={contractText} />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-200 dark:border-white/[0.08] px-8 py-12 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02]">
              <svg className="h-6 w-6 text-gray-400 dark:text-white/30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2Z" />
              </svg>
            </div>
            <p className="text-[14px] font-semibold text-gray-500 dark:text-white/50">{t.project.noContract}</p>
            <Link
              href={`/chat?prefill=${contractPrefill}`}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-2 text-[13px] font-semibold text-amber-300 transition-all hover:bg-amber-400/10"
            >
              {t.project.askContract} →
            </Link>
          </div>
        )}
      </div>

      {/* Timeline */}
      <div className="glass rounded-2xl p-6">
        <h2 className="mb-4 text-[15px] font-bold text-gray-800 dark:text-white/80">{t.project.timeline}</h2>
        {actionList.length === 0 ? (
          <p className="text-[13px] text-gray-500 dark:text-white/35">{t.project.noActions}</p>
        ) : (
          <ol className="relative ml-3 border-l border-gray-200 dark:border-white/[0.08]">
            {actionList.map((a) => {
              const st = String((a.payload as { status?: string }).status ?? '');
              const detail =
                a.action_type === 'status_updated'
                  ? `→ ${(t.status as Record<string, string>)[st] ?? st}`
                  : a.action_type === 'followup_generated'
                  ? `${t.project.toneLabel}: ${String((a.payload as { tone?: string }).tone ?? '')}`
                  : '';
              return (
                <li key={a.id} className="mb-5 ml-5 last:mb-0">
                  <span className="absolute -left-[5px] mt-1.5 flex h-2.5 w-2.5 items-center justify-center rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.5)]" />
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="flex items-center gap-1.5 text-[14px] font-semibold text-gray-900 dark:text-white/90">
                        <span className="inline-flex h-3 w-3 items-center justify-center text-amber-300">{ACTION_ICONS[a.action_type] ?? '·'}</span>
                        {ACTION_LABELS[a.action_type] ?? a.action_type}
                      </p>
                      <p className="mt-0.5 text-[12px] text-gray-500 dark:text-white/40">{detail}</p>
                    </div>
                    <p className="flex-shrink-0 font-mono text-[11px] text-gray-400 dark:text-white/30">{timeAgo(a.created_at, lang)}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}