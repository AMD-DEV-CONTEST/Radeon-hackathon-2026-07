'use client';

import { useState } from 'react';
import { createSupabaseBrowserClient } from '@/lib/supabase-browser';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';

// Demo deployments (competition judging, public demos) let visitors walk
// straight into the app. On a real deployment middleware would bounce this
// link back to /login anyway, so showing it there is just a dead end.
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

export default function LoginPage() {
  const [email, setEmail]     = useState('');
  const [status, setStatus]   = useState<'idle' | 'loading' | 'sent' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const router = useRouter();
  const searchParams = useSearchParams();

  // Set when the user was bounced here mid-flow (e.g. starting a checkout);
  // only relative paths are honoured, and the callback re-validates it.
  const rawNext = searchParams.get('next');
  const next = rawNext && rawNext.startsWith('/') && !rawNext.startsWith('//')
    ? rawNext
    : '/dashboard';

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setStatus('loading');
    setErrorMsg('');

    const supabase = createSupabaseBrowserClient();
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: {
        emailRedirectTo:
          `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });

    if (error) {
      setErrorMsg(error.message);
      setStatus('error');
    } else {
      setStatus('sent');
    }
  }

  return (
    <div className="flex min-h-[80vh] items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-400">
            <svg className="h-7 w-7 text-black" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z" />
            </svg>
          </div>
          <h1 className="text-[22px] font-bold tracking-tight text-gray-900 dark:text-white">Solo Worker OS</h1>
          <p className="mt-1.5 text-[14px] text-gray-500 dark:text-white/40">自由职业者的 AI 操作系统</p>
        </div>

        {DEMO_MODE ? (
          <>
            <div className="mb-4">
              <Link
                href="/dashboard"
                className="block w-full rounded-xl bg-gray-50 dark:bg-white/[0.06] border border-gray-200 dark:border-white/[0.1] py-3 text-center text-[14px] font-semibold text-gray-800 dark:text-white/80 transition-all hover:bg-gray-100 dark:hover:bg-white/[0.1]"
              >
                直接进入 →
              </Link>
              <p className="mt-2 text-center text-[11px] text-gray-400 dark:text-white/25">演示模式 · 无需登录</p>
            </div>

            <div className="flex items-center gap-3 mb-4">
              <div className="flex-1 border-t border-gray-200 dark:border-white/[0.06]" />
              <span className="text-[11px] text-gray-400 dark:text-white/25">或使用邮件登录</span>
              <div className="flex-1 border-t border-gray-200 dark:border-white/[0.06]" />
            </div>
          </>
        ) : null}

        {/* Card */}
        <div className="glass rounded-2xl p-6">
          {status === 'sent' ? (
            <div className="flex flex-col items-center py-4 text-center">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-400/10">
                <svg className="h-6 w-6 text-emerald-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 0 1-2.25 2.25h-15a2.25 2.25 0 0 1-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25m19.5 0v.243a2.25 2.25 0 0 1-1.07 1.916l-7.5 4.615a2.25 2.25 0 0 1-2.36 0L3.32 8.91a2.25 2.25 0 0 1-1.07-1.916V6.75" />
                </svg>
              </div>
              <p className="text-[15px] font-semibold text-gray-800 dark:text-white/80">登录邮件已发送</p>
              <p className="mt-1 text-[13px] text-gray-500 dark:text-white/40">请检查 <span className="text-amber-300">{email}</span> 的收件箱</p>
              <button
                type="button"
                onClick={() => { setStatus('idle'); router.push(next); }}
                className="mt-5 text-[13px] text-gray-400 dark:text-white/30 hover:text-gray-700 dark:hover:text-white/60 transition-colors"
              >
                跳过，直接进入 →
              </button>
            </div>
          ) : (
            <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">
                  邮箱地址
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  className="focus-ring w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.03] px-4 py-3 text-[15px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none transition-all"
                />
              </div>

              {status === 'error' && (
                <p className="rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-[13px] text-red-300">
                  {errorMsg || '发送失败，请稍后重试'}
                </p>
              )}

              <button
                type="submit"
                disabled={status === 'loading' || !email.trim()}
                className="w-full rounded-xl bg-amber-400 py-3 text-[14px] font-bold text-black transition-all duration-200 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {status === 'loading' ? '发送中…' : '发送登录链接'}
              </button>

              <p className="text-center text-[12px] text-gray-400 dark:text-white/25">
                无需密码 · 点击邮件中的链接即可登录
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
