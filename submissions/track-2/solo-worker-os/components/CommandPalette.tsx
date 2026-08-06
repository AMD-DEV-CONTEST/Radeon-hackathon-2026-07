'use client';

import { type ReactNode, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

interface PaletteItem {
  type: 'page' | 'action' | 'project';
  icon: ReactNode;
  label: string;
  sub?: string;
  href: string;
}

// ─── Linear-style minimal icons (stroke 1.6, 24x24) ─────────────────────────

const COMMAND_ICON_PATHS: Record<string, string> = {
  dashboard: 'M4 4h7v7H4V4Zm9 0h7v7h-7V4Zm-9 9h7v7H4v-7Zm9 0h7v7h-7v-7Z',
  chat:      'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z',
  projects:  'M20 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2ZM16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2',
  settings:  'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.29.24-.438.613-.431.992a7.723 7.723 0 0 1 0 .255c-.007.378.14.75.43.99l1.005.828c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.542-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.29-.24.437-.613.43-.992a7.723 7.723 0 0 1 0-.255c.007-.378-.14-.75-.43-.99l-1.004-.828a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28Z',
  user:      'M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z',
  money:     'M12 6v12m-3-2.818.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  chart:     'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z',
  doc:       'M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z',
};

function CommandIcon({ name }: { name: string }) {
  const d = COMMAND_ICON_PATHS[name];
  if (!d) return null;
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

const STATIC: PaletteItem[] = [
  { type: 'page',   icon: 'dashboard', label: 'Dashboard',               href: '/dashboard' },
  { type: 'page',   icon: 'chat', label: 'Chat with Agent',         href: '/chat' },
  { type: 'page',   icon: 'projects', label: 'All Projects',            href: '/projects' },
  { type: 'page',   icon: 'settings', label: 'Settings',                href: '/settings' },
  { type: 'action', icon: 'user', label: 'New client conversation',  href: '/chat?prefill=I+have+a+new+client+%E2%80%94+let+me+give+you+the+details' },
  { type: 'action', icon: 'money', label: 'Chase unpaid invoices',   href: '/chat?prefill=Which+projects+have+unpaid+invoices%3F+Help+me+write+reminders.' },
  { type: 'action', icon: 'chart', label: 'Weekly business summary', href: '/chat?prefill=Give+me+a+summary+of+my+business+this+week.' },
  { type: 'action', icon: 'doc', label: 'Draft a contract',        href: '/chat?prefill=Generate+a+contract+for+my+most+recent+project.' },
];

interface ProjectRow { id: string; client_name: string; project_type: string; status: string }

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [projects, setProjects] = useState<PaletteItem[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  const items: PaletteItem[] = [...STATIC, ...projects];

  const filtered = query.trim()
    ? items.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()) || (item.sub?.toLowerCase().includes(query.toLowerCase())))
    : items;

  // Keyboard shortcut to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Listen for custom event from Nav button
  useEffect(() => {
    const handler = () => setOpen(true);
    document.addEventListener('open-command-palette', handler);
    return () => document.removeEventListener('open-command-palette', handler);
  }, []);

  // Focus + fetch projects on open
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 10);
      fetch('/api/projects')
        .then((r) => r.json())
        .then((d: { projects?: ProjectRow[] }) => {
          const rows = d.projects ?? [];
          setProjects(
            rows.map((p) => ({
              type: 'project' as const,
              icon: (
                <span
                  className={
                    'h-2 w-2 rounded-full ' +
                    (p.status === 'paid'
                      ? 'bg-emerald-500 dark:bg-emerald-400'
                      : p.status === 'active'
                      ? 'bg-amber-500 dark:bg-amber-400'
                      : 'border border-gray-300 dark:border-white/30')
                  }
                />
              ),
              label: p.client_name,
              sub: p.project_type,
              href: `/project/${p.id}`,
            }))
          );
        })
        .catch(() => {});
    }
  }, [open]);

  // Reset selection on query change
  useEffect(() => setSelectedIdx(0), [query]);

  // Keyboard navigation inside palette
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && filtered[selectedIdx]) {
        navigate(filtered[selectedIdx].href);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, filtered, selectedIdx]);

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${selectedIdx}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIdx]);

  function navigate(href: string) {
    router.push(href);
    setOpen(false);
  }

  if (!open) return null;

  const TYPE_LABEL: Record<string, string> = {
    page: 'page',
    action: 'action',
    project: 'project',
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[12vh]"
      onClick={() => setOpen(false)}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm dark:bg-black/60" />

      {/* Panel */}
      <div
        className="relative w-full max-w-lg animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="overflow-hidden rounded-2xl border border-black/[0.08] bg-white/95 shadow-2xl backdrop-blur-2xl dark:border-white/10 dark:bg-[#0d0d10]/95">
          {/* Search input */}
          <div className="flex items-center gap-3 border-b border-black/[0.06] px-4 py-3.5 dark:border-white/[0.06]">
            <svg className="h-4 w-4 flex-shrink-0 text-gray-400 dark:text-white/35" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search pages, projects, actions…"
              className="flex-1 bg-transparent text-[14px] text-gray-800 placeholder:text-gray-400 focus:outline-none dark:text-white dark:placeholder:text-white/30"
            />
            <kbd className="hidden rounded-md border border-black/[0.08] bg-black/[0.04] px-2 py-1 text-[11px] font-mono text-gray-400 sm:block dark:border-white/[0.08] dark:bg-white/[0.04] dark:text-white/30">
              ESC
            </kbd>
          </div>

          {/* Results list */}
          <div ref={listRef} className="max-h-[320px] overflow-y-auto py-2">
            {filtered.length === 0 ? (
              <p className="px-5 py-8 text-center text-[13px] text-gray-400 dark:text-white/30">
                No results for &ldquo;{query}&rdquo;
              </p>
            ) : (
              <div>
                {filtered.map((item, i) => (
                  <button
                    key={`${item.href}-${i}`}
                    data-idx={i}
                    type="button"
                    onClick={() => navigate(item.href)}
                    onMouseEnter={() => setSelectedIdx(i)}
                    className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors ${
                      i === selectedIdx ? 'bg-black/[0.06] dark:bg-white/[0.07]' : 'hover:bg-black/[0.04] dark:hover:bg-white/[0.04]'
                    }`}
                  >
                    <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-black/[0.06] bg-black/[0.02] text-gray-500 dark:border-white/[0.06] dark:bg-white/[0.03] dark:text-white/50">
                      {typeof item.icon === 'string' ? <CommandIcon name={item.icon} /> : item.icon}
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block truncate text-[13px] font-medium text-gray-800 dark:text-white/80">
                        {item.label}
                      </span>
                      {item.sub && (
                        <span className="block truncate text-[11px] text-gray-400 dark:text-white/35">{item.sub}</span>
                      )}
                    </span>
                    <span className="text-[11px] text-gray-300 flex-shrink-0 dark:text-white/25">
                      {TYPE_LABEL[item.type]}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center gap-4 border-t border-black/[0.04] px-4 py-2 dark:border-white/[0.04]">
            <span className="text-[11px] text-gray-300 dark:text-white/25">
              <kbd className="font-mono">↑↓</kbd> navigate &nbsp;
              <kbd className="font-mono">↵</kbd> open &nbsp;
              <kbd className="font-mono">ESC</kbd> close
            </span>
            <span className="ml-auto font-mono text-[11px] text-gray-300 dark:text-white/20">⌘K</span>
          </div>
        </div>
      </div>
    </div>
  );
}
