import Link from 'next/link';
import StatusBadge from './StatusBadge';
import { formatMoney, daysRemaining } from '@/lib/utils';
import type { Project } from '@/lib/types';
import type { Lang } from '@/lib/i18n';

export default function ProjectCard({ project, lang = 'en' }: { project: Project; lang?: Lang }) {
  const days = daysRemaining(project.deadline);
  const overdue = days < 0 && project.status !== 'paid';

  const dayStr = overdue
    ? lang === 'zh' ? `逾期${Math.abs(days)}天` : `${Math.abs(days)}d overdue`
    : days === 0
    ? lang === 'zh' ? '今日截止' : 'due today'
    : lang === 'zh' ? `剩余${days}天` : `${days}d left`;

  return (
    <Link
      href={`/project/${project.id}`}
      className="group relative block overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-white/[0.03] transition-all duration-200 hover:border-gray-300 dark:hover:border-white/[0.12]"
    >
      <div className="relative p-6">
        {/* Header row */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[16px] font-bold leading-tight text-gray-900 dark:text-white">
              {project.project_type}
            </p>
            <p className="mt-1 truncate text-[13px] text-gray-500 dark:text-white/45">{project.client_name}</p>
          </div>
          <StatusBadge status={project.status} lang={lang} />
        </div>

        {/* Footer row */}
        <div className="mt-5 flex items-center justify-between border-t border-gray-200 dark:border-white/[0.06] pt-4">
          <span className="font-mono text-[18px] font-bold text-gray-900 dark:text-white tracking-tight">
            {formatMoney(Number(project.budget), project.currency)}
          </span>
          <span
            className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-colors ${
              overdue
                ? 'bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400'
                : days === 0
                ? 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400'
                : days <= 3
                ? 'bg-gray-100 dark:bg-white/[0.06] text-gray-600 dark:text-white/55'
                : 'bg-gray-100 dark:bg-white/[0.04] text-gray-500 dark:text-white/45'
            }`}
          >
            {dayStr}
          </span>
        </div>
      </div>
    </Link>
  );
}