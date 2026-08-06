import Link from 'next/link';
import { getServerLang } from '@/lib/i18n-server';

export default function NotFound() {
  const lang = getServerLang();
  const title = lang === 'zh' ? '页面未找到' : 'Page not found';
  const desc = lang === 'zh'
    ? '此页面不存在或可能已被移动。您的 AI 助手仍在仪表盘等您。'
    : "This page doesn't exist or may have been moved. Your AI agent is still ready to help on the dashboard.";
  const ctaDashboard = lang === 'zh' ? '前往仪表盘' : 'Go to Dashboard';
  const ctaChat = lang === 'zh' ? '打开聊天' : 'Open Chat';

  return (
    <div className="flex min-h-[65vh] flex-col items-center justify-center text-center">
      {/* Giant blurred 404 */}
      <div className="relative mb-8 select-none">
        <p className="font-mono text-[128px] font-extrabold leading-none tracking-tighter text-black/[0.03] dark:text-white/[0.03]">
          404
        </p>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex h-20 w-20 items-center justify-center rounded-2xl border border-amber-400/20 bg-amber-400/5">
            <svg className="h-9 w-9 text-amber-400/60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
            </svg>
          </div>
        </div>
      </div>

      <h1 className="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{title}</h1>
      <p className="mt-3 max-w-sm text-[14px] leading-relaxed text-gray-500 dark:text-white/40">
        {desc}
      </p>

      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 rounded-xl bg-amber-400 px-5 py-2.5 text-[14px] font-bold text-black transition-all duration-200 hover:bg-amber-300"
        >
          <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M9.293 2.293a1 1 0 0 1 1.414 0l7 7A1 1 0 0 1 17 11h-1v6a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6H3a1 1 0 0 1-.707-1.707l7-7Z" clipRule="evenodd" />
          </svg>
          {ctaDashboard}
        </Link>
        <Link
          href="/chat"
          className="inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.03] px-5 py-2.5 text-[14px] font-semibold text-gray-600 dark:text-white/60 transition-all duration-200 hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white/90"
        >
          {ctaChat}
        </Link>
      </div>
    </div>
  );
}
