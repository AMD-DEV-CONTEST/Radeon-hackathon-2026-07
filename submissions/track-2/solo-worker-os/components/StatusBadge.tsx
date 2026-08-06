import type { ProjectStatus } from '@/lib/types';
import type { Lang } from '@/lib/i18n';

// ─── 统一灰色系配色 ──────────────────────────────────────────────────────────
// 所有状态使用统一的灰色背景，仅通过小圆点颜色区分
const STYLES: Record<ProjectStatus, { bg: string; text: string; dot: string }> = {
  active: {
    bg: 'bg-gray-100 dark:bg-white/[0.06]',
    text: 'text-gray-600 dark:text-white/70',
    dot: 'bg-amber-500',
  },
  delivered: {
    bg: 'bg-gray-100 dark:bg-white/[0.06]',
    text: 'text-gray-600 dark:text-white/70',
    dot: 'bg-violet-500',
  },
  invoiced: {
    bg: 'bg-gray-100 dark:bg-white/[0.06]',
    text: 'text-gray-600 dark:text-white/70',
    dot: 'bg-teal-500',
  },
  paid: {
    bg: 'bg-gray-100 dark:bg-white/[0.06]',
    text: 'text-gray-600 dark:text-white/70',
    dot: 'bg-emerald-500',
  },
};

const LABELS_ZH: Record<ProjectStatus, string> = {
  active: '进行中',
  delivered: '已交付',
  invoiced: '已开票',
  paid: '已付款',
};

export default function StatusBadge({
  status,
  label,
  lang = 'en',
}: {
  status: ProjectStatus;
  label?: string;
  lang?: Lang;
}) {
  const s = STYLES[status];
  const text = label ?? (lang === 'zh' ? LABELS_ZH[status] : status.charAt(0).toUpperCase() + status.slice(1));
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-lg ${s.bg} px-3 py-1 text-[12px] font-semibold ${s.text}`}
    >
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      {text}
    </span>
  );
}