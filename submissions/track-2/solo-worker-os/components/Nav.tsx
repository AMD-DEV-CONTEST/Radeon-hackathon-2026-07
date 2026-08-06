'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState, useEffect } from 'react';
import { useLang } from './LanguageProvider';
import LanguageToggle from './LanguageToggle';
import ThemeToggle from './ThemeToggle';
import NotificationBell from './NotificationBell';
import SignOutButton from './SignOutButton';

export default function Nav() {
  const pathname = usePathname();
  const { t, lang } = useLang();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem('solo-worker-avatar');
      if (saved) setAvatarUrl(saved);
      else setAvatarUrl('/avatar.jpg');
    } catch {}
  }, []);

  const links = [
    { href: '/dashboard',  label: t.nav.dashboard, icon: 'grid' },
    { href: '/chat',       label: t.nav.chat,      icon: 'chat' },
    { href: '/projects',   label: t.nav.projects,  icon: 'briefcase' },
    { href: '/knowledge',  label: t.nav.knowledge,  icon: 'book' },
    { href: '/settings',   label: t.nav.settings,   icon: 'gear' },
  ];

  function renderIcon(name: string) {
    const paths: Record<string, string> = {
      grid:      'M4 4h7v7H4V4Zm9 0h7v7h-7V4Zm-9 9h7v7H4v-7Zm9 0h7v7h-7v-7Z',
      chat:      'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z',
      briefcase: 'M20 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2ZM16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2',
      book:      'M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25',
      gear:      'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.29.24-.438.613-.431.992a7.723 7.723 0 0 1 0 .255c-.007.378.14.75.43.99l1.005.828c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.542-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.29-.24.437-.613.43-.992a7.723 7.723 0 0 1 0-.255c.007-.378-.14-.75-.43-.99l-1.004-.828a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28Z',
    };
    const d = paths[name];
    if (!d) return null;
    return <path strokeLinecap="round" strokeLinejoin="round" d={d} />;
  }

  function openPalette() {
    document.dispatchEvent(new Event('open-command-palette'));
    setMobileOpen(false);
  }

  return (
    <header className="sticky top-0 z-50 border-b border-black/[0.06] bg-white/85 backdrop-blur-xl dark:border-white/[0.06] dark:bg-[#0e0e11]/85">
      <div className="mx-auto flex max-w-[1400px] items-center justify-between px-4 py-2.5 sm:px-6 lg:px-8">
        {/* Logo */}
        <Link href="/" className="group flex items-center gap-2.5">
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt="Solo Worker OS"
              className="h-8 w-8 rounded-lg object-cover ring-1 ring-inset ring-black/10 dark:ring-white/20"
            />
          ) : (
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white">
              S
            </span>
          )}
          <span className="hidden text-[14px] font-bold tracking-tight text-gray-900 sm:block dark:text-white">
            Solo Worker <span className="text-accent">OS</span>
          </span>
        </Link>

        {/* Desktop nav — center pill */}
        <nav className="hidden items-center gap-0.5 rounded-lg border border-black/[0.06] bg-black/[0.02] p-1 md:flex dark:border-white/[0.08] dark:bg-white/[0.03]">
          {links.map((l) => {
            const active = pathname === l.href || pathname.startsWith(l.href + '/');
            return (
              <Link
                key={l.href}
                href={l.href}
                prefetch={true}
                className={`flex items-center gap-2.5 rounded-md px-4 py-2 text-[14px] font-semibold transition-all duration-200 ${
                  active
                    ? 'bg-black/[0.06] text-gray-900 dark:bg-white/[0.1] dark:text-white'
                    : 'text-gray-500 hover:bg-black/[0.04] hover:text-gray-700 dark:text-white/45 dark:hover:bg-white/[0.06] dark:hover:text-white/80'
                }`}
              >
                <svg className="h-[16px] w-[16px] flex-shrink-0 opacity-60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                  {renderIcon(l.icon)}
                </svg>
                {l.label}
              </Link>
            );
          })}
        </nav>

        {/* Right side — search + theme + language + notifications + sign out */}
        <div className="hidden items-center gap-1.5 md:flex">
          <button
            type="button"
            onClick={openPalette}
            title={lang === 'zh' ? '搜索 (⌘K)' : 'Search (⌘K)'}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-black/[0.04] hover:text-gray-700 dark:text-white/40 dark:hover:bg-white/[0.06] dark:hover:text-white/70"
          >
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
            </svg>
          </button>
          <ThemeToggle />
          <LanguageToggle />
          <NotificationBell />
          <SignOutButton />
        </div>

        {/* Mobile right side */}
        <div className="flex items-center gap-1.5 md:hidden">
          <button
            type="button"
            onClick={openPalette}
            title={lang === 'zh' ? '搜索' : 'Search'}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 transition-colors hover:text-gray-700 dark:text-white/40 dark:hover:text-white/70"
          >
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => setMobileOpen((v) => !v)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 transition-colors hover:text-gray-700 dark:text-white/40 dark:hover:text-white/70"
            aria-label="Toggle menu"
          >
            {mobileOpen ? (
              <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
              </svg>
            ) : (
              <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M2 4.75A.75.75 0 0 1 2.75 4h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 4.75ZM2 10a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 10Zm0 5.25a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1-.75-.75Z" clipRule="evenodd" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile menu dropdown */}
      {mobileOpen && (
        <div className="border-t border-black/[0.06] bg-white/95 px-4 py-3 md:hidden animate-slide-down dark:border-white/[0.06] dark:bg-[#0e0e11]/95">
          <nav className="flex flex-col gap-1">
            {links.map((l) => {
              const active = pathname === l.href || pathname.startsWith(l.href + '/');
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  prefetch={true}
                  onClick={() => setMobileOpen(false)}
                  className={`flex items-center gap-3 rounded-lg px-4 py-2.5 text-[14px] font-semibold transition-all ${
                    active
                      ? 'bg-black/[0.06] text-gray-900 dark:bg-white/[0.1] dark:text-white'
                      : 'text-gray-500 hover:bg-black/[0.03] hover:text-gray-700 dark:text-white/50 dark:hover:bg-white/[0.05] dark:hover:text-white/80'
                  }`}
                >
                  <svg className="h-[16px] w-[16px] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                    {renderIcon(l.icon)}
                  </svg>
                  {l.label}
                </Link>
              );
            })}
            {/* Marketing pages — mobile only */}
            <div className="flex gap-4 px-4 py-2 text-[13px] border-t border-black/[0.06] mt-1 pt-3 dark:border-white/[0.06]">
              <Link href="/" onClick={() => setMobileOpen(false)} className={`font-medium ${pathname === '/' ? 'text-gray-700 dark:text-white/70' : 'text-gray-400 hover:text-gray-600 dark:text-white/35 dark:hover:text-white/60'}`}>
                {lang === 'zh' ? '首页' : 'Home'}
              </Link>
              <Link href="/demo" onClick={() => setMobileOpen(false)} className={`font-medium ${pathname === '/demo' ? 'text-gray-700 dark:text-white/70' : 'text-gray-400 hover:text-gray-600 dark:text-white/35 dark:hover:text-white/60'}`}>
                {lang === 'zh' ? '演示' : 'Demo'}
              </Link>
              <Link href="/pricing" onClick={() => setMobileOpen(false)} className={`font-medium ${pathname === '/pricing' ? 'text-gray-700 dark:text-white/70' : 'text-gray-400 hover:text-gray-600 dark:text-white/35 dark:hover:text-white/60'}`}>
                {lang === 'zh' ? '定价' : 'Pricing'}
              </Link>
            </div>
            <div className="mt-2 border-t border-black/[0.06] pt-2 flex items-center justify-between dark:border-white/[0.06]">
              <div className="flex items-center gap-1.5">
                <ThemeToggle />
                <LanguageToggle />
              </div>
              <SignOutButton />
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
