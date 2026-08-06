'use client';

import { useState, useEffect } from 'react';
import { useLang } from '@/components/LanguageProvider';
import { translations } from '@/lib/i18n';
import { ToggleRow } from '@/components/ui/Switch';

interface UserPrefs {
  theme: 'dark';
  compactMode: boolean;
  showTimestamps: boolean;
  defaultSuggestedPrompts: boolean;
}

const DEFAULT_PREFS: UserPrefs = {
  theme: 'dark',
  compactMode: false,
  showTimestamps: true,
  defaultSuggestedPrompts: true,
};

function loadPrefs(): UserPrefs {
  if (typeof window === 'undefined') return DEFAULT_PREFS;
  try {
    const raw = localStorage.getItem('solo-worker-prefs');
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch {}
  return DEFAULT_PREFS;
}

function savePrefs(prefs: UserPrefs) {
  localStorage.setItem('solo-worker-prefs', JSON.stringify(prefs));
}

const SHORTCUTS_KEYS = [
  ['⌘', 'K'],
  ['↑', '↓'],
  ['↵'],
  ['Esc'],
  ['⌘', '↵'],
] as const;

export default function SettingsPage() {
  const { lang, setLang } = useLang();
  const t = translations[lang];
  const s = t.settings;
  const [prefs, setPrefs] = useState<UserPrefs>(DEFAULT_PREFS);
  const [saved, setSaved] = useState(false);

  // Avatar state
  const [avatarDesc, setAvatarDesc] = useState('');
  const [avatarPrompt, setAvatarPrompt] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [avatarLoading, setAvatarLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Load saved avatar
  useEffect(() => {
    try {
      const savedAvatar = localStorage.getItem('solo-worker-avatar');
      if (savedAvatar) setAvatarUrl(savedAvatar);
    } catch {}
  }, []);

  useEffect(() => {
    setPrefs(loadPrefs());
  }, []);

  function update<K extends keyof UserPrefs>(key: K, value: UserPrefs[K]) {
    const next = { ...prefs, [key]: value };
    setPrefs(next);
    savePrefs(next);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function generateAvatarPrompt() {
    if (!avatarDesc.trim()) return;
    setAvatarLoading(true);
    try {
      const res = await fetch('/api/avatar/prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: avatarDesc }),
      });
      const data = await res.json() as { prompt?: string; error?: string };
      if (data.prompt) setAvatarPrompt(data.prompt);
    } catch {}
    setAvatarLoading(false);
  }

  async function copyPrompt() {
    if (!avatarPrompt) return;
    await navigator.clipboard.writeText(avatarPrompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function saveAvatar() {
    if (!avatarUrl.trim()) return;
    localStorage.setItem('solo-worker-avatar', avatarUrl.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  function resetAvatar() {
    setAvatarUrl('');
    localStorage.removeItem('solo-worker-avatar');
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const SHORTCUTS = SHORTCUTS_KEYS.map((keys, i) => ({
    keys,
    description: [s.shortcutPalette, s.shortcutNavigate, s.shortcutSelect, s.shortcutClose, s.shortcutSend][i],
  }));

  return (
    <div className="mx-auto max-w-3xl space-y-8 pb-16">
      {/* Header */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-[20px] font-bold tracking-tight text-gray-900 dark:text-white">{s.title}</h1>
          {saved && (
            <span className="rounded-full border border-emerald-300 dark:border-emerald-400/20 bg-emerald-100 dark:bg-emerald-400/10 px-3 py-0.5 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
              {s.saved}
            </span>
          )}
        </div>
        <p className="text-[14px] text-gray-500 dark:text-white/40">{s.prefsDesc}</p>
      </div>

      {/* Language */}
      <section className="glass rounded-2xl p-6 space-y-5">
        <h2 className="text-[13px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.languageSection}</h2>
        <div className="flex gap-3">
          {(['en', 'zh'] as const).map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLang(l)}
              className={`rounded-xl border px-5 py-2.5 text-[13px] font-semibold transition-all duration-300 ${
                lang === l
                  ? 'border-amber-300 dark:border-amber-400/40 bg-amber-100 dark:bg-amber-400/10 text-amber-700 dark:text-amber-300'
                  : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] text-gray-500 dark:text-white/50 hover:border-gray-300 dark:hover:border-white/[0.12] hover:text-gray-700 dark:hover:text-white/80'
              }`}
            >
              {l === 'en' ? 'English' : '中文'}
            </button>
          ))}
        </div>
      </section>

      {/* Display */}
      <section className="glass rounded-2xl p-6 space-y-1">
        <div className="mb-5 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-gray-200 dark:border-white/[0.06] bg-gray-100 dark:bg-white/[0.02]">
            <svg className="h-4 w-4 text-amber-600/70 dark:text-amber-300/70" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
            </svg>
          </div>
          <h2 className="text-[13px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/40">{s.displaySection}</h2>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-white/[0.04]">
          <ToggleRow
            checked={prefs.showTimestamps}
            onCheckedChange={(v) => update('showTimestamps', v)}
            label={s.showTimestamps}
            description={lang === 'zh' ? '在聊天消息中显示发送时间' : 'Show timestamps on chat messages'}
            icon={<svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>}
          />
          <ToggleRow
            checked={prefs.defaultSuggestedPrompts}
            onCheckedChange={(v) => update('defaultSuggestedPrompts', v)}
            label={s.showSuggestedPrompts}
            description={lang === 'zh' ? '显示推荐对话提示' : 'Show suggested conversation prompts'}
            icon={<svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" /></svg>}
          />
          <ToggleRow
            checked={prefs.compactMode}
            onCheckedChange={(v) => update('compactMode', v)}
            label={s.compactMode}
            description={lang === 'zh' ? '减小元素间距以在屏幕上显示更多内容' : 'Reduce spacing to fit more content on screen'}
            icon={<svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path strokeLinecap="round" strokeLinejoin="round" d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z" /><path strokeLinecap="round" strokeLinejoin="round" d="m14.5 12.5 2-2m-5 5 2-2m-5 5 2-2m7-7 2-2" /></svg>}
          />
        </div>
      </section>

      {/* Brand Avatar */}
      <section className="glass rounded-2xl p-6 space-y-5">
        <h2 className="text-[13px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.avatarSection}</h2>
        <p className="text-[13px] text-gray-500 dark:text-white/40">{s.avatarDesc}</p>

        <div className="space-y-1.5">
          <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.avatarLabel}</label>
          <textarea
            value={avatarDesc}
            onChange={(e) => setAvatarDesc(e.target.value)}
            rows={3}
            placeholder={s.avatarPlaceholder}
            className="glass focus-ring w-full resize-none rounded-xl px-4 py-3 text-[13px] leading-relaxed text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
          />
          <button
            type="button"
            onClick={generateAvatarPrompt}
            disabled={avatarLoading || !avatarDesc.trim()}
            className="rounded-xl bg-amber-500 dark:bg-amber-400 px-5 py-2.5 text-[13px] font-bold text-black transition-all disabled:opacity-40"
          >
            {avatarLoading ? s.avatarGenerating : s.avatarGenerateBtn}
          </button>
        </div>

        {avatarPrompt && (
          <div className="space-y-2 animate-fade-up">
            <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.avatarPromptLabel}</label>
            <div className="flex gap-2">
              <div className="glass flex-1 rounded-xl px-4 py-3 text-[13px] leading-relaxed text-gray-600 dark:text-white/70">
                {avatarPrompt}
              </div>
              <button
                type="button"
                onClick={copyPrompt}
                className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] px-4 py-2 text-[12px] font-semibold text-gray-500 dark:text-white/50 transition-all hover:border-gray-300 dark:hover:border-white/[0.12] hover:text-gray-700 dark:hover:text-white/80"
              >
                {copied ? s.avatarPromptCopied : s.avatarCopyBtn}
              </button>
            </div>
          </div>
        )}

        <div className="space-y-1.5">
          <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.avatarUrlLabel}</label>
          <input
            type="text"
            value={avatarUrl}
            onChange={(e) => setAvatarUrl(e.target.value)}
            placeholder={s.avatarUrlPlaceholder}
            className="glass focus-ring w-full rounded-xl px-4 py-2.5 text-[13px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
          />
        </div>

        {avatarUrl && (
          <div className="space-y-3 animate-fade-up">
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.avatarPreview}</p>
            <div className="flex items-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.03]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={avatarUrl} alt="Avatar preview" className="h-full w-full object-cover" />
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={saveAvatar}
                  className="rounded-xl bg-amber-500 dark:bg-amber-400 px-5 py-2.5 text-[13px] font-bold text-black transition-all"
                >
                  {s.avatarSaveBtn}
                </button>
                <button
                  type="button"
                  onClick={resetAvatar}
                  className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] px-4 py-2.5 text-[13px] font-semibold text-gray-500 dark:text-white/50 transition-all hover:border-gray-300 dark:hover:border-white/[0.12] hover:text-gray-700 dark:hover:text-white/80"
                >
                  {s.avatarReset}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Keyboard shortcuts */}
      <section className="glass rounded-2xl p-6 space-y-5">
        <h2 className="text-[13px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.keyboardSection}</h2>
        <div className="space-y-2">
          {SHORTCUTS.map((sc, i) => (
            <div key={i} className="flex items-center justify-between rounded-xl px-4 py-3 hover:bg-gray-100 dark:hover:bg-white/[0.02]">
              <span className="text-[13px] text-gray-600 dark:text-white/60">{sc.description}</span>
              <div className="flex items-center gap-1">
                {sc.keys.map((k, j) => (
                  <kbd
                    key={j}
                    className="rounded-md border border-gray-200 dark:border-white/[0.1] bg-gray-100 dark:bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-gray-500 dark:text-white/40 min-w-[26px] text-center"
                  >
                    {k}
                  </kbd>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* About */}
      <section className="glass rounded-2xl p-6 space-y-4">
        <h2 className="text-[13px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{s.aboutSection}</h2>
        <div className="space-y-2 text-[13px] text-gray-500 dark:text-white/50">
          <div className="flex justify-between">
            <span>{s.version}</span>
            <span className="font-mono text-gray-400 dark:text-white/30">1.0.0</span>
          </div>
          <div className="flex justify-between">
            <span>{s.stack}</span>
            <span className="font-mono text-gray-400 dark:text-white/30">Next.js 14 · MTClaw · Tailwind</span>
          </div>
        </div>
        <p className="text-[12px] text-gray-400 dark:text-white/25 pt-2">{s.aboutDesc}</p>
      </section>
    </div>
  );
}