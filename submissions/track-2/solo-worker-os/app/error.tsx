'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useLang } from '@/components/LanguageProvider';

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const { lang } = useLang();
  useEffect(() => {
    console.error('[Solo Worker OS]', error);
  }, [error]);

  const title = lang === 'zh' ? '出错了' : 'Something went wrong';
  const desc = lang === 'zh'
    ? '发生了一个意外错误。我们已记录此问题并将进行调查。'
    : 'An unexpected error occurred. This has been noted and we\'ll look into it.';
  const retryLabel = lang === 'zh' ? '重试' : 'Try again';
  const dashboardLabel = lang === 'zh' ? '返回仪表盘' : 'Back to Dashboard';

  return (
    <div className="flex min-h-[65vh] flex-col items-center justify-center text-center">
      <div className="relative mb-8">
        <div className="h-20 w-20 rounded-2xl border border-red-400/20 bg-red-400/5 flex items-center justify-center mx-auto">
          <svg className="h-9 w-9 text-red-400/60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
        </div>
      </div>

      <h1 className="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{title}</h1>
      <p className="mt-3 max-w-sm text-[14px] leading-relaxed text-gray-500 dark:text-white/40">
        {desc}
      </p>

      {error.digest && (
        <p className="mt-2 font-mono text-[11px] text-gray-400 dark:text-white/20">
          {lang === 'zh' ? '错误ID' : 'Error ID'}: {error.digest}
        </p>
      )}

      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-2 rounded-xl bg-amber-400 px-5 py-2.5 text-[14px] font-bold text-black transition-all duration-200 hover:bg-amber-300"
        >
          <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
          </svg>
          {retryLabel}
        </button>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.03] px-5 py-2.5 text-[14px] font-semibold text-gray-600 dark:text-white/60 transition-all duration-200 hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white/90"
        >
          {dashboardLabel}
        </Link>
      </div>
    </div>
  );
}
