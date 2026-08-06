'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

interface Notification {
  id: string;
  type: string;
  title: string;
  body: string;
  project_id: string | null;
  read: boolean;
  created_at: string;
}

// ─── Linear-style minimal icons (stroke 1.6, 24x24) ─────────────────────────

const NOTIFY_ICON_PATHS: Record<string, string> = {
  clock: 'M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  chart: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z',
  chat:  'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z',
};

function NotifyIcon({ name }: { name: string }) {
  const d = NOTIFY_ICON_PATHS[name] ?? NOTIFY_ICON_PATHS.chat;
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

const TYPE_ICON: Record<string, string> = {
  deadline_reminder: 'clock',
  weekly_report: 'chart',
  custom: 'chat',
};

function timeAgoShort(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function NotificationBell() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  const unread = notifications.filter((n) => !n.read).length;

  async function load() {
    try {
      const res = await fetch('/api/notifications');
      const d = await res.json() as { notifications: Notification[] };
      setNotifications(d.notifications ?? []);
    } catch {}
  }

  // Poll every 60 seconds
  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 60_000);
    return () => clearInterval(id);
  }, []);

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  async function markRead(id: string) {
    setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, read: true } : n));
    await fetch('/api/notifications', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
  }

  async function markAllRead() {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    await fetch('/api/notifications', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ all: true }),
    });
  }

  function handleClick(n: Notification) {
    void markRead(n.id);
    if (n.project_id) router.push(`/project/${n.project_id}`);
    setOpen(false);
  }

  return (
    <div ref={panelRef} className="relative">
      {/* Bell button */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-black/[0.06] bg-black/[0.02] text-gray-400 transition-colors hover:text-gray-700 dark:border-white/[0.06] dark:bg-white/[0.02] dark:text-white/40 dark:hover:text-white/70"
        aria-label="Notifications"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[9px] font-extrabold text-white dark:bg-amber-400 dark:text-black">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute right-0 top-11 z-[300] w-80 animate-scale-in overflow-hidden rounded-2xl border border-black/[0.08] bg-white/95 shadow-2xl backdrop-blur-2xl dark:border-white/10 dark:bg-[#0d0d10]/95">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-black/[0.06] px-4 py-3 dark:border-white/[0.06]">
            <span className="text-[13px] font-bold text-gray-800 dark:text-white/80">Notifications</span>
            {unread > 0 && (
              <button
                type="button"
                onClick={() => void markAllRead()}
                className="text-[11px] text-amber-600 hover:text-amber-700 dark:text-amber-300 dark:hover:text-amber-400 transition-colors"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-80 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <p className="text-[13px] text-gray-400 dark:text-white/30">No notifications yet</p>
                <p className="mt-1 text-[11px] text-gray-400 dark:text-white/20">Run /api/cron to generate alerts</p>
              </div>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => handleClick(n)}
                  className={`flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-black/[0.04] dark:hover:bg-white/[0.04] ${
                    n.read ? 'opacity-50' : ''
                  }`}
                >
                  <span className="mt-0.5 flex-shrink-0 text-gray-400 dark:text-white/50">
                    <NotifyIcon name={TYPE_ICON[n.type] ?? 'chat'} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-semibold text-gray-800 dark:text-white/80">{n.title}</p>
                    <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-gray-500 dark:text-white/40">{n.body}</p>
                    <p className="mt-1 font-mono text-[10px] text-gray-400 dark:text-white/25">{timeAgoShort(n.created_at)}</p>
                  </div>
                  {!n.read && (
                    <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-amber-500 dark:bg-amber-400" />
                  )}
                </button>
              ))
            )}
          </div>

          {/* Footer CTA */}
          <div className="border-t border-black/[0.04] px-4 py-2.5 dark:border-white/[0.04]">
            <button
              type="button"
              onClick={async () => {
                await fetch('/api/cron');
                await load();
              }}
              className="w-full rounded-lg py-1.5 text-[11px] font-medium text-gray-400 transition-colors hover:bg-black/[0.04] hover:text-gray-600 dark:text-white/30 dark:hover:bg-white/[0.04] dark:hover:text-white/60"
            >
              Check for new alerts now
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
