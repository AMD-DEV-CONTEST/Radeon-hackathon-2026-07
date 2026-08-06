'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useLang } from './LanguageProvider';
import type { ProjectStatus } from '@/lib/types';

const COLOR_MAP: Record<string, string> = {
  violet:  'border-violet-400/25 bg-violet-400/8 text-violet-300 hover:border-violet-400/40 hover:bg-violet-400/15',
  teal:    'border-teal-400/25 bg-teal-400/8 text-teal-300 hover:border-teal-400/40 hover:bg-teal-400/15',
  emerald: 'border-emerald-400/25 bg-emerald-400/8 text-emerald-300 hover:border-emerald-400/40 hover:bg-emerald-400/15',
};

export default function ProjectStatusButtons({
  projectId,
  currentStatus,
}: {
  projectId: string;
  currentStatus: ProjectStatus;
}) {
  const router = useRouter();
  const { lang, t } = useLang();
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  const transitions: Partial<Record<ProjectStatus, { status: ProjectStatus; labelZh: string; labelEn: string; color: string }>> = {
    active:    { status: 'delivered', labelZh: '标记已交付', labelEn: 'Mark as Delivered', color: 'violet' },
    delivered: { status: 'invoiced',  labelZh: '标记已开票', labelEn: 'Mark as Invoiced',  color: 'teal' },
    invoiced:  { status: 'paid',      labelZh: '标记已付款', labelEn: 'Mark as Paid',      color: 'emerald' },
  };

  const transition = transitions[currentStatus];
  if (!transition) return null;

  async function updateStatus() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: transition!.status }),
      });
      if (!res.ok) throw new Error('Update failed');
      setDone(true);
      setTimeout(() => {
        if (mountedRef.current) router.refresh();
      }, 600);
    } catch {
      setError(lang === 'zh' ? '更新失败，请重试' : 'Update failed — please retry');
      setLoading(false);
    }
  }

  const colorCls = done
    ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300'
    : COLOR_MAP[transition.color] ?? COLOR_MAP.teal;

  return (
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        onClick={() => void updateStatus()}
        disabled={loading || done}
        className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-[13px] font-semibold transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${colorCls}`}
      >
        {done ? (
          <>
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
            </svg>
            {lang === 'zh' ? '已更新' : 'Updated!'}
          </>
        ) : loading ? (
          <>
            <span className="h-3 w-3 animate-pulse-soft rounded-full bg-current opacity-70" />
            {lang === 'zh' ? '更新中…' : 'Updating…'}
          </>
        ) : (
          lang === 'zh' ? transition.labelZh : transition.labelEn
        )}
      </button>
      {error && (
        <span className="text-[12px] text-red-300/70">{error}</span>
      )}
    </div>
  );
}
