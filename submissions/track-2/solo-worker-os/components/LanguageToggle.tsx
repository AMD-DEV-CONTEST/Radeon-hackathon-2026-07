'use client';

import { useLang } from './LanguageProvider';
import { type Lang } from '@/lib/i18n';

export default function LanguageToggle() {
  const { lang, setLang } = useLang();
  const options: { value: Lang; label: string }[] = [
    { value: 'en', label: 'EN' },
    { value: 'zh', label: '\u4e2d' },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-black/[0.06] bg-black/[0.02] p-0.5 dark:border-white/[0.06] dark:bg-white/[0.03]">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => setLang(o.value)}
          className={`rounded-md px-2 py-0.5 text-[11px] font-bold transition-all duration-200 ${
            lang === o.value
              ? 'bg-accent/20 text-accent dark:bg-amber-400/20 dark:text-amber-300'
              : 'text-gray-400 hover:text-gray-700 dark:text-white/40 dark:hover:text-white/70'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
